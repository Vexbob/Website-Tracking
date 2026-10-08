"""Overcast — der Podcast-Export als OPML lesen (v2.42.0).

Overcast gibt unter „Export OPML (extended)“ eine Datei heraus, die neben den
Abos jede Folge nennt, mit der man etwas getan hat:

    <outline type="rss" title="Beispiel-Podcast" xmlUrl="…">
      <outline type="podcast-episode" overcastId="…" title="…" pubDate="…"
               enclosureUrl="…" userUpdatedDate="…" played="1" progress="819"
               userDeleted="1"/>

Was die Datei NICHT nennt: wann gehoert wurde und wie lang eine Folge ist.
``userUpdatedDate`` ist die letzte Aenderung -- bei einer fertigen Folge der
Moment, in dem sie fertig wurde, bei einer angefangenen der letzte Stand.
``progress`` (Sekunden) steht nur bei angefangenen Folgen; ist eine fertig,
faellt es weg. Die Laenge holt ``feed_laengen`` deshalb aus dem oeffentlichen
RSS-Feed der Sendung (``itunes:duration``), zugeordnet ueber die Audio-
Adresse. Abgefragt werden nur die Feeds -- nichts ueber das Konto.

Ins Hoerregister (``music_entries``) kommt eine Folge als Art „Podcast“, mit
der Sendung als „Interpret“ und der Folge als „Titel“ -- genau so, wie der
Spotify-Export Podcasts liefert. Damit laufen Ueberblick, Ranglisten und
Verlauf ohne zweiten Weg mit:

- fertig gehoert: 1 Wiedergabe, Hoerzeit = Laenge der Folge (falls bekannt);
- angefangen: 0 Wiedergaben, Hoerzeit = gehoerte Sekunden.

Ein Export ist ein Stand, kein Verlauf: Overcast laesst alte Folgen
irgendwann aus der Datei fallen. Deshalb ERGAENZT ein Import nur
(``podcast_folgen``, je Folge eine Zeile ueber ``overcastId``), und die
Register-Zeilen werden danach aus allen gespeicherten Folgen neu gebaut.
"""
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BLOCK = "Overcast"
ART = "Podcast"
ORTSZEIT = ZoneInfo("Europe/Vienna")
MAX_BYTES = 10 * 1024 * 1024
FEED_MAX_BYTES = 20 * 1024 * 1024
ZEITLIMIT = 20
USER_AGENT = "Vexbob/1.0 (persoenlicher Tracker, Einzelnutzer)"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


class OvercastFehler(Exception):
    """Die Datei ist kein Overcast-Export oder unlesbar."""


def _zeit(text):
    """ISO-Zeit mit Versatz (``2026-09-19T11:06:30-04:00``) -> aware datetime."""
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _zahl(text):
    try:
        return int(float(text)) if text not in (None, "") else None
    except ValueError:
        return None


def _audio(url: str) -> str:
    """Audio-Adresse ohne Abfrageteil -- Feeds haengen gern Zaehlparameter an."""
    return (url or "").split("?", 1)[0].strip()


def lesen(roh: bytes) -> dict:
    """Die OPML-Datei -> ``{"podcasts": [...], "folgen": [...]}``.

    Je Folge: overcast_id, podcast, feed_url, titel, veroeffentlicht,
    zuletzt, gehoert, fortschritt_s, geloescht, audio_url.
    """
    if not roh:
        raise OvercastFehler("Die Datei ist leer.")
    if len(roh) > MAX_BYTES:
        raise OvercastFehler("Die Datei ist größer als 10 MB.")
    try:
        wurzel = ET.fromstring(roh)
    except ET.ParseError:
        raise OvercastFehler("Das ist keine OPML-Datei (kein lesbares XML).")
    if wurzel.tag != "opml":
        raise OvercastFehler("Das ist keine OPML-Datei.")
    podcasts, folgen = [], []
    for feed in wurzel.iter("outline"):
        if feed.attrib.get("type") != "rss":
            continue
        name = (feed.attrib.get("title") or feed.attrib.get("text") or "").strip()
        feed_url = (feed.attrib.get("xmlUrl") or "").strip()
        podcasts.append({"name": name, "feed_url": feed_url})
        for f in feed.iter("outline"):
            if f.attrib.get("type") != "podcast-episode" or not f.attrib.get("overcastId"):
                continue
            folgen.append({
                "overcast_id": f.attrib["overcastId"],
                "podcast": name,
                "feed_url": feed_url,
                "titel": (f.attrib.get("title") or "").strip(),
                "veroeffentlicht": _zeit(f.attrib.get("pubDate")),
                "zuletzt": _zeit(f.attrib.get("userUpdatedDate")),
                "gehoert": f.attrib.get("played") == "1",
                "fortschritt_s": _zahl(f.attrib.get("progress")),
                "geloescht": f.attrib.get("userDeleted") == "1",
                "audio_url": _audio(f.attrib.get("enclosureUrl")),
            })
    if not podcasts:
        raise OvercastFehler("In der Datei steht kein Podcast. Ist es der Overcast-Export "
                             "„OPML (extended)“?")
    return {"podcasts": podcasts, "folgen": folgen}


def dauer_lesen(text):
    """``itunes:duration`` -> Sekunden. Erlaubt sind ``3472``, ``57:52`` und
    ``1:02:03``; alles andere ist unbekannt (``None``)."""
    if not text:
        return None
    teile = text.strip().split(":")
    if not all(re.fullmatch(r"\d+(\.\d+)?", t) for t in teile) or len(teile) > 3:
        return None
    sekunden = 0.0
    for t in teile:
        sekunden = sekunden * 60 + float(t)
    return int(sekunden) if sekunden > 0 else None


def laengen_aus_feed(roh: bytes) -> dict:
    """RSS -> ``{audio_url: sekunden}``. Ein Feed, der sich nicht lesen
    laesst, liefert nichts -- er haelt den Import nicht auf."""
    try:
        doc = ET.fromstring(roh)
    except ET.ParseError:
        return {}
    raus = {}
    for item in doc.iter("item"):
        enc = item.find("enclosure")
        dauer = dauer_lesen(item.findtext(ITUNES + "duration"))
        if enc is not None and dauer:
            raus[_audio(enc.attrib.get("url"))] = dauer
    return raus


def feed_holen(url: str) -> bytes:
    if not re.match(r"^https?://", url or ""):
        return b""
    anfrage = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
            return antwort.read(FEED_MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return b""


def register_zeilen(folgen) -> list:
    """Die gespeicherten Folgen -> Zeilen fuer ``music_entries`` (eine je
    Folge und Tag). Ohne Wiedergabe und ohne gehoerte Zeit kommt eine Folge
    nicht ins Register -- sie wurde nur abonniert oder geloescht."""
    raus = []
    for f in folgen:
        zuletzt = f["zuletzt"]
        if zuletzt is None:
            continue
        gehoert = bool(f["gehoert"])
        if gehoert:
            ms = f["laenge_s"] * 1000 if f.get("laenge_s") else None
        else:
            ms = f["fortschritt_s"] * 1000 if f.get("fortschritt_s") else None
        if not gehoert and not ms:
            continue
        tag = zuletzt.astimezone(ORTSZEIT).date()
        raus.append({
            "block": BLOCK, "grain": "tag", "period_key": tag.isoformat(),
            "period_start": tag, "period_end": tag, "group_by": "titel", "kind": ART,
            "artist": f["podcast"] or "", "title": f["titel"] or "", "album": "",
            "plays": 1 if gehoert else 0, "ms_played": ms,
            "first_play": zuletzt, "last_play": zuletzt,
        })
    return raus


def zusammenfassung(folgen) -> dict:
    """Was gespeichert ist -- fuer die Karte im Import-Reiter."""
    gehoert = [f for f in folgen if f["gehoert"]]
    return {
        "folgen": len(folgen),
        "podcasts": len({f["podcast"] for f in folgen}),
        "gehoert": len(gehoert),
        "angefangen": sum(1 for f in folgen if not f["gehoert"] and f.get("fortschritt_s")),
        "ohne_laenge": sum(1 for f in gehoert if not f.get("laenge_s")),
        "von": min((f["zuletzt"] for f in folgen if f["zuletzt"]), default=None),
        "bis": max((f["zuletzt"] for f in folgen if f["zuletzt"]), default=None),
    }

