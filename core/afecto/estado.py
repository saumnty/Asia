"""El estado afectivo estimado y su suavizado en el tiempo."""
from dataclasses import asdict, dataclass, field
from datetime import datetime

APPRAISAL = ("importancia", "bloqueo", "control", "urgencia")


def clamp(value, low=-1.0, high=1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Estimate:
    """Lo que dice el modelo de un mensaje. appraisal: importancia, bloqueo, control y urgencia (0 a 1)."""

    valence: float = 0.0
    arousal: float = 0.0
    label: str = "neutral"
    appraisal: dict = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class State:
    """Valencia (desagradable -1 a agradable 1) y activación (calmado -1 a agitado 1), con confianza y fecha."""

    valence: float = 0.0
    arousal: float = 0.0
    confidence: float = 0.0
    label: str = "neutral"
    appraisal: dict = field(default_factory=dict)
    updated: str = ""
    corrected: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def faded(state: State, now: datetime, half_life_hours: float) -> State:
    """El estado anterior, con la confianza a la mitad cada half_life_hours."""
    if not state.updated:
        return State()

    hours = max(0.0, (now - datetime.fromisoformat(state.updated)).total_seconds() / 3600)
    weight = 0.5 ** (hours / half_life_hours) if half_life_hours > 0 else 0.0
    return State(state.valence, state.arousal, state.confidence * weight, state.label, state.appraisal, state.updated,
                 state.corrected)


def smoothed(previous: State, estimate: Estimate, now: datetime, half_life_hours: float) -> State:
    """El estado nuevo: media de lo anterior (desvanecido) y lo estimado, pesada por la confianza.

    Un solo mensaje con confianza alta pesa más que un estado viejo; uno sin
    señal (confianza 0) apenas lo mueve.
    """
    before = faded(previous, now, half_life_hours)
    weights = before.confidence + estimate.confidence

    if weights <= 0:
        return State(updated=now.isoformat(timespec="seconds"))

    def mix(old, new):
        return round(clamp((before.confidence * old + estimate.confidence * new) / weights), 3)

    return State(
        valence=mix(before.valence, estimate.valence),
        arousal=mix(before.arousal, estimate.arousal),
        confidence=clamp(max(estimate.confidence, before.confidence), 0.0, 1.0),
        label=estimate.label if estimate.confidence >= before.confidence else before.label,
        appraisal=estimate.appraisal or before.appraisal,
        updated=now.isoformat(timespec="seconds"),
    )
