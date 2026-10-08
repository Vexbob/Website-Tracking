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
    # v2.36.0: wo es das Ding gibt. "" oder null entfernt den Link.
    link: Optional[str] = None


class SavGoalCreate(BaseModel):
    name: str
    target_amount: float
    activate: bool = True
    link: Optional[str] = None


class SavGoalTransfer(BaseModel):
    """v1.26.0: Ueberweisung vom Allgemein-Konto (Puffer) auf ein Sparziel."""
    amount: float
    note: Optional[str] = None


class SavGoalGiveUp(BaseModel):
    """v2.35.0: Sparziel aufgeben -- das Angesparte zieht in den Puffer.
    ``note`` sagt, warum; sie steht am Vermerk im Verlauf."""
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
    # v2.9.0: Kachel an eine Quelle aus einem anderen Modul haengen. Die
    # Quelle liest nur -- gebucht wird erst, wenn bestaetigt wird.
    auto_source: Optional[str] = None
    auto_params: Optional[dict] = None


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
    auto_source: Optional[str] = None     # v2.9.0, "" oder None loest die Bindung
    auto_params: Optional[dict] = None


class AchAutoConfirm(BaseModel):
    """Bestaetigung eines Stands aus einer verbundenen Quelle.

    Bewusst OHNE Wert: den liest der Server selbst aus der Quelle. Ein Wert im
    Body waere eine Gutschrift ueber eine Zahl, die in keiner Messung steht.
    """
    note: Optional[str] = None


# ---------- Progress-/Wochen-/Monatsziele ----------
class PGCreate(BaseModel):
    title: str
    reward_amount: float
    rhythm_type: str = "weekly"
    target_count: int
    streak_bonus_amount: float = 0
    streak_bonus_threshold: int = 0
    reward_goal_id: Optional[int] = None  # v1.18.2
    # v2.16.0: Teilbelohnung -- ab ``partial_count`` Check-ins gibt es am
    # Periodenende ``partial_percent`` % der Belohnung (0 = aus)
    partial_count: int = 0
    partial_percent: float = 0


class PGUpd(BaseModel):
    title: Optional[str] = None
    reward_amount: Optional[float] = None
    target_count: Optional[int] = None
    rhythm_type: Optional[str] = None
    streak_bonus_amount: Optional[float] = None
    streak_bonus_threshold: Optional[int] = None
    reward_goal_id: Optional[int] = None  # v1.18.2
    partial_count: Optional[int] = None
    partial_percent: Optional[float] = None


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
    link: Optional[str] = None


class PotUpd(BaseModel):
    """v2.36.0: ein Wunsch laesst sich nachtraeglich aendern (vorher nur
    anlegen und loeschen) -- sonst liesse sich ein Link nie nachtragen."""
    name: Optional[str] = None
    estimated_price: Optional[float] = None
    link: Optional[str] = None


class FICreate(BaseModel):
    title: str
    category: Optional[str] = None
    # v2.36.0: die vollstaendige Vorlage (dieselben Felder wie beim Anlegen
    # eines Wochenziels oder Achievements). Ohne sie ist die Idee ein Titel.
    config: Optional[dict] = None


class FIUpd(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    config: Optional[dict] = None


# ---------- Reorder / Backup ----------
class ReorderBody(BaseModel):
    order: list[int]


class MetricOrderBody(BaseModel):
    """Reihenfolge der Vitalwerte-Diagramme (v1.46.1).

    Anders als bei Achievements/Wochenzielen sind das keine DB-IDs, sondern
    die Metrik-Typen selbst (``steps``, ``heart_rate``, ...).
    """
    order: list[str]


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
class TrophaeGekauft(BaseModel):
    """v2.43.0: Haken „gekauft“ an einer Trophaee. ``datum`` ist der Tag in
    Ortszeit des Browsers (sonst heute nach Serveruhr)."""
    gekauft: bool
    datum: Optional[str] = None


class TrophyCreate(BaseModel):
    name: str
    target_amount: float
    final_amount: float
    started_at: Optional[str] = None
    icon: Optional[str] = "🏆"
    color: Optional[str] = "gold"
    note: Optional[str] = None
    photo_url: Optional[str] = None
