"""Unit tests for the Notizen-Modul helper logic. Run: pytest backend/tests/"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers.notes_router import _clean_tags, ALLOWED_COLORS


def test_clean_tags_strips_hash_and_whitespace():
    assert _clean_tags(["#Idee", " Arbeit ", "  #projekt "]) == ["Idee", "Arbeit", "projekt"]


def test_clean_tags_dedupes_case_insensitive():
    # Erste Schreibweise gewinnt, spätere Duplikate (gleiche Lowercase) fallen weg.
    assert _clean_tags(["Idee", "idee", "IDEE"]) == ["Idee"]


def test_clean_tags_ignores_empty_and_none():
    assert _clean_tags(["", "  ", None, "#", "echt"]) == ["echt"]


def test_clean_tags_handles_none_input():
    assert _clean_tags(None) == []
    assert _clean_tags([]) == []


def test_allowed_colors_contains_defaults():
    for c in ("default", "red", "green", "blue", "purple", "pink"):
        assert c in ALLOWED_COLORS
