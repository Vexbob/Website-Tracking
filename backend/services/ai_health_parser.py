"""KI-Fallback fuer unbekannte Auto-Health-Export-Metric-Namen (Gemini).

Wird nur angestossen, wenn ``services.health_ingest`` einen ``metric_type``
bekommt, der nicht in ``SIMPLE_METRIC_MAP`` steht (z.B. nach einem
App-Update mit neuer Bezeichnung). Fragt das Modell, welchem der bekannten
internen Metric-Typen der unbekannte Name am ehesten entspricht — analog zum
Kassenbon-Parser (``services.ai_receipt_parser``), inkl. Fallback auf
``None`` bei jedem Fehler (dann wird der Datenpunkt uebersprungen statt den
ganzen Sync-Batch zu verwerfen).

Konfiguration per ENV: GEMINI_API_KEY, GEMINI_MODEL (siehe ai_receipt_parser.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("vexbob.ai_health")

_client = None
_client_init_tried = False


def _get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def _get_client():
    global _client, _client_init_tried
    if _client_init_tried:
        return _client
    _client_init_tried = True
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.info("GEMINI_API_KEY nicht gesetzt - Health-Metric-Resolver deaktiviert.")
        return None
    try:
        from google import genai  # type: ignore
        _client = genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning("Gemini-Client-Init fuer Health-Resolver fehlgeschlagen: %s", e)
        _client = None
    return _client


def _call_gemini_sync(prompt: str) -> Optional[str]:
    client = _get_client()
    resp = client.models.generate_content(model=_get_model_name(), contents=prompt)
    return (resp.text or "").strip()


async def resolve_metric_name(unknown_name: str, known_types: list[str]) -> Optional[str]:
    """Fragt Gemini, welchem bekannten internen ``metric_type`` der
    unbekannte Auto-Health-Export-Name entspricht. Gibt None zurueck, wenn
    kein Client verfuegbar ist, das Modell nicht sicher antworten kann, oder
    irgendein Fehler auftritt."""
    if _get_client() is None:
        return None
    prompt = (
        "Du bekommst den Namen einer Apple-Health-Metrik aus der App "
        "'Auto Health Export' sowie eine Liste bekannter interner Metric-Typen. "
        "Antworte AUSSCHLIESSLICH mit einem der bekannten Typen aus der Liste "
        "(exakt so geschrieben), oder mit dem Wort 'unknown', wenn keiner passt.\n\n"
        f"Unbekannter Name: {unknown_name}\n"
        f"Bekannte Typen: {json.dumps(known_types)}\n"
    )
    try:
        text = await asyncio.wait_for(asyncio.to_thread(_call_gemini_sync, prompt), timeout=15.0)
    except Exception as e:
        logger.info("Health-Metric-Resolver Aufruf fehlgeschlagen: %s", e)
        return None
    if not text:
        return None
    candidate = text.strip().strip("`").strip()
    if candidate in known_types:
        return candidate
    return None
