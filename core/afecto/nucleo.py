"""AffectCore: la interfaz del núcleo afectivo (ver core/afecto/__init__.py)."""
import re
from datetime import datetime

from core import paths
from core.afecto.estado import Estimate, State, smoothed
from core.afecto.estimacion import estimate
from core.afecto.politica import instruction, style, zone
from core.atomic_write import write_json_atomic
from config.settings_manager import read_json

# Valor de sesión de "/afecto on" y "/afecto off"; sin él, afecto.activo de la configuración.
AFFECT_SETTING = "affect_mode"
DEFAULT_HALF_LIFE_HOURS = 3.0
# Lo que dice el usuario de sí mismo vale más que una estimación.
CORRECTION_CONFIDENCE = 0.9
# "no, solo estoy concentrado", "no estoy enojado, estoy cansado", "en realidad estoy bien".
CORRECTION = re.compile(
    r"^\s*(?:no,?\s+(?:solo|sólo|solamente|nada más)\s+|no\s+estoy\s+\w+,?\s+(?:solo\s+|sólo\s+)?|en realidad\s+)"
    r"(?:estoy|ando|me siento)\b",
    re.IGNORECASE,
)


def affect_enabled(settings) -> bool:
    session = settings.get(AFFECT_SETTING)

    if session is not None:
        return bool(session)

    return bool((settings.get("afecto") or {}).get("activo"))


def state_file():
    return paths.DATA_DIR / "afecto" / "estado.json"


def is_correction(text: str) -> bool:
    return bool(CORRECTION.match(text or ""))


class AffectCore:
    def __init__(self, settings, path=None, now=datetime.now):
        self.settings = settings
        self.path = path or state_file()
        self.now = now

    def half_life(self) -> float:
        return float((self.settings.get("afecto") or {}).get("vida_media_horas", DEFAULT_HALF_LIFE_HOURS))

    def state(self) -> State:
        return State.from_dict(read_json(self.path)) if self.path.exists() else State()

    def save(self, state: State):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, state.to_dict())

    def clear(self) -> bool:
        if not self.path.exists():
            return False

        self.path.unlink()
        return True

    def observe(self, text: str, ask, domain="general") -> State:
        """Estima el mensaje (con el modelo de domain) y lo suaviza con el estado anterior; lo guarda."""
        state = smoothed(self.state(), estimate(text, ask, domain), self.now(), self.half_life())
        self.save(state)
        return state

    def correct(self, text: str, ask) -> State:
        """El estado que dice el usuario, sin suavizar: reemplaza la estimación."""
        said: Estimate = estimate(text, ask)
        state = State(said.valence, said.arousal, CORRECTION_CONFIDENCE, said.label, said.appraisal,
                      self.now().isoformat(timespec="seconds"), corrected=True)
        self.save(state)
        return state

    @staticmethod
    def instruction(state: State) -> str:
        return instruction(state)

    @staticmethod
    def describe(state: State) -> str:
        """Lo que muestra /estado: la hipótesis, visible y corregible."""
        if not state.updated:
            return "No tengo ninguna estimación de tu estado."

        source = "lo que me dijiste" if state.corrected else "una estimación de tus mensajes, puede fallar"
        return (
            f"Hipótesis ({source}): {state.label}, zona {zone(state)}; valencia {state.valence:+.2f}, "
            f"activación {state.arousal:+.2f}, confianza {state.confidence:.2f}, del {state.updated}. "
            f"Estilo: {style(state)}. Corrígeme (\"no, solo estoy concentrado\") o bórralo con /afecto borrar."
        )
