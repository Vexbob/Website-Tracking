"""Ausgaben-Modul Helper: Auto-Kategorisierung, Bild-Utilities."""
import io
import logging
from typing import Optional

logger = logging.getLogger("vexbob.expenses")


async def suggest_category(conn, user_id: int, description: str,
                            store_id: Optional[int] = None) -> Optional[int]:
    """Sucht in category_rules eine passende Kategorie für eine Item-Beschreibung.
    Strategie: LIKE-Match (case-insensitive), Store-spezifische Regel bevorzugt,
    danach nach hit_count sortiert.
    """
    if not description:
        return None
    desc_lower = description.lower()
    rows = await conn.fetch(
        """SELECT id, category_id, keyword, store_id, hit_count
           FROM category_rules
           WHERE user_id=$1 AND $2 LIKE '%' || LOWER(keyword) || '%'
           ORDER BY (store_id IS NOT NULL AND store_id=$3) DESC,
                    LENGTH(keyword) DESC, hit_count DESC
           LIMIT 1""",
        user_id, desc_lower, store_id)
    if rows:
        return rows[0]["category_id"]
    return None


async def learn_rule(conn, user_id: int, description: str,
                     category_id: int, store_id: Optional[int] = None):
    """Lernt/verstärkt eine Regel: wenn User eine Kategorie manuell wählt,
    wird sein 1-2 Wort-Keyword hier gespeichert oder hit_count erhöht.
    """
    if not description or not category_id:
        return
    keyword = _extract_keyword(description)
    if not keyword or len(keyword) < 3:
        return
    # Existiert die Regel bereits?
    existing = await conn.fetchrow(
        """SELECT id FROM category_rules
           WHERE user_id=$1 AND LOWER(keyword)=LOWER($2)
                 AND category_id=$3
                 AND (store_id IS NOT DISTINCT FROM $4)""",
        user_id, keyword, category_id, store_id)
    if existing:
        await conn.execute(
            "UPDATE category_rules SET hit_count=hit_count+1 WHERE id=$1",
            existing["id"])
    else:
        await conn.execute(
            "INSERT INTO category_rules (user_id, keyword, category_id, store_id, hit_count) "
            "VALUES ($1, $2, $3, $4, 1)",
            user_id, keyword, category_id, store_id)


def _extract_keyword(desc: str) -> Optional[str]:
    """Zieht das aussagekräftigste Wort aus der Beschreibung."""
    if not desc:
        return None
    words = [w for w in desc.split() if len(w) >= 3 and w.isalpha()]
    if not words:
        return None
    # längstes Wort zuerst — meist der Produkt-Kern
    words.sort(key=len, reverse=True)
    return words[0]


# ---------- Bild-Processing ----------

MAX_IMAGE_DIM = 1600      # px – längste Kante nach Kompression
JPEG_QUALITY = 82
THUMB_DIM = 320


def process_image(raw_bytes: bytes) -> tuple:
    """Nimmt Rohdaten (JPEG/PNG/HEIC), gibt (image_data, thumb_data, mime, size).
    Konvertiert zu JPEG, verkleinert auf MAX_IMAGE_DIM, erstellt Thumbnail.
    """
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        # EXIF-Rotation anwenden
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Hauptbild
        img_main = img.copy()
        img_main.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)
        buf_main = io.BytesIO()
        img_main.save(buf_main, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        main_bytes = buf_main.getvalue()

        # Thumbnail
        img_thumb = img.copy()
        img_thumb.thumbnail((THUMB_DIM, THUMB_DIM), Image.LANCZOS)
        buf_thumb = io.BytesIO()
        img_thumb.save(buf_thumb, format="JPEG", quality=75, optimize=True)
        thumb_bytes = buf_thumb.getvalue()

        return main_bytes, thumb_bytes, "image/jpeg", len(main_bytes)
    except Exception as e:
        logger.exception(f"Image processing failed: {e}")
        # Fallback: Rohdaten ohne Verarbeitung
        return raw_bytes, None, "application/octet-stream", len(raw_bytes)
