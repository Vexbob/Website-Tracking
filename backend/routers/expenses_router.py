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
    quantity: Optional[float] = 1
    quantity_unit: Optional[str] = None
    unit_price: Optional[float] = None
    total_price: float
    category_id: Optional[int] = None
    original_price: Optional[float] = None
    is_reduced: Optional[bool] = False

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
        """SELECT ei.*, c.name AS category_name, c.color AS category_color, c.icon AS category_icon
           FROM expense_items ei
           LEFT JOIN expense_categories c ON c.id=ei.category_id
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
                await db.execute(
                    """INSERT INTO expense_items
                       (user_id, expense_id, description, quantity, quantity_unit,
                        unit_price, total_price, category_id, sort_order,
                        original_price, is_reduced)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                    user["id"], eid, it.description.strip(),
                    it.quantity or 1, it.quantity_unit,
                    it.unit_price, it.total_price, cat_id, idx,
                    it.original_price, bool(it.is_reduced))
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
    row = await db.fetchrow(
        """INSERT INTO expense_items
           (user_id, expense_id, description, quantity, quantity_unit,
            unit_price, total_price, category_id,
            original_price, is_reduced)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
        user["id"], eid, b.description.strip(), b.quantity or 1, b.quantity_unit,
        b.unit_price, b.total_price, cat_id, b.original_price, bool(b.is_reduced))
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
    await db.execute(
        """UPDATE expense_items
           SET description=$1, quantity=$2, quantity_unit=$3, unit_price=$4,
               total_price=$5, category_id=$6, original_price=$7, is_reduced=$8
           WHERE id=$9 AND user_id=$10""",
        b.description.strip(), b.quantity or 1, b.quantity_unit,
        b.unit_price, b.total_price,
        cat_id, b.original_price, bool(b.is_reduced), iid, user["id"])
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

    # Bekannte Läden & Kategorien des Users für Store-Match und AI-Parsing
    user_stores_rows = await db.fetch("SELECT name FROM stores WHERE user_id=$1", user["id"])
    user_stores = [r["name"] for r in user_stores_rows]
    cat_rows = await db.fetch(
        "SELECT id, name FROM expense_categories WHERE user_id=$1", user["id"])
    try:
        parsed = await ai_parse_receipt(
            ocr_text,
            [{"id": r["id"], "name": r["name"]} for r in cat_rows],
            [{"name": r["name"]} for r in user_stores_rows],
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
    import database as db_module

    user_id = user["id"]
    uid_key = user["username"]  # nur für Log

    async def stream():
        # Connection FÜR die gesamte Stream-Dauer halten
        if db_module._pool is None:
            import asyncpg as _apg
            db_module._pool = await _apg.create_pool(
                db_module.DATABASE_URL, ssl="require", min_size=1, max_size=10)
        conn = await db_module._pool.acquire()
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
            valid_cat_ids = {c["id"] for c in categories}

            yield _json.dumps({"type": "start", "total": total}) + "\n"

            processed = 0
            updated_items = 0
            errors = 0

            for row in rows:
                eid = row["expense_id"]
                ocr_text = row["ocr_raw_text"] or ""
                try:
                    parsed = await ai_parse_receipt(ocr_text, categories, stores)
                    items = parsed.get("items") or []
                    await conn.execute(
                        "DELETE FROM expense_items WHERE expense_id=$1 AND user_id=$2",
                        eid, user_id)
                    for idx, it in enumerate(items):
                        cid = it.get("category_id")
                        if cid is not None and cid not in valid_cat_ids:
                            cid = None
                        await conn.execute(
                            """INSERT INTO expense_items
                               (user_id, expense_id, description, quantity, quantity_unit,
                                unit_price, total_price, category_id, sort_order,
                                original_price, is_reduced)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                            user_id, eid,
                            (it.get("description") or "").strip(),
                            it.get("quantity") or 1,
                            it.get("quantity_unit"),
                            it.get("unit_price"),
                            it.get("total_price"),
                            cid,
                            idx,
                            it.get("original_price"),
                            bool(it.get("is_reduced")),
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
            try:
                await db_module._pool.release(conn)
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
    ocr_text = row["ocr_raw_text"] or ""
    try:
        parsed = await ai_parse_receipt(
            ocr_text,
            [{"id": r["id"], "name": r["name"]} for r in cat_rows],
            [{"name": r["name"]} for r in user_stores_rows],
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


@router.get("/api/expenses/stats/monthly")
async def stats_monthly(db=Depends(get_db), user=Depends(get_current_user), months: int = 12):
    months = max(1, min(months, 60))
    since = date.today().replace(day=1)
    y, m = since.year, since.month
    for _ in range(months - 1):
        m -= 1
        if m == 0:
            m = 12; y -= 1
    since = date(y, m, 1)
    rows = await db.fetch(
        """SELECT TO_CHAR(purchase_date, 'YYYY-MM') AS month,
                  SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2
           GROUP BY month ORDER BY month""",
        user["id"], since)
    return [{"month": r["month"], "total": float(r["total"] or 0),
             "count": int(r["count"])} for r in rows]

@router.get("/api/expenses/stats/weekly")
async def stats_weekly(db=Depends(get_db), user=Depends(get_current_user), weeks: int = 12):
    """Ausgaben pro ISO-Kalenderwoche (letzte N Wochen)."""
    weeks = max(1, min(weeks, 52))
    since = date.today() - timedelta(days=7 * (weeks - 1) + date.today().weekday())
    rows = await db.fetch(
        """SELECT TO_CHAR(purchase_date, 'IYYY-"KW"IW') AS week,
                  DATE_TRUNC('week', purchase_date)::date AS week_start,
                  SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2
           GROUP BY week, week_start ORDER BY week_start""",
        user["id"], since)
    return [{"week": r["week"], "week_start": r["week_start"].isoformat() if r["week_start"] else None,
             "total": float(r["total"] or 0), "count": int(r["count"])} for r in rows]


@router.get("/api/expenses/stats/daily")
async def stats_daily(db=Depends(get_db), user=Depends(get_current_user), days: int = 30):
    """Ausgaben pro Tag (letzte N Tage, mit Lücken als 0)."""
    days = max(1, min(days, 365))
    since = date.today() - timedelta(days=days - 1)
    rows = await db.fetch(
        """SELECT purchase_date AS d, SUM(total_amount) AS total, COUNT(*) AS count
           FROM expenses WHERE user_id=$1 AND purchase_date >= $2
           GROUP BY purchase_date ORDER BY purchase_date""",
        user["id"], since)
    by_day = {r["d"].isoformat(): (float(r["total"] or 0), int(r["count"])) for r in rows}
    out = []
    cur = since
    end = date.today()
    while cur <= end:
        key = cur.isoformat()
        total, count = by_day.get(key, (0.0, 0))
        out.append({"date": key, "total": total, "count": count})
        cur += timedelta(days=1)
    return out


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


# ---------- Produkt-Preisverlauf (Aggregation aller gekauften Artikel) ----------
@router.get("/api/expenses/products")
async def list_products(db=Depends(get_db), user=Depends(get_current_user)):
    """Aggregierte Produktliste über alle Bons — fuer den Preisverlauf-Tab.

    Gruppiert nach normalisierter Beschreibung (Basisname vor "(").
    Fuer jedes Produkt: letzter Preis + Rabatt-/Preiserhoehung ggue. vorherigem Kauf,
    plus Preis/kg oder Preis/L falls Einheit bekannt.
    """
    rows = await db.fetch(
        """SELECT ei.description, ei.total_price, ei.quantity, ei.quantity_unit,
                  ei.original_price, ei.is_reduced,
                  e.purchase_date, e.store_id,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon,
                  c.name AS category_name
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           WHERE ei.user_id=$1 AND ei.description IS NOT NULL AND ei.description != ''
           ORDER BY e.purchase_date DESC, ei.id DESC""",
        user["id"])

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

    groups = defaultdict(list)
    for r in rows:
        k = norm_key(r["description"])
        if not k:
            continue
        groups[k].append(r)

    products = []
    for key, purchases in groups.items():
        last = purchases[0]
        prev = purchases[1] if len(purchases) > 1 else None
        prices = [float(p["total_price"]) for p in purchases]
        unit_prices = [unit_price_of(p) for p in purchases]

        change_abs = None
        change_pct = None
        change_direction = None
        if prev is not None:
            last_up = unit_price_of(last)
            prev_up = unit_price_of(prev)
            if prev_up > 0:
                change_abs = round(last_up - prev_up, 4)
                change_pct = round((change_abs / prev_up) * 100.0, 1)
                if change_pct >= 1:
                    change_direction = "up"
                elif change_pct <= -1:
                    change_direction = "down"

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

        products.append({
            "key": key,
            "description": last["description"],
            "category_name": last["category_name"],
            "count": len(purchases),
            "last_date": last["purchase_date"].isoformat() if last["purchase_date"] else None,
            "last_price": tp,
            "last_unit_price": round(unit_price_of(last), 4),
            "last_quantity": float(last["quantity"] or 1),
            "last_quantity_unit": last["quantity_unit"],
            "last_original_price": float(last["original_price"]) if last["original_price"] is not None else None,
            "last_is_reduced": bool(last["is_reduced"]),
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
            "price_per_kg": price_per_kg,
            "price_per_l": price_per_l,
        })

    products.sort(key=lambda p: p["last_date"] or "", reverse=True)
    return products


@router.get("/api/expenses/products/history")
async def product_history(key: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Alle Käufe eines Produkts (nach normalisiertem Basisnamen) für Zeitreihen-Chart."""
    key = (key or "").strip().lower()
    if len(key) < 2:
        raise HTTPException(400, "Key zu kurz")
    rows = await db.fetch(
        """SELECT ei.description, ei.total_price, ei.quantity, ei.quantity_unit,
                  ei.original_price, ei.is_reduced,
                  e.purchase_date,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           WHERE ei.user_id=$1
           ORDER BY e.purchase_date ASC, ei.id ASC""",
        user["id"])

    import re

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
        if u == "g":
            return (tp / qty) * 1000.0
        if u == "ml":
            return (tp / qty) * 1000.0
        return tp / qty

    out = []
    for r in rows:
        if norm_key(r["description"]) != key:
            continue
        qty = float(r["quantity"] or 1) or 1
        tp = float(r["total_price"])
        out.append({
            "date": r["purchase_date"].isoformat() if r["purchase_date"] else None,
            "description": r["description"],
            "total_price": tp,
            "quantity": qty,
            "quantity_unit": r["quantity_unit"],
            # unit_price = einheits-normalisiert (€/kg bei g/kg, €/L bei ml/l, sonst €/Stk)
            "unit_price": round(unit_price_norm(qty, tp, r["quantity_unit"]), 4),
            "original_price": float(r["original_price"]) if r["original_price"] is not None else None,
            "is_reduced": bool(r["is_reduced"]),
            "store_name": r["store_name"] or "Ohne Laden",
            "store_color": r["store_color"] or "#9ca3af",
            "store_icon": r["store_icon"] or "🏪",
        })
    return out


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

