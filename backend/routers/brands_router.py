"""Marken-Router (v1.16.0).

Endpoints:
  GET    /api/brands              — Liste aller Marken des Users
  POST   /api/brands              — neue Marke anlegen
  PUT    /api/brands/{bid}        — Marke bearbeiten
  DELETE /api/brands/{bid}        — Marke loeschen

Alle Endpoints sind User-scoped (ownership check per user_id).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import asyncpg

from database import get_db
from auth import get_current_user
from deps import (
    limiter,
    LIMIT_WRITE_STANDARD,
    _ser_exp,
)

router = APIRouter(tags=["brands"])


class BrandCreate(BaseModel):
    name: str
    is_private_label: Optional[bool] = False
    store_id: Optional[int] = None
    parent_company: Optional[str] = None


class BrandUpdate(BaseModel):
    name: Optional[str] = None
    is_private_label: Optional[bool] = None
    store_id: Optional[int] = None
    parent_company: Optional[str] = None


@router.get("/api/brands")
async def list_brands(
    q: Optional[str] = None,
    store_id: Optional[int] = None,
    private_only: bool = False,
    limit: int = 5000,
    sort: str = "name",  # "name" | "purchases" (v1.21.0: Rangliste nach Kaufhaeufigkeit)
    db=Depends(get_db), user=Depends(get_current_user)
):
    """Liste aller Marken des Users. Optionaler Filter per ``q`` (case-insensitive
    Substring auf Name) und ``store_id`` (nur Eigenmarken von einem Laden).

    ``sort=purchases`` (v1.21.0) liefert zusaetzlich ``purchase_count`` (Anzahl
    Positionen, die dieser Marke zugeordnet sind) und sortiert absteigend danach
    — fuer die "meistgekaufte Marke"-Ansicht in der Marken-Verwaltung.

    Bei ~800 Seed-Marken pro User ist der Default-Limit 5000 groesszuegig genug
    (Client filtert clientseitig fuer Autocomplete).
    """
    # Bugfix: alle Spalten in der WHERE-Klausel MUESSEN mit Tabellen-Alias
    # praefixiert sein, sonst kollidiert ``user_id`` zwischen ``brands`` und
    # ``stores`` (beide Tabellen haben eine ``user_id``-Spalte) und Postgres
    # wirft ``column reference "user_id" is ambiguous``.
    conds = ["b.user_id=$1"]
    params: list = [user["id"]]
    if q and len(q.strip()) >= 1:
        params.append("%" + q.strip().lower() + "%")
        conds.append(f"LOWER(b.name) LIKE ${len(params)}")
    if store_id:
        params.append(store_id)
        conds.append(f"b.store_id=${len(params)}")
    if private_only:
        conds.append("b.is_private_label=TRUE")
    params.append(max(1, min(limit, 10000)))
    order_by = "purchase_count DESC, LOWER(b.name)" if sort == "purchases" else "LOWER(b.name)"
    rows = await db.fetch(
        f"""SELECT b.*, s.name AS store_name, s.color AS store_color, s.icon AS store_icon,
                   COALESCE((SELECT COUNT(*) FROM expense_items ei
                             WHERE ei.brand_id=b.id AND ei.user_id=b.user_id), 0) AS purchase_count
            FROM brands b LEFT JOIN stores s ON s.id=b.store_id
            WHERE {' AND '.join(conds)}
            ORDER BY {order_by}
            LIMIT ${len(params)}""",
        *params)
    return [_ser_exp(r) for r in rows]


@router.post("/api/brands")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_brand(request: Request, b: BrandCreate,
                       db=Depends(get_db), user=Depends(get_current_user)):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "Name erforderlich")
    if b.store_id:
        ok = await db.fetchval(
            "SELECT 1 FROM stores WHERE id=$1 AND user_id=$2",
            b.store_id, user["id"])
        if not ok:
            raise HTTPException(400, "Laden unbekannt")
    try:
        row = await db.fetchrow(
            "INSERT INTO brands (user_id, name, is_private_label, store_id, "
            "parent_company, seed_source) "
            "VALUES ($1, $2, $3, $4, $5, NULL) RETURNING *",
            user["id"], name, bool(b.is_private_label),
            b.store_id, b.parent_company)
    except asyncpg.UniqueViolationError:
        raise HTTPException(400, "Marke existiert bereits")
    return _ser_exp(row)


@router.put("/api/brands/{bid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def update_brand(request: Request, bid: int, b: BrandUpdate,
                       db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow(
        "SELECT id FROM brands WHERE id=$1 AND user_id=$2", bid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    fields, vals = [], []
    if b.name is not None:
        n = b.name.strip()
        if not n:
            raise HTTPException(400, "Name darf nicht leer sein")
        vals.append(n); fields.append(f"name=${len(vals)}")
    if b.is_private_label is not None:
        vals.append(bool(b.is_private_label)); fields.append(f"is_private_label=${len(vals)}")
    if b.store_id is not None:
        sid = b.store_id or None
        if sid:
            ok = await db.fetchval(
                "SELECT 1 FROM stores WHERE id=$1 AND user_id=$2", sid, user["id"])
            if not ok:
                raise HTTPException(400, "Laden unbekannt")
        vals.append(sid); fields.append(f"store_id=${len(vals)}")
    if b.parent_company is not None:
        vals.append(b.parent_company or None); fields.append(f"parent_company=${len(vals)}")
    if not fields:
        return _ser_exp(await db.fetchrow("SELECT * FROM brands WHERE id=$1", bid))
    vals.extend([bid, user["id"]])
    try:
        await db.execute(
            f"UPDATE brands SET {','.join(fields)} "
            f"WHERE id=${len(vals)-1} AND user_id=${len(vals)}",
            *vals)
    except asyncpg.UniqueViolationError:
        raise HTTPException(400, "Marke mit diesem Namen existiert bereits")
    return _ser_exp(await db.fetchrow("SELECT * FROM brands WHERE id=$1", bid))


@router.delete("/api/brands/{bid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_brand(request: Request, bid: int,
                       db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(
        "DELETE FROM brands WHERE id=$1 AND user_id=$2", bid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}
