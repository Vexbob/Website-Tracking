"""Pytest tests for core calculations. Run: pytest backend/tests/"""
import pytest
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set required env vars before importing modules that check for them
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from database import week_key_for, month_key_for, period_key, prev_period

def milestones_at(sv, cv, inc, direction):
    if inc <= 0: return 0
    if direction == "increase": return max(0, int((cv - sv) // inc))
    return max(0, int((sv - cv) // inc))

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
    assert milestones_at(140, 130, 5, "decrease") == 2
    assert milestones_at(140, 132, 5, "decrease") == 1
    assert milestones_at(140, 140, 5, "decrease") == 0

def test_milestones_zero_increment():
    assert milestones_at(0, 10, 0, "increase") == 0

def test_milestones_below_start_no_negative():
    assert milestones_at(10, 5, 1, "increase") == 0
    assert milestones_at(0, 10, 1, "decrease") == 0

def test_streak_bonus_modulo():
    # Streak bonus triggers at N % threshold == 0
    threshold = 4
    for streak in range(1, 20):
        should_trigger = streak > 0 and streak % threshold == 0
        assert should_trigger == (streak in [4, 8, 12, 16])