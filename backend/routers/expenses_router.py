"""Ausgaben-Router — alle Endpoints rund um Ausgaben, Läden, Kategorien,
Belege (OCR), Statistik, Preisverlauf und Export.

Kein Prefix: die Endpoints behalten ihre alten absoluten Pfade
(``/api/expenses``, ``/api/stores``, ``/api/expense-categories``,
``/api/category-rules``, ``/api/expense-items``, ``/api/receipts``).
"""
import asyncio
from datetime import date, timedelta, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import Response
from pydantic import BaseModel
import asyncpg

from database import get_db
from auth import get_current_user
from deps import (
    logger, limiter,
    LIMIT_WRITE_FREQUENT, LIMIT_WRITE_STANDARD, LIMIT_WRITE_RARE,
    MAX_UPLOAD_BYTES,
    _num, _ser_exp, _parse_iso_date,
)

# Ausgaben-Services (nur hier importiert)
from services.expenses import suggest_category, learn_rule, process_image
from services.ocr import get_ocr_provider
from services.receipt_parser import parse_receipt
from services.ai_receipt_parser import ai_parse_receipt


router = APIRouter(tags=["expenses"])



# ---------- Models: Ausgaben ----------
class StoreCreate(BaseModel):
    name: str
    color: Optional[str] = "#6b7280"
    icon: Optional[str] = None

class StoreUpd(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None

class CatCreate(BaseModel):
    name: str
    color: Optional[str] = "#3b82f6"
    icon: Optional[str] = None

class CatUpd(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None

class RuleCreate(BaseModel):
    keyword: str
    category_id: int
    store_id: Optional[int] = None

class ExpenseItemIn(BaseModel):
    description: str
    # Optional strukturierte Felder — wenn nicht mitgegeben, aus description abgeleitet:
    base_name: Optional[str] = None
    original_text: Optional[str] = None
    quantity: Optional[float] = 1
    quantity_unit: Optional[str] = None
    unit_price: Optional[float] = None
    total_price: float
    category_id: Optional[int] = None
    original_price: Optional[float] = None
    is_reduced: Optional[bool] = False
    price_comparable: Optional[bool] = True
    user_edited: Optional[bool] = False
    # v1.16.0: Marken-Verknuepfung. Entweder ``brand_id`` direkt oder
    # ``brand_name`` (dann wird eine passende Marke gesucht bzw. angelegt).
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None


async def _resolve_brand_id(db, user_id: int,
                            brand_id: Optional[int],
                            brand_name: Optional[str],
                            store_id: Optional[int]) -> Optional[int]:
    """Loest ``brand_name`` in eine ``brand_id`` auf. Findet keine passende
    Marke, wird eine neue User-Marke angelegt (User-Anlage, kein Seed).

    Wenn ``brand_id`` bereits gesetzt und dem User gehoert, wird sie ver-
    wendet. Ansonsten wird ``brand_name`` (case-insensitive) gesucht.
    """
    if brand_id:
        ok = await db.fetchval(
            "SELECT 1 FROM brands WHERE id=$1 AND user_id=$2", brand_id, user_id)
        return brand_id if ok else None
    if not brand_name:
        return None
    name_clean = brand_name.strip()
    if not name_clean:
        return None
    # Existierende Marke suchen
    existing = await db.fetchval(
        "SELECT id FROM brands WHERE user_id=$1 AND LOWER(name)=LOWER($2)",
        user_id, name_clean)
    if existing:
        return existing
    # Neu anlegen. Wenn ein store_id mitgeliefert wurde, ist es plausibel eine
    # Eigenmarke — der User kann das spaeter in der UI korrigieren.
    try:
        return await db.fetchval(
            "INSERT INTO brands (user_id, name, is_private_label, store_id, seed_source) "
            "VALUES ($1, $2, FALSE, $3, NULL) RETURNING id",
            user_id, name_clean, store_id)
    except asyncpg.UniqueViolationError:
        # Race-Condition: parallel angelegt
        return await db.fetchval(
            "SELECT id FROM brands WHERE user_id=$1 AND LOWER(name)=LOWER($2)",
            user_id, name_clean)

def _derive_base_and_original(item: ExpenseItemIn):
    """Wenn base_name/original_text nicht vom Client mitkamen: aus description ableiten.
    Format-Erwartung: "Basisname (Original)" oder "Basisname 2kg (Original)"."""
    base = (item.base_name or "").strip()
    orig = (item.original_text or "").strip()
    if not base:
        desc = (item.description or "").strip()
        if "(" in desc and desc.endswith(")"):
            bp, op = desc.rsplit("(", 1)
            base = bp.strip()
            if not orig:
                orig = op.rstrip(")").strip()
        else:
            base = desc
    # Menge/Einheit-Suffix am Basisnamen entfernen (Sanity)
    import re as _re
    base = _re.sub(
        r"\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|pack|btl|blatt)\s*$",
        "", base, flags=_re.IGNORECASE
    ).strip() or base
    return base, (orig or None)


class ExpenseCreate(BaseModel):
    store_id: Optional[int] = None
    receipt_image_id: Optional[int] = None
    purchase_date: str
    total_amount: float
    vat_amount: Optional[float] = None
    payment_method: Optional[str] = None
    is_recurring: Optional[bool] = False
    recurring_pattern: Optional[str] = None
    note: Optional[str] = None
    expense_type: Optional[str] = "receipt"  # receipt|online_order|restaurant|subscription|other
    items: Optional[list[ExpenseItemIn]] = None

class ExpenseUpd(BaseModel):
    store_id: Optional[int] = None
    purchase_date: Optional[str] = None
    total_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    payment_method: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurring_pattern: Optional[str] = None
    note: Optional[str] = None
    expense_type: Optional[str] = None

# ---------- Stores ----------
@router.get("/api/stores")
async def list_stores(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT * FROM stores WHERE user_id=$1 ORDER BY sort_order NULLS LAST, LOWER(name)",
        user["id"])
    return [_ser_exp(r) for r in rows]

@router.post("/api/stores")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_store(request: Request, b: StoreCreate, db=Depends(get_db), user=Depends(get_current_user)):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "Name erforderlich")
    try:
        row = await db.fetchrow(
            "INSERT INTO stores (user_id,name,color,icon) VALUES ($1,$2,$3,$4) RETURNING *",
            user["id"], name, b.color or "#6b7280", b.icon)
    except asyncpg.UniqueViolationError:
        raise HTTPException(400, "Laden existiert bereits")
    return _ser_exp(row)

@router.put("/api/stores/{sid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def update_store(request: Request, sid: int, b: StoreUpd, db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow("SELECT id FROM stores WHERE id=$1 AND user_id=$2", sid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    fields, vals = [], []
    if b.name is not None:
        fields.append(f"name=${len(vals)+1}"); vals.append(b.name.strip())
    if b.color is not None:
        fields.append(f"color=${len(vals)+1}"); vals.append(b.color)
    if b.icon is not None:
        fields.append(f"icon=${len(vals)+1}"); vals.append(b.icon)
    if not fields:
        return _ser_exp(await db.fetchrow("SELECT * FROM stores WHERE id=$1", sid))
    vals.extend([sid, user["id"]])
    await db.execute(f"UPDATE stores SET {','.join(fields)} WHERE id=${len(vals)-1} AND user_id=${len(vals)}", *vals)
    return _ser_exp(await db.fetchrow("SELECT * FROM stores WHERE id=$1", sid))

@router.delete("/api/stores/{sid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_store(request: Request, sid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM stores WHERE id=$1 AND user_id=$2", sid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


# ---------- Kategorien ----------
@router.get("/api/expense-categories")
async def list_categories(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT * FROM expense_categories WHERE user_id=$1 ORDER BY sort_order NULLS LAST, LOWER(name)",
        user["id"])
    return [_ser_exp(r) for r in rows]

@router.post("/api/expense-categories")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_category(request: Request, b: CatCreate, db=Depends(get_db), user=Depends(get_current_user)):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "Name erforderlich")
    try:
        row = await db.fetchrow(
            "INSERT INTO expense_categories (user_id,name,color,icon) VALUES ($1,$2,$3,$4) RETURNING *",
            user["id"], name, b.color or "#3b82f6", b.icon)
    except asyncpg.UniqueViolationError:
        raise HTTPException(400, "Kategorie existiert bereits")
    return _ser_exp(row)

@router.put("/api/expense-categories/{cid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def update_category(request: Request, cid: int, b: CatUpd, db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow("SELECT id FROM expense_categories WHERE id=$1 AND user_id=$2", cid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    fields, vals = [], []
    if b.name is not None:
        fields.append(f"name=${len(vals)+1}"); vals.append(b.name.strip())
    if b.color is not None:
        fields.append(f"color=${len(vals)+1}"); vals.append(b.color)
    if b.icon is not None:
        fields.append(f"icon=${len(vals)+1}"); vals.append(b.icon)
    if not fields:
        return _ser_exp(await db.fetchrow("SELECT * FROM expense_categories WHERE id=$1", cid))
    vals.extend([cid, user["id"]])
    await db.execute(f"UPDATE expense_categories SET {','.join(fields)} WHERE id=${len(vals)-1} AND user_id=${len(vals)}", *vals)
    return _ser_exp(await db.fetchrow("SELECT * FROM expense_categories WHERE id=$1", cid))

@router.delete("/api/expense-categories/{cid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_category(request: Request, cid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM expense_categories WHERE id=$1 AND user_id=$2", cid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


@router.post("/api/expense-categories/{cid}/merge-into/{target_id}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def merge_category(request: Request, cid: int, target_id: int,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Verschmilzt die Quell-Kategorie in die Ziel-Kategorie:
    - alle expense_items werden umgehängt
    - alle category_rules werden umgehängt (Duplikate ignoriert)
    - Quell-Kategorie wird gelöscht.
    Beide müssen dem User gehören.
    """
    if cid == target_id:
        raise HTTPException(400, "Quelle und Ziel identisch")
    src = await db.fetchval("SELECT id FROM expense_categories WHERE id=$1 AND user_id=$2", cid, user["id"])
    dst = await db.fetchval("SELECT id FROM expense_categories WHERE id=$1 AND user_id=$2", target_id, user["id"])
    if not src or not dst:
        raise HTTPException(404, "Kategorie nicht gefunden")
    moved_items = 0
    moved_rules = 0
    async with db.transaction():
        r = await db.execute(
            "UPDATE expense_items SET category_id=$1 WHERE category_id=$2 AND user_id=$3",
            target_id, cid, user["id"])
        try: moved_items = int(r.split()[-1])
        except (ValueError, IndexError): pass
        # Rules umhängen: doppelte (keyword, store_id) für Ziel-Kategorie entfernen,
        # damit UPDATE keine UniqueViolation wirft, dann Rest verschieben.
        await db.execute(
            """DELETE FROM category_rules
               WHERE category_id=$1 AND user_id=$2
                 AND (LOWER(keyword), COALESCE(store_id, -1)) IN (
                     SELECT LOWER(keyword), COALESCE(store_id, -1)
                     FROM category_rules
                     WHERE category_id=$3 AND user_id=$2
                 )""",
            cid, user["id"], target_id)
        r = await db.execute(
            "UPDATE category_rules SET category_id=$1 WHERE category_id=$2 AND user_id=$3",
            target_id, cid, user["id"])
        try: moved_rules = int(r.split()[-1])
        except (ValueError, IndexError): pass
        await db.execute("DELETE FROM expense_categories WHERE id=$1 AND user_id=$2", cid, user["id"])
    logger.info(f"User {user['id']} merged category {cid} into {target_id}: {moved_items} items, {moved_rules} rules")
    return {"status": "merged", "moved_items": moved_items, "moved_rules": moved_rules}


# ---------- Category Rules (mitlernend) ----------
@router.get("/api/category-rules")
async def list_rules(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT * FROM category_rules WHERE user_id=$1 ORDER BY hit_count DESC, keyword",
        user["id"])
    return [_ser_exp(r) for r in rows]

@router.post("/api/category-rules")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_rule(request: Request, b: RuleCreate, db=Depends(get_db), user=Depends(get_current_user)):
    kw = (b.keyword or "").strip()
    if not kw:
        raise HTTPException(400, "Keyword erforderlich")
    cat = await db.fetchval("SELECT id FROM expense_categories WHERE id=$1 AND user_id=$2",
                             b.category_id, user["id"])
    if not cat:
        raise HTTPException(400, "Kategorie unbekannt")
    row = await db.fetchrow(
        "INSERT INTO category_rules (user_id,keyword,category_id,store_id,hit_count) "
        "VALUES ($1,$2,$3,$4,1) RETURNING *",
        user["id"], kw, b.category_id, b.store_id)
    return _ser_exp(row)

@router.delete("/api/category-rules/{rid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_rule(request: Request, rid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM category_rules WHERE id=$1 AND user_id=$2", rid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}

@router.post("/api/category-rules/suggest")
async def suggest_rule(body: dict, db=Depends(get_db), user=Depends(get_current_user)):
    """Body: {description: str, store_id?: int} -> {category_id: int|null}"""
    desc = (body.get("description") or "").strip()
    store_id = body.get("store_id")
    cid = await suggest_category(db, user["id"], desc, store_id)
    return {"category_id": cid}


# ---------- Expenses ----------

@router.get("/api/expenses")
async def list_expenses(
    db=Depends(get_db), user=Depends(get_current_user),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    store_id: Optional[int] = None,
    category_id: Optional[int] = None,
    expense_type: Optional[str] = None,
    q: Optional[str] = None,          # Volltextsuche (Notiz, Laden, Item-Beschreibungen)
    limit: int = 200,
):
    conds = ["e.user_id=$1"]
    params = [user["id"]]
    if date_from:
        params.append(_parse_iso_date(date_from))
        conds.append(f"e.purchase_date >= ${len(params)}")
    if date_to:
        params.append(_parse_iso_date(date_to))
        conds.append(f"e.purchase_date <= ${len(params)}")
    if store_id:
        params.append(store_id)
        conds.append(f"e.store_id=${len(params)}")
    if expense_type:
        params.append(expense_type)
        conds.append(f"e.expense_type=${len(params)}")
    if category_id:
        params.append(category_id)
        conds.append(
            f"EXISTS (SELECT 1 FROM expense_items ei WHERE ei.expense_id=e.id AND ei.category_id=${len(params)})")
    if q and len(q.strip()) >= 2:
        params.append("%" + q.strip().lower() + "%")
        idx = len(params)
        conds.append(
            f"(LOWER(COALESCE(s.name,'')) LIKE ${idx} "
            f"OR LOWER(COALESCE(e.note,'')) LIKE ${idx} "
            f"OR EXISTS (SELECT 1 FROM expense_items ei WHERE ei.expense_id=e.id AND LOWER(ei.description) LIKE ${idx}))"
        )
    params.append(max(1, min(limit, 500)))
    rows = await db.fetch(
        f"""SELECT e.*, s.name AS store_name, s.color AS store_color, s.icon AS store_icon,
                   (SELECT COUNT(*) FROM expense_items ei WHERE ei.expense_id=e.id) AS item_count,
                   (e.receipt_image_id IS NOT NULL) AS has_image
           FROM expenses e
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE {' AND '.join(conds)}
           ORDER BY e.purchase_date DESC, e.id DESC
           LIMIT ${len(params)}""",
        *params)
    return [_ser_exp(r) for r in rows]

@router.get("/api/expenses/{eid:int}")
async def get_expense(eid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        """SELECT e.*, s.name AS store_name, s.color AS store_color, s.icon AS store_icon
           FROM expenses e LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.id=$1 AND e.user_id=$2""", eid, user["id"])
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    items = await db.fetch(
        """SELECT ei.*, c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
                  b.name AS brand_name, b.is_private_label AS brand_is_private_label
           FROM expense_items ei
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           LEFT JOIN brands b ON b.id=ei.brand_id
           WHERE ei.expense_id=$1 ORDER BY sort_order NULLS LAST, ei.id""", eid)
    result = _ser_exp(row)
    result["items"] = [_ser_exp(i) for i in items]
    return result

@router.post("/api/expenses")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def create_expense(request: Request, b: ExpenseCreate,
                          db=Depends(get_db), user=Depends(get_current_user)):
    d = _parse_iso_date(b.purchase_date)
    if d is None:
        raise HTTPException(400, "purchase_date erforderlich")
    if b.total_amount is None or b.total_amount < 0:
        raise HTTPException(400, "total_amount ungültig")
    # Ownership checks
    if b.store_id:
        ok = await db.fetchval("SELECT 1 FROM stores WHERE id=$1 AND user_id=$2", b.store_id, user["id"])
        if not ok:
            raise HTTPException(400, "Laden unbekannt")
    if b.receipt_image_id:
        ok = await db.fetchval("SELECT 1 FROM receipt_images WHERE id=$1 AND user_id=$2",
                                b.receipt_image_id, user["id"])
        if not ok:
            raise HTTPException(400, "Bild unbekannt")

    exp_type = (b.expense_type or "receipt").strip()
    if exp_type not in ("receipt", "online_order", "restaurant", "subscription", "other"):
        exp_type = "receipt"

    async with db.transaction():
        row = await db.fetchrow(
            """INSERT INTO expenses
               (user_id, receipt_image_id, store_id, purchase_date, total_amount,
                vat_amount, payment_method, is_recurring, recurring_pattern, note, expense_type)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *""",
            user["id"], b.receipt_image_id, b.store_id, d, b.total_amount,
            b.vat_amount, b.payment_method, bool(b.is_recurring),
            b.recurring_pattern, b.note, exp_type)
        eid = row["id"]
        if b.items:
            for idx, it in enumerate(b.items):
                cat_id = it.category_id
                if cat_id is None:
                    cat_id = await suggest_category(db, user["id"], it.description, b.store_id)
                if cat_id:
                    ok = await db.fetchval(
                        "SELECT 1 FROM expense_categories WHERE id=$1 AND user_id=$2",
                        cat_id, user["id"])
                    if not ok:
                        cat_id = None
                base_n, orig_t = _derive_base_and_original(it)
                # v1.16.0: Marke aufloesen (id oder name)
                brand_id = await _resolve_brand_id(
                    db, user["id"], it.brand_id, it.brand_name, b.store_id)
                await db.execute(
                    """INSERT INTO expense_items
                       (user_id, expense_id, description, base_name, original_text,
                        quantity, quantity_unit, unit_price, total_price, category_id,
                        sort_order, original_price, is_reduced,
                        price_comparable, user_edited, brand_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                    user["id"], eid, it.description.strip(),
                    base_n, orig_t,
                    it.quantity or 1, it.quantity_unit,
                    it.unit_price, it.total_price, cat_id, idx,
                    it.original_price, bool(it.is_reduced),
                    bool(it.price_comparable) if it.price_comparable is not None else True,
                    bool(it.user_edited), brand_id)
                if cat_id and it.category_id is not None:
                    await learn_rule(db, user["id"], it.description, cat_id, b.store_id)
    return await get_expense(eid, db=db, user=user)


@router.put("/api/expenses/{eid:int}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def update_expense(request: Request, eid: int, b: ExpenseUpd,
                          db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow("SELECT id FROM expenses WHERE id=$1 AND user_id=$2", eid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    fields, vals = [], []
    def add(col, v):
        vals.append(v); fields.append(f"{col}=${len(vals)}")
    if b.store_id is not None: add("store_id", b.store_id or None)
    if b.purchase_date is not None: add("purchase_date", _parse_iso_date(b.purchase_date))
    if b.total_amount is not None: add("total_amount", b.total_amount)
    if b.vat_amount is not None: add("vat_amount", b.vat_amount)
    if b.payment_method is not None: add("payment_method", b.payment_method)
    if b.is_recurring is not None: add("is_recurring", bool(b.is_recurring))
    if b.recurring_pattern is not None: add("recurring_pattern", b.recurring_pattern)
    if b.note is not None: add("note", b.note)
    if b.expense_type is not None and b.expense_type in ("receipt","online_order","restaurant","subscription","other"):
        add("expense_type", b.expense_type)
    if not fields:
        return await get_expense(eid, db=db, user=user)
    vals.extend([eid, user["id"]])
    await db.execute(
        f"UPDATE expenses SET {','.join(fields)} WHERE id=${len(vals)-1} AND user_id=${len(vals)}",
        *vals)
    return await get_expense(eid, db=db, user=user)

@router.delete("/api/expenses/{eid:int}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def delete_expense(request: Request, eid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM expenses WHERE id=$1 AND user_id=$2", eid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


# ---------- Expense Items ----------
@router.post("/api/expenses/{eid:int}/items")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def add_item(request: Request, eid: int, b: ExpenseItemIn,
                    db=Depends(get_db), user=Depends(get_current_user)):
    exp = await db.fetchrow("SELECT id, store_id FROM expenses WHERE id=$1 AND user_id=$2", eid, user["id"])
    if not exp:
        raise HTTPException(404, "Ausgabe nicht gefunden")
    cat_id = b.category_id
    if cat_id is None:
        cat_id = await suggest_category(db, user["id"], b.description, exp["store_id"])
    if cat_id:
        ok = await db.fetchval("SELECT 1 FROM expense_categories WHERE id=$1 AND user_id=$2",
                                cat_id, user["id"])
        if not ok:
            cat_id = None
    base_n, orig_t = _derive_base_and_original(b)
    row = await db.fetchrow(
        """INSERT INTO expense_items
           (user_id, expense_id, description, base_name, original_text,
            quantity, quantity_unit, unit_price, total_price, category_id,
            original_price, is_reduced, price_comparable, user_edited)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING *""",
        user["id"], eid, b.description.strip(), base_n, orig_t,
        b.quantity or 1, b.quantity_unit, b.unit_price, b.total_price, cat_id,
        b.original_price, bool(b.is_reduced),
        bool(b.price_comparable) if b.price_comparable is not None else True,
        bool(b.user_edited))
    if cat_id and b.category_id is not None:
        await learn_rule(db, user["id"], b.description, cat_id, exp["store_id"])
    return _ser_exp(row)

@router.put("/api/expense-items/{iid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def update_item(request: Request, iid: int, b: ExpenseItemIn,
                       db=Depends(get_db), user=Depends(get_current_user)):
    existing = await db.fetchrow(
        "SELECT ei.*, e.store_id FROM expense_items ei JOIN expenses e ON e.id=ei.expense_id "
        "WHERE ei.id=$1 AND ei.user_id=$2", iid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    cat_id = b.category_id
    if cat_id:
        ok = await db.fetchval("SELECT 1 FROM expense_categories WHERE id=$1 AND user_id=$2",
                                cat_id, user["id"])
        if not ok:
            raise HTTPException(400, "Kategorie unbekannt")
    base_n, orig_t = _derive_base_and_original(b)
    # PUT durch User => user_edited=true (schützt vor Reparse-Überschreiben)
    await db.execute(
        """UPDATE expense_items
           SET description=$1, base_name=$2, original_text=$3,
               quantity=$4, quantity_unit=$5, unit_price=$6,
               total_price=$7, category_id=$8, original_price=$9, is_reduced=$10,
               price_comparable=$11, user_edited=TRUE
           WHERE id=$12 AND user_id=$13""",
        b.description.strip(), base_n, orig_t,
        b.quantity or 1, b.quantity_unit,
        b.unit_price, b.total_price,
        cat_id, b.original_price, bool(b.is_reduced),
        bool(b.price_comparable) if b.price_comparable is not None else True,
        iid, user["id"])
    # Regel lernen wenn Kategorie manuell gesetzt wurde
    if cat_id and cat_id != existing["category_id"]:
        await learn_rule(db, user["id"], b.description, cat_id, existing["store_id"])
    return _ser_exp(await db.fetchrow("SELECT * FROM expense_items WHERE id=$1", iid))

@router.delete("/api/expense-items/{iid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def delete_item(request: Request, iid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM expense_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


# ---------- Receipts (Bilder + OCR) ----------
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB Rohupload (wird danach komprimiert)

@router.get("/api/receipts")
async def list_receipts(db=Depends(get_db), user=Depends(get_current_user), limit: int = 100):
    rows = await db.fetch(
        """SELECT id, filename, mime_type, size_bytes, uploaded_at,
                  (SELECT id FROM expenses e WHERE e.receipt_image_id=r.id LIMIT 1) AS expense_id
           FROM receipt_images r
           WHERE user_id=$1 ORDER BY uploaded_at DESC LIMIT $2""",
        user["id"], max(1, min(limit, 500)))
    return [_ser_exp(r) for r in rows]

@router.post("/api/receipts/upload")
@limiter.limit(LIMIT_WRITE_RARE)
async def upload_receipt(request: Request,
                          file: UploadFile = File(...),
                          run_ocr: bool = Form(True),
                          db=Depends(get_db), user=Depends(get_current_user)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Leere Datei")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Datei zu groß (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
    main_bytes, thumb_bytes, mime, size = process_image(raw)

    ocr_text = ""
    ocr_name = None
    ocr_error = None
    ocr_provider_available = False
    if run_ocr:
        provider = get_ocr_provider()
        ocr_provider_available = provider.available
        ocr_name = provider.name
        if provider.available:
            try:
                ocr_text = provider.extract_text(main_bytes) or ""
            except Exception as e:
                logger.exception(f"OCR failed: {e}")
                ocr_error = str(e)
        else:
            ocr_error = "Provider nicht konfiguriert (GOOGLE_APPLICATION_CREDENTIALS_JSON fehlt?)"

    row = await db.fetchrow(
        """INSERT INTO receipt_images
           (user_id, filename, mime_type, size_bytes, image_data, thumbnail_data,
            ocr_provider, ocr_raw_text)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, filename, mime_type, size_bytes, uploaded_at""",
        user["id"], file.filename or "receipt.jpg", mime, size,
        main_bytes, thumb_bytes, ocr_name, ocr_text)

    # Bekannte Läden, Kategorien & Marken des Users für AI-Parsing (v1.16.0)
    user_stores_rows = await db.fetch("SELECT name FROM stores WHERE user_id=$1", user["id"])
    user_stores = [r["name"] for r in user_stores_rows]
    cat_rows = await db.fetch(
        "SELECT id, name FROM expense_categories WHERE user_id=$1", user["id"])
    brand_rows = await db.fetch(
        "SELECT name FROM brands WHERE user_id=$1", user["id"])
    try:
        parsed = await ai_parse_receipt(
            ocr_text,
            [{"id": r["id"], "name": r["name"]} for r in cat_rows],
            [{"name": r["name"]} for r in user_stores_rows],
            brands=[{"name": r["name"]} for r in brand_rows],
        )
    except Exception as e:
        logger.warning(f"AI parse failed, falling back to regex: {e}")
        parsed = parse_receipt(ocr_text, user_stores=user_stores)
        parsed["_parser"] = "regex"
        parsed["_fallback_reason"] = f"outer_exception: {e}"

    return {
        "receipt": _ser_exp(row),
        "ocr": {
            "provider": ocr_name,
            "provider_available": ocr_provider_available,
            "available": bool(ocr_text),
            "error": ocr_error,
            "raw_text": ocr_text,
            "text_length": len(ocr_text),
            "parsed": parsed,
        },
    }

@router.get("/api/receipts/{rid}/image")
async def get_receipt_image(rid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT image_data, mime_type FROM receipt_images WHERE id=$1 AND user_id=$2",
        rid, user["id"])
    if not row or not row["image_data"]:
        raise HTTPException(404, "Bild nicht gefunden")
    return Response(content=bytes(row["image_data"]), media_type=row["mime_type"] or "image/jpeg")

@router.get("/api/receipts/{rid}/thumb")
async def get_receipt_thumb(rid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT thumbnail_data, image_data, mime_type FROM receipt_images WHERE id=$1 AND user_id=$2",
        rid, user["id"])
    if not row:
        raise HTTPException(404, "Bild nicht gefunden")
    data = row["thumbnail_data"] or row["image_data"]
    if not data:
        raise HTTPException(404, "Bild-Daten fehlen")
    return Response(content=bytes(data), media_type="image/jpeg")

@router.delete("/api/receipts/{rid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_receipt(request: Request, rid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM receipt_images WHERE id=$1 AND user_id=$2", rid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}

@router.post("/api/receipts/reparse-all")
@limiter.limit(LIMIT_WRITE_RARE)
async def reparse_all_receipts(request: Request,
                                user=Depends(get_current_user)):
    """Iteriert über alle Bons des Users mit gespeichertem OCR-Rohtext, ruft den
    AI-Parser erneut auf und ersetzt die Einzelpositionen. Existierende Ausgaben-
    Kopfdaten (Betrag, Datum, Laden, Notiz) bleiben unverändert — nur ``items``
    werden neu geschrieben (alte gelöscht, neue eingefügt).

    Antwortet mit Streaming-NDJSON. Wichtig: wir dürfen hier NICHT ``Depends(get_db)``
    nutzen, weil FastAPI die Connection freigibt sobald der Handler zurückkehrt —
    der StreamingResponse-Generator läuft aber danach weiter und würde eine bereits
    freigegebene Connection nutzen. Stattdessen holen wir uns die Connection direkt
    aus dem Pool und geben sie am Ende manuell zurück.
    """
    from fastapi.responses import StreamingResponse
    import json as _json
    from database import get_pool

    user_id = user["id"]
    uid_key = user["username"]  # nur für Log

    async def stream():
        # v1.33.0: race-safe Pool-Zugriff. Connection FUER die gesamte Stream-
        # Dauer halten -- Depends(get_db) wuerde sie zu frueh freigeben.
        pool = await get_pool()
        conn = await pool.acquire()
        try:
            rows = await conn.fetch(
                """SELECT e.id AS expense_id, e.store_id, r.ocr_raw_text
                   FROM expenses e
                   JOIN receipt_images r ON r.id=e.receipt_image_id
                   WHERE e.user_id=$1 AND r.ocr_raw_text IS NOT NULL
                     AND LENGTH(r.ocr_raw_text) > 5
                   ORDER BY e.id""",
                user_id)
            total = len(rows)

            cat_rows = await conn.fetch(
                "SELECT id, name FROM expense_categories WHERE user_id=$1", user_id)
            categories = [{"id": r["id"], "name": r["name"]} for r in cat_rows]
            store_rows = await conn.fetch(
                "SELECT name FROM stores WHERE user_id=$1", user_id)
            stores = [{"name": r["name"]} for r in store_rows]
            brand_rows_re = await conn.fetch(
                "SELECT name FROM brands WHERE user_id=$1", user_id)
            brands_ctx = [{"name": r["name"]} for r in brand_rows_re]
            valid_cat_ids = {c["id"] for c in categories}

            yield _json.dumps({"type": "start", "total": total}) + "\n"

            processed = 0
            updated_items = 0
            errors = 0

            for row in rows:
                eid = row["expense_id"]
                ocr_text = row["ocr_raw_text"] or ""
                try:
                    # User-editierte Items dieses Bons vor dem DELETE sichern
                    protected = await conn.fetch(
                        """SELECT description, base_name, original_text, quantity, quantity_unit,
                                  unit_price, total_price, category_id, sort_order,
                                  original_price, is_reduced, price_comparable, product_group
                           FROM expense_items
                           WHERE expense_id=$1 AND user_id=$2 AND user_edited=TRUE""",
                        eid, user_id)

                    parsed = await ai_parse_receipt(ocr_text, categories, stores, brands=brands_ctx)
                    items = parsed.get("items") or []
                    await conn.execute(
                        "DELETE FROM expense_items WHERE expense_id=$1 AND user_id=$2",
                        eid, user_id)
                    # User-Items zuerst zurückschreiben (behalten user_edited=true)
                    for p in protected:
                        await conn.execute(
                            """INSERT INTO expense_items
                               (user_id, expense_id, description, base_name, original_text,
                                quantity, quantity_unit, unit_price, total_price, category_id,
                                sort_order, original_price, is_reduced,
                                price_comparable, product_group, user_edited)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,TRUE)""",
                            user_id, eid, p["description"], p["base_name"], p["original_text"],
                            p["quantity"], p["quantity_unit"], p["unit_price"], p["total_price"],
                            p["category_id"], p["sort_order"], p["original_price"],
                            p["is_reduced"], p["price_comparable"], p["product_group"])
                    # Danach die AI-generierten Items (frisches Grouping)
                    for idx, it in enumerate(items):
                        cid = it.get("category_id")
                        if cid is not None and cid not in valid_cat_ids:
                            cid = None
                        # v1.16.0: brand_name -> brand_id aufloesen (via conn)
                        bid = await _resolve_brand_id(
                            conn, user_id, None, it.get("brand_name"), None)
                        await conn.execute(
                            """INSERT INTO expense_items
                               (user_id, expense_id, description, base_name, original_text,
                                quantity, quantity_unit, unit_price, total_price, category_id,
                                sort_order, original_price, is_reduced,
                                price_comparable, user_edited, brand_id)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,FALSE,$15)""",
                            user_id, eid,
                            (it.get("description") or "").strip(),
                            it.get("base_name"),
                            it.get("original_text"),
                            it.get("quantity") or 1,
                            it.get("quantity_unit"),
                            it.get("unit_price"),
                            it.get("total_price"),
                            cid,
                            len(protected) + idx,
                            it.get("original_price"),
                            bool(it.get("is_reduced")),
                            bool(it.get("price_comparable")) if it.get("price_comparable") is not None else True,
                            bid,
                        )
                    updated_items += len(items)
                    yield _json.dumps({
                        "type": "progress", "expense_id": eid,
                        "processed": processed + 1, "total": total,
                        "items": len(items), "ok": True,
                    }) + "\n"
                except Exception as e:
                    errors += 1
                    logger.exception(f"Reparse failed for expense {eid}: {e}")
                    yield _json.dumps({
                        "type": "progress", "expense_id": eid,
                        "processed": processed + 1, "total": total,
                        "ok": False, "error": str(e)[:120],
                    }) + "\n"
                processed += 1

            yield _json.dumps({
                "type": "done",
                "total": total, "updated_items": updated_items, "errors": errors,
            }) + "\n"
        finally:
            # v1.33.0: Pool ueber die zentrale Fabrik statt direkt auf
            # db_module._pool zugreifen (Race-Fix). ``pool`` kommt aus dem
            # umschliessenden Scope oben.
            try:
                await pool.release(conn)
            except Exception:
                pass

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.get("/api/receipts/{rid}/ocr")
async def get_receipt_ocr(rid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT ocr_raw_text, ocr_provider FROM receipt_images WHERE id=$1 AND user_id=$2",
        rid, user["id"])
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    user_stores_rows = await db.fetch("SELECT name FROM stores WHERE user_id=$1", user["id"])
    user_stores = [r["name"] for r in user_stores_rows]
    cat_rows = await db.fetch(
        "SELECT id, name FROM expense_categories WHERE user_id=$1", user["id"])
    brand_rows = await db.fetch(
        "SELECT name FROM brands WHERE user_id=$1", user["id"])
    ocr_text = row["ocr_raw_text"] or ""
    try:
        parsed = await ai_parse_receipt(
            ocr_text,
            [{"id": r["id"], "name": r["name"]} for r in cat_rows],
            [{"name": r["name"]} for r in user_stores_rows],
            brands=[{"name": r["name"]} for r in brand_rows],
        )
    except Exception as e:
        logger.warning(f"AI parse failed, falling back to regex: {e}")
        parsed = parse_receipt(ocr_text, user_stores=user_stores)
        parsed["_parser"] = "regex"
        parsed["_fallback_reason"] = f"outer_exception: {e}"
    return {
        "provider": row["ocr_provider"],
        "raw_text": ocr_text,
        "parsed": parsed,
    }


# ---------- Statistik / Analyse ----------
@router.get("/api/expenses/stats/summary")
async def stats_summary(db=Depends(get_db), user=Depends(get_current_user)):
    """Kompaktes Dashboard-KPI-Set."""
    today = date.today()
    month_start = today.replace(day=1)
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    year_start = today.replace(month=1, day=1)

    async def sum_between(a, b):
        v = await db.fetchval(
            "SELECT COALESCE(SUM(total_amount),0) FROM expenses "
            "WHERE user_id=$1 AND purchase_date BETWEEN $2 AND $3",
            user["id"], a, b)
        return float(v or 0)

    total_all = await db.fetchval(
        "SELECT COALESCE(SUM(total_amount),0) FROM expenses WHERE user_id=$1", user["id"])
    count_all = await db.fetchval(
        "SELECT COUNT(*) FROM expenses WHERE user_id=$1", user["id"])
    return {
        "today":       await sum_between(today, today),
        "this_week":   await sum_between(week_start, today),
        "this_month":  await sum_between(month_start, today),
        "prev_month":  await sum_between(prev_month_start, prev_month_end),
        "this_year":   await sum_between(year_start, today),
        "total":       float(total_all or 0),
        "count":       int(count_all or 0),
    }

@router.get("/api/expenses/stats/by-category")
async def stats_by_category(db=Depends(get_db), user=Depends(get_current_user),
                              date_from: Optional[str] = Query(None, alias="from"),
                              date_to: Optional[str] = Query(None, alias="to")):
    conds = ["ei.user_id=$1"]
    params = [user["id"]]
    if date_from:
        params.append(_parse_iso_date(date_from))
        conds.append(f"e.purchase_date >= ${len(params)}")
    if date_to:
        params.append(_parse_iso_date(date_to))
        conds.append(f"e.purchase_date <= ${len(params)}")
    rows = await db.fetch(
        f"""SELECT COALESCE(c.id, 0) AS category_id,
                   COALESCE(c.name, 'Unkategorisiert') AS name,
                   COALESCE(c.color, '#9ca3af') AS color,
                   COALESCE(c.icon, '❓') AS icon,
                   SUM(ei.total_price) AS total,
                   COUNT(*) AS item_count
            FROM expense_items ei
            JOIN expenses e ON e.id=ei.expense_id
            LEFT JOIN expense_categories c ON c.id=ei.category_id
            WHERE {' AND '.join(conds)}
            GROUP BY c.id, c.name, c.color, c.icon
            ORDER BY total DESC""",
        *params)
    return [_ser_exp(r) for r in rows]

@router.get("/api/expenses/stats/by-store")
async def stats_by_store(db=Depends(get_db), user=Depends(get_current_user),
                          date_from: Optional[str] = Query(None, alias="from"),
                          date_to: Optional[str] = Query(None, alias="to")):
    conds = ["e.user_id=$1"]
    params = [user["id"]]
    if date_from:
        params.append(_parse_iso_date(date_from))
        conds.append(f"e.purchase_date >= ${len(params)}")
    if date_to:
        params.append(_parse_iso_date(date_to))
        conds.append(f"e.purchase_date <= ${len(params)}")
    rows = await db.fetch(
        f"""SELECT COALESCE(s.id, 0) AS store_id,
                   COALESCE(s.name, 'Ohne Laden') AS name,
                   COALESCE(s.color, '#9ca3af') AS color,
                   COALESCE(s.icon, '🏪') AS icon,
                   SUM(e.total_amount) AS total,
                   COUNT(*) AS visit_count
            FROM expenses e
            LEFT JOIN stores s ON s.id=e.store_id
            WHERE {' AND '.join(conds)}
            GROUP BY s.id, s.name, s.color, s.icon
            ORDER BY total DESC""",
        *params)
    return [_ser_exp(r) for r in rows]


def _resolve_range(date_from: Optional[str], date_to: Optional[str],
                   fallback_days: int) -> tuple:
    """Ermittelt (since, until) aus optionalen ISO-Strings, mit Fallback."""
    until = _parse_iso_date(date_to) if date_to else date.today()
    if date_from:
        since = _parse_iso_date(date_from)
    else:
        since = until - timedelta(days=fallback_days - 1)
    return since, until


async def _insights_tops(db, user, since, until, prev_since, prev_until):
    """Top-Laeden + Top-Kategorien inkl. Vorperiode-Vergleich."""
    ts_rows = await db.fetch(
        """SELECT COALESCE(s.id,0) AS sid, COALESCE(s.name,'Ohne Laden') AS name,
                  COALESCE(s.color,'#9ca3af') AS color, COALESCE(s.icon,'🏪') AS icon,
                  SUM(e.total_amount) AS total, COUNT(*) AS visits
           FROM expenses e LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.user_id=$1 AND e.purchase_date BETWEEN $2 AND $3
           GROUP BY s.id, s.name, s.color, s.icon
           ORDER BY total DESC LIMIT 8""", user["id"], since, until)
    top_stores = []
    for r in ts_rows:
        prev = float(await db.fetchval(
            "SELECT COALESCE(SUM(e.total_amount),0) FROM expenses e "
            "WHERE e.user_id=$1 AND e.purchase_date BETWEEN $2 AND $3 AND COALESCE(e.store_id,0)=$4",
            user["id"], prev_since, prev_until, r["sid"]) or 0)
        top_stores.append({"name": r["name"], "color": r["color"], "icon": r["icon"],
                            "total": float(r["total"] or 0), "visits": int(r["visits"]),
                            "prev_total": prev,
                            "avg_per_visit": float(r["total"] or 0) / int(r["visits"]) if int(r["visits"]) else 0})

    tc_rows = await db.fetch(
        """SELECT COALESCE(c.id,0) AS cid, COALESCE(c.name,'Unkategorisiert') AS name,
                  COALESCE(c.color,'#9ca3af') AS color, COALESCE(c.icon,'❓') AS icon,
                  SUM(ei.total_price) AS total, COUNT(*) AS items
           FROM expense_items ei JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           WHERE ei.user_id=$1 AND e.purchase_date BETWEEN $2 AND $3
           GROUP BY c.id, c.name, c.color, c.icon
           ORDER BY total DESC LIMIT 10""", user["id"], since, until)
    top_categories = []
    for r in tc_rows:
        prev = float(await db.fetchval(
            """SELECT COALESCE(SUM(ei.total_price),0) FROM expense_items ei
               JOIN expenses e ON e.id=ei.expense_id
               WHERE ei.user_id=$1 AND e.purchase_date BETWEEN $2 AND $3
                 AND COALESCE(ei.category_id,0)=$4""",
            user["id"], prev_since, prev_until, r["cid"]) or 0)
        top_categories.append({"name": r["name"], "color": r["color"], "icon": r["icon"],
                                "total": float(r["total"] or 0), "items": int(r["items"]),
                                "prev_total": prev})
    return top_stores, top_categories


@router.get("/api/expenses/stats/monthly")
async def stats_monthly(db=Depends(get_db), user=Depends(get_current_user),
                         months: int = 12,
                         date_from: Optional[str] = Query(None, alias="from"),
                         date_to: Optional[str] = Query(None, alias="to")):
    """Ausgaben pro Monat. v1.18.0: optionaler ISO-Datumsbereich."""
    if date_from or date_to:
        since, until = _resolve_range(date_from, date_to, 365)
        since = since.replace(day=1)
    else:
        months = max(1, min(months, 60))
        today = date.today()
        since = today.replace(day=1)
        y, m = since.year, since.month
        for _ in range(months - 1):
            m -= 1
            if m == 0:
                m = 12; y -= 1
        since = date(y, m, 1)
        until = today
    rows = await db.fetch(
        """SELECT TO_CHAR(purchase_date, 'YYYY-MM') AS month,
                  SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2 AND purchase_date <= $3
           GROUP BY month ORDER BY month""",
        user["id"], since, until)
    return [{"month": r["month"], "total": float(r["total"] or 0),
             "count": int(r["count"])} for r in rows]

@router.get("/api/expenses/stats/weekly")
async def stats_weekly(db=Depends(get_db), user=Depends(get_current_user),
                         weeks: int = 12,
                         date_from: Optional[str] = Query(None, alias="from"),
                         date_to: Optional[str] = Query(None, alias="to")):
    """Ausgaben pro ISO-Kalenderwoche. v1.18.0: from/to."""
    if date_from or date_to:
        since, until = _resolve_range(date_from, date_to, 90)
    else:
        weeks = max(1, min(weeks, 52))
        today = date.today()
        since = today - timedelta(days=7 * (weeks - 1) + today.weekday())
        until = today
    rows = await db.fetch(
        """SELECT TO_CHAR(purchase_date, 'IYYY-"KW"IW') AS week,
                  DATE_TRUNC('week', purchase_date)::date AS week_start,
                  SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2 AND purchase_date <= $3
           GROUP BY week, week_start ORDER BY week_start""",
        user["id"], since, until)
    return [{"week": r["week"], "week_start": r["week_start"].isoformat() if r["week_start"] else None,
             "total": float(r["total"] or 0), "count": int(r["count"])} for r in rows]


@router.get("/api/expenses/stats/daily")
async def stats_daily(db=Depends(get_db), user=Depends(get_current_user),
                        days: int = 30,
                        date_from: Optional[str] = Query(None, alias="from"),
                        date_to: Optional[str] = Query(None, alias="to")):
    """Ausgaben pro Tag (Lücken als 0). v1.18.0: from/to."""
    if date_from or date_to:
        since, until = _resolve_range(date_from, date_to, 30)
    else:
        days = max(1, min(days, 730))
        until = date.today()
        since = until - timedelta(days=days - 1)
    if (until - since).days > 730:
        since = until - timedelta(days=730)
    rows = await db.fetch(
        """SELECT purchase_date AS d, SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2 AND purchase_date <= $3
           GROUP BY purchase_date ORDER BY purchase_date""",
        user["id"], since, until)
    by_day = {r["d"].isoformat(): (float(r["total"] or 0), int(r["count"])) for r in rows}
    out = []
    cur = since
    while cur <= until:
        key = cur.isoformat()
        total, count = by_day.get(key, (0.0, 0))
        out.append({"date": key, "total": total, "count": count})
        cur += timedelta(days=1)
    return out


@router.get("/api/expenses/stats/insights")
async def stats_insights(db=Depends(get_db), user=Depends(get_current_user),
                          date_from: Optional[str] = Query(None, alias="from"),
                          date_to: Optional[str] = Query(None, alias="to")):
    """Insights (v1.18.0): KPIs, Vorperiode-Vergleich, Wochentag-Verteilung,
    Top-Artikel/Läden/Kategorien."""
    since, until = _resolve_range(date_from, date_to, 30)
    span = (until - since).days + 1
    prev_until = since - timedelta(days=1)
    prev_since = prev_until - timedelta(days=span - 1)

    async def sum_range(a, b):
        return float(await db.fetchval(
            "SELECT COALESCE(SUM(total_amount),0) FROM expenses WHERE user_id=$1 "
            "AND purchase_date BETWEEN $2 AND $3", user["id"], a, b) or 0)

    total = await sum_range(since, until)
    prev_total = await sum_range(prev_since, prev_until)
    tx_count = int(await db.fetchval(
        "SELECT COUNT(*) FROM expenses WHERE user_id=$1 AND purchase_date BETWEEN $2 AND $3",
        user["id"], since, until) or 0)
    avg_tx = (total / tx_count) if tx_count else 0.0

    biggest = await db.fetchrow(
        "SELECT id, total_amount, purchase_date, store_id FROM expenses "
        "WHERE user_id=$1 AND purchase_date BETWEEN $2 AND $3 "
        "ORDER BY total_amount DESC LIMIT 1", user["id"], since, until)
    biggest_tx = None
    if biggest:
        store_name = await db.fetchval(
            "SELECT name FROM stores WHERE id=$1", biggest["store_id"]) if biggest["store_id"] else None
        biggest_tx = {"id": biggest["id"], "amount": float(biggest["total_amount"] or 0),
                       "date": biggest["purchase_date"].isoformat(), "store_name": store_name}

    wd_rows = await db.fetch(
        """SELECT EXTRACT(ISODOW FROM purchase_date)::int AS dow,
                  SUM(total_amount) AS total, COUNT(*) AS c
           FROM expenses WHERE user_id=$1 AND purchase_date BETWEEN $2 AND $3
           GROUP BY dow ORDER BY dow""", user["id"], since, until)
    by_weekday = [{"dow": i, "total": 0.0, "count": 0} for i in range(7)]
    for r in wd_rows:
        idx = int(r["dow"]) - 1
        by_weekday[idx] = {"dow": idx, "total": float(r["total"] or 0), "count": int(r["c"])}

    ti_rows = await db.fetch(
        """SELECT LOWER(TRIM(ei.description)) AS key, MIN(ei.description) AS name,
                  SUM(ei.total_price) AS total, COUNT(*) AS n,
                  MAX(e.purchase_date) AS last_date
           FROM expense_items ei JOIN expenses e ON e.id = ei.expense_id
           WHERE ei.user_id=$1 AND e.purchase_date BETWEEN $2 AND $3
             AND ei.description IS NOT NULL AND TRIM(ei.description) <> ''
           GROUP BY key ORDER BY total DESC LIMIT 12""", user["id"], since, until)
    top_items = [{"name": r["name"], "total": float(r["total"] or 0), "count": int(r["n"]),
                   "avg": float(r["total"] or 0) / int(r["n"]) if int(r["n"]) else 0,
                   "last_date": r["last_date"].isoformat() if r["last_date"] else None} for r in ti_rows]

    top_stores, top_categories = await _insights_tops(db, user, since, until, prev_since, prev_until)
    return {
        "range": {"from": since.isoformat(), "to": until.isoformat(), "days": span},
        "kpi": {"total": total, "tx_count": tx_count, "avg_tx": avg_tx,
                 "avg_per_day": total / span if span else 0, "biggest_tx": biggest_tx},
        "compare_prev": {"total": prev_total, "diff_abs": total - prev_total,
                          "diff_pct": ((total - prev_total) / prev_total * 100.0) if prev_total > 0 else None,
                          "range": {"from": prev_since.isoformat(), "to": prev_until.isoformat()}},
        "by_weekday": by_weekday, "top_items": top_items,
        "top_stores": top_stores, "top_categories": top_categories,
    }


@router.get("/api/expenses/heatmap")
async def expenses_heatmap(db=Depends(get_db), user=Depends(get_current_user)):
    since = date.today() - timedelta(days=365)
    rows = await db.fetch(
        """SELECT purchase_date AS d, SUM(total_amount) AS s, COUNT(*) AS c
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2
           GROUP BY purchase_date""",
        user["id"], since)
    by_day = {r["d"].isoformat(): (float(r["s"] or 0), int(r["c"])) for r in rows}
    max_amount = max((v[0] for v in by_day.values()), default=0.0)
    out = []
    cur = since
    end = date.today()
    while cur <= end:
        key = cur.isoformat()
        amount, count = by_day.get(key, (0.0, 0))
        if amount <= 0 or max_amount <= 0:
            level = 0
        else:
            ratio = amount / max_amount
            if ratio < 0.25: level = 1
            elif ratio < 0.5: level = 2
            elif ratio < 0.75: level = 3
            else: level = 4
        out.append({"date": key, "amount": round(amount, 2), "count": count, "level": level})
        cur += timedelta(days=1)
    return out

@router.get("/api/expenses/price-history")
async def price_history(q: str = Query(..., min_length=2),
                         db=Depends(get_db), user=Depends(get_current_user)):
    """Preisverlauf mit echtem Vergleich:
    - alle Käufe passend zum Suchbegriff
    - Summary: Ø-Preis, günstigster/teuerster Laden, Diff in € und %
    - je Kauf: Diff zum Ø-Preis (billiger/teurer)
    Berechnet mit Einzelpreis (total_price/quantity), damit Mengen vergleichbar werden.
    """
    rows = await db.fetch(
        """SELECT ei.id, ei.description, ei.total_price, ei.quantity, ei.unit_price,
                  ei.original_price, ei.is_reduced,
                  e.purchase_date, e.store_id,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE ei.user_id=$1 AND LOWER(ei.description) LIKE '%' || LOWER($2) || '%'
           ORDER BY e.purchase_date DESC
           LIMIT 500""",
        user["id"], q)
    if not rows:
        return {
            "count": 0, "items": [], "by_store": [],
            "avg_unit_price": None, "cheapest": None, "most_expensive": None,
            "max_diff_pct": 0,
        }

    def unit_price(r):
        qty = float(r["quantity"] or 1) or 1
        return float(r["total_price"]) / qty

    items = []
    for r in rows:
        up = unit_price(r)
        items.append({
            "id": r["id"],
            "description": r["description"],
            "total_price": float(r["total_price"]),
            "quantity": float(r["quantity"] or 1),
            "unit_price_calc": round(up, 4),
            "original_price": float(r["original_price"]) if r["original_price"] is not None else None,
            "is_reduced": bool(r["is_reduced"]),
            "purchase_date": r["purchase_date"].isoformat() if r["purchase_date"] else None,
            "store_id": r["store_id"],
            "store_name": r["store_name"] or "Ohne Laden",
            "store_color": r["store_color"] or "#9ca3af",
            "store_icon": r["store_icon"] or "🏪",
        })

    all_up = [i["unit_price_calc"] for i in items]
    avg = sum(all_up) / len(all_up)

    # Diff pro Item zum Durchschnitt
    for i in items:
        diff = i["unit_price_calc"] - avg
        i["diff_to_avg"] = round(diff, 2)
        i["diff_pct"] = round((diff / avg) * 100.0, 1) if avg > 0 else 0.0

    # Pro Store aggregieren
    from collections import defaultdict
    store_group = defaultdict(list)
    for i in items:
        store_group[(i["store_id"], i["store_name"], i["store_color"], i["store_icon"])].append(i)
    by_store = []
    for (sid, sname, scolor, sicon), group in store_group.items():
        ups = [g["unit_price_calc"] for g in group]
        by_store.append({
            "store_id": sid, "store_name": sname,
            "store_color": scolor, "store_icon": sicon,
            "avg_unit_price": round(sum(ups) / len(ups), 4),
            "min_unit_price": round(min(ups), 4),
            "max_unit_price": round(max(ups), 4),
            "count": len(group),
            "diff_to_avg_pct": round(((sum(ups)/len(ups)) - avg) / avg * 100.0, 1) if avg > 0 else 0.0,
        })
    by_store.sort(key=lambda x: x["avg_unit_price"])

    cheapest = by_store[0] if by_store else None
    most_expensive = by_store[-1] if by_store else None
    max_diff_pct = round(
        (most_expensive["avg_unit_price"] - cheapest["avg_unit_price"]) / cheapest["avg_unit_price"] * 100.0, 1
    ) if cheapest and cheapest["avg_unit_price"] > 0 and cheapest is not most_expensive else 0.0

    return {
        "count": len(items),
        "items": items,
        "by_store": by_store,
        "avg_unit_price": round(avg, 4),
        "cheapest": cheapest,
        "most_expensive": most_expensive,
        "max_diff_pct": max_diff_pct,
    }

@router.get("/api/expenses/recurring/suggestions")
async def recurring_suggestions(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        """SELECT store_id, s.name AS store_name,
                  ROUND(total_amount::numeric, 0) AS approx_amount,
                  COUNT(DISTINCT DATE_TRUNC('month', purchase_date)) AS months,
                  AVG(total_amount) AS avg_amount,
                  MAX(purchase_date) AS last_date
           FROM expenses e
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.user_id=$1 AND e.is_recurring=FALSE AND store_id IS NOT NULL
           GROUP BY store_id, s.name, approx_amount
           HAVING COUNT(DISTINCT DATE_TRUNC('month', purchase_date)) >= 3
           ORDER BY months DESC, last_date DESC
           LIMIT 20""",
        user["id"])
    return [_ser_exp(r) for r in rows]

@router.get("/api/expenses/duplicates/check")
async def check_duplicate(
    date: str, total: float, store_id: Optional[int] = None,
    db=Depends(get_db), user=Depends(get_current_user)):
    d = _parse_iso_date(date)
    conds = ["user_id=$1", "purchase_date=$2", "ABS(total_amount - $3) < 1.0"]
    params = [user["id"], d, total]
    if store_id:
        params.append(store_id)
        conds.append(f"store_id=${len(params)}")
    rows = await db.fetch(
        f"SELECT id, purchase_date, total_amount, store_id FROM expenses "
        f"WHERE {' AND '.join(conds)} LIMIT 5", *params)
    return [_ser_exp(r) for r in rows]


# ---------- Duplikat-Erkennung & automatische Zusammenfuehrung (v1.21.0) ----------
@router.get("/api/expenses/duplicates")
async def list_duplicate_groups(db=Depends(get_db), user=Depends(get_current_user)):
    """Findet bereits bestehende Duplikat-Kandidaten im gesamten Bestand:
    gleicher Laden (oder beide ohne Laden), gleiches Kaufdatum, Betrag
    innerhalb von 1 Euro Differenz. Gruppiert die betroffenen Bons, damit das
    Frontend sie dem User zur Bestaetigung anzeigen kann, statt sie blind
    automatisch zu loeschen.
    """
    rows = await db.fetch(
        """SELECT e.id, e.purchase_date, e.total_amount, e.store_id, e.expense_type,
                  e.receipt_image_id, e.note,
                  s.name AS store_name, s.icon AS store_icon,
                  (SELECT COUNT(*) FROM expense_items ei WHERE ei.expense_id=e.id) AS item_count
           FROM expenses e
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.user_id=$1
           ORDER BY e.purchase_date DESC, e.id DESC""",
        user["id"])

    groups = []
    used = set()
    rows_list = list(rows)
    for i, a in enumerate(rows_list):
        if a["id"] in used:
            continue
        cluster = [a]
        for b in rows_list[i+1:]:
            if b["id"] in used:
                continue
            if a["purchase_date"] != b["purchase_date"]:
                continue
            if a["store_id"] != b["store_id"]:
                continue
            if abs(float(a["total_amount"]) - float(b["total_amount"])) >= 1.0:
                continue
            cluster.append(b)
        if len(cluster) > 1:
            for c in cluster:
                used.add(c["id"])
            # Bevorzugt den Bon mit Beleg-Bild und mehr Positionen als "Original"
            cluster.sort(key=lambda r: (r["receipt_image_id"] is not None, r["item_count"] or 0), reverse=True)
            groups.append({
                "keep_id": cluster[0]["id"],
                "items": [{
                    "id": r["id"],
                    "purchase_date": r["purchase_date"].isoformat() if r["purchase_date"] else None,
                    "total_amount": float(r["total_amount"]),
                    "store_name": r["store_name"] or "Ohne Laden",
                    "store_icon": r["store_icon"] or "🏪",
                    "expense_type": r["expense_type"],
                    "has_image": r["receipt_image_id"] is not None,
                    "item_count": int(r["item_count"] or 0),
                    "note": r["note"],
                } for r in cluster],
            })
    return {"groups": groups, "count": len(groups)}


@router.post("/api/expenses/duplicates/merge")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def merge_duplicate_expenses(request: Request, body: dict,
                                    db=Depends(get_db), user=Depends(get_current_user)):
    """Fuehrt mehrere Duplikat-Bons zu einem zusammen.
    Body: {keep_id: int, remove_ids: [int, ...]}
    - Positionen (expense_items) der zu entfernenden Bons werden auf den
      behaltenen Bon umgehaengt (keine Daten gehen verloren).
    - Ist der behaltene Bon ohne Beleg-Bild, aber einer der zu entfernenden
      Bons hat eines, wird das Bild uebernommen.
    - Die zu entfernenden Bons werden anschliessend geloescht.
    """
    keep_id = body.get("keep_id")
    remove_ids = [i for i in (body.get("remove_ids") or []) if i != keep_id]
    if not keep_id or not remove_ids:
        raise HTTPException(400, "keep_id und remove_ids erforderlich")

    keep = await db.fetchrow(
        "SELECT id, receipt_image_id FROM expenses WHERE id=$1 AND user_id=$2", keep_id, user["id"])
    if not keep:
        raise HTTPException(404, "Ziel-Bon nicht gefunden")
    owned_removes = await db.fetch(
        "SELECT id, receipt_image_id FROM expenses WHERE id = ANY($1) AND user_id=$2",
        remove_ids, user["id"])
    owned_ids = [r["id"] for r in owned_removes]
    if not owned_ids:
        raise HTTPException(404, "Keine der Duplikat-IDs gehoert dem User")

    moved_items = 0
    async with db.transaction():
        r = await db.execute(
            "UPDATE expense_items SET expense_id=$1 WHERE expense_id = ANY($2) AND user_id=$3",
            keep_id, owned_ids, user["id"])
        try: moved_items = int(r.split()[-1])
        except (ValueError, IndexError): pass

        if not keep["receipt_image_id"]:
            donor = next((r for r in owned_removes if r["receipt_image_id"]), None)
            if donor:
                await db.execute(
                    "UPDATE expenses SET receipt_image_id=$1 WHERE id=$2 AND user_id=$3",
                    donor["receipt_image_id"], keep_id, user["id"])

        await db.execute(
            "DELETE FROM expenses WHERE id = ANY($1) AND user_id=$2", owned_ids, user["id"])

    logger.info(f"User {user['id']} merged duplicate expenses {owned_ids} into {keep_id}: {moved_items} items moved")
    return {"status": "merged", "keep_id": keep_id, "removed_ids": owned_ids, "moved_items": moved_items}


# ---------- Produkt-Preisverlauf (Aggregation aller gekauften Artikel) ----------
@router.get("/api/expenses/products")
async def list_products(
    min_count: int = 2,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
    store_id: Optional[int] = None,
    db=Depends(get_db), user=Depends(get_current_user),
):
    """Aggregierte Produktliste über alle Bons — fuer den Preisverlauf-Tab
    und die Produkt-Statistik-Seite.

    Gruppiert nach normalisierter Beschreibung (Basisname vor "(").
    Fuer jedes Produkt: letzter Preis + Rabatt-/Preiserhoehung ggue. vorherigem Kauf,
    plus Preis/kg oder Preis/L falls Einheit bekannt.

    Parameter ``min_count`` (v1.16.0, strikt ab v1.17.x): Nur Produkte mit
    mindestens N Kaeufen zurueckgeben — die Standard-Ansicht zeigt nur Produkte,
    die man mehrmals gekauft hat (Einmal-Kaeufe sind fuer Preisverlauf
    uninteressant). ``min_count=1`` gibt alle Produkte zurueck.

    Optionale Filter (v1.20.0) fuer die Produkt-Statistik-Seite: ``date_from``/
    ``date_to`` (ISO-Datum, beschraenkt auf einzelne Kaeufe im Zeitraum),
    ``category_id`` und ``store_id`` (beschraenken auf Kaeufe der letzten
    Kategorie/Laden). Die Aggregation (Anzahl, Gesamtsumme etc.) bezieht sich
    dann nur auf die gefilterten Kaeufe.
    """
    conds = ["ei.user_id=$1", "COALESCE(ei.price_comparable, TRUE)=TRUE",
             "(ei.base_name IS NOT NULL OR (ei.description IS NOT NULL AND ei.description != ''))",
             "ei.total_price > 0"]
    params = [user["id"]]
    # Bugfix (war Ursache fuer HTTP 500 auf der Produkt-Seite): date_from/
    # date_to kamen als rohe Strings an und wurden ungecastet gegen die
    # ``date``-Spalte ``purchase_date`` verglichen -> asyncpg/Postgres wirft
    # "operator does not exist: date >= text". Muessen zuerst in echte
    # date-Objekte geparst werden, wie es der Rest des Moduls auch macht.
    df = _parse_iso_date(date_from) if date_from else None
    dt = _parse_iso_date(date_to) if date_to else None
    if df:
        params.append(df)
        conds.append(f"e.purchase_date >= ${len(params)}")
    if dt:
        params.append(dt)
        conds.append(f"e.purchase_date <= ${len(params)}")
    if category_id:
        params.append(category_id)
        conds.append(f"ei.category_id = ${len(params)}")
    if store_id:
        params.append(store_id)
        conds.append(f"e.store_id = ${len(params)}")

    # Nur Artikel die als vergleichbar markiert sind (KI-Flag price_comparable=true)
    rows = await db.fetch(
        f"""SELECT ei.description, ei.base_name, ei.original_text,
                  ei.total_price, ei.quantity, ei.quantity_unit,
                  ei.original_price, ei.is_reduced, ei.product_group,
                  ei.brand_id, ei.category_id,
                  e.purchase_date, e.store_id,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon,
                  c.name AS category_name,
                  b.name AS brand_name, b.is_private_label AS brand_is_private_label
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           LEFT JOIN brands b ON b.id=ei.brand_id
           WHERE {' AND '.join(conds)}
           ORDER BY e.purchase_date DESC, ei.id DESC""",
        *params)


    from collections import defaultdict
    import re

    def norm_key(desc):
        """Normalisiert zu einem Produkt-Basisnamen:
        - alles nach '(' abschneiden (Originaltext),
        - Menge+Einheit am Ende entfernen ('2kg', '500g', '1L', '10 Stk'),
        - lowercase, Whitespace normalisieren.
        So gruppieren "Vollmilch 1L (ESL-Vollm.)" und "Vollmilch 500ml (Clever)"
        beide zu 'vollmilch'.
        """
        d = (desc or "").strip()
        if "(" in d:
            d = d.split("(", 1)[0].strip()
        # Trailing Menge+Einheit entfernen (mehrfach falls "2 Stk 500g" etc.)
        d = re.sub(r"\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|pack|btl|blatt|x\d+)\s*$",
                   "", d, flags=re.IGNORECASE)
        d = re.sub(r"\s+", " ", d).strip().lower()
        return d

    def unit_price_of(r):
        """Einheits-normalisierter Preis für Vergleiche über Größenvarianten hinweg.
        - kg/L: total_price / quantity → Preis pro kg/L
        - g:    (total_price / quantity) * 1000 → Preis pro kg
        - ml:   (total_price / quantity) * 1000 → Preis pro L
        - sonst: total_price / quantity (Stk/Pack/etc.)
        """
        qty = float(r["quantity"] or 1) or 1
        tp = float(r["total_price"])
        unit = (r["quantity_unit"] or "").lower()
        if unit == "g":
            return (tp / qty) * 1000.0
        if unit == "ml":
            return (tp / qty) * 1000.0
        return tp / qty

    def group_key(r):
        # Priorität: product_group (manuelle Zuordnung) → base_name → norm_key(description)
        pg = (r["product_group"] or "").strip().lower()
        if pg:
            return pg
        bn = (r["base_name"] or "").strip().lower()
        if bn:
            return bn
        return norm_key(r["description"])

    groups = defaultdict(list)
    for r in rows:
        k = group_key(r)
        if not k:
            continue
        groups[k].append(r)

    products = []
    for key, purchases in groups.items():
        # rows sind DESC nach Datum → purchases[0] = neuester Kauf
        last = purchases[0]
        prices = [float(p["total_price"]) for p in purchases]
        unit_prices = [unit_price_of(p) for p in purchases]

        # --- Preisänderung PRO LADEN berechnen (nicht cross-store!) ---
        # Suche vorherigen Kauf beim SELBEN Laden wie der letzte Kauf.
        change_abs = change_pct = change_direction = None
        last_store_id = last["store_id"]
        same_store_prev = None
        for p in purchases[1:]:
            if p["store_id"] == last_store_id:
                same_store_prev = p
                break
        if same_store_prev is not None:
            last_up = unit_price_of(last)
            prev_up = unit_price_of(same_store_prev)
            if prev_up > 0:
                change_abs = round(last_up - prev_up, 4)
                change_pct = round((change_abs / prev_up) * 100.0, 1)
                if change_pct >= 1:
                    change_direction = "up"
                elif change_pct <= -1:
                    change_direction = "down"

        # --- Store-Vergleich: welcher Laden ist im Schnitt am günstigsten? ---
        by_store = defaultdict(list)
        for p in purchases:
            by_store[(p["store_id"], p["store_name"], p["store_color"], p["store_icon"])].append(unit_price_of(p))
        store_stats = []
        for (sid, sname, scolor, sicon), ups in by_store.items():
            store_stats.append({
                "store_id": sid,
                "store_name": sname or "Ohne Laden",
                "store_color": scolor or "#9ca3af",
                "store_icon": sicon or "🏪",
                "avg_unit_price": round(sum(ups) / len(ups), 4),
                "count": len(ups),
            })
        cheapest = min(store_stats, key=lambda s: s["avg_unit_price"]) if store_stats else None
        expensive = max(store_stats, key=lambda s: s["avg_unit_price"]) if len(store_stats) > 1 else None
        max_diff_pct = None
        if cheapest and expensive and cheapest["store_id"] != expensive["store_id"] and cheapest["avg_unit_price"] > 0:
            max_diff_pct = round(
                (expensive["avg_unit_price"] - cheapest["avg_unit_price"]) / cheapest["avg_unit_price"] * 100.0, 1)

        # €/kg bzw €/L für die Preis-Sub-Zeile in der Liste
        price_per_kg = None
        price_per_l = None
        unit = (last["quantity_unit"] or "").lower() if last["quantity_unit"] else ""
        qty = float(last["quantity"] or 0)
        tp = float(last["total_price"])
        if qty > 0 and tp > 0:
            if unit == "kg":
                price_per_kg = round(tp / qty, 2)
            elif unit == "g":
                price_per_kg = round(tp / (qty / 1000.0), 2)
            elif unit == "l":
                price_per_l = round(tp / qty, 2)
            elif unit == "ml":
                price_per_l = round(tp / (qty / 1000.0), 2)

        # Titel: base_name wenn vorhanden, sonst aus description ableiten
        title = (last["base_name"] or "").strip()
        if not title:
            title = norm_key(last["description"]).title() or last["description"]

        # v1.17.x: Filter nach min_count strikt — Produkte mit weniger als
        # ``min_count`` Kaeufen werden konsequent ausgeblendet.
        # (Frueher Ausnahme fuer brand_id gesetzt: fiel weg, weil der KI-Parser
        # inzwischen fast jedem Item eine Marke zuordnet und dadurch die
        # UI-Zusage "nur mehrfach gekaufte Produkte" verletzt wurde.)
        if len(purchases) < min_count:
            continue

        # Sammle Marken-Info (von der letzten Buchung)
        last_brand_id = last.get("brand_id")
        last_brand_name = last.get("brand_name")

        products.append({
            "key": key,
            "title": title,
            "description": last["description"],
            "base_name": last["base_name"],
            "original_text": last["original_text"],
            "category_name": last["category_name"],
            "brand_id": last_brand_id,
            "brand_name": last_brand_name,
            "brand_is_private_label": bool(last.get("brand_is_private_label")),
            "count": len(purchases),
            "last_date": last["purchase_date"].isoformat() if last["purchase_date"] else None,
            "last_price": tp,
            "last_unit_price": round(unit_price_of(last), 4),
            "last_quantity": float(last["quantity"] or 1),
            "last_quantity_unit": last["quantity_unit"],
            "last_original_price": float(last["original_price"]) if last["original_price"] is not None else None,
            "last_is_reduced": bool(last["is_reduced"]),
            "last_store_id": last["store_id"],
            "last_store_name": last["store_name"] or "Ohne Laden",
            "last_store_color": last["store_color"] or "#9ca3af",
            "last_store_icon": last["store_icon"] or "🏪",
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "min_unit_price": round(min(unit_prices), 4),
            "max_unit_price": round(max(unit_prices), 4),
            "avg_unit_price": round(sum(unit_prices) / len(unit_prices), 4),
            "price_change_abs": change_abs,
            "price_change_pct": change_pct,
            "price_change_direction": change_direction,
            "price_change_same_store": same_store_prev is not None,
            "price_per_kg": price_per_kg,
            "price_per_l": price_per_l,
            "cheapest_store": cheapest,
            "most_expensive_store": expensive,
            "max_diff_pct": max_diff_pct,
        })

    # Default-Sortierung: neuester Kauf zuerst (User erwartet was er zuletzt gekauft hat)
    products.sort(key=lambda p: p["last_date"] or "", reverse=True)
    return products


class ItemGroupOverride(BaseModel):
    # None => zurück zum automatischen Grouping (Basisname)
    # Sonst: expliziter Gruppenschlüssel (z.B. "_solo_<random>" für "alleine lassen")
    product_group: Optional[str] = None


@router.put("/api/expense-items/{iid:int}/product-group")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def set_item_product_group(request: Request, iid: int, b: ItemGroupOverride,
                                  db=Depends(get_db), user=Depends(get_current_user)):
    """Überschreibt die Produkt-Gruppe eines einzelnen Items.

    Anwendungsfall: Ein Artikel wurde vom Preisverlauf-Grouping fälschlich mit
    einem anderen Produkt zusammengefasst (z.B. „Kaffeesahne" landet in „Milch").
    Der User setzt eine eigene ``product_group`` — entweder einen sprechenden
    eigenen Namen oder ``null`` um zum automatischen Grouping zurückzukehren.
    Wenn hier ein zufälliger eindeutiger String gesetzt wird, ist das Item
    danach in einer eigenen Ein-Item-Gruppe.
    """
    existing = await db.fetchval(
        "SELECT 1 FROM expense_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    pg = (b.product_group or "").strip() or None
    await db.execute(
        "UPDATE expense_items SET product_group=$1 WHERE id=$2 AND user_id=$3",
        pg, iid, user["id"])
    return {"status": "ok", "item_id": iid, "product_group": pg}


class ItemPriceComparableToggle(BaseModel):
    price_comparable: bool


@router.put("/api/expense-items/{iid:int}/price-comparable")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def toggle_price_comparable(request: Request, iid: int, b: ItemPriceComparableToggle,
                                   db=Depends(get_db), user=Depends(get_current_user)):
    """Schaltet ein Item aus dem Preisvergleich aus (oder wieder ein).
    Nützlich für Einmalkäufe wie Töpfe, Vorratsdosen, Werkzeug etc., die die
    KI falsch als vergleichbar eingestuft hat. Setzt zusätzlich user_edited=TRUE,
    damit ein zukünftiger Reparse diese manuelle Entscheidung nicht überschreibt."""
    existing = await db.fetchval(
        "SELECT 1 FROM expense_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    await db.execute(
        "UPDATE expense_items SET price_comparable=$1, user_edited=TRUE WHERE id=$2 AND user_id=$3",
        bool(b.price_comparable), iid, user["id"])
    return {"status": "ok", "item_id": iid, "price_comparable": bool(b.price_comparable)}


@router.get("/api/expenses/products/history")
async def product_history(key: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Alle Käufe eines Produkts (nach normalisiertem Basisnamen ODER expliziter
    product_group) fuer Zeitreihen-Chart und Item-Liste."""
    key = (key or "").strip().lower()
    if len(key) < 2:
        raise HTTPException(400, "Key zu kurz")
    rows = await db.fetch(
        """SELECT ei.id AS item_id, ei.description, ei.base_name, ei.original_text,
                  ei.total_price, ei.quantity, ei.quantity_unit,
                  ei.original_price, ei.is_reduced, ei.product_group,
                  ei.price_comparable, ei.expense_id,
                  e.purchase_date, e.store_id,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE ei.user_id=$1
           ORDER BY e.purchase_date ASC, ei.id ASC""",
        user["id"])

    import re
    from collections import defaultdict

    def norm_key(desc):
        d = (desc or "").strip()
        if "(" in d:
            d = d.split("(", 1)[0].strip()
        d = re.sub(r"\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|pack|btl|blatt|x\d+)\s*$",
                   "", d, flags=re.IGNORECASE)
        d = re.sub(r"\s+", " ", d).strip().lower()
        return d

    def unit_price_norm(qty, tp, unit):
        u = (unit or "").lower()
        if u in ("g", "ml"):
            return (tp / qty) * 1000.0
        return tp / qty

    def item_key(r):
        pg = (r["product_group"] or "").strip().lower()
        if pg:
            return pg
        bn = (r["base_name"] or "").strip().lower()
        if bn:
            return bn
        return norm_key(r["description"])

    items = []
    for r in rows:
        if item_key(r) != key:
            continue
        qty = float(r["quantity"] or 1) or 1
        tp = float(r["total_price"])
        items.append({
            "item_id": r["item_id"],
            "expense_id": r["expense_id"],
            "date": r["purchase_date"].isoformat() if r["purchase_date"] else None,
            "description": r["description"],
            "base_name": r["base_name"],
            "original_text": r["original_text"],
            "total_price": tp,
            "quantity": qty,
            "quantity_unit": r["quantity_unit"],
            "unit_price": round(unit_price_norm(qty, tp, r["quantity_unit"]), 4),
            "original_price": float(r["original_price"]) if r["original_price"] is not None else None,
            "is_reduced": bool(r["is_reduced"]),
            "product_group": r["product_group"],
            "price_comparable": bool(r["price_comparable"]) if r["price_comparable"] is not None else True,
            "store_id": r["store_id"],
            "store_name": r["store_name"] or "Ohne Laden",
            "store_color": r["store_color"] or "#9ca3af",
            "store_icon": r["store_icon"] or "🏪",
        })

    # Store-Vergleichs-Summary
    by_store = defaultdict(list)
    for it in items:
        by_store[(it["store_id"], it["store_name"], it["store_color"], it["store_icon"])].append(it["unit_price"])
    store_summary = []
    for (sid, sname, scolor, sicon), ups in by_store.items():
        store_summary.append({
            "store_id": sid, "store_name": sname,
            "store_color": scolor, "store_icon": sicon,
            "avg_unit_price": round(sum(ups) / len(ups), 4),
            "count": len(ups),
        })
    store_summary.sort(key=lambda s: s["avg_unit_price"])
    cheapest = store_summary[0] if store_summary else None
    expensive = store_summary[-1] if len(store_summary) > 1 else None
    max_diff_pct = None
    if cheapest and expensive and cheapest["store_id"] != expensive["store_id"] and cheapest["avg_unit_price"] > 0:
        max_diff_pct = round(
            (expensive["avg_unit_price"] - cheapest["avg_unit_price"]) / cheapest["avg_unit_price"] * 100.0, 1)

    return {
        "items": items,
        "store_summary": store_summary,
        "cheapest_store": cheapest,
        "most_expensive_store": expensive,
        "max_diff_pct": max_diff_pct,
    }


# ---------- Export ----------
@router.get("/api/expenses/export")
async def export_expenses(db=Depends(get_db), user=Depends(get_current_user)):
    """CSV-Export aller Bons + Einzelpositionen (Semikolon-getrennt, UTF-8 mit BOM).

    Eine Zeile pro Position; Bons ohne Positionen erscheinen mit einer Zeile.
    """
    rows = await db.fetch(
        """SELECT e.id, e.purchase_date, e.total_amount, e.payment_method,
                  e.expense_type, e.note,
                  s.name AS store_name
           FROM expenses e
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.user_id=$1 ORDER BY e.purchase_date DESC, e.id DESC""",
        user["id"])

    item_rows = await db.fetch(
        """SELECT ei.expense_id, ei.description, ei.quantity, ei.quantity_unit,
                  ei.unit_price, ei.total_price, ei.is_reduced, ei.original_price,
                  c.name AS category_name
           FROM expense_items ei
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           WHERE ei.user_id=$1 ORDER BY ei.expense_id, ei.sort_order NULLS LAST, ei.id""",
        user["id"])
    items_by_exp = {}
    for it in item_rows:
        items_by_exp.setdefault(it["expense_id"], []).append(it)

    import csv
    import io as _io

    def euro(v):
        if v is None:
            return ""
        try:
            return f"{float(v):.2f}".replace(".", ",")
        except (TypeError, ValueError):
            return ""

    buf = _io.StringIO()
    # Semikolon + Anführungszeichen als Text-Qualifier -> Excel-kompatibel (DE-Locale)
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow([
        "Datum", "Laden", "Typ", "Gesamt (EUR)", "Zahlungsart",
        "Position", "Menge", "Einheit", "Einzelpreis (EUR)", "Positionspreis (EUR)",
        "Original-Preis (EUR)", "Reduziert", "Kategorie", "Notiz",
    ])
    for r in rows:
        base = [
            r["purchase_date"].isoformat() if r["purchase_date"] else "",
            r["store_name"] or "",
            r["expense_type"] or "",
            euro(r["total_amount"]),
            r["payment_method"] or "",
        ]
        note = (r["note"] or "").replace("\n", " ").replace("\r", " ")
        items = items_by_exp.get(r["id"], [])
        if not items:
            w.writerow(base + ["", "", "", "", "", "", "", "", note])
            continue
        for it in items:
            w.writerow(base + [
                it["description"] or "",
                euro(it["quantity"]),
                it["quantity_unit"] or "",
                euro(it["unit_price"]),
                euro(it["total_price"]),
                euro(it["original_price"]),
                "ja" if it["is_reduced"] else "",
                it["category_name"] or "",
                note,
            ])
    # BOM voranstellen -> Excel öffnet UTF-8 mit Umlauten korrekt
    content = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ausgaben.csv"',
            "Cache-Control": "no-store",
        },
    )

@router.get("/api/expenses/ocr/status")
async def ocr_status(user=Depends(get_current_user)):
    """Zeigt an, ob OCR im Backend verfügbar ist."""
    p = get_ocr_provider()
    return {"provider": p.name, "available": p.available}

