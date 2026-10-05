"""Gesundheit: eigene Messgroessen und Werte von Hand (v2.37.0).

Endpoints:
  GET    /api/health/eigene              — eigene Messgroessen samt Anzahl und letztem Wert
  POST   /api/health/eigene              — eigene Messgroesse anlegen
  PUT    /api/health/eigene/{gid}        — umbenennen, Einheit, Tagessumme ja/nein
  DELETE /api/health/eigene/{gid}        — Messgroesse samt Werten loeschen
  POST   /api/health/manuell             — einen Wert von Hand eintragen
  GET    /api/health/manuell             — die zuletzt von Hand eingetragenen Werte
  DELETE /api/health/manuell/{art}/{id}  — einen Handeintrag loeschen

Werte fuer VORHANDENE Groessen (Gewicht, Ruhepuls, Schritte ...) landen in
``health_metric_samples``, Blutdruck und Blutzucker in ihren eigenen
Tabellen -- jeweils mit ``source = 'manual'``. Sie erscheinen damit in
denselben Diagrammen wie die Werte vom iPhone, und geloescht werden kann
von hier aus nur, was von Hand kam: ein importierter Wert gehoert dem Import.

Eigene Groessen haben eigene Tabellen (Migration 057) und heissen im
Frontend ``eigen_<id>`` -- dieselbe Form wie ein Metrik-Typ, damit das
Vitalwerte-Raster sie ohne Sonderweg zeichnet.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import limiter, LIMIT_WRITE_STANDARD, _ser_exp
from services.health_ingest import SIMPLE_METRIC_MAP

router = APIRouter(tags=["health"])

VORHANDENE = sorted(set(SIMPLE_METRIC_MAP.values()))
EIGEN = "eigen_"
NAME_MAX = 60
EINHEIT_MAX = 20


class GroesseEingabe(BaseModel):
    name: str
    einheit: Optional[str] = None
    kumulativ: bool = False


class GroesseAendern(BaseModel):
    name: Optional[str] = None
    einheit: Optional[str] = None
    kumulativ: Optional[bool] = None


class WertEingabe(BaseModel):
    # ``weight``, ``blood_pressure``, ``blood_glucose`` oder ``eigen_<id>``
    metrik: str
    # Zeitpunkt mit Zeitzone vom Browser; ``datum`` ist der Ortstag dazu.
    # Beides kommt vom Browser: der Server laeuft in UTC und kann nicht
    # wissen, zu welchem Tag 23:30 Ortszeit gehoert.
    zeitpunkt: str
    datum: str
    wert: Optional[float] = None
    systolisch: Optional[float] = None
    diastolisch: Optional[float] = None


def eigen_id(metrik: str) -> Optional[int]:
    """``eigen_12`` -> 12, alles andere -> None."""
    if not isinstance(metrik, str) or not metrik.startswith(EIGEN):
        return None
    try:
        return int(metrik[len(EIGEN):])
    except ValueError:
        return None


async def eigene_schluessel(db, user_id: int) -> set:
    """Die ``eigen_<id>``-Schluessel dieses Kontos -- fuer die Reihenfolge der
    Vitalwerte-Karten, die sonst nur die festen Typen kennt."""
    rows = await db.fetch("SELECT id FROM health_eigene_groessen WHERE user_id=$1", user_id)
    return {f"{EIGEN}{r['id']}" for r in rows}


async def eigene_reihe(db, user_id: int, gid: int, seit: Optional[date]) -> list:
    """Die Werte einer eigenen Groesse in der Form der Zeitreihen
    (``qty``, ``recorded_at``, ``sample_date``, ``unit``) -- das Diagramm
    braucht dann keinen eigenen Weg."""
    g = await db.fetchrow(
        "SELECT einheit, kumulativ FROM health_eigene_groessen WHERE id=$1 AND user_id=$2",
        gid, user_id)
    if not g:
        raise HTTPException(404, "Unbekannte Messgröße")
    bedingung, werte = "user_id=$1 AND groesse_id=$2", [user_id, gid]
    if seit is not None:
        werte.append(seit)
        bedingung += f" AND sample_date >= ${len(werte)}"
    if g["kumulativ"]:
        # Eine Tagessumme ist ein Wert je Tag -- drei Glaeser Wasser zu drei
        # Uhrzeiten sind EIN Punkt im Diagramm, nicht drei.
        rows = await db.fetch(
            f"SELECT sample_date, SUM(wert) AS wert FROM health_eigene_werte "
            f"WHERE {bedingung} GROUP BY sample_date ORDER BY sample_date", *werte)
        return [{"qty": float(r["wert"]), "unit": g["einheit"],
                 "recorded_at": r["sample_date"].isoformat(),
                 "sample_date": r["sample_date"].isoformat()} for r in rows]
    rows = await db.fetch(
        f"SELECT id, recorded_at, sample_date, wert FROM health_eigene_werte "
        f"WHERE {bedingung} ORDER BY recorded_at", *werte)
    return [{"id": r["id"], "qty": float(r["wert"]), "unit": g["einheit"],
             "recorded_at": r["recorded_at"].isoformat(),
             "sample_date": r["sample_date"].isoformat()} for r in rows]


def _name(wert) -> str:
    name = (wert or "").strip()
    if not name:
        raise HTTPException(400, "Die Messgröße braucht einen Namen.")
    if len(name) > NAME_MAX:
        raise HTTPException(400, f"Höchstens {NAME_MAX} Zeichen für den Namen.")
    return name


def _einheit(wert) -> Optional[str]:
    einheit = (wert or "").strip() or None
    if einheit and len(einheit) > EINHEIT_MAX:
        raise HTTPException(400, f"Höchstens {EINHEIT_MAX} Zeichen für die Einheit.")
    return einheit


def _zeit(zeitpunkt: str, datum: str):
    """Zeitpunkt (mit Zone) und Ortstag pruefen. Nichts in der Zukunft: was
    morgen gemessen wird, weiss heute niemand."""
    try:
        zp = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00"))
        tag = date.fromisoformat(datum)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Datum oder Uhrzeit sind nicht lesbar.")
    if zp.tzinfo is None:
        zp = zp.replace(tzinfo=timezone.utc)
    if zp > datetime.now(timezone.utc):
        raise HTTPException(400, "Der Zeitpunkt liegt in der Zukunft.")
    return zp, tag


def _zahl(v, was: str) -> float:
    if v is None:
        raise HTTPException(400, f"{was} fehlt.")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{was} ist keine Zahl.")
    if f != f or abs(f) > 1e9:                  # NaN, Unsinn
        raise HTTPException(400, f"{was} ist keine brauchbare Zahl.")
    return f


# ---------------------------------------------------------------- Groessen
@router.get("/api/health/eigene")
async def eigene_liste(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        """SELECT g.id, g.name, g.einheit, g.kumulativ,
                  COUNT(w.id)::int AS anzahl, MAX(w.recorded_at) AS zuletzt
             FROM health_eigene_groessen g
             LEFT JOIN health_eigene_werte w ON w.groesse_id = g.id
            WHERE g.user_id=$1
            GROUP BY g.id ORDER BY g.id""", user["id"])
    return [{"id": r["id"], "key": f"{EIGEN}{r['id']}", "name": r["name"],
             "einheit": r["einheit"], "kumulativ": r["kumulativ"],
             "anzahl": r["anzahl"],
             "zuletzt": r["zuletzt"].isoformat() if r["zuletzt"] else None} for r in rows]


@router.post("/api/health/eigene")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def eigene_anlegen(request: Request, b: GroesseEingabe,
                         db=Depends(get_db), user=Depends(get_current_user)):
    name = _name(b.name)
    doppelt = await db.fetchval(
        "SELECT 1 FROM health_eigene_groessen WHERE user_id=$1 AND lower(name)=lower($2)",
        user["id"], name)
    if doppelt:
        raise HTTPException(400, f"„{name}“ gibt es schon.")
    r = await db.fetchrow(
        "INSERT INTO health_eigene_groessen (user_id, name, einheit, kumulativ) "
        "VALUES ($1,$2,$3,$4) RETURNING id, name, einheit, kumulativ",
        user["id"], name, _einheit(b.einheit), bool(b.kumulativ))
    return {"id": r["id"], "key": f"{EIGEN}{r['id']}", "name": r["name"],
            "einheit": r["einheit"], "kumulativ": r["kumulativ"], "anzahl": 0, "zuletzt": None}


@router.put("/api/health/eigene/{gid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def eigene_aendern(request: Request, gid: int, b: GroesseAendern,
                         db=Depends(get_db), user=Depends(get_current_user)):
    alt = await db.fetchrow(
        "SELECT * FROM health_eigene_groessen WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not alt:
        raise HTTPException(404, "Messgröße nicht gefunden")
    gesetzt = b.model_fields_set
    name = _name(b.name) if "name" in gesetzt else alt["name"]
    einheit = _einheit(b.einheit) if "einheit" in gesetzt else alt["einheit"]
    kumulativ = bool(b.kumulativ) if "kumulativ" in gesetzt and b.kumulativ is not None else alt["kumulativ"]
    await db.execute(
        "UPDATE health_eigene_groessen SET name=$1, einheit=$2, kumulativ=$3 "
        "WHERE id=$4 AND user_id=$5", name, einheit, kumulativ, gid, user["id"])
    return {"status": "ok"}


@router.delete("/api/health/eigene/{gid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def eigene_loeschen(request: Request, gid: int,
                          db=Depends(get_db), user=Depends(get_current_user)):
    weg = await db.fetchval(
        "DELETE FROM health_eigene_groessen WHERE id=$1 AND user_id=$2 RETURNING id",
        gid, user["id"])
    if not weg:
        raise HTTPException(404, "Messgröße nicht gefunden")
    return {"status": "deleted"}


# ---------------------------------------------------------------- Werte
@router.post("/api/health/manuell")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def wert_eintragen(request: Request, b: WertEingabe,
                         db=Depends(get_db), user=Depends(get_current_user)):
    zp, tag = _zeit(b.zeitpunkt, b.datum)
    uid = user["id"]
    gid = eigen_id(b.metrik)
    if gid is not None:
        if not await db.fetchval(
                "SELECT 1 FROM health_eigene_groessen WHERE id=$1 AND user_id=$2", gid, uid):
            raise HTTPException(404, "Unbekannte Messgröße")
        await db.execute(
            "INSERT INTO health_eigene_werte (user_id, groesse_id, recorded_at, sample_date, wert) "
            "VALUES ($1,$2,$3,$4,$5)", uid, gid, zp, tag, _zahl(b.wert, "Der Wert"))
    elif b.metrik == "blood_pressure":
        sys_, dia = _zahl(b.systolisch, "Der obere Wert"), _zahl(b.diastolisch, "Der untere Wert")
        if dia >= sys_:
            raise HTTPException(400, "Der obere Wert (systolisch) muss über dem unteren liegen.")
        await db.execute(
            "INSERT INTO health_blood_pressure (user_id, recorded_at, systolic, diastolic, source) "
            "VALUES ($1,$2,$3,$4,'manual') "
            "ON CONFLICT (user_id, recorded_at, source) DO UPDATE "
            "SET systolic=EXCLUDED.systolic, diastolic=EXCLUDED.diastolic",
            uid, zp, sys_, dia)
    elif b.metrik == "blood_glucose":
        await db.execute(
            "INSERT INTO health_blood_glucose (user_id, recorded_at, value, source) "
            "VALUES ($1,$2,$3,'manual') "
            "ON CONFLICT (user_id, recorded_at, source) DO UPDATE SET value=EXCLUDED.value",
            uid, zp, _zahl(b.wert, "Der Wert"))
    elif b.metrik in VORHANDENE:
        # Zwei Eintraege zur selben Minute ueberschreiben sich -- dieselbe
        # Regel wie beim Import (UNIQUE user, Typ, Zeitpunkt, Quelle).
        await db.execute(
            "INSERT INTO health_metric_samples (user_id, metric_type, recorded_at, sample_date, qty, source) "
            "VALUES ($1,$2,$3,$4,$5,'manual') "
            "ON CONFLICT (user_id, metric_type, recorded_at, source) DO UPDATE SET qty=EXCLUDED.qty",
            uid, b.metrik, zp, tag, _zahl(b.wert, "Der Wert"))
    else:
        raise HTTPException(400, "Unbekannte Messgröße")
    return {"status": "ok"}


@router.get("/api/health/manuell")
async def zuletzt_von_hand(limit: int = 20, db=Depends(get_db), user=Depends(get_current_user)):
    """Was zuletzt von Hand eingetragen wurde -- aus allen vier Tabellen,
    neueste zuerst. Der Weg zurueck fuer einen Vertipper."""
    uid, n = user["id"], max(1, min(int(limit), 100))
    teile = []
    for r in await db.fetch(
            "SELECT id, metric_type, qty, recorded_at, created_at FROM health_metric_samples "
            "WHERE user_id=$1 AND source='manual' ORDER BY created_at DESC LIMIT $2", uid, n):
        teile.append({"art": "wert", "id": r["id"], "metrik": r["metric_type"],
                      "wert": float(r["qty"]) if r["qty"] is not None else None,
                      "recorded_at": r["recorded_at"], "created_at": r["created_at"]})
    for r in await db.fetch(
            "SELECT id, systolic, diastolic, recorded_at, created_at FROM health_blood_pressure "
            "WHERE user_id=$1 AND source='manual' ORDER BY created_at DESC LIMIT $2", uid, n):
        teile.append({"art": "blutdruck", "id": r["id"], "metrik": "blood_pressure",
                      "systolisch": float(r["systolic"]), "diastolisch": float(r["diastolic"]),
                      "recorded_at": r["recorded_at"], "created_at": r["created_at"]})
    for r in await db.fetch(
            "SELECT id, value, recorded_at, created_at FROM health_blood_glucose "
            "WHERE user_id=$1 AND source='manual' ORDER BY created_at DESC LIMIT $2", uid, n):
        teile.append({"art": "blutzucker", "id": r["id"], "metrik": "blood_glucose",
                      "wert": float(r["value"]),
                      "recorded_at": r["recorded_at"], "created_at": r["created_at"]})
    for r in await db.fetch(
            "SELECT w.id, w.groesse_id, w.wert, w.recorded_at, w.created_at "
            "FROM health_eigene_werte w WHERE w.user_id=$1 ORDER BY w.created_at DESC LIMIT $2",
            uid, n):
        teile.append({"art": "eigen", "id": r["id"], "metrik": f"{EIGEN}{r['groesse_id']}",
                      "wert": float(r["wert"]),
                      "recorded_at": r["recorded_at"], "created_at": r["created_at"]})
    teile.sort(key=lambda t: t["created_at"] or t["recorded_at"], reverse=True)
    return [_ser_exp(t) for t in teile[:n]]


TABELLEN = {
    "wert": "health_metric_samples",
    "blutdruck": "health_blood_pressure",
    "blutzucker": "health_blood_glucose",
}


@router.delete("/api/health/manuell/{art}/{eid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def handeintrag_loeschen(request: Request, art: str, eid: int,
                               db=Depends(get_db), user=Depends(get_current_user)):
    """Nur Handeintraege: ein Wert vom iPhone gehoert seinem Import und
    kaeme beim naechsten Sync ohnehin wieder."""
    if art == "eigen":
        weg = await db.fetchval(
            "DELETE FROM health_eigene_werte WHERE id=$1 AND user_id=$2 RETURNING id",
            eid, user["id"])
    elif art in TABELLEN:
        weg = await db.fetchval(
            f"DELETE FROM {TABELLEN[art]} WHERE id=$1 AND user_id=$2 AND source='manual' RETURNING id",
            eid, user["id"])
    else:
        raise HTTPException(400, "Unbekannte Art")
    if not weg:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return {"status": "deleted"}
