"""Ausgaben-Router — alle Endpoints rund um Ausgaben, Läden, Kategorien,
Belege (OCR), Statistik, Preisverlauf und Export.

Kein Prefix: die Endpoints behalten ihre alten absoluten Pfade
(``/api/expenses``, ``/api/stores``, ``/api/expense-categories``,
``/api/category-rules``, ``/api/expense-items``, ``/api/receipts``).
"""
import asyncio
import re
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
    dismissed_rows = await db.fetch(
        "SELECT expense_ids FROM dismissed_expense_duplicates WHERE user_id=$1", user["id"])
    dismissed = {r["expense_ids"] for r in dismissed_rows}

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
            fingerprint = ",".join(str(x) for x in sorted(m["id"] for m in cluster))
            if fingerprint in dismissed:
                continue
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


@router.post("/api/expenses/duplicates/dismiss")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def dismiss_duplicate_group(request: Request, body: dict,
                                   db=Depends(get_db), user=Depends(get_current_user)):
    """Blendet eine einzelne Duplikat-Gruppe dauerhaft aus den Vorschlaegen
    aus, ohne die Bons zu loeschen oder zusammenzufuehren. Da eine Gruppe
    keine stabile ID hat (wird bei jedem Request frisch geclustert), dient
    die sortierte Liste ihrer expense-IDs als Fingerabdruck.
    Body: {expense_ids: [int, ...]} (alle IDs der betroffenen Gruppe)
    """
    ids = [i for i in (body.get("expense_ids") or []) if isinstance(i, int)]
    if len(ids) < 2:
        raise HTTPException(400, "expense_ids (mind. 2) erforderlich")
    owned = await db.fetch(
        "SELECT id FROM expenses WHERE id = ANY($1) AND user_id=$2", ids, user["id"])
    if len(owned) != len(set(ids)):
        raise HTTPException(404, "Nicht alle IDs gehoeren dem User")
    fingerprint = ",".join(str(i) for i in sorted(ids))
    await db.execute(
        """INSERT INTO dismissed_expense_duplicates (user_id, expense_ids)
           VALUES ($1, $2) ON CONFLICT (user_id, expense_ids) DO NOTHING""",
        user["id"], fingerprint)
    return {"status": "dismissed"}


# ---------- Produktliste (Aggregation aller gekauften Artikel) ----------
#
# v1.42.0: Der Preisvergleich ist ersatzlos entfallen (Ø-Preis je Einheit,
# guenstigster/teuerster Laden, €/kg-Normierung, Preisaenderung ggue. dem
# Vorkauf). Er hat Artikel miteinander verrechnet, deren Einheiten gar nicht
# vergleichbar waren: fehlte die Mengeneinheit oder stand auf dem Bon "1 Pack"
# statt "500 g", landete ein €/Stueck-Wert im selben Durchschnitt wie die
# €/kg-Werte -- inklusive erfundener Preissprunge und eines falschen
# "guenstigster Laden"-Rankings. Was bleibt, ist eine ehrliche Einkaufs-
# statistik: was wurde wie oft gekauft, was hat es zusammen gekostet und in
# welchen Laeden. Der Laden ist dabei NIE Teil des Gruppenschluessels -- ein
# Produkt ist eine Zeile, egal in wie vielen Laeden es gekauft wurde.

_QTY_SUFFIX_RE = re.compile(
    r"\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|pack|btl|blatt|x\d+)\s*$", re.IGNORECASE)


def _norm_product_key(desc: Optional[str]) -> str:
    """Normalisiert eine Beschreibung zum Produkt-Basisnamen:
    alles ab '(' abschneiden (Originaltext vom Bon), eine angehaengte
    Menge+Einheit entfernen, Whitespace normalisieren, lowercase.
    """
    d = (desc or "").strip()
    if "(" in d:
        d = d.split("(", 1)[0].strip()
    d = _QTY_SUFFIX_RE.sub("", d)
    return re.sub(r"\s+", " ", d).strip().lower()


def _product_key(r) -> str:
    """Gruppenschluessel eines Items.

    Prioritaet: ``product_group`` (manuell zusammengefuehrt oder herausgeloest)
    -> ``base_name`` -> normalisierte ``description``. Der Laden kommt bewusst
    nicht vor.
    """
    pg = (r["product_group"] or "").strip().lower()
    if pg:
        return pg
    bn = (r["base_name"] or "").strip().lower()
    if bn:
        return bn
    return _norm_product_key(r["description"])


async def _fetch_product_rows(db, user_id: int, conds=None, params=None):
    """Alle fuer die Produktaggregation relevanten Positionen, neueste zuerst."""
    conds = list(conds or [])
    params = list(params or [user_id])
    base = ["ei.user_id=$1", "COALESCE(ei.price_comparable, TRUE)=TRUE",
            "(ei.base_name IS NOT NULL OR (ei.description IS NOT NULL AND ei.description != ''))",
            "ei.total_price > 0"]
    return await db.fetch(
        f"""SELECT ei.id AS item_id, ei.description, ei.base_name, ei.original_text,
                  ei.total_price, ei.quantity, ei.quantity_unit,
                  ei.original_price, ei.is_reduced, ei.product_group,
                  ei.brand_id, ei.category_id, ei.expense_id,
                  e.purchase_date, e.store_id,
                  s.name AS store_name, s.color AS store_color, s.icon AS store_icon,
                  c.name AS category_name,
                  b.name AS brand_name, b.is_private_label AS brand_is_private_label
           FROM expense_items ei
           JOIN expenses e ON e.id=ei.expense_id
           LEFT JOIN stores s ON s.id=e.store_id
           LEFT JOIN expense_categories c ON c.id=ei.category_id
           LEFT JOIN brands b ON b.id=ei.brand_id
           WHERE {' AND '.join(base + conds)}
           ORDER BY e.purchase_date DESC, ei.id DESC""",
        *params)


def _stores_of(purchases) -> list:
    """Alle Laeden einer Produktgruppe mit Anzahl und Summe, haeufigster zuerst.

    Ersetzt die alte Einzel-Spalte "letzter Laden": ein Produkt, das in drei
    Laeden gekauft wurde, ist EINE Zeile mit drei Laeden -- nicht drei Zeilen.
    """
    from collections import defaultdict
    agg = defaultdict(lambda: {"count": 0, "total": 0.0})
    meta = {}
    for p in purchases:
        sid = p["store_id"]
        agg[sid]["count"] += 1
        agg[sid]["total"] += float(p["total_price"])
        meta.setdefault(sid, (p["store_name"], p["store_color"], p["store_icon"]))
    out = []
    for sid, vals in agg.items():
        name, color, icon = meta[sid]
        out.append({
            "store_id": sid,
            "store_name": name or "Ohne Laden",
            "store_color": color or "#9ca3af",
            "store_icon": icon or "🏪",
            "count": vals["count"],
            "total": round(vals["total"], 2),
        })
    out.sort(key=lambda s: (-s["count"], -s["total"]))
    return out


@router.get("/api/expenses/products")
async def list_products(
    min_count: int = 2,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
    store_id: Optional[int] = None,
    db=Depends(get_db), user=Depends(get_current_user),
):
    """Aggregierte Produktliste ueber alle Bons fuer die Produkt-Seite.

    Gruppiert nach ``product_group`` -> ``base_name`` -> normalisierter
    Beschreibung. Je Produkt: Anzahl Kaeufe, Gesamtausgaben, Ø-/Min-/Max-Preis,
    letzter Kauf und ALLE Laeden, in denen es gekauft wurde.

    ``min_count``: nur Produkte mit mindestens N Kaeufen (1 = alle).
    Optionale Filter ``date_from``/``date_to``/``category_id``/``store_id``
    beschraenken die beruecksichtigten Kaeufe; der Store-Filter schraenkt also
    die Datenbasis ein, er spaltet aber keine Produkte auf.
    """
    conds, params = [], [user["id"]]
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

    rows = await _fetch_product_rows(db, user["id"], conds, params)

    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        k = _product_key(r)
        if k:
            groups[k].append(r)

    products = []
    for key, purchases in groups.items():
        if len(purchases) < min_count:
            continue
        # rows sind DESC nach Datum -> purchases[0] = neuester Kauf
        last = purchases[0]
        prices = [float(p["total_price"]) for p in purchases]
        total_spent = sum(prices)
        title = ((last["base_name"] or "").strip()
                 or _norm_product_key(last["description"]).title()
                 or (last["description"] or key))
        products.append({
            "key": key,
            "title": title,
            "description": last["description"],
            "base_name": last["base_name"],
            "original_text": last["original_text"],
            "category_name": last["category_name"],
            "brand_id": last["brand_id"],
            "brand_name": last["brand_name"],
            "brand_is_private_label": bool(last["brand_is_private_label"]),
            "is_merged": bool((last["product_group"] or "").strip()),
            "count": len(purchases),
            "total_spent": round(total_spent, 2),
            "avg_price": round(total_spent / len(purchases), 2),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "last_date": last["purchase_date"].isoformat() if last["purchase_date"] else None,
            "last_price": round(float(last["total_price"]), 2),
            "last_quantity": float(last["quantity"] or 1),
            "last_quantity_unit": last["quantity_unit"],
            "last_original_price": float(last["original_price"]) if last["original_price"] is not None else None,
            "last_is_reduced": bool(last["is_reduced"]),
            "stores": _stores_of(purchases),
        })

    products.sort(key=lambda p: p["last_date"] or "", reverse=True)
    return products


# ---------- Varianten zusammenfuehren ----------
#
# Die KI leitet den Basisnamen aus dem Bon-Text ab, und jeder Laden druckt
# denselben Artikel anders: "Gouda", "Gouda jung" und "Goudakaese" wurden
# dadurch zu drei Produkten, die zufaellig je einem Laden entsprachen. Statt
# Namen heuristisch zu verschmelzen (und dabei "Gouda" mit "Gouda-Auflauf" zu
# verwechseln) schlaegt der Server Kandidaten vor und der User bestaetigt --
# die Entscheidung landet als ``product_group`` dauerhaft an den Positionen
# und gilt damit auch fuer kuenftige Kaeufe mit demselben Namen.

_MERGE_MIN_STEM = 4  # kuerzere Wortstaemme ("Ei", "Bio") wuerden alles verbinden


def _merge_words(key: str) -> set:
    return {w for w in re.split(r"[^0-9a-zA-ZäöüÄÖÜß]+", key.lower()) if len(w) >= _MERGE_MIN_STEM}


def _merge_compact(key: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]+", "", key.lower())


def _is_variant_of(a: str, b: str) -> bool:
    """TRUE, wenn zwei Gruppenschluessel dasselbe Produkt in anderer Schreibweise
    sein koennten: einer ist Praefix des anderen ("gouda"/"goudakaese") oder die
    Wortmenge des einen steckt in der des anderen ("gouda"/"gouda jung").
    Alles andere wird NICHT vorgeschlagen -- lieber ein Vorschlag zu wenig als
    zwei falsch verschmolzene Produkte.
    """
    ca, cb = _merge_compact(a), _merge_compact(b)
    if not ca or not cb or ca == cb:
        return False
    if min(len(ca), len(cb)) >= _MERGE_MIN_STEM and (ca.startswith(cb) or cb.startswith(ca)):
        return True
    wa, wb = _merge_words(a), _merge_words(b)
    if wa and wb and (wa < wb or wb < wa):
        return True
    return False


@router.get("/api/expenses/products/merge-suggestions")
async def product_merge_suggestions(db=Depends(get_db), user=Depends(get_current_user)):
    """Findet Produktgruppen, die vermutlich Schreibweisen desselben Artikels
    sind, und schlaegt sie zum Zusammenfuehren vor. Bereits abgelehnte
    Vorschlaege (gleiche Schluesselmenge) tauchen nicht wieder auf.
    """
    rows = await _fetch_product_rows(db, user["id"])
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        k = _product_key(r)
        if k:
            groups[k].append(r)

    keys = sorted(groups.keys())
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if _is_variant_of(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    clusters = defaultdict(list)
    for k in keys:
        clusters[find(k)].append(k)

    dismissed = {r["product_keys"] for r in await db.fetch(
        "SELECT product_keys FROM dismissed_product_merges WHERE user_id=$1", user["id"])}

    out = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        fingerprint = "|".join(sorted(members))
        if fingerprint in dismissed:
            continue
        variants = []
        for k in sorted(members, key=lambda m: (-len(groups[m]), m)):
            purchases = groups[k]
            last = purchases[0]
            variants.append({
                "key": k,
                "title": (last["base_name"] or "").strip() or k,
                "count": len(purchases),
                "stores": [s["store_name"] for s in _stores_of(purchases)],
            })
        # Der kuerzeste Name ist in aller Regel der generische ("Gouda")
        suggested = min(members, key=lambda m: (len(m), m))
        out.append({
            "fingerprint": fingerprint,
            "keys": sorted(members),
            "suggested_key": suggested,
            "suggested_title": next(v["title"] for v in variants if v["key"] == suggested),
            "total_count": sum(v["count"] for v in variants),
            "variants": variants,
        })
    out.sort(key=lambda s: -s["total_count"])
    return out


class ProductMerge(BaseModel):
    keys: list
    title: Optional[str] = None


@router.post("/api/expenses/products/merge")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def merge_products(request: Request, b: ProductMerge,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Fuehrt mehrere Produktgruppen dauerhaft zu einer zusammen, indem allen
    betroffenen Positionen dieselbe ``product_group`` gesetzt wird."""
    keys = {(k or "").strip().lower() for k in (b.keys or []) if (k or "").strip()}
    if len(keys) < 2:
        raise HTTPException(400, "Mindestens zwei Produkt-Schlüssel nötig")
    target = (b.title or "").strip().lower() or min(keys, key=lambda m: (len(m), m))

    rows = await _fetch_product_rows(db, user["id"])
    item_ids = [r["item_id"] for r in rows if _product_key(r) in keys]
    if not item_ids:
        raise HTTPException(404, "Keine Positionen zu diesen Schlüsseln gefunden")
    await db.execute(
        "UPDATE expense_items SET product_group=$1, user_edited=TRUE "
        "WHERE id = ANY($2) AND user_id=$3",
        target, item_ids, user["id"])
    logger.info(f"User {user['id']} merged product groups {sorted(keys)} -> '{target}' "
                f"({len(item_ids)} items)")
    return {"status": "merged", "product_group": target, "items": len(item_ids)}


@router.post("/api/expenses/products/merge-dismiss")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def dismiss_product_merge(request: Request, b: ProductMerge,
                                 db=Depends(get_db), user=Depends(get_current_user)):
    """Blendet einen Zusammenfuehren-Vorschlag dauerhaft aus, ohne etwas zu
    aendern (analog zu den Bon-Duplikaten)."""
    keys = sorted({(k or "").strip().lower() for k in (b.keys or []) if (k or "").strip()})
    if len(keys) < 2:
        raise HTTPException(400, "Mindestens zwei Produkt-Schlüssel nötig")
    await db.execute(
        """INSERT INTO dismissed_product_merges (user_id, product_keys)
           VALUES ($1, $2) ON CONFLICT (user_id, product_keys) DO NOTHING""",
        user["id"], "|".join(keys))
    return {"status": "dismissed"}


@router.post("/api/expenses/products/split")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def split_product(request: Request, b: ProductMerge,
                        db=Depends(get_db), user=Depends(get_current_user)):
    """Nimmt ein Zusammenfuehren zurueck: ``product_group`` wird fuer alle
    Positionen der Gruppe geleert, die Artikel fallen auf ihren Basisnamen
    zurueck."""
    keys = {(k or "").strip().lower() for k in (b.keys or []) if (k or "").strip()}
    if not keys:
        raise HTTPException(400, "Produkt-Schlüssel nötig")
    rows = await _fetch_product_rows(db, user["id"])
    item_ids = [r["item_id"] for r in rows if _product_key(r) in keys]
    if not item_ids:
        raise HTTPException(404, "Keine Positionen zu diesen Schlüsseln gefunden")
    await db.execute(
        "UPDATE expense_items SET product_group=NULL WHERE id = ANY($1) AND user_id=$2",
        item_ids, user["id"])
    return {"status": "split", "items": len(item_ids)}


class ItemGroupOverride(BaseModel):
    # None => zurück zum automatischen Grouping (Basisname)
    # Sonst: expliziter Gruppenschlüssel
    product_group: Optional[str] = None


@router.put("/api/expense-items/{iid:int}/product-group")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def set_item_product_group(request: Request, iid: int, b: ItemGroupOverride,
                                  db=Depends(get_db), user=Depends(get_current_user)):
    """Überschreibt die Produkt-Gruppe einer EINZELNEN Position — z.B. um einen
    falsch einsortierten Artikel aus einer Gruppe herauszuloesen. ``null`` setzt
    auf das automatische Grouping (Basisname) zurueck."""
    existing = await db.fetchval(
        "SELECT 1 FROM expense_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if not existing:
        raise HTTPException(404, "Nicht gefunden")
    pg = (b.product_group or "").strip().lower() or None
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
    """Blendet eine Position aus der Produktliste aus (oder wieder ein).
    Nuetzlich fuer Einmalkaeufe wie Toepfe, Werkzeug oder Pfandzeilen, die in
    einer Einkaufsstatistik nichts verloren haben. Setzt ``user_edited=TRUE``,
    damit ein Reparse die Entscheidung nicht ueberschreibt."""
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
    """Alle Kaeufe eines Produkts (nach Gruppenschluessel) fuer die Detail-
    Ansicht: Zeitreihe des tatsaechlich bezahlten Preises plus Kaufliste mit
    Menge, Einheit und Laden. Bewusst OHNE Einheiten-Normierung -- gezeigt wird,
    was an der Kasse bezahlt wurde, nicht ein hochgerechneter €/kg-Wert."""
    key = (key or "").strip().lower()
    if len(key) < 2:
        raise HTTPException(400, "Key zu kurz")
    rows = await _fetch_product_rows(db, user["id"])
    mine = [r for r in rows if _product_key(r) == key]
    items = []
    for r in reversed(mine):  # _fetch_product_rows liefert DESC -> hier ASC
        items.append({
            "item_id": r["item_id"],
            "expense_id": r["expense_id"],
            "date": r["purchase_date"].isoformat() if r["purchase_date"] else None,
            "description": r["description"],
            "base_name": r["base_name"],
            "original_text": r["original_text"],
            "total_price": round(float(r["total_price"]), 2),
            "quantity": float(r["quantity"] or 1),
            "quantity_unit": r["quantity_unit"],
            "original_price": float(r["original_price"]) if r["original_price"] is not None else None,
            "is_reduced": bool(r["is_reduced"]),
            "product_group": r["product_group"],
            "store_id": r["store_id"],
            "store_name": r["store_name"] or "Ohne Laden",
            "store_color": r["store_color"] or "#9ca3af",
            "store_icon": r["store_icon"] or "🏪",
        })
    return {"items": items, "stores": _stores_of(mine)}


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

