"""OCR-Service mit Provider-Abstraktion.

Aktuell implementiert: Google Cloud Vision (Standard).
Weitere Provider können durch Ableitung von OCRProvider hinzugefügt werden.

Konfiguration per ENV:
    OCR_PROVIDER=google                          # aktueller Provider
    GOOGLE_APPLICATION_CREDENTIALS_JSON=<json>   # Inhalt des Service-Account-Keys
    GOOGLE_APPLICATION_CREDENTIALS=/pfad/zur.json  # ODER Dateipfad (klassisch)

Fehlt die Config, wirft ``get_ocr_provider()`` KEINEN Fehler, sondern gibt
einen ``NoopOCR``-Provider zurück, der leer antwortet — so bleibt der Upload
funktionsfähig und der User füllt manuell aus.
"""
import os
import json
import logging
import tempfile
from typing import Optional

logger = logging.getLogger("vexbob.ocr")

_provider_instance = None


class OCRProvider:
    name = "base"

    def extract_text(self, image_bytes: bytes) -> str:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return False


class NoopOCR(OCRProvider):
    name = "noop"

    def extract_text(self, image_bytes: bytes) -> str:
        return ""

    @property
    def available(self) -> bool:
        return False


class GoogleVisionOCR(OCRProvider):
    name = "google"

    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        # JSON aus ENV -> temp file, damit google-cloud-vision es findet
        json_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if json_str and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            try:
                # Validieren + minifizieren
                parsed = json.loads(json_str)
                fd, path = tempfile.mkstemp(prefix="gcp-vision-", suffix=".json")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(parsed, f)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
                logger.info(f"Google Vision credentials written to {path}")
            except Exception as e:
                logger.warning(f"GOOGLE_APPLICATION_CREDENTIALS_JSON invalid: {e}")
                return

        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.info("GoogleVisionOCR: no credentials configured")
            return

        try:
            from google.cloud import vision
            self._client = vision.ImageAnnotatorClient()
            logger.info("Google Vision client initialized")
        except Exception as e:
            logger.warning(f"Google Vision client init failed: {e}")
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def extract_text(self, image_bytes: bytes) -> str:
        if not self._client:
            return ""
        try:
            from google.cloud import vision
            image = vision.Image(content=image_bytes)
            # document_text_detection ist besser für strukturierte Belege
            response = self._client.document_text_detection(
                image=image,
                image_context={"language_hints": ["de"]},
            )
            if response.error.message:
                logger.warning(f"Google Vision error: {response.error.message}")
                return ""
            return response.full_text_annotation.text or ""
        except Exception as e:
            logger.exception(f"Google Vision extract_text failed: {e}")
            return ""


def get_ocr_provider() -> OCRProvider:
    """Lazy-Singleton. Wählt Provider anhand OCR_PROVIDER-ENV."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance
    choice = (os.getenv("OCR_PROVIDER") or "google").lower()
    if choice == "google":
        p = GoogleVisionOCR()
        _provider_instance = p if p.available else NoopOCR()
    else:
        logger.warning(f"Unknown OCR_PROVIDER '{choice}', using Noop")
        _provider_instance = NoopOCR()
    return _provider_instance
