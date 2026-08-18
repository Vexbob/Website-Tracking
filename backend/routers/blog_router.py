"""Blog-Router (v1.18.0).

Öffentliche Read-Endpoints unter ``/api/public/blog/*`` (kein Auth).
Admin-Write-Endpoints unter ``/api/blog/*`` (require_admin).
"""
import re
import unicodedata
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from database import get_db
from auth import require_admin
from deps import limiter, LIMIT_WRITE_STANDARD

router = APIRouter()


class BlogCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    content_html: str = Field("", max_length=200000)
    slug: Optional[str] = Field(None, max_length=200)
    cover_url: Optional[str] = Field(None, max_length=500)
    tags: List[str] = Field(default_factory=list)


class BlogUpdate(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    content_html: Optional[str] = None
    slug: Optional[str] = None
    cover_url: Optional[str] = None
    tags: Optional[List[str]] = None


def _slugify(text: str) -> str:
    if not text:
        return "post"
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    return t or "post"


async def _unique_slug(conn, base: str, exclude_id: Optional[int] = None) -> str:
    slug = base
    i = 2
    while True:
        if exclude_id is not None:
            row = await conn.fetchval(
                "SELECT id FROM blog_posts WHERE slug=$1 AND id<>$2", slug, exclude_id)
        else:
            row = await conn.fetchval("SELECT id FROM blog_posts WHERE slug=$1", slug)
        if not row:
            return slug
        slug = f"{base}-{i}"
        i += 1


def _ser_post(r) -> dict:
    d = dict(r)
    for k in ("published_at", "updated_at", "created_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


def _serialize_public(r) -> dict:
    d = _ser_post(r)
    d.pop("author_id", None)
    return d


# ---------- ÖFFENTLICH ----------
@router.get("/api/public/blog/posts")
@limiter.limit("120/minute")
async def public_list(request: Request, db=Depends(get_db),
                       limit: int = Query(10, ge=1, le=50),
                       offset: int = Query(0, ge=0),
                       tag: Optional[str] = None):
    conds = ["published_at IS NOT NULL", "published_at <= NOW()"]
    params: list = []
    if tag:
        params.append(tag)
        conds.append("$1 = ANY(tags)")
    where = " AND ".join(conds)
    rows = await db.fetch(
        f"""SELECT id, slug, title, subtitle, author_name, cover_url, tags,
                   published_at, updated_at, view_count
            FROM blog_posts
            WHERE {where}
            ORDER BY published_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}""",
        *params, limit, offset)
    return [_serialize_public(r) for r in rows]


@router.get("/api/public/blog/posts/{slug}")
@limiter.limit("120/minute")
async def public_detail(request: Request, slug: str, db=Depends(get_db)):
    row = await db.fetchrow(
        "SELECT * FROM blog_posts WHERE slug=$1 AND published_at IS NOT NULL "
        "AND published_at <= NOW()", slug)
    if not row:
        raise HTTPException(404, "Post nicht gefunden")
    try:
        await db.execute("UPDATE blog_posts SET view_count = view_count + 1 WHERE id=$1", row["id"])
    except Exception:
        pass
    return _serialize_public(row)


@router.get("/api/public/blog/tags")
@limiter.limit("120/minute")
async def public_tags(request: Request, db=Depends(get_db)):
    rows = await db.fetch(
        """SELECT tag, COUNT(*) AS n
           FROM (SELECT unnest(tags) AS tag FROM blog_posts
                 WHERE published_at IS NOT NULL AND published_at <= NOW()) t
           GROUP BY tag ORDER BY n DESC""")
    return [{"tag": r["tag"], "count": int(r["n"])} for r in rows]

# ---------- ADMIN ----------
@router.get("/api/blog/posts")
async def admin_list(db=Depends(get_db), admin=Depends(require_admin)):
    rows = await db.fetch(
        "SELECT * FROM blog_posts ORDER BY COALESCE(published_at, updated_at) DESC")
    return [_ser_post(r) for r in rows]


@router.get("/api/blog/posts/{pid}")
async def admin_detail(pid: int, db=Depends(get_db), admin=Depends(require_admin)):
    row = await db.fetchrow("SELECT * FROM blog_posts WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    return _ser_post(row)


@router.post("/api/blog/posts")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def admin_create(request: Request, b: BlogCreate, db=Depends(get_db),
                        admin=Depends(require_admin)):
    base = _slugify(b.slug or b.title)
    slug = await _unique_slug(db, base)
    tags = [t.strip() for t in (b.tags or []) if t.strip()]
    row = await db.fetchrow(
        """INSERT INTO blog_posts (slug, title, subtitle, content_html, author_id, author_name,
                                     cover_url, tags)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        slug, b.title, b.subtitle, b.content_html or "",
        admin["id"], admin["username"], b.cover_url, tags)
    return _ser_post(row)


@router.put("/api/blog/posts/{pid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def admin_update(request: Request, pid: int, b: BlogUpdate, db=Depends(get_db),
                        admin=Depends(require_admin)):
    row = await db.fetchrow("SELECT * FROM blog_posts WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    sets = []; vals: list = []; idx = 1
    if b.title is not None:
        sets.append(f"title=${idx}"); vals.append(b.title); idx += 1
    if b.subtitle is not None:
        sets.append(f"subtitle=${idx}"); vals.append(b.subtitle); idx += 1
    if b.content_html is not None:
        sets.append(f"content_html=${idx}"); vals.append(b.content_html); idx += 1
    if b.cover_url is not None:
        sets.append(f"cover_url=${idx}"); vals.append(b.cover_url); idx += 1
    if b.tags is not None:
        clean = [t.strip() for t in b.tags if t.strip()]
        sets.append(f"tags=${idx}"); vals.append(clean); idx += 1
    if b.slug is not None:
        new_slug = await _unique_slug(db, _slugify(b.slug), exclude_id=pid)
        sets.append(f"slug=${idx}"); vals.append(new_slug); idx += 1
    if not sets:
        return _ser_post(row)
    sets.append("updated_at=NOW()")
    vals.append(pid)
    await db.execute(
        f"UPDATE blog_posts SET {', '.join(sets)} WHERE id=${idx}", *vals)
    return _ser_post(await db.fetchrow("SELECT * FROM blog_posts WHERE id=$1", pid))


@router.post("/api/blog/posts/{pid}/publish")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def admin_publish(request: Request, pid: int, db=Depends(get_db),
                         admin=Depends(require_admin)):
    row = await db.fetchrow("SELECT id FROM blog_posts WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    await db.execute(
        "UPDATE blog_posts SET published_at=NOW(), updated_at=NOW() WHERE id=$1", pid)
    return _ser_post(await db.fetchrow("SELECT * FROM blog_posts WHERE id=$1", pid))


@router.post("/api/blog/posts/{pid}/unpublish")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def admin_unpublish(request: Request, pid: int, db=Depends(get_db),
                           admin=Depends(require_admin)):
    row = await db.fetchrow("SELECT id FROM blog_posts WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    await db.execute(
        "UPDATE blog_posts SET published_at=NULL, updated_at=NOW() WHERE id=$1", pid)
    return _ser_post(await db.fetchrow("SELECT * FROM blog_posts WHERE id=$1", pid))


@router.delete("/api/blog/posts/{pid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def admin_delete(request: Request, pid: int, db=Depends(get_db),
                        admin=Depends(require_admin)):
    row = await db.fetchval("SELECT id FROM blog_posts WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    await db.execute("DELETE FROM blog_posts WHERE id=$1", pid)
    return {"status": "deleted"}

