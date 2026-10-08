"""Overcast: der Podcast-Export als OPML (v2.42.0). Alles mit erfundenen Daten."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services import overcast as oc                             # noqa: E402
from services import music_ingest                               # noqa: E402

OPML = b'''<?xml version="1.0" encoding="utf-8"?>
<opml version="1.0"><head><title>Overcast Podcast Subscriptions</title></head><body>
  <outline text="playlists"><outline type="podcast-playlist" title="Queue" sortedEpisodeIds="1,2"/></outline>
  <outline text="feeds">
    <outline type="rss" overcastId="10" text="Beispiel-Podcast" title="Beispiel-Podcast" xmlUrl="https://feeds.example.org/bsp.xml">
      <outline type="podcast-episode" overcastId="1" title="Fertig gehoert" pubDate="2026-08-01T05:00:00-04:00"
               enclosureUrl="https://media.example.org/1.mp3?ref=feed" userUpdatedDate="2026-09-19T20:30:00-04:00" played="1" userDeleted="1"/>
      <outline type="podcast-episode" overcastId="2" title="Angefangen" pubDate="2026-08-08T05:00:00-04:00"
               enclosureUrl="https://media.example.org/2.mp3" userUpdatedDate="2026-09-20T08:00:00-04:00" progress="819"/>
      <outline type="podcast-episode" overcastId="3" title="Nur geloescht" pubDate="2026-08-15T05:00:00-04:00"
               enclosureUrl="https://media.example.org/3.mp3" userUpdatedDate="2026-09-21T08:00:00-04:00" userDeleted="1"/>
    </outline>
  </outline>
</body></opml>'''

FEED = b'''<?xml version="1.0"?><rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
  <item><title>Fertig gehoert</title><enclosure url="https://media.example.org/1.mp3"/><itunes:duration>57:52</itunes:duration></item>
  <item><title>Angefangen</title><enclosure url="https://media.example.org/2.mp3"/><itunes:duration>3472</itunes:duration></item>
  <item><title>Kaputt</title><enclosure url="https://media.example.org/4.mp3"/><itunes:duration>bald</itunes:duration></item>
</channel></rss>'''


def test_der_export_wird_gelesen():
    d = oc.lesen(OPML)
    assert d["podcasts"] == [{"name": "Beispiel-Podcast", "feed_url": "https://feeds.example.org/bsp.xml"}]
    f = {x["overcast_id"]: x for x in d["folgen"]}
    assert f["1"]["gehoert"] and f["1"]["podcast"] == "Beispiel-Podcast"
    # Zaehlparameter an der Audio-Adresse fallen weg, sonst passt der Feed nicht.
    assert f["1"]["audio_url"] == "https://media.example.org/1.mp3"
    assert not f["2"]["gehoert"] and f["2"]["fortschritt_s"] == 819
    assert f["3"]["geloescht"] and f["3"]["fortschritt_s"] is None


@pytest.mark.parametrize("roh, meldung", [
    (b"", "leer"), (b"kein xml", "keine OPML"), (b"<rss/>", "keine OPML"),
    (b"<opml><body></body></opml>", "kein Podcast")])
def test_was_kein_overcast_export_ist(roh, meldung):
    with pytest.raises(oc.OvercastFehler) as e:
        oc.lesen(roh)
    assert meldung in str(e.value)


@pytest.mark.parametrize("text, sekunden", [
    ("3472", 3472), ("57:52", 3472), ("1:02:03", 3723), ("", None), ("bald", None), ("0", None)])
def test_laenge_aus_dem_feed(text, sekunden):
    assert oc.dauer_lesen(text) == sekunden


def test_laengen_je_audio_adresse():
    assert oc.laengen_aus_feed(FEED) == {"https://media.example.org/1.mp3": 3472,
                                         "https://media.example.org/2.mp3": 3472}
    assert oc.laengen_aus_feed(b"<html>kaputt") == {}


def test_register_zeilen():
    folgen = oc.lesen(OPML)["folgen"]
    for f in folgen:
        f["laenge_s"] = 3472 if f["overcast_id"] == "1" else None
    z = {x["title"]: x for x in oc.register_zeilen(folgen)}
    # Fertig: eine Wiedergabe mit der Laenge; der Tag in Ortszeit -- 20:30 in
    # New York ist in Wien schon der naechste Tag.
    assert z["Fertig gehoert"]["plays"] == 1 and z["Fertig gehoert"]["ms_played"] == 3472000
    assert z["Fertig gehoert"]["period_start"] == date(2026, 9, 20)
    assert z["Fertig gehoert"]["kind"] == "Podcast" and z["Fertig gehoert"]["artist"] == "Beispiel-Podcast"
    # Angefangen: keine Wiedergabe, aber die gehoerte Zeit.
    assert z["Angefangen"]["plays"] == 0 and z["Angefangen"]["ms_played"] == 819000
    # Weder gehoert noch angefangen: kommt nicht ins Register.
    assert "Nur geloescht" not in z
    s = oc.zusammenfassung(folgen)
    assert (s["folgen"], s["podcasts"], s["gehoert"], s["angefangen"], s["ohne_laenge"]) == (3, 1, 1, 1, 0)


def test_ein_spotify_import_ersetzt_keine_overcast_zeilen():
    assert "block <> 'Overcast'" in music_ingest._OVERLAP and oc.BLOCK == "Overcast"
