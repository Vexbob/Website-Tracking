"""CS2 — den Bestand aus einer Datei uebernehmen.

Der Weg, auf dem der Bestand vom Rechner auf den Server kommt: dort ausgeben,
hier einspielen, danach nur noch hier weiterarbeiten.

Das Format ist JSON und kennt **keine IDs**. Zwei Datenbanken vergeben
verschiedene, und eine Datei, die welche mitbringt, trifft auf dem Ziel
entweder nichts oder das Falsche. Verknuepft wird ueber Namen -- Kategorie,
Gegenstand, Lager --, und die legt der Import an, wenn es sie noch nicht gibt.

    {
      "modul": "cs2", "fassung": 1, "erzeugt_am": "2026-09-23T10:00:00+00:00",
      "kategorien":   [{"name": "Skin", "wear": true, "stattrak": true,
                        "playskin": true, "reihenfolge": 0}],
      "lager":        [{"name": "Unsortiert", "auffang": true, "reihenfolge": 0}],
      "gegenstaende": [{"kategorie": "Skin", "name": "AK-47 | Frontside Misty"}],
      "positionen":   [{"kategorie": "Skin", "gegenstand": "AK-47 | Frontside Misty",
                        "wear": "FT", "stattrak": false, "playskin": true,
                        "lager": "Skins & Anything", "menge": 1,
                        "preis": "16.10", "preis_am": "2026-09-22T10:13:16+00:00"}],
      "staende":      [{"datum": "2026-09-22", "brutto": "3089.81", …}]
    }

Zwei Regeln, die den Import ungefaehrlich halten:

1. **Er ersetzt nichts, was er nicht nennt.** Zusammengefuehrt wird ueber die
   Signatur einer Position; was in der Datei fehlt, bleibt im Bestand stehen.
   Eine Datei kann also nichts loeschen -- auch nicht versehentlich.
2. **Vorschau ist Pflicht, nicht Hoeflichkeit.** ``vorschau`` sagt vorher, was
   neu waere und was sich aendern wuerde, samt Beispielen. Ein Import, der
   still 116 Zeilen umschreibt, ist nicht ueberpruefbar.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Optional

FASSUNG = 1

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
    lager = await db.fetch(
        "SELECT name, is_default, sort_order FROM cs2_storages "
        " WHERE user_id=$1 ORDER BY sort_order, name", user_id)
    items = await db.fetch(
        "SELECT c.name AS kategorie, i.name FROM cs2_items i "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        " WHERE i.user_id=$1 ORDER BY c.name, i.name", user_id)
    positionen = await db.fetch(
        "SELECT c.name AS kategorie, i.name AS gegenstand, p.wear, p.stattrak, "
        "       p.playskin, s.name AS lager, p.quantity, p.price_eur, p.priced_at "
        "  FROM cs2_positions p "
        "  JOIN cs2_items i      ON i.id = p.item_id "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        "  JOIN cs2_storages s   ON s.id = p.storage_id "
        " WHERE p.user_id=$1 ORDER BY c.name, i.name", user_id)
    staende = await db.fetch(
        "SELECT taken_on, total_gross, total_net, playskin_gross, playskin_net, "
        "       rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots WHERE user_id=$1 ORDER BY taken_on", user_id)

    return {
        "modul": "cs2",
        "fassung": FASSUNG,
        "erzeugt_am": datetime.now(timezone.utc).isoformat(),
        "kategorien": [{"name": r["name"], "wear": r["supports_wear"],
                        "stattrak": r["supports_stattrak"],
                        "playskin": r["supports_playskin"],
                        "reihenfolge": r["sort_order"]} for r in kategorien],
        "lager": [{"name": r["name"], "auffang": r["is_default"],
                   "reihenfolge": r["sort_order"]} for r in lager],
        "gegenstaende": [{"kategorie": r["kategorie"], "name": r["name"]} for r in items],
        "positionen": [{
            "kategorie": r["kategorie"], "gegenstand": r["gegenstand"],
            "wear": r["wear"], "stattrak": r["stattrak"], "playskin": r["playskin"],
            "lager": r["lager"], "menge": r["quantity"],
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
    if dok.get("fassung") != FASSUNG:
        raise TransferFehler(
            f"Die Datei hat Fassung {dok.get('fassung')}, dieses Modul liest {FASSUNG}.")

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
        sauber.append({
            "kategorie": kat, "gegenstand": name, "wear": wear,
            "stattrak": bool(p.get("stattrak")), "playskin": bool(p.get("playskin")),
            "lager": (p.get("lager") or "").strip() or None,
            "menge": menge,
            "preis": _betrag(p.get("preis"), wo),
            "preis_am": _zeitpunkt(p.get("preis_am"), wo),
        })
    return {
        "kategorien": dok.get("kategorien") or [],
        "lager": dok.get("lager") or [],
        "gegenstaende": dok.get("gegenstaende") or [],
        "positionen": sauber,
        "staende": dok.get("staende") or [],
        "erzeugt_am": dok.get("erzeugt_am"),
    }


# =========================================================================
# Vorschau und Einspielen
# =========================================================================

async def _bestand_nach_signatur(db, user_id: int) -> dict:
    rows = await db.fetch(
        "SELECT c.name AS kategorie, i.name AS gegenstand, p.wear, p.stattrak, "
        "       p.playskin, s.name AS lager, p.quantity, p.price_eur "
        "  FROM cs2_positions p "
        "  JOIN cs2_items i      ON i.id = p.item_id "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        "  JOIN cs2_storages s   ON s.id = p.storage_id "
        " WHERE p.user_id=$1", user_id)
    return {(r["kategorie"], r["gegenstand"], r["wear"], r["stattrak"],
             r["playskin"], r["lager"]): r for r in rows}


def _signatur(p: dict, auffang: str) -> tuple:
    return (p["kategorie"], p["gegenstand"], p["wear"], p["stattrak"],
            p["playskin"], p["lager"] or auffang)


async def vorschau(db, user_id: int, daten: dict) -> dict:
    """Was der Import tun wuerde -- ohne etwas zu tun.

    Pflicht vor dem Einspielen. Gezeigt werden Zahlen UND Beispiele: eine
    Zahl allein sagt nicht, ob die Zuordnung stimmt.
    """
    auffang = await db.fetchval(
        "SELECT name FROM cs2_storages WHERE user_id=$1 AND is_default LIMIT 1",
        user_id) or "Unsortiert"
    vorhanden = await _bestand_nach_signatur(db, user_id)

    neu, geaendert, gleich = [], [], 0
    for p in daten["positionen"]:
        alt = vorhanden.get(_signatur(p, auffang))
        if alt is None:
            neu.append(p)
        elif alt["quantity"] != p["menge"] or alt["price_eur"] != p["preis"]:
            geaendert.append((p, alt))
        else:
            gleich += 1

    def zeige(p, alt=None) -> dict:
        d = {"gegenstand": p["gegenstand"], "kategorie": p["kategorie"],
             "lager": p["lager"] or auffang, "wear": p["wear"],
             "menge": p["menge"],
             "preis": None if p["preis"] is None else float(p["preis"])}
        if alt is not None:
            d["menge_alt"] = alt["quantity"]
            d["preis_alt"] = None if alt["price_eur"] is None else float(alt["price_eur"])
        return d

    kat_da = {r["name"] for r in await db.fetch(
        "SELECT name FROM cs2_categories WHERE user_id=$1", user_id)}
    lag_da = {r["name"] for r in await db.fetch(
        "SELECT name FROM cs2_storages WHERE user_id=$1", user_id)}

    return {
        "erzeugt_am": daten.get("erzeugt_am"),
        "positionen": len(daten["positionen"]),
        "neu": len(neu), "geaendert": len(geaendert), "gleich": gleich,
        # Was die Datei NICHT nennt, bleibt stehen -- das ist kein Verlust,
        # aber man soll es wissen.
        "bleibt_stehen": len(vorhanden) - (len(geaendert) + gleich),
        "neue_kategorien": sorted({k.get("name") for k in daten["kategorien"]
                                   if k.get("name") and k["name"] not in kat_da}),
        "neue_lager": sorted({l.get("name") for l in daten["lager"]
                              if l.get("name") and l["name"] not in lag_da}),
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

        auffang_id = await db.fetchval(
            "SELECT id FROM cs2_storages WHERE user_id=$1 AND is_default LIMIT 1", user_id)
        lag_id = {}
        for l in daten["lager"]:
            if not l.get("name"):
                continue
            # Das Auffanglager des Ziels bleibt das Auffanglager. Zwei waeren
            # einer zu viel, und der Index laesst ohnehin nur eines zu.
            lag_id[l["name"]] = await db.fetchval(
                "INSERT INTO cs2_storages (user_id, name, is_default, sort_order) "
                "VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (user_id, name) DO UPDATE SET name=EXCLUDED.name "
                "RETURNING id",
                user_id, l["name"],
                bool(l.get("auffang")) and auffang_id is None,
                int(l.get("reihenfolge") or 0))
        for p in daten["positionen"]:
            if p["lager"] and p["lager"] not in lag_id:
                lag_id[p["lager"]] = await db.fetchval(
                    "INSERT INTO cs2_storages (user_id, name) VALUES ($1,$2) "
                    "ON CONFLICT (user_id, name) DO UPDATE SET name=EXCLUDED.name "
                    "RETURNING id", user_id, p["lager"])
        if auffang_id is None:
            auffang_id = await db.fetchval(
                "INSERT INTO cs2_storages (user_id, name, is_default) "
                "VALUES ($1,'Unsortiert',TRUE) "
                "ON CONFLICT (user_id, name) DO UPDATE SET is_default=TRUE RETURNING id",
                user_id)

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
            ziel = lag_id.get(p["lager"], auffang_id)
            war_da = await db.fetchval(
                "SELECT 1 FROM cs2_positions WHERE user_id=$1 AND item_id=$2 "
                "  AND wear IS NOT DISTINCT FROM $3 AND stattrak=$4 AND playskin=$5 "
                "  AND storage_id=$6",
                user_id, item_id[schluessel], p["wear"], p["stattrak"],
                p["playskin"], ziel)
            await db.execute(
                "INSERT INTO cs2_positions (user_id, item_id, storage_id, wear, "
                "       stattrak, playskin, quantity, price_eur, priced_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7::int,$8::numeric,$9) "
                "ON CONFLICT (user_id, item_id, COALESCE(wear, ''::text), stattrak, "
                "             playskin, storage_id) "
                "DO UPDATE SET quantity=EXCLUDED.quantity, "
                "              price_eur=EXCLUDED.price_eur, "
                "              priced_at=EXCLUDED.priced_at",
                user_id, item_id[schluessel], ziel, p["wear"], p["stattrak"],
                p["playskin"], p["menge"], p["preis"], p["preis_am"])
            if war_da:
                geaendert += 1
            else:
                neu += 1

        staende = 0
        for s in daten["staende"]:
            if not s.get("datum"):
                continue
            await db.execute(
                "INSERT INTO cs2_snapshots (user_id, taken_on, total_gross, total_net, "
                "       playskin_gross, playskin_net, rows_valid, rows_incomplete, "
                "       stale_rows, note) "
                "VALUES ($1,$2::date,$3::numeric,$4::numeric,$5::numeric,$6::numeric,"
                "        $7::int,$8::int,$9::int,$10) "
                "ON CONFLICT (user_id, taken_on) DO UPDATE SET "
                "       total_gross=EXCLUDED.total_gross, total_net=EXCLUDED.total_net, "
                "       playskin_gross=EXCLUDED.playskin_gross, "
                "       playskin_net=EXCLUDED.playskin_net, "
                "       rows_valid=EXCLUDED.rows_valid, "
                "       rows_incomplete=EXCLUDED.rows_incomplete, "
                "       stale_rows=EXCLUDED.stale_rows, note=EXCLUDED.note",
                user_id, s["datum"], s.get("brutto") or 0, s.get("netto") or 0,
                s.get("playskin_brutto") or 0, s.get("playskin_netto") or 0,
                int(s.get("positionen") or 0), int(s.get("unvollstaendig") or 0),
                int(s.get("veraltet") or 0), s.get("notiz"))
            staende += 1

    return {"neu": neu, "geaendert": geaendert, "staende": staende}
