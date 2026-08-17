"""Unit tests for the Notizen-Modul helper logic. Run: pytest backend/tests/"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers.notes_router import ALLOWED_COLORS


def test_allowed_colors_contains_defaults():
    for c in ("default", "red", "orange", "yellow", "green", "blue", "purple", "pink"):
        assert c in ALLOWED_COLORS


def test_allowed_colors_is_a_set():
    # Determinismus fuer Membership-Checks; keine versehentlichen Erweiterungen.
    assert isinstance(ALLOWED_COLORS, (set, frozenset))
    assert len(ALLOWED_COLORS) == 8
