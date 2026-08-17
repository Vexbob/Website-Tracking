"""Notizen-Router — schnelle Notiz-Ablage mit Farben, Pin & Archiv (Master-Detail).

Kein Prefix: die Endpoints behalten ihre absoluten Pfade (``/api/notes`` …).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from database import get_db
from auth import get_current_user
from deps import (
    logger, limiter,
    LIMIT_WRITE_FREQUENT, LIMIT_WRITE_STANDARD,
)


router = APIRouter(tags=["notes"])

ALLOWED_COLORS = {
    "default", "red", "orange", "yellow", "green", "blue", "purple", "pink",
}
ALLOWED_FORMATS = {"markdown", "html"}


# ---------- Models ----------
class NoteCreate(BaseModel):
    title: Optional[str] = ""
    content: Optional[str] = ""
    color: Optional[str] = "default"
    pinned: Optional[bool] = False
    # v1.17.0: Speicherformat. Default 'markdown' fuer neue Notizen.
    format: Optional[str] = "markdown"


class NoteUpd(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    color: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    sort_order: Optional[int] = None
    # v1.17.0: Client kann Format aendern (z.B. bei Migration alter HTML-Notizen).
    format: Optional[str] = None


class ReorderBody(BaseModel):
    order: list[int]


def _ser(row) -> dict:
    """asyncpg-Row -> dict mit ISO-Datumsstrings."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ---------- Endpoints ----------
@router.get("/api/notes")
async def list_notes(
    db=Depends(get_db), user=Depends(get_current_user),
    archived: Optional[bool] = None,
):
    """Alle Notizen des Users. pinned zuerst, dann updated_at absteigend."""
    where = "user_id=$1"
    params = [user["id"]]
    if archived is not None:
        params.append(archived)
        where += f" AND archived=${len(params)}"
    rows = await db.fetch(
        f"SELECT * FROM notes WHERE {where} "
        "ORDER BY pinned DESC, updated_at DESC, id DESC",
        *params,
    )
    return [_ser(r) for r in rows]


@router.get("/api/notes/{nid}")
async def get_note(nid: int, db=Depends(get_db), user=Depends(get_current_user)):
    """Einzelne Notiz abrufen (deep-link-fähig)."""
    row = await db.fetchrow(
        "SELECT * FROM notes WHERE id=$1 AND user_id=$2", nid, user["id"])
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    return _ser(row)


@router.post("/api/notes")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def create_note(request: Request, b: NoteCreate, db=Depends(get_db), user=Depends(get_current_user)):
    color = (b.color or "default").strip() or "default"
    if color not in ALLOWED_COLORS:
        raise HTTPException(400, f"Unbekannte Farbe: {color}")
    fmt = (b.format or "markdown").strip() or "markdown"
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(400, f"Unbekanntes Format: {fmt}")
    row = await db.fetchrow(
        "INSERT INTO notes (user_id,title,content,color,pinned,format) "
        "VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
        user["id"], (b.title or "").strip(), (b.content or "").rstrip(),
        color, bool(b.pinned), fmt,
    )
    logger.info(f"User {user['id']} created note {row['id']}")
    return _ser(row)


@router.put("/api/notes/{nid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def update_note(request: Request, nid: int, b: NoteUpd, db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow(
        "SELECT id FROM notes WHERE id=$1 AND user_id=$2", nid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    if b.color is not None and b.color not in ALLOWED_COLORS:
        raise HTTPException(400, f"Unbekannte Farbe: {b.color}")
    if b.format is not None and b.format not in ALLOWED_FORMATS:
        raise HTTPException(400, f"Unbekanntes Format: {b.format}")

    fields, vals = [], []
    if b.title is not None:
        fields.append(f"title=${len(vals)+1}"); vals.append(b.title.strip())
    if b.content is not None:
        fields.append(f"content=${len(vals)+1}"); vals.append(b.content.rstrip())
    if b.color is not None:
        fields.append(f"color=${len(vals)+1}"); vals.append(b.color)
    if b.pinned is not None:
        fields.append(f"pinned=${len(vals)+1}"); vals.append(bool(b.pinned))
    if b.archived is not None:
        fields.append(f"archived=${len(vals)+1}"); vals.append(bool(b.archived))
    if b.sort_order is not None:
        fields.append(f"sort_order=${len(vals)+1}"); vals.append(int(b.sort_order))
    if b.format is not None:
        fields.append(f"format=${len(vals)+1}"); vals.append(b.format)

    if not fields:
        return _ser(await db.fetchrow("SELECT * FROM notes WHERE id=$1", nid))

    vals.extend([nid, user["id"]])
    await db.execute(
        f"UPDATE notes SET {','.join(fields)} "
        f"WHERE id=${len(vals)-1} AND user_id=${len(vals)}",
        *vals,
    )
    return _ser(await db.fetchrow("SELECT * FROM notes WHERE id=$1", nid))



@router.delete("/api/notes/{nid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def delete_note(request: Request, nid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(
        "DELETE FROM notes WHERE id=$1 AND user_id=$2", nid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


@router.put("/api/notes/reorder")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def reorder_notes(request: Request, b: ReorderBody, db=Depends(get_db), user=Depends(get_current_user)):
    """Setzt sort_order für die übergebenen Notiz-IDs (Reihenfolge im Array)."""
    if not b.order:
        return {"status": "ok"}
    rows = await db.fetch(
        "SELECT id FROM notes WHERE id = ANY($1::int[]) AND user_id=$2",
        list(b.order), user["id"],
    )
    owned = {r["id"] for r in rows}
    async with db.transaction():
        for idx, nid in enumerate(b.order):
            if nid not in owned:
                continue
            await db.execute(
                "UPDATE notes SET sort_order=$1 WHERE id=$2 AND user_id=$3",
                idx, nid, user["id"],
            )
    return {"status": "ok"}
