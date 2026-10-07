"""Depot — der Trade-Republic-Kontoauszug (v2.38.0, Modul im Bau).

Endpoints:
  POST   /api/depot/import?speichern=0|1  — Auszug (PDF) lesen; ohne ``speichern``
                                            nur die Vorschau, mit: uebernehmen
  GET    /api/depot/uebersicht            — Depotwert, Verlauf, Wertpapiere, Summen
  GET    /api/depot/statistik?von&bis     — der Reiter Statistik ueber einen Zeitraum
  POST   /api/depot/kurse                 — Kurse nachholen (gedeckelt, ``more``)
  PUT    /api/depot/stueck/{isin}         — Stueckzahl laut App (DELETE nimmt sie weg)
  GET    /api/depot/wertpapier/{isin}     — Kursverlauf mit den eigenen Ausfuehrungen
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
import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query

from auth import get_current_user
from database import get_db
from deps import limiter, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD, _ser_exp
from services import depot_import as leser
from services import depot_kurse as kursdienst
from services import depot_rechnung as rechnung

router = APIRouter(tags=["depot"])

HANDEL = ("kauf", "sparplan", "verkauf")
# Wie viele ISINs ein Aufruf von /api/depot/kurse holt: je ISIN bis zu drei
# Abfragen, und der Aufruf soll in Sekunden fertig sein.
KURSE_JE_AUFRUF = 3


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


def statistik(rows, von, bis, aw) -> dict:
    """Alles fuer den Reiter Statistik, ueber EINEN Zeitraum gerechnet.

    ``rows`` ist der ganze Bestand (nach Datum), ``aw`` die Auswertung
    daraus (``depot_rechnung.auswerten``): Realisiert und Ergebnis brauchen
    auch, was vor dem Zeitraum lag -- den Einstand der Kaeufe davor und den
    Stand am Tag vor dem Anfang."""
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
    ergebnis_je = {x["monat"]: x["ergebnis"] for x in rechnung.ergebnis_monate(aw["verlauf"], list(monate))}
    reihe = [{"monat": m, "kauf": _f(t["kauf"]), "sparplan": _f(t["sparplan"]),
              "verkauf": _f(t["verkauf"]), "zinsen": _f(t["zinsen"]),
              "ertraege": _f(t["ertraege"]), "ergebnis": ergebnis_je.get(m)} for m, t in monate.items()]

    name_von = namen(rows)
    sparplan = defaultdict(Decimal)
    for b in im:
        if b["art"] == "sparplan" and b["isin"]:
            sparplan[b["isin"]] -= Decimal(b["betrag"])
    sparplan_liste = sorted(
        ({"isin": i, "name": name_von.get(i) or i, "summe": _f(x)} for i, x in sparplan.items()),
        key=lambda x: -x["summe"])

    # Realisiert je Wertpapier: jeder Verkauf im Zeitraum, auch ein Teil-
    # verkauf einer Position, die noch im Bestand ist.
    je = defaultdict(lambda: [Decimal(0), None])
    for t, isin, betrag in aw["realisiert"]:
        if von <= t <= bis:
            je[isin][0] += betrag
            je[isin][1] = t
    bestand = {i for i, x in aw["positionen"].items() if x["im_bestand"]}
    ergebnisse = sorted(({"isin": i, "name": name_von.get(i) or i, "ergebnis": round(_f(x[0]), 2),
                          "letzte": x[1].isoformat(), "im_bestand": i in bestand}
                         for i, x in je.items()), key=lambda x: -x["ergebnis"])

    sparplan_monate = [r["sparplan"] for r in reihe if r["sparplan"] > 0]
    summe = lambda *arten: sum((Decimal(b["betrag"]) for b in im if b["art"] in arten), Decimal(0))
    ergebnis, ergebnis_ab = rechnung.ergebnis_zeitraum(aw["verlauf"], von, bis)
    return {
        "von": von.isoformat(), "bis": bis.isoformat(),
        "monate": reihe,
        "sparplan": sparplan_liste,
        "ergebnisse": ergebnisse,
        "verlauf_ab": aw["beginn"].isoformat(),
        "kennzahlen": {
            # Durchschnitt ueber die Monate, in denen der Sparplan lief -- ein
            # Zeitraum, der vor dem ersten Sparplan beginnt, druckte ihn sonst.
            "sparplan_schnitt": round(sum(sparplan_monate) / len(sparplan_monate), 2) if sparplan_monate else 0.0,
            "sparplan_monate": len(sparplan_monate),
            "ausfuehrungen": sum(1 for b in im if b["art"] in HANDEL),
            "ertraege_zinsen": _f(summe("zinsen", *ERTRAEGE)),
            "eingezahlt_netto": _f(summe(*rechnung.EXTERN)),
            "realisiert": round(_f(sum((x[0] for x in je.values()), Decimal(0))), 2),
            "ergebnis": ergebnis, "ergebnis_ab": ergebnis_ab,
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


async def _laden(db, uid) -> tuple:
    """Buchungen, Kurse und die Stueckzahlen laut App eines Kontos."""
    rows = await db.fetch(
        "SELECT datum, art, isin, name, stueck, betrag, saldo FROM depot_buchungen "
        "WHERE user_id=$1 ORDER BY datum, reihe", uid)
    anker = {r["isin"]: (r["stueck"], r["datum"]) for r in await db.fetch(
        "SELECT isin, stueck, datum FROM depot_stueck WHERE user_id=$1", uid)}
    isins = sorted({r["isin"] for r in rows if r["isin"]})
    kurse = defaultdict(list)
    if isins:
        for r in await db.fetch(
                "SELECT isin, datum, kurs FROM depot_kurse WHERE isin = ANY($1::text[]) "
                "ORDER BY isin, datum", isins):
            kurse[r["isin"]].append((r["datum"], Decimal(r["kurs"])))
    return rows, dict(kurse), anker


def _heute() -> date:
    return datetime.now(timezone.utc).date()


async def _kurse_offen(db, rows, anker) -> dict:
    """``{isin: ab}`` -- was heute noch Kurse braucht. Je ISIN einmal am Tag;
    was die Quelle nicht kennt, wird erst nach einer Woche wieder gefragt."""
    bedarf = rechnung.kursbedarf(rows, anker)
    if not bedarf:
        return {}
    quellen = {r["isin"]: r for r in await db.fetch(
        "SELECT isin, gefunden, geholt_ab, geholt_at FROM depot_kursquellen WHERE isin = ANY($1::text[])",
        list(bedarf))}
    heute = _heute()
    offen = {}
    for isin, ab in sorted(bedarf.items()):
        q = quellen.get(isin)
        if q is None:
            offen[isin] = ab
        elif not q["gefunden"]:
            if q["geholt_at"].date() < heute - timedelta(days=7):
                offen[isin] = ab
        elif q["geholt_ab"] is None or q["geholt_ab"] > ab or q["geholt_at"].date() < heute:
            offen[isin] = ab
    return offen


@router.get("/api/depot/uebersicht")
async def uebersicht(db=Depends(get_db), user=Depends(get_current_user)):
    rows, kurse, anker = await _laden(db, user["id"])
    if not rows:
        return {"leer": True}
    aw = rechnung.auswerten(rows, kurse, anker, heute=_heute())
    papiere = []
    for w in wertpapiere(rows):
        x = aw["positionen"].get(w["isin"], {})
        w.update(x)
        # Fuer Verkauftes: was es gebracht hat -- realisiert und Ertraege.
        w["ergebnis"] = round((x.get("realisiert") or 0) + w["ertraege"], 2)
        w["stueck_bekannt"] = x.get("stueck") is not None or not x.get("im_bestand")
        papiere.append(w)
    papiere.sort(key=lambda w: w["letzte"] or "", reverse=True)
    papiere.sort(key=lambda w: (not w["im_bestand"], -(w.get("wert") or w.get("einstand") or 0)))
    letzte = rows[-1]
    return {
        "leer": False,
        "von": rows[0]["datum"].isoformat(), "bis": letzte["datum"].isoformat(),
        "anzahl": len(rows), "saldo": _f(letzte["saldo"]),
        "arten": _summen_je_art(rows),
        "wertpapiere": papiere,
        "depot": dict(aw["jetzt"], verlauf_ab=aw["beginn"].isoformat()),
        "verlauf": [{k: p[k] for k in ("datum", "wert", "einstand", "ergebnis")} for p in aw["verlauf"]],
        "realisiert_jahre": rechnung.realisiert_jahre(aw["realisiert"], rows[0]["datum"].year, aw["ende"].year),
        "kurse_offen": len(await _kurse_offen(db, rows, anker)),
    }


@router.get("/api/depot/statistik")
async def statistik_abruf(von: Optional[str] = None, bis: Optional[str] = None,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Der Reiter Statistik ueber einen Zeitraum. Ohne ``von`` gilt der ganze
    Bestand. Gerechnet wird hier, nicht im Browser -- eine Auswertung hat
    EINE Grundgesamtheit."""
    rows, kurse, anker = await _laden(db, user["id"])
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
    aw = rechnung.auswerten(rows, kurse, anker, heute=_heute())
    return dict(statistik(rows, anfang, ende, aw), leer=False)


@router.post("/api/depot/kurse")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def kurse_holen(request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    """Kurse nachholen -- gedeckelt auf wenige ISINs je Aufruf. ``more``
    sagt, ob noch welche offen sind; das Frontend ruft dann weiter (Muster:
    der Schach-Import). Eine ISIN, die die Quelle nicht kennt, haelt nichts
    auf: das steht an ihr, die naechste kommt dran. Antwortet die Quelle gar
    nicht, endet der Lauf sofort -- zehnmal dieselbe Zeitueberschreitung
    hilft niemandem."""
    rows, _, anker = await _laden(db, user["id"])
    offen = await _kurse_offen(db, rows, anker)
    geholt, ohne = 0, 0
    for isin, ab_voll in list(offen.items())[:KURSE_JE_AUFRUF]:
        q = await db.fetchrow("SELECT * FROM depot_kursquellen WHERE isin=$1", isin)
        try:
            if q is None or not q["gefunden"] or not q["notierung"]:
                q = await asyncio.to_thread(kursdienst.quelle_finden, isin)
                await db.execute(
                    "INSERT INTO depot_kursquellen (isin, gefunden, typ, instrument, notierung, markt, name, "
                    "fehler, geholt_ab, geholt_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NULL,NOW()) "
                    "ON CONFLICT (isin) DO UPDATE SET gefunden=EXCLUDED.gefunden, typ=EXCLUDED.typ, "
                    "instrument=EXCLUDED.instrument, notierung=EXCLUDED.notierung, markt=EXCLUDED.markt, "
                    "name=EXCLUDED.name, fehler=EXCLUDED.fehler, geholt_ab=NULL, geholt_at=NOW()",
                    isin, q["gefunden"], q.get("typ"), q.get("instrument"), q.get("notierung"),
                    q.get("markt"), q.get("name"), q.get("fehler"))
                if not q["gefunden"]:
                    ohne += 1
                    continue
                geholt_ab = None
            else:
                geholt_ab = q["geholt_ab"]
            # Einmal den ganzen Verlauf, danach nur die letzten Tage -- der
            # juengste Schlusskurs kann sich am selben Abend noch aendern.
            letzter = await db.fetchval("SELECT MAX(datum) FROM depot_kurse WHERE isin=$1", isin)
            voll = geholt_ab is None or geholt_ab > ab_voll or letzter is None
            ab = ab_voll if voll else letzter - timedelta(days=5)
            kurse = await asyncio.to_thread(kursdienst.verlauf_holen, dict(q), ab)
            if kurse:
                await db.executemany(
                    "INSERT INTO depot_kurse (isin, datum, kurs) VALUES ($1,$2,$3) "
                    "ON CONFLICT (isin, datum) DO UPDATE SET kurs=EXCLUDED.kurs",
                    [(isin, t, k) for t, k in kurse])
            await db.execute(
                "UPDATE depot_kursquellen SET geholt_at=NOW(), fehler=NULL, "
                "geholt_ab=LEAST(COALESCE(geholt_ab, $2), $2) WHERE isin=$1",
                isin, ab_voll if voll else (geholt_ab or ab_voll))
            geholt += 1
        except kursdienst.KursFehler as e:
            if "erreichbar" in str(e):
                return {"more": False, "geholt": geholt, "offen": len(offen) - geholt,
                        "fehler": "Die Kursquelle ist gerade nicht erreichbar."}
            # Die Quelle antwortet, aber nicht brauchbar: an der ISIN
            # festhalten und erst nach einer Woche wieder fragen.
            await db.execute(
                "INSERT INTO depot_kursquellen (isin, gefunden, fehler, geholt_at) VALUES ($1, FALSE, $2, NOW()) "
                "ON CONFLICT (isin) DO UPDATE SET gefunden=FALSE, fehler=EXCLUDED.fehler, geholt_at=NOW()",
                isin, str(e))
            ohne += 1
    rest = max(0, len(offen) - KURSE_JE_AUFRUF)
    return {"more": rest > 0, "geholt": geholt, "offen": rest,
            "fehler": "Für einige Wertpapiere gibt es keinen Kurs." if ohne else None}


@router.put("/api/depot/stueck/{isin}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def stueck_setzen(request: Request, isin: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Die Stueckzahl laut App fuer ein Wertpapier, dessen Bestand der Auszug
    nicht hergibt. Gilt zum genannten Tag (sonst heute)."""
    body = await request.json()
    if not leser.ISIN.fullmatch(isin or ""):
        raise HTTPException(400, "Keine ISIN")
    try:
        stueck = Decimal(str(body.get("stueck")).replace(",", "."))
        tag = date.fromisoformat(body["datum"]) if body.get("datum") else _heute()
    except Exception:
        raise HTTPException(400, "Stückzahl oder Datum nicht lesbar")
    if not (Decimal(0) <= stueck < Decimal("1000000000")):
        raise HTTPException(400, "Die Stückzahl muss zwischen 0 und einer Milliarde liegen")
    if tag > _heute():
        raise HTTPException(400, "Das Datum liegt in der Zukunft")
    await db.execute(
        "INSERT INTO depot_stueck (user_id, isin, stueck, datum) VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (user_id, isin) DO UPDATE SET stueck=EXCLUDED.stueck, datum=EXCLUDED.datum, "
        "geaendert_at=NOW()", user["id"], isin, stueck, tag)
    rows, _, anker = await _laden(db, user["id"])
    p = rechnung.positionen(rows, anker).get(isin)
    return {"status": "ok", "fehler": p["fehler"] if p else None}


@router.delete("/api/depot/stueck/{isin}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def stueck_weg(request: Request, isin: str, db=Depends(get_db), user=Depends(get_current_user)):
    await db.execute("DELETE FROM depot_stueck WHERE user_id=$1 AND isin=$2", user["id"], isin)
    return {"status": "deleted"}


@router.get("/api/depot/wertpapier/{isin}")
async def wertpapier_kurse(isin: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Kursverlauf eines Wertpapiers mit den eigenen Ausfuehrungen darauf --
    nur, was dieses Konto gehandelt hat."""
    rows = await db.fetch(
        "SELECT datum, art, stueck, betrag FROM depot_buchungen WHERE user_id=$1 AND isin=$2 "
        "AND art = ANY($3::text[]) ORDER BY datum, reihe", user["id"], isin, list(HANDEL))
    if not rows:
        raise HTTPException(404, "Wertpapier nicht gefunden")
    kurse = await db.fetch("SELECT datum, kurs FROM depot_kurse WHERE isin=$1 ORDER BY datum", isin)
    quelle = await db.fetchrow("SELECT markt, gefunden, fehler FROM depot_kursquellen WHERE isin=$1", isin)
    return {
        "kurse": [{"datum": r["datum"].isoformat(), "kurs": _f(r["kurs"])} for r in kurse],
        # Der Ausfuehrungskurs: Betrag je Stueck (bei Einzelkaeufen samt Gebuehr).
        "ausfuehrungen": [{"datum": r["datum"].isoformat(), "art": r["art"],
                           "kurs": round(abs(float(r["betrag"])) / float(r["stueck"]), 4)}
                          for r in rows if r["stueck"]],
        "markt": quelle["markt"] if quelle else None,
        "fehler": quelle["fehler"] if quelle and not quelle["gefunden"] else None,
    }


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
