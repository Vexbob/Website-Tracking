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

v1.59.0: Dazu ``/api/ui/prefs`` -- ein generischer Sammel-Endpoint fuer die
uebrigen kleinen Einstellungen der Oberflaeche. Jeder Schluessel steht mit
seinem Pruefer in ``UI_PREFS``; eine neue Einstellung ist damit eine Funktion
und eine Zeile, kein neues Endpoint-Paar. Die Tab-Leiste behaelt ihre eigenen
Endpoints, weil das Frontend dort auch Grenzen und erlaubte Ziele abholt.
"""
import json
from typing import Any, Dict, List

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


# =====================================================================
# Generische Oberflaechen-Einstellungen (v1.59.0)
# =====================================================================
# Jeder Eintrag: Schluessel -> Pruefer. Der Pruefer bekommt den rohen Wert und
# gibt den bereinigten zurueck oder wirft ValueError. Er ist gleichzeitig die
# Dokumentation dessen, was der Schluessel bedeuten darf.

DESKTOP_NAV_PREF = "ui_nav_desktop"


def _check_nav_desktop(value: Any) -> List[str]:
    """Welche Module in der Navigationsleiste am Rechner offen stehen, und in
    welcher Reihenfolge. Leere Liste heisst "noch nie eingestellt" -- das
    Frontend nimmt dann alle Module in ihrer eigenen Reihenfolge. Was nicht
    mehr in die Zeile passt, wandert dort automatisch ins Punkte-Menue; hier
    steht also die Wunschreihenfolge, nicht das Ergebnis."""
    if not isinstance(value, list):
        raise ValueError("erwartet eine Liste von Modul-Pfaden")
    seen, out = set(), []
    for x in value:
        href = str(x)
        if href not in ALLOWED_NAV_TABS:
            raise ValueError(f"Unbekanntes Navigationsziel: {href}")
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


UI_PREFS = {
    DESKTOP_NAV_PREF: _check_nav_desktop,
}


class PrefsBody(BaseModel):
    prefs: Dict[str, Any]


@router.get("/api/ui/prefs")
async def get_prefs(db=Depends(get_db), user=Depends(get_current_user)):
    """Alle bekannten Einstellungen auf einmal. Fehlende oder kaputte Werte
    fehlen in der Antwort, statt als Nullwert durchzurutschen -- das Frontend
    kennt seine Standardwerte selbst und muss sie hier nicht doppelt lesen."""
    rows = await db.fetch(
        "SELECT key, value FROM user_prefs WHERE user_id=$1 AND key = ANY($2::text[])",
        user["id"], list(UI_PREFS.keys()))
    out: Dict[str, Any] = {}
    for r in rows:
        check = UI_PREFS.get(r["key"])
        try:
            out[r["key"]] = check(json.loads(r["value"]))
        except (ValueError, TypeError):
            logger.warning("Ungueltige Einstellung %s fuer User %s", r["key"], user["id"])
    return {"prefs": out, "keys": sorted(UI_PREFS.keys())}


@router.put("/api/ui/prefs")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def set_prefs(request: Request, b: PrefsBody,
                    db=Depends(get_db), user=Depends(get_current_user)):
    """Speichert eine oder mehrere Einstellungen. Ein unbekannter Schluessel
    ist ein Fehler und kein stilles Verwerfen: sonst meldet die Oberflaeche
    "gespeichert" und beim naechsten Laden ist nichts da."""
    if not b.prefs:
        raise HTTPException(400, "Keine Einstellungen uebergeben")
    cleaned: Dict[str, Any] = {}
    for key, value in b.prefs.items():
        check = UI_PREFS.get(key)
        if check is None:
            raise HTTPException(400, f"Unbekannte Einstellung: {key}")
        try:
            cleaned[key] = check(value)
        except ValueError as e:
            raise HTTPException(400, f"{key}: {e}")
    for key, value in cleaned.items():
        await db.execute(
            "INSERT INTO user_prefs (user_id, key, value) VALUES ($1,$2,$3) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
            user["id"], key, json.dumps(value))
    return {"status": "ok", "prefs": cleaned}


@router.delete("/api/ui/prefs/{key}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def reset_pref(request: Request, key: str, db=Depends(get_db),
                     user=Depends(get_current_user)):
    """Zuruecksetzen loescht die Zeile, statt einen Standardwert zu speichern --
    so zieht ein spaeter geaenderter Standard automatisch nach."""
    if key not in UI_PREFS:
        raise HTTPException(400, f"Unbekannte Einstellung: {key}")
    await db.execute(
        "DELETE FROM user_prefs WHERE user_id=$1 AND key=$2", user["id"], key)
    return {"status": "reset", "key": key}
