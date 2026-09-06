"""UI-Router — nutzerbezogene Oberflaechen-Einstellungen (v1.51.0).

Kein Prefix: die Endpoints behalten ihre absoluten Pfade (``/api/ui/...``).

Erster Bewohner: die Belegung der mobilen Tab-Leiste am unteren Bildschirm-
rand. Sie zeigte bisher fest verdrahtet vier Module -- welche vier, war eine
Annahme im Frontend. Jetzt waehlt der Nutzer zwei bis sechs davon selbst aus
und bestimmt ihre Reihenfolge.

Gespeichert wird in ``user_prefs`` (Key/Value mit JSON als TEXT) -- derselbe
Ablageplatz wie fuer die Reihenfolge der Vitalwerte-Diagramme und aus
demselben Grund: die Leiste soll auf jedem Geraet dieselbe sein statt pro
Browser im localStorage zu haengen.
"""
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import logger, limiter, LIMIT_WRITE_STANDARD

router = APIRouter(tags=["ui"])

NAV_TABS_PREF = "ui_nav_tabs"

# Erlaubte Ziele -- dieselbe Liste, die der Modul-Switcher im Frontend fuehrt.
# Bewusst OHNE Rechtepruefung: die Auswahl ist reine Navigation, und wer ein
# Modul nicht benutzen darf, kommt ueber einen Tab genauso wenig hinein wie
# ueber einen getippten Link. Das Frontend blendet Ziele, die dem Konto
# fehlen (Admin-Bereich), beim Zeichnen ohnehin aus.
ALLOWED_NAV_TABS = [
    "/", "/sparziel/", "/ausgaben/", "/notizen/", "/health/",
    "/blog/", "/blog/admin/", "/admin/",
]

# Zwei ist die Untergrenze, ab der eine Leiste ueberhaupt Navigation ist.
# Sechs passt auf einem schmalen iPhone gerade noch mit lesbarem Label --
# darueber wird jeder Tab zur Rate-Uebung.
NAV_TABS_MIN, NAV_TABS_MAX = 2, 6


class NavTabsBody(BaseModel):
    tabs: List[str]


def _clean_tabs(raw_list) -> List[str]:
    """Bekannte Ziele in gegebener Reihenfolge, ohne Dubletten."""
    seen = set()
    out: List[str] = []
    for x in raw_list or []:
        href = str(x)
        if href in ALLOWED_NAV_TABS and href not in seen:
            seen.add(href)
            out.append(href)
    return out


@router.get("/api/ui/nav-tabs")
async def get_nav_tabs(db=Depends(get_db), user=Depends(get_current_user)):
    """Belegung der mobilen Tab-Leiste.

    Eine leere Liste heisst "noch nie eingestellt" -- das Frontend nimmt dann
    seine eigene Standardbelegung. Grenzen und erlaubte Ziele kommen mit,
    damit der Einstell-Dialog sie nicht ein zweites Mal definieren muss.
    """
    raw = await db.fetchval(
        "SELECT value FROM user_prefs WHERE user_id=$1 AND key=$2",
        user["id"], NAV_TABS_PREF)
    tabs: List[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tabs = _clean_tabs(parsed)
        except (ValueError, TypeError):
            logger.warning("Ungueltige Tab-Leisten-Einstellung fuer User %s", user["id"])
    return {"tabs": tabs, "allowed": ALLOWED_NAV_TABS,
            "min": NAV_TABS_MIN, "max": NAV_TABS_MAX}


@router.put("/api/ui/nav-tabs")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def set_nav_tabs(request: Request, b: NavTabsBody,
                        db=Depends(get_db), user=Depends(get_current_user)):
    """Speichert Auswahl UND Reihenfolge. Unbekannte Ziele sind ein Fehler
    statt still zu verschwinden -- sonst kaeme eine halbe Leiste zurueck und
    niemand wuesste warum."""
    for x in b.tabs:
        if str(x) not in ALLOWED_NAV_TABS:
            raise HTTPException(400, f"Unbekanntes Navigationsziel: {x}")
    tabs = _clean_tabs(b.tabs)
    if not (NAV_TABS_MIN <= len(tabs) <= NAV_TABS_MAX):
        raise HTTPException(
            400, f"Die Tab-Leiste braucht {NAV_TABS_MIN} bis {NAV_TABS_MAX} Eintraege "
                 f"(bekommen: {len(tabs)})")
    await db.execute(
        "INSERT INTO user_prefs (user_id, key, value) VALUES ($1,$2,$3) "
        "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
        user["id"], NAV_TABS_PREF, json.dumps(tabs))
    return {"status": "ok", "tabs": tabs}


@router.delete("/api/ui/nav-tabs")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def reset_nav_tabs(request: Request, db=Depends(get_db),
                          user=Depends(get_current_user)):
    """Zuruecksetzen = Zeile loeschen, nicht die Standardbelegung speichern.
    So zieht eine kuenftig geaenderte Standardbelegung automatisch nach."""
    await db.execute(
        "DELETE FROM user_prefs WHERE user_id=$1 AND key=$2",
        user["id"], NAV_TABS_PREF)
    return {"status": "reset", "tabs": []}
