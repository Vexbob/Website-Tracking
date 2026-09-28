"""Bon-Fotos: doppelt so groß, dafür nur die letzten 20 (v2.23.0).

Bei 1600 px war das Kleingedruckte langer Bons nicht mehr lesbar. Jetzt
werden Bons mit 3200 px gespeichert; damit die Datenbank dafür nicht
wächst, behält jedes Konto nur die Fotos seiner letzten 20 Uploads.
Andere Bilder (Gerichte, Blog) bleiben bei 1600 px.
"""
import asyncio
import inspect
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from PIL import Image

from routers import expenses_router as er
from services import expenses as ex


def _jpeg(breite, hoehe):
    buf = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def _groesse(daten):
    return Image.open(io.BytesIO(daten)).size


def test_ein_bon_behaelt_3200_px():
    haupt, _, mime, _ = ex.process_image(_jpeg(1000, 4000), ex.RECEIPT_IMAGE_DIM)
    assert mime == "image/jpeg"
    assert _groesse(haupt) == (800, 3200)


def test_andere_bilder_bleiben_bei_1600_px():
    haupt, daumen, _, _ = ex.process_image(_jpeg(1000, 4000))
    assert _groesse(haupt) == (400, 1600)
    assert max(_groesse(daumen)) == ex.THUMB_DIM


def test_der_upload_nimmt_die_bongroesse():
    quelle = inspect.getsource(er.upload_receipt)
    assert "process_image(raw, RECEIPT_IMAGE_DIM)" in quelle


class _Attrappe:
    def __init__(self):
        self.aufrufe = []

    async def execute(self, sql, *werte):
        self.aufrufe.append((sql, werte))
        return "DELETE 3"


def test_nur_die_letzten_20_bleiben():
    db = _Attrappe()
    weg = asyncio.run(er.receipt_images_kuerzen(db, 7))
    assert weg == 3
    sql, werte = db.aufrufe[0]
    assert sql.startswith("DELETE FROM receipt_images WHERE user_id=$1")
    # die neuesten zuerst, und nur die eigenen
    assert "ORDER BY uploaded_at DESC, id DESC LIMIT $2" in sql
    assert werte == (7, 20)


def test_gekuerzt_wird_direkt_nach_dem_speichern():
    quelle = inspect.getsource(er.upload_receipt)
    assert quelle.index("INSERT INTO receipt_images") < quelle.index("receipt_images_kuerzen(db")
