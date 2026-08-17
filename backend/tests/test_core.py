"""Pytest tests for core calculations. Run: pytest backend/tests/"""
import pytest
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set required env vars before importing modules that check for them
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from database import week_key_for, month_key_for, period_key, prev_period

# Importiere die echte Funktion aus main.py, damit Bugfixes hier
# automatisch mitgetestet werden (v1.15.0: Fliesskomma-Toleranz).
from main import _milestones_at as milestones_at

def test_week_key_format():
    assert week_key_for(date(2025, 11, 20)) == "2025-W47"
    assert week_key_for(date(2025, 1, 1)) == "2025-W01"

def test_month_key_format():
    assert month_key_for(date(2025, 11, 20)) == "2025-11"
    assert month_key_for(date(2025, 1, 5)) == "2025-01"

def test_period_key_dispatch():
    d = date(2025, 11, 20)
    assert period_key("weekly", d) == "2025-W47"
    assert period_key("monthly", d) == "2025-11"

def test_prev_period_weekly():
    assert prev_period("weekly", date(2025, 11, 20)) == date(2025, 11, 13)

def test_prev_period_monthly():
    assert prev_period("monthly", date(2025, 3, 15)) == date(2025, 2, 1)
    assert prev_period("monthly", date(2025, 1, 15)) == date(2024, 12, 1)

def test_milestones_increase():
    assert milestones_at(0, 10, 2.5, "increase") == 4
    assert milestones_at(0, 9, 2.5, "increase") == 3
    assert milestones_at(0, 0, 2.5, "increase") == 0
    assert milestones_at(0, 2.5, 2.5, "increase") == 1

def test_milestones_decrease():
    # v1.15.1: bei "decrease" gilt: Meilenstein #k gilt erst als erreicht,
    # wenn cv < sv - k*inc  (strikt drunter, nicht gleich).
    assert milestones_at(140, 129, 5, "decrease") == 2   # 129 < 130 → 2 Meilensteine
    assert milestones_at(140, 130, 5, "decrease") == 1   # 130 = Schwelle Nr.2, zaehlt NICHT
    assert milestones_at(140, 131, 5, "decrease") == 1   # 131 < 135 → 1 Meilenstein
    assert milestones_at(140, 135, 5, "decrease") == 0   # 135 = Schwelle Nr.1, zaehlt NICHT
    assert milestones_at(140, 140, 5, "decrease") == 0

def test_milestones_decrease_strict_v1_15_1():
    """Regression v1.15.1: 'auf der Schwelle stehen' ist bei fallenden
    Achievements KEIN erreichter Meilenstein — erst wenn der Wert echt
    drunter liegt. Schwelle #k liegt bei sv - k*inc.
    """
    # Gewicht-abnehmen: sv=90, inc=1. Schwelle #1 = 89, #2 = 88, ...
    # Bei cv=89 ist Schwelle #1 (89) NICHT strikt drunter -> 0 Meilensteine.
    # Bei cv=88 ist Schwelle #1 (89) drunter, #2 (88) NICHT -> 1 Meilenstein.
    for cv in range(80, 91):
        expected = max(0, 90 - cv - 1)  # cv=90→0, 89→0, 88→1, ..., 80→9
        assert milestones_at(90, cv, 1, "decrease") == expected, (
            f"cv={cv} sollte {expected} Meilensteine ergeben"
        )
    # Fliesskomma-Sicherheit: 90 - (0.1*10) darf nicht faelschlich
    # als "strikt drunter 89" erkannt werden.
    cv = 90.0
    for _ in range(10):
        cv -= 0.1  # cv wird ~89.00000000000001 durch Rundung
    # cv liegt nicht strikt unter 89 -> 0 Meilensteine
    assert milestones_at(90, cv, 1, "decrease") == 0

def test_milestones_zero_increment():
    assert milestones_at(0, 10, 0, "increase") == 0

def test_milestones_below_start_no_negative():
    assert milestones_at(10, 5, 1, "increase") == 0
    assert milestones_at(0, 10, 1, "decrease") == 0

def test_milestones_float_accumulation_v1_15_0():
    """Regression: 10 x +0.1 muss einen Meilenstein bei inc=1 ergeben.

    Vor v1.15.0 lieferte ``int((cv - sv) // inc)`` durch Fliesskomma-
    Rundungsfehler (0.1+...+0.1 = 0.9999...) faelschlich 0. Damit blieb
    die Reward-Auszahlung aus.
    """
    cv = 0.0
    for _ in range(10):
        cv += 0.1
    # cv ist typischerweise 0.9999999999999999 — trotzdem muessen es 1 sein
    assert milestones_at(0, cv, 1, "increase") == 1

    # Auch bei step_amount kleiner als threshold_increment:
    # 4 x +0.5 = 2.0, threshold = 2 => 1 Meilenstein.
    cv = 0.0
    for _ in range(4):
        cv += 0.5
    assert milestones_at(0, cv, 2, "increase") == 1

    # Kein false positive: 1.9 mit inc=2 sollte 0 Meilensteine liefern.
    assert milestones_at(0, 1.9, 2, "increase") == 0

def test_streak_bonus_modulo():
    # Streak bonus triggers at N % threshold == 0
    threshold = 4
    for streak in range(1, 20):
        should_trigger = streak > 0 and streak % threshold == 0
        assert should_trigger == (streak in [4, 8, 12, 16])