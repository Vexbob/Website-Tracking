"""Depot — der Trade-Republic-Kontoauszug (v2.38.0, Modul im Bau).

Endpoints:
  POST   /api/depot/import?speichern=0|1  — Auszug (PDF) lesen; ohne ``speichern``
                                            nur die Vorschau, mit: uebernehmen
  GET    /api/depot/uebersicht            — Stand, Summen je Art, Wertpapiere
  GET    /api/depot/buchungen             — Buchungen, neueste zuerst (Filter: art, isin)
  GET    /api/depot/imports               — die abgelegten Auszuege
  DELETE /api/depot/imports/{iid}         — einen Auszug samt seinen Buchungen loeschen

Ein Auszug wird gelesen UND geprueft (``services/depot_import.py``), bevor
irgendetwas gespeichert wird. Die Vorschau zeigt, was ein Auszug ersetzen
wuerde -- er ersetzt alle Buchungen seines Zeitraums, sonst stuende jede
Buchung aus zwei Auszuegen doppelt da.

Hinweis: Bewusst OHNE ``from __future__ import annotations`` -- FastAPI 0.109
loest ``UploadFile = File(...)`` sonst nicht auf (siehe health_router.py).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query

from auth import get_current_user
from database import get_db
from deps import limiter, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD, _ser_exp
from services import depot_import as leser

router = APIRouter(tags=["depot"])

HANDEL = ("kauf", "sparplan", "verkauf")


def _f(d) -> float:
    return float(d) if d is not None else 0.0


def _summen_je_art(buchungen) -> dict:
    """{art: {anzahl, summe}} -- aus Dicts (Vorschau) oder Zeilen (Bestand)."""
    raus = defaultdict(lambda: {"anzahl": 0, "summe": Decimal(0)})
    for b in buchungen:
        raus[b["art"]]["anzahl"] += 1
        raus[b["art"]]["summe"] += Decimal(b["betrag"])
    return {k: {"anzahl": v["anzahl"], "summe": _f(v["summe"]),
                "label": leser.ARTEN.get(k, k)} for k, v in raus.items()}


def namen(buchungen) -> dict:
    """Je ISIN EIN Name, gewaehlt ueber den ganzen Bestand -- sonst hiesse
    dasselbe Wertpapier im Ring anders als in der Liste darunter."""
    alle = defaultdict(list)
    for b in buchungen:
        if b["isin"] and b["name"]:
            alle[b["isin"]].append(b["name"])
    return {isin: leser.bester_name(n) for isin, n in alle.items()}


def wertpapiere(buchungen) -> list:
    """Je ISIN: gekauft, verkauft, Ertraege, Ausfuehrungen, Stueck.

    ``stueck`` ist nur dann eine Zahl, wenn JEDE Kauf- und Verkaufszeile sie
    nennt -- die aelteren deutschen Zeilen des Auszugs tun es nicht. Sonst
    steht ``stueck_bekannt: false`` da, und im Bestand ist eine Position, wenn
    ihre letzte Ausfuehrung ein Kauf war.
    """
    g = defaultdict(lambda: {"namen": [], "gekauft": Decimal(0), "verkauft": Decimal(0),
                             "ertraege": Decimal(0), "ausfuehrungen": 0, "stueck": Decimal(0),
                             "ohne_stueck": 0, "letzte": None, "letzte_art": None})
    for b in buchungen:
        if not b["isin"] or b["art"] not in HANDEL + ("ertrag", "geschenk"):
            continue
        x = g[b["isin"]]
        x["namen"].append(b["name"])
        betrag = Decimal(b["betrag"])
        if b["art"] in HANDEL:
            x["ausfuehrungen"] += 1
            if b["art"] == "verkauf":
                x["verkauft"] += betrag
            else:
                x["gekauft"] -= betrag
            if b["stueck"] is None:
                x["ohne_stueck"] += 1
            else:
                x["stueck"] += Decimal(b["stueck"]) * (-1 if b["art"] == "verkauf" else 1)
            if x["letzte"] is None or b["datum"] >= x["letzte"]:
                x["letzte"], x["letzte_art"] = b["datum"], b["art"]
        else:
            x["ertraege"] += betrag
    name_von = namen(buchungen)
    raus = []
    for isin, x in g.items():
        if not x["ausfuehrungen"]:
            continue
        bekannt = x["ohne_stueck"] == 0
        im_bestand = (x["stueck"] > Decimal("0.000001")) if bekannt else x["letzte_art"] != "verkauf"
        raus.append({
            "isin": isin, "name": name_von.get(isin) or isin,
            "gekauft": _f(x["gekauft"]), "verkauft": _f(x["verkauft"]),
            "ertraege": _f(x["ertraege"]), "ausfuehrungen": x["ausfuehrungen"],
            "stueck": _f(x["stueck"]) if bekannt else None, "stueck_bekannt": bekannt,
            "im_bestand": bool(im_bestand),
            # Fuer Verkauftes ist das Ergebnis die Auskunft: was herauskam
            # minus was hineinging, Ertraege dazu.
            "ergebnis": _f(x["verkauft"] - x["gekauft"] + x["ertraege"]),
            "letzte": x["letzte"].isoformat() if x["letzte"] else None,
            "letzte_art": x["letzte_art"],
        })
    # Erst der Bestand, darin und darunter die zuletzt bewegten zuerst.
    raus.sort(key=lambda w: w["letzte"] or "", reverse=True)
    raus.sort(key=lambda w: not w["im_bestand"])
    return raus


def _monat(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _monate(von, bis) -> list:
    """Alle Monate von ``von`` bis ``bis`` -- lueckenlos, auch die ohne
    Buchung. Sonst stuenden zwei Balken nebeneinander, zwischen denen ein
    halbes Jahr lag."""
    raus, j, m = [], von.year, von.month
    while (j, m) <= (bis.year, bis.month):
        raus.append(f"{j:04d}-{m:02d}")
        m += 1
        if m > 12:
            j, m = j + 1, 1
    return raus


ERTRAEGE = ("ertrag", "praemie", "geschenk", "steuer")


def verlauf(rows) -> list:
    """Je Monatsende: eingezahlt (Einzahlungen − Auszahlungen) und investiert
    (Kaeufe − Verkaeufe), jeweils aufgelaufen seit der ersten Buchung. Der
    Abstand der beiden ist, was als Cash und Gewinn uebrig ist -- liegt
    „investiert“ ueber „eingezahlt“, arbeitet dort Geld, das Verkaeufe
    gebracht haben."""
    if not rows:
        return []
    eingezahlt = investiert = Decimal(0)
    stand = {}
    for b in rows:
        betrag = Decimal(b["betrag"])
        if b["art"] in ("einzahlung", "auszahlung"):
            eingezahlt += betrag
        elif b["art"] in HANDEL:
            investiert -= betrag
        stand[_monat(b["datum"])] = (eingezahlt, investiert)
    raus, letzter = [], (Decimal(0), Decimal(0))
    for m in _monate(rows[0]["datum"], rows[-1]["datum"]):
        letzter = stand.get(m, letzter)
        raus.append({"monat": m, "eingezahlt": _f(letzter[0]), "investiert": _f(letzter[1])})
    return raus


def statistik(rows, von, bis) -> dict:
    """Alles fuer den Reiter Statistik, ueber EINEN Zeitraum gerechnet.

    ``rows`` ist der ganze Bestand (nach Datum): das Ergebnis eines
    verkauften Wertpapiers braucht auch die Kaeufe vor dem Zeitraum. Gezeigt
    wird es, wenn sein letzter Verkauf im Zeitraum liegt."""
    im = [b for b in rows if von <= b["datum"] <= bis]
    monate = {m: defaultdict(Decimal) for m in _monate(von, bis)}
    for b in im:
        art, betrag = b["art"], Decimal(b["betrag"])
        t = monate[_monat(b["datum"])]
        if art in ("kauf", "sparplan"):
            t[art] -= betrag
        elif art == "verkauf":
            t["verkauf"] += betrag
        elif art == "zinsen":
            t["zinsen"] += betrag
        elif art in ERTRAEGE:
            t["ertraege"] += betrag
        elif art in ("einzahlung", "auszahlung"):
            t[art] += betrag
    reihe = [{"monat": m, "kauf": _f(t["kauf"]), "sparplan": _f(t["sparplan"]),
              "verkauf": _f(t["verkauf"]), "zinsen": _f(t["zinsen"]),
              "ertraege": _f(t["ertraege"])} for m, t in monate.items()]

    name_von = namen(rows)
    sparplan = defaultdict(Decimal)
    for b in im:
        if b["art"] == "sparplan" and b["isin"]:
            sparplan[b["isin"]] -= Decimal(b["betrag"])
    sparplan_liste = sorted(
        ({"isin": i, "name": name_von.get(i) or i, "summe": _f(x)} for i, x in sparplan.items()),
        key=lambda x: -x["summe"])

    ergebnisse = [{"isin": w["isin"], "name": w["name"], "ergebnis": w["ergebnis"],
                   "letzte": w["letzte"]}
                  for w in wertpapiere(rows)
                  if not w["im_bestand"] and w["letzte"]
                  and von.isoformat() <= w["letzte"] <= bis.isoformat()]
    ergebnisse.sort(key=lambda x: -x["ergebnis"])

    sparplan_monate = [r["sparplan"] for r in reihe if r["sparplan"] > 0]
    summe = lambda *arten: sum((Decimal(b["betrag"]) for b in im if b["art"] in arten), Decimal(0))
    return {
        "von": von.isoformat(), "bis": bis.isoformat(),
        "monate": reihe,
        "verlauf": [v for v in verlauf(rows) if _monat(von) <= v["monat"] <= _monat(bis)],
        "sparplan": sparplan_liste,
        "ergebnisse": ergebnisse,
        "kennzahlen": {
            # Durchschnitt ueber die Monate, in denen der Sparplan lief -- ein
            # Zeitraum, der vor dem ersten Sparplan beginnt, druckte ihn sonst.
            "sparplan_schnitt": round(sum(sparplan_monate) / len(sparplan_monate), 2) if sparplan_monate else 0.0,
            "sparplan_monate": len(sparplan_monate),
            "ausfuehrungen": sum(1 for b in im if b["art"] in HANDEL),
            "ertraege_zinsen": _f(summe("zinsen", *ERTRAEGE)),
            "eingezahlt_netto": _f(summe("einzahlung", "auszahlung")),
            "realisiert": _f(sum((Decimal(str(e["ergebnis"])) for e in ergebnisse), Decimal(0))),
        },
    }


async def _lesen(file: UploadFile) -> tuple:
    roh = await file.read(leser.MAX_BYTES + 1)
    try:
        return roh, leser.lesen(roh)
    except leser.LeseFehler as e:
        raise HTTPException(400, str(e))


@router.post("/api/depot/import")
@limiter.limit(LIMIT_WRITE_RARE)
async def importieren(request: Request, speichern: bool = Query(False),
                      file: UploadFile = File(...),
                      db=Depends(get_db), user=Depends(get_current_user)):
    roh, auszug = await _lesen(file)
    uid = user["id"]
    summe = leser.pruefsumme(roh)
    schon = await db.fetchrow(
        "SELECT hochgeladen_at FROM depot_imports WHERE user_id=$1 AND pruefsumme=$2", uid, summe)
    ersetzt = int(await db.fetchval(
        "SELECT COUNT(*) FROM depot_buchungen WHERE user_id=$1 AND datum BETWEEN $2 AND $3",
        uid, auszug["von"], auszug["bis"]) or 0)
    buchungen = auszug["buchungen"]
    vorschau = {
        "dateiname": file.filename, "von": auszug["von"].isoformat(), "bis": auszug["bis"].isoformat(),
        "anzahl": len(buchungen), "summe_ein": _f(auszug["summe_ein"]),
        "summe_aus": _f(auszug["summe_aus"]), "endsaldo": _f(auszug["endsaldo"]),
        "arten": _summen_je_art(buchungen),
        "wertpapiere": len({b["isin"] for b in buchungen if b["isin"] and b["art"] in HANDEL}),
        "ersetzt": ersetzt,
        "schon_da": schon["hochgeladen_at"].isoformat() if schon else None,
    }
    if not speichern:
        return vorschau
    if schon:
        raise HTTPException(400, "Genau dieser Auszug ist schon übernommen.")
    async with db.transaction():
        await db.execute(
            "DELETE FROM depot_buchungen WHERE user_id=$1 AND datum BETWEEN $2 AND $3",
            uid, auszug["von"], auszug["bis"])
        iid = await db.fetchval(
            "INSERT INTO depot_imports (user_id, dateiname, groesse, pruefsumme, zeitraum_von, "
            "zeitraum_bis, buchungen, endsaldo, ersetzt) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id",
            uid, (file.filename or "kontoauszug.pdf")[:200], len(roh), summe,
            auszug["von"], auszug["bis"], len(buchungen), auszug["endsaldo"], ersetzt)
        await db.execute(
            "INSERT INTO depot_import_dateien (import_id, user_id, daten) VALUES ($1,$2,$3)",
            iid, uid, roh)
        # Die Reihenfolge innerhalb eines Tages steht im Auszug -- sie haelt
        # den Saldo nachvollziehbar, wenn an einem Tag mehreres passiert.
        reihe = defaultdict(int)
        zeilen = []
        for b in buchungen:
            reihe[b["datum"]] += 1
            zeilen.append((uid, iid, b["datum"], reihe[b["datum"]], b["art"], b["typ"],
                           b["beschreibung"], b["isin"], b["name"], b["stueck"],
                           b["betrag"], b["saldo"]))
        await db.executemany(
            "INSERT INTO depot_buchungen (user_id, import_id, datum, reihe, art, typ, beschreibung, "
            "isin, name, stueck, betrag, saldo) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
            zeilen)
    vorschau["import_id"] = iid
    return vorschau


@router.get("/api/depot/uebersicht")
async def uebersicht(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT datum, art, isin, name, stueck, betrag, saldo FROM depot_buchungen "
        "WHERE user_id=$1 ORDER BY datum, reihe", user["id"])
    if not rows:
        return {"leer": True}
    letzte = rows[-1]
    return {
        "leer": False,
        "von": rows[0]["datum"].isoformat(), "bis": letzte["datum"].isoformat(),
        "anzahl": len(rows), "saldo": _f(letzte["saldo"]),
        "arten": _summen_je_art(rows),
        "wertpapiere": wertpapiere(rows),
        "verlauf": verlauf(rows),
    }


@router.get("/api/depot/statistik")
async def statistik_abruf(von: Optional[str] = None, bis: Optional[str] = None,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Der Reiter Statistik ueber einen Zeitraum. Ohne ``von`` gilt der ganze
    Bestand. Gerechnet wird hier, nicht im Browser -- eine Auswertung hat
    EINE Grundgesamtheit."""
    rows = await db.fetch(
        "SELECT datum, art, isin, name, stueck, betrag FROM depot_buchungen "
        "WHERE user_id=$1 ORDER BY datum, reihe", user["id"])
    if not rows:
        return {"leer": True}
    try:
        anfang = date.fromisoformat(von) if von else rows[0]["datum"]
        ende = date.fromisoformat(bis) if bis else rows[-1]["datum"]
    except ValueError:
        raise HTTPException(400, "Zeitraum nicht lesbar")
    if anfang > ende:
        raise HTTPException(400, "„Von“ liegt nach „Bis“")
    anfang = max(anfang, rows[0]["datum"])
    return dict(statistik(rows, anfang, ende), leer=False)


@router.get("/api/depot/buchungen")
async def buchungen(art: Optional[str] = None, isin: Optional[str] = None,
                    limit: int = 100, offset: int = 0,
                    db=Depends(get_db), user=Depends(get_current_user)):
    bedingung, werte = ["user_id=$1"], [user["id"]]
    if art:
        arten = [a for a in art.split(",") if a in leser.ARTEN]
        if arten:
            werte.append(arten)
            bedingung.append(f"art = ANY(${len(werte)}::text[])")
    if isin:
        werte.append(isin)
        bedingung.append(f"isin = ${len(werte)}")
    wo = " AND ".join(bedingung)
    gesamt = int(await db.fetchval(f"SELECT COUNT(*) FROM depot_buchungen WHERE {wo}", *werte) or 0)
    werte += [max(1, min(int(limit), 500)), max(0, int(offset))]
    rows = await db.fetch(
        f"SELECT id, datum, art, typ, beschreibung, isin, name, stueck, betrag, saldo "
        f"FROM depot_buchungen WHERE {wo} ORDER BY datum DESC, reihe DESC "
        f"LIMIT ${len(werte) - 1} OFFSET ${len(werte)}", *werte)
    return {"gesamt": gesamt,
            "buchungen": [dict(_ser_exp(r), art_label=leser.ARTEN.get(r["art"], r["art"])) for r in rows]}


@router.get("/api/depot/imports")
async def imports(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT id, dateiname, hochgeladen_at, groesse, zeitraum_von, zeitraum_bis, buchungen, "
        "endsaldo, ersetzt FROM depot_imports WHERE user_id=$1 ORDER BY hochgeladen_at DESC",
        user["id"])
    return [_ser_exp(r) for r in rows]


@router.delete("/api/depot/imports/{iid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def loeschen(request: Request, iid: int, db=Depends(get_db), user=Depends(get_current_user)):
    weg = await db.fetchval(
        "DELETE FROM depot_imports WHERE id=$1 AND user_id=$2 RETURNING id", iid, user["id"])
    if not weg:
        raise HTTPException(404, "Auszug nicht gefunden")
    return {"status": "deleted"}
