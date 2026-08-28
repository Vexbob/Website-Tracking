"""Export-Router — kombinierter Gesamt-Export (Sparziel + Ausgaben + Gesundheit).

Kein Prefix: absoluter Pfad ``/api/export/all``.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from database import get_db
from auth import get_current_user
from services.full_export import build_full_export_csv

router = APIRouter(tags=["export"])


@router.get("/api/export/all")
async def export_all(db=Depends(get_db), user=Depends(get_current_user)):
    """Eine einzige CSV mit Sparziel-, Ausgaben- und Gesundheitsdaten,
    inkl. erklärender Kommentarzeilen vor jeder Sektion (siehe
    services/full_export.py)."""
    csv = await build_full_export_csv(db, user)
    return Response(
        content=csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=vexbob-gesamt-export.csv"},
    )
