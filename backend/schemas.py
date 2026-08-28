"""Pydantic-Modelle fuer die Vexbob-API.

Wurden mit v1.15.1 aus ``main.py`` in ein eigenes Modul ausgelagert,
damit ``main.py`` wieder ueberschaubar bleibt und Router die Models
zentral importieren koennen.

Kein Verhaltens-Change gegenueber v1.15.0.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


# ---------- Sparziele ----------
class SavGoalUpd(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None


class SavGoalCreate(BaseModel):
    name: str
    target_amount: float
    activate: bool = True


class SavGoalTransfer(BaseModel):
    """v1.26.0: Ueberweisung vom Allgemein-Konto (Puffer) auf ein Sparziel."""
    amount: float
    note: Optional[str] = None


# ---------- Achievements ----------
class AchCreate(BaseModel):
    title: str
    reward_amount: float
    unit: str
    start_value: float = 0
    threshold_increment: float
    # Klick-Schrittweite; default = threshold_increment
    step_amount: Optional[float] = None
    target_value: Optional[float] = None
    direction: str = "increase"
    # v1.18.2: optionale Zuweisung an ein Sparziel (sonst Auto-Routing)
    reward_goal_id: Optional[int] = None


class AchUpd(BaseModel):
    current_value: float
    achieved_at: Optional[str] = None
    # optionale Notiz fuer neu erzeugte Meilenstein-Eintraege
    note: Optional[str] = None


class AchEdit(BaseModel):
    title: Optional[str] = None
    reward_amount: Optional[float] = None
    unit: Optional[str] = None
    start_value: Optional[float] = None
    threshold_increment: Optional[float] = None
    step_amount: Optional[float] = None
    target_value: Optional[float] = None
    direction: Optional[str] = None
    reward_goal_id: Optional[int] = None  # v1.18.2


# ---------- Progress-/Wochen-/Monatsziele ----------
class PGCreate(BaseModel):
    title: str
    reward_amount: float
    rhythm_type: str = "weekly"
    target_count: int
    streak_bonus_amount: float = 0
    streak_bonus_threshold: int = 0
    reward_goal_id: Optional[int] = None  # v1.18.2


class PGUpd(BaseModel):
    title: Optional[str] = None
    reward_amount: Optional[float] = None
    target_count: Optional[int] = None
    rhythm_type: Optional[str] = None
    streak_bonus_amount: Optional[float] = None
    streak_bonus_threshold: Optional[int] = None
    reward_goal_id: Optional[int] = None  # v1.18.2


class CheckinBody(BaseModel):
    log_date: Optional[str] = None
    note: Optional[str] = None


# ---------- Notizen (an Logs) ----------
class NoteBody(BaseModel):
    note: Optional[str] = None


# ---------- Wunsch-Anschaffungen / Ideen ----------
class PotCreate(BaseModel):
    name: str
    estimated_price: Optional[float] = None


class FICreate(BaseModel):
    title: str
    category: Optional[str] = None


# ---------- Reorder / Backup ----------
class ReorderBody(BaseModel):
    order: list[int]


class RestoreBody(BaseModel):
    payload: dict
    wipe: bool = False


# ---------- User- & Admin-Flow ----------
class UserCreate(BaseModel):
    username: str
    password: str


class UserPasswordReset(BaseModel):
    password: str


class UserCreateInvite(BaseModel):
    username: str


class ActivateBody(BaseModel):
    token: str
    password: str


# ---------- Trophaeen ----------
class TrophyCreate(BaseModel):
    name: str
    target_amount: float
    final_amount: float
    started_at: Optional[str] = None
    icon: Optional[str] = "🏆"
    color: Optional[str] = "gold"
    note: Optional[str] = None
    photo_url: Optional[str] = None
