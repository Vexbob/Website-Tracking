"""CS2 — den Bestand aus einer Datei uebernehmen.

Der Weg, auf dem der Bestand vom Rechner auf den Server kommt: dort ausgeben,
hier einspielen, danach nur noch hier weiterarbeiten.

Das Format ist JSON und kennt **keine IDs**. Zwei Datenbanken vergeben
verschiedene, und eine Datei, die welche mitbringt, trifft auf dem Ziel
entweder nichts oder das Falsche. Verknuepft wird ueber Namen -- Kategorie
und Gegenstand --, und die legt der Import an, wenn es sie noch nicht gibt.

    {
      "modul": "cs2", "fassung": 2, "erzeugt_am": "2026-09-23T10:00:00+00:00",
      "kategorien":   [{"name": "Skin", "wear": true, "stattrak": true,
                        "playskin": true, "reihenfolge": 0}],
      "gegenstaende": [{"kategorie": "Skin", "name": "AK-47 | Frontside Misty"}],
      "positionen":   [{"kategorie": "Skin", "gegenstand": "AK-47 | Frontside Misty",
                        "wear": "FT", "stattrak": false, "playskin": true,
                        "menge": 1, "preis": "16.10",
                        "preis_am": "2026-09-22T10:13:16+00:00"}],
      "staende":      [{"datum": "2026-09-22", "brutto": "3089.81",
                        "je_kategorie": {"Case": "2520.21", …}, …}]
    }

**Fassung 1 wird weiter gelesen.** Sie trug an jeder Position noch ein
``lager``; seit dem Wegfall der Lagerzuordnung gehoert es nicht mehr zur
Signatur. Der Import ignoriert das Feld -- und fuehrt Zeilen, die sich nur
darin unterschieden, zusammen, statt sie einander ueberschreiben zu lassen.
Siehe ``_zusammenfuehren``.

Zwei Regeln, die den Import ungefaehrlich halten:

1. **Er ersetzt nichts, was er nicht nennt.** Zusammengefuehrt wird ueber die
   Signatur einer Position; was in der Datei fehlt, bleibt im Bestand stehen.
   Eine Datei kann also nichts loeschen -- auch nicht versehentlich.
2. **Vorschau ist Pflicht, nicht Hoeflichkeit.** ``vorschau`` sagt vorher, was
   neu waere und was sich aendern wuerde, samt Beispielen. Ein Import, der
   still 116 Zeilen umschreibt, ist nicht ueberpruefbar.
"""
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from typing import Optional

# Was ``aufnehmen`` schreibt. ``LESBAR`` sagt, was ``pruefen`` annimmt: die
# alte Fassung bleibt lesbar, weil sonst eine Datei wertlos waere, die jemand
# vor dem Wegfall der Lager erzeugt hat.
FASSUNG = 2
LESBAR = (1, 2)

WEAR_WERTE = ["FN", "MW", "FT", "WW", "BS"]


class TransferFehler(Exception):
    """Die Datei taugt nicht -- mit einem Satz, der sagt warum."""


# =========================================================================
# Aufnehmen
# =========================================================================

async def aufnehmen(db, user_id: int) -> dict:
    """Den ganzen Bestand als Uebertragungsdokument."""
    kategorien = await db.fetch(
        "SELECT name, supports_wear, supports_stattrak, supports_playskin, sort_order "
        "  FROM cs2_categories WHERE user_id=$1 ORDER BY sort_order, name", user_id)
    items = await db.fetch(
        "SELECT c.name AS kategorie, i.name FROM cs2_items i "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        " WHERE i.user_id=$1 ORDER BY c.name, i.name", user_id)
    positionen = await db.fetch(
        "SELECT c.name AS kategorie, i.name AS gegenstand, p.wear, p.stattrak, "
        "       p.playskin, p.quantity, p.price_eur, p.priced_at "
        "  FROM cs2_positions p "
        "  JOIN cs2_items i      ON i.id = p.item_id "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        " WHERE p.user_id=$1 ORDER BY c.name, i.name", user_id)
    staende = await db.fetch(
        "SELECT id, taken_on, total_gross, total_net, playskin_gross, playskin_net, "
        "       rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots WHERE user_id=$1 ORDER BY taken_on", user_id)
    # Die Aufteilung je Stand -- wieder ueber den Namen, nicht ueber die id.
    aufteilung: dict = {}
    for r in await db.fetch(
            "SELECT sc.snapshot_id, c.name, sc.gross "
            "  FROM cs2_snapshot_categories sc "
            "  JOIN cs2_categories c ON c.id = sc.category_id "
            "  JOIN cs2_snapshots s  ON s.id = sc.snapshot_id "
            " WHERE s.user_id=$1", user_id):
        aufteilung.setdefault(r["snapshot_id"], {})[r["name"]] = str(r["gross"])

    return {
        "modul": "cs2",
        "fassung": FASSUNG,
        "erzeugt_am": datetime.now(timezone.utc).isoformat(),
        "kategorien": [{"name": r["name"], "wear": r["supports_wear"],
                        "stattrak": r["supports_stattrak"],
                        "playskin": r["supports_playskin"],
                        "reihenfolge": r["sort_order"]} for r in kategorien],
        "gegenstaende": [{"kategorie": r["kategorie"], "name": r["name"]} for r in items],
        "positionen": [{
            "kategorie": r["kategorie"], "gegenstand": r["gegenstand"],
            "wear": r["wear"], "stattrak": r["stattrak"], "playskin": r["playskin"],
            "menge": r["quantity"],
            "preis": None if r["price_eur"] is None else str(r["price_eur"]),
            "preis_am": None if r["priced_at"] is None else r["priced_at"].isoformat(),
        } for r in positionen],
        "staende": [{
            "datum": r["taken_on"].isoformat(),
            "brutto": str(r["total_gross"]), "netto": str(r["total_net"]),
            "playskin_brutto": str(r["playskin_gross"]),
            "playskin_netto": str(r["playskin_net"]),
            "positionen": r["rows_valid"], "unvollstaendig": r["rows_incomplete"],
            "veraltet": r["stale_rows"], "notiz": r["note"],
            "je_kategorie": aufteilung.get(r["id"], {}),
        } for r in staende],
    }


# =========================================================================
# Pruefen
# =========================================================================

def _betrag(wert, wo: str) -> Optional[Decimal]:
    if wert in (None, ""):
        return None
    try:
        d = Decimal(str(wert))
    except (InvalidOperation, ValueError):
        raise TransferFehler(f"{wo}: „{wert}“ ist kein Betrag.")
    if d < 0:
        raise TransferFehler(f"{wo}: ein Betrag unter null ergibt keinen Sinn.")
    return d.quantize(Decimal("0.01"))


def _zeitpunkt(wert, wo: str):
    if wert in (None, ""):
        return None
    try:
        t = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except ValueError:
        raise TransferFehler(f"{wo}: „{wert}“ ist kein Zeitpunkt.")
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _datum(wert, wo: str) -> date:
    """Ein Tagesdatum. Streng, weil daraus ein Primaerschluessel wird.

    Die Umwandlung gehoert HIERHER und nicht in ein ``$1::date`` in der
    Abfrage: asyncpg leitet aus dem Cast den Typ ``date`` ab und lehnt eine
    Zeichenkette dann ab. Ein Stand mit unlesbarem Datum soll ausserdem die
    Datei ablehnen und nicht die Einfuegung -- dort stuende nur noch ein
    Fehler aus dem Treiber.
    """
    try:
        return date.fromisoformat(str(wert)[:10])
    except (TypeError, ValueError):
        raise TransferFehler(f"{wo}: „{wert}“ ist kein Datum.")


def _ganz(wert, wo: str) -> int:
    if wert in (None, ""):
        return 0
    try:
        return max(0, int(wert))
    except (TypeError, ValueError):
        raise TransferFehler(f"{wo}: „{wert}“ ist keine Anzahl.")


def _staende_pruefen(roh) -> list:
    """Die festgehaltenen Staende lesen -- genauso streng wie die Positionen.

    Sie liefen bis v2.14.0 ungeprueft durch, weil die erste Datei gar keine
    enthielt: was nie vorkommt, faellt auch nicht auf. Ein unlesbares Datum
    scheiterte dann erst beim Einfuegen, mit einer Meldung aus dem
    Datenbanktreiber statt einem Satz, der sagt, welche Zeile gemeint ist.
    """
    if not isinstance(roh, list):
        raise TransferFehler("„staende“ ist keine Liste.")
    sauber = []
    for nr, s in enumerate(roh, 1):
        wo = f"Stand {nr}"
        if not isinstance(s, dict):
            raise TransferFehler(f"{wo} ist kein Datensatz.")
        if not s.get("datum"):
            continue
        je_kat = s.get("je_kategorie") or {}
        if not isinstance(je_kat, dict):
            raise TransferFehler(f"{wo}: „je_kategorie“ ist keine Zuordnung.")
        sauber.append({
            "datum": _datum(s["datum"], wo),
            "brutto": _betrag(s.get("brutto"), wo) or Decimal("0"),
            "netto": _betrag(s.get("netto"), wo) or Decimal("0"),
            "playskin_brutto": _betrag(s.get("playskin_brutto"), wo) or Decimal("0"),
            "playskin_netto": _betrag(s.get("playskin_netto"), wo) or Decimal("0"),
            "positionen": _ganz(s.get("positionen"), wo),
            "unvollstaendig": _ganz(s.get("unvollstaendig"), wo),
            "veraltet": _ganz(s.get("veraltet"), wo),
            "notiz": (s.get("notiz") or None),
            "je_kategorie": {str(k): (_betrag(v, wo) or Decimal("0"))
                             for k, v in je_kat.items() if k},
        })
    return sauber


def pruefen(dok) -> dict:
    """Die Datei lesen und dabei sagen, was ihr fehlt.

    Wirft ``TransferFehler`` mit einem deutschen Satz. Geprueft wird streng:
    eine halb gelesene Datei ist schlimmer als eine abgelehnte, weil man
    hinterher nicht sieht, was fehlt.
    """
    if not isinstance(dok, dict):
        raise TransferFehler("Die Datei enthält kein Übertragungsdokument.")
    if dok.get("modul") != "cs2":
        raise TransferFehler(
            f"Diese Datei gehört zum Modul „{dok.get('modul') or '?'}“, nicht zu CS2.")
    if dok.get("fassung") not in LESBAR:
        raise TransferFehler(
            f"Die Datei hat Fassung {dok.get('fassung')}, dieses Modul liest "
            + " und ".join(str(f) for f in LESBAR) + ".")

    positionen = dok.get("positionen")
    if not isinstance(positionen, list):
        raise TransferFehler("Der Datei fehlt die Liste „positionen“.")

    sauber = []
    for nr, p in enumerate(positionen, 1):
        wo = f"Position {nr}"
        if not isinstance(p, dict):
            raise TransferFehler(f"{wo} ist kein Datensatz.")
        kat = (p.get("kategorie") or "").strip()
        name = (p.get("gegenstand") or "").strip()
        if not kat or not name:
            raise TransferFehler(f"{wo}: Kategorie oder Gegenstand fehlt.")
        wear = (p.get("wear") or None)
        if wear is not None and wear not in WEAR_WERTE:
            raise TransferFehler(f"{wo}: „{wear}“ ist keine Abnutzung.")
        menge = p.get("menge")
        if menge is not None:
            try:
                menge = int(menge)
            except (TypeError, ValueError):
                raise TransferFehler(f"{wo}: „{p.get('menge')}“ ist keine Stückzahl.")
            if menge < 0:
                raise TransferFehler(f"{wo}: eine Stückzahl unter null ergibt keinen Sinn.")
        # ``lager`` aus Fassung 1 wird bewusst nicht uebernommen: es gehoert
        # nicht mehr zur Signatur. Es abzulehnen waere haerter als noetig --
        # ein Feld zu viel macht eine Datei nicht unlesbar.
        sauber.append({
            "kategorie": kat, "gegenstand": name, "wear": wear,
            "stattrak": bool(p.get("stattrak")), "playskin": bool(p.get("playskin")),
            "menge": menge,
            "preis": _betrag(p.get("preis"), wo),
            "preis_am": _zeitpunkt(p.get("preis_am"), wo),
        })
    positionen, zusammengefuehrt = _zusammenfuehren(sauber)
    return {
        "kategorien": dok.get("kategorien") or [],
        "gegenstaende": dok.get("gegenstaende") or [],
        "positionen": positionen,
        "zusammengefuehrt": zusammengefuehrt,
        "staende": _staende_pruefen(dok.get("staende") or []),
        "erzeugt_am": dok.get("erzeugt_am"),
    }


def _zusammenfuehren(positionen: list) -> tuple:
    """Zeilen mit gleicher Signatur zu einer machen -- und sagen, wie viele.

    Noetig fuer Fassung 1: dort konnte derselbe Gegenstand in zwei Lagern
    stehen, und ohne diesen Schritt traefen beide Zeilen im Import auf
    dieselbe Signatur. ``ON CONFLICT DO UPDATE`` nimmt dann die zuletzt
    eingefuegte, und die erste waere STILL verschwunden -- der Bestand haette
    hinterher weniger Stuecke, ohne dass es irgendwo staende.

    Zusammengefuehrt wird nach derselben Regel wie ein Nachkauf: Stueckzahlen
    addieren sich, Preis und Preisstand kommen von der zuletzt gepflegten
    Zeile.
    """
    raus: dict = {}
    doppelt = 0
    for p in positionen:
        s = (p["kategorie"], p["gegenstand"], p["wear"], p["stattrak"], p["playskin"])
        alt = raus.get(s)
        if alt is None:
            raus[s] = dict(p)
            continue
        doppelt += 1
        if alt["menge"] is None:
            alt["menge"] = p["menge"]
        elif p["menge"] is not None:
            alt["menge"] += p["menge"]
        # Der juengere Preisstand gewinnt; ohne Stand gewinnt der vorhandene.
        if p["preis_am"] is not None and (alt["preis_am"] is None
                                          or p["preis_am"] > alt["preis_am"]):
            alt["preis"] = p["preis"]
            alt["preis_am"] = p["preis_am"]
        elif alt["preis"] is None:
            alt["preis"] = p["preis"]
    return list(raus.values()), doppelt


# =========================================================================
# Vorschau und Einspielen
# =========================================================================

async def _bestand_nach_signatur(db, user_id: int) -> dict:
    rows = await db.fetch(
        "SELECT c.name AS kategorie, i.name AS gegenstand, p.wear, p.stattrak, "
        "       p.playskin, p.quantity, p.price_eur "
        "  FROM cs2_positions p "
        "  JOIN cs2_items i      ON i.id = p.item_id "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        " WHERE p.user_id=$1", user_id)
    return {(r["kategorie"], r["gegenstand"], r["wear"], r["stattrak"],
             r["playskin"]): r for r in rows}


def _signatur(p: dict) -> tuple:
    return (p["kategorie"], p["gegenstand"], p["wear"], p["stattrak"], p["playskin"])


async def vorschau(db, user_id: int, daten: dict) -> dict:
    """Was der Import tun wuerde -- ohne etwas zu tun.

    Pflicht vor dem Einspielen. Gezeigt werden Zahlen UND Beispiele: eine
    Zahl allein sagt nicht, ob die Zuordnung stimmt.
    """
    vorhanden = await _bestand_nach_signatur(db, user_id)

    neu, geaendert, gleich = [], [], 0
    for p in daten["positionen"]:
        alt = vorhanden.get(_signatur(p))
        if alt is None:
            neu.append(p)
        elif alt["quantity"] != p["menge"] or alt["price_eur"] != p["preis"]:
            geaendert.append((p, alt))
        else:
            gleich += 1

    def zeige(p, alt=None) -> dict:
        d = {"gegenstand": p["gegenstand"], "kategorie": p["kategorie"],
             "wear": p["wear"], "menge": p["menge"],
             "preis": None if p["preis"] is None else float(p["preis"])}
        if alt is not None:
            d["menge_alt"] = alt["quantity"]
            d["preis_alt"] = None if alt["price_eur"] is None else float(alt["price_eur"])
        return d

    kat_da = {r["name"] for r in await db.fetch(
        "SELECT name FROM cs2_categories WHERE user_id=$1", user_id)}

    return {
        "erzeugt_am": daten.get("erzeugt_am"),
        "positionen": len(daten["positionen"]),
        "neu": len(neu), "geaendert": len(geaendert), "gleich": gleich,
        # Was die Datei NICHT nennt, bleibt stehen -- das ist kein Verlust,
        # aber man soll es wissen.
        "bleibt_stehen": len(vorhanden) - (len(geaendert) + gleich),
        "neue_kategorien": sorted({k.get("name") for k in daten["kategorien"]
                                   if k.get("name") and k["name"] not in kat_da}),
        # Aus einer Datei der Fassung 1: Zeilen, die sich nur im Lager
        # unterschieden und deshalb schon beim Lesen zu einer wurden.
        "zusammengefuehrt": daten.get("zusammengefuehrt", 0),
        "staende": len(daten["staende"]),
        "beispiele_neu": [zeige(p) for p in neu[:5]],
        "beispiele_geaendert": [zeige(p, a) for p, a in geaendert[:5]],
    }


async def einspielen(db, user_id: int, daten: dict) -> dict:
    """Die Datei uebernehmen. Alles in EINER Transaktion.

    Halb eingespielt waere der schlechteste Ausgang: man saehe der Liste
    hinterher nicht an, wo sie aufgehoert hat.
    """
    regeln = {k["name"]: k for k in daten["kategorien"] if k.get("name")}
    async with db.transaction():
        kat_id = {}
        for name in sorted({p["kategorie"] for p in daten["positionen"]}
                           | set(regeln)
                           | {g.get("kategorie") for g in daten["gegenstaende"]
                              if g.get("kategorie")}):
            r = regeln.get(name, {})
            kat_id[name] = await db.fetchval(
                "INSERT INTO cs2_categories (user_id, name, supports_wear, "
                "       supports_stattrak, supports_playskin, sort_order) "
                "VALUES ($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (user_id, name) DO UPDATE SET "
                "       supports_wear=EXCLUDED.supports_wear, "
                "       supports_stattrak=EXCLUDED.supports_stattrak, "
                "       supports_playskin=EXCLUDED.supports_playskin "
                "RETURNING id",
                user_id, name, bool(r.get("wear")), bool(r.get("stattrak")),
                bool(r.get("playskin")), int(r.get("reihenfolge") or 0))

        item_id = {}
        for g in daten["gegenstaende"]:
            if g.get("kategorie") in kat_id and g.get("name"):
                item_id[(g["kategorie"], g["name"])] = await db.fetchval(
                    "INSERT INTO cs2_items (user_id, category_id, name) VALUES ($1,$2,$3) "
                    "ON CONFLICT (user_id, category_id, name) DO UPDATE SET name=EXCLUDED.name "
                    "RETURNING id", user_id, kat_id[g["kategorie"]], g["name"])

        neu = geaendert = 0
        for p in daten["positionen"]:
            schluessel = (p["kategorie"], p["gegenstand"])
            if schluessel not in item_id:
                item_id[schluessel] = await db.fetchval(
                    "INSERT INTO cs2_items (user_id, category_id, name) VALUES ($1,$2,$3) "
                    "ON CONFLICT (user_id, category_id, name) DO UPDATE SET name=EXCLUDED.name "
                    "RETURNING id", user_id, kat_id[p["kategorie"]], p["gegenstand"])
            war_da = await db.fetchval(
                "SELECT 1 FROM cs2_positions WHERE user_id=$1 AND item_id=$2 "
                "  AND wear IS NOT DISTINCT FROM $3 AND stattrak=$4 AND playskin=$5",
                user_id, item_id[schluessel], p["wear"], p["stattrak"], p["playskin"])
            await db.execute(
                "INSERT INTO cs2_positions (user_id, item_id, wear, "
                "       stattrak, playskin, quantity, price_eur, priced_at) "
                "VALUES ($1,$2,$3,$4,$5,$6::int,$7::numeric,$8) "
                "ON CONFLICT (user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin) "
                "DO UPDATE SET quantity=EXCLUDED.quantity, "
                "              price_eur=EXCLUDED.price_eur, "
                "              priced_at=EXCLUDED.priced_at",
                user_id, item_id[schluessel], p["wear"], p["stattrak"],
                p["playskin"], p["menge"], p["preis"], p["preis_am"])
            if war_da:
                geaendert += 1
            else:
                neu += 1

        staende = 0
        for s in daten["staende"]:
            if not s.get("datum"):
                continue
            snap_id = await db.fetchval(
                "INSERT INTO cs2_snapshots (user_id, taken_on, total_gross, total_net, "
                "       playskin_gross, playskin_net, rows_valid, rows_incomplete, "
                "       stale_rows, note) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
                "ON CONFLICT (user_id, taken_on) DO UPDATE SET "
                "       total_gross=EXCLUDED.total_gross, total_net=EXCLUDED.total_net, "
                "       playskin_gross=EXCLUDED.playskin_gross, "
                "       playskin_net=EXCLUDED.playskin_net, "
                "       rows_valid=EXCLUDED.rows_valid, "
                "       rows_incomplete=EXCLUDED.rows_incomplete, "
                "       stale_rows=EXCLUDED.stale_rows, note=EXCLUDED.note "
                "RETURNING id",
                user_id, s["datum"], s["brutto"], s["netto"],
                s["playskin_brutto"], s["playskin_netto"], s["positionen"],
                s["unvollstaendig"], s["veraltet"], s["notiz"])
            # Die Aufteilung wird ersetzt, nicht ergaenzt: ein Stand hat genau
            # eine, und zwei uebereinander waeren doppelte Betraege.
            je_kat = s.get("je_kategorie") or {}
            if je_kat:
                await db.execute(
                    "DELETE FROM cs2_snapshot_categories WHERE snapshot_id=$1", snap_id)
                for name, wert in je_kat.items():
                    kid = kat_id.get(name)
                    if kid is None:
                        # Eine Kategorie, die es nur in der Historie gibt. Sie
                        # anzulegen waere das Kleinere: sonst faellt der
                        # Betrag aus der Aufteilung, und die Summe der Balken
                        # ergaebe nicht mehr den Stand.
                        kid = await db.fetchval(
                            "INSERT INTO cs2_categories (user_id, name) VALUES ($1,$2) "
                            "ON CONFLICT (user_id, name) DO UPDATE SET name=EXCLUDED.name "
                            "RETURNING id", user_id, name)
                        kat_id[name] = kid
                    await db.execute(
                        "INSERT INTO cs2_snapshot_categories (snapshot_id, category_id, gross) "
                        "VALUES ($1,$2,$3) "
                        "ON CONFLICT (snapshot_id, category_id) DO UPDATE SET gross=EXCLUDED.gross",
                        snap_id, kid, wert)
            staende += 1

    return {"neu": neu, "geaendert": geaendert, "staende": staende}
