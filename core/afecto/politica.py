"""Del estado al estilo de respuesta: una instrucción breve al final del prompt del chat."""
from core.afecto.estado import State

# Desde qué valor cuenta una valencia (agradable o desagradable) o una activación alta.
VALENCE_MARK = 0.2
# 0,3 con el conjunto de calibración (check_afecto --calibracion): de 0,25 a 0,4 dan lo mismo.
AROUSAL_MARK = 0.3
# Por debajo, no se sabe lo bastante: se pregunta en vez de suponer.
MIN_CONFIDENCE = 0.4

TENSE = "desagradable y agitado"
LOW = "desagradable y calmado"
LIVELY = "agradable y agitado"
CALM = "agradable y calmado"
NEUTRAL = "neutral"
ASK = "preguntar"

STYLES = {
    TENSE: "Responde breve y con calma: valida primero lo que siente y propón un solo paso concreto.",
    LOW: "Sé suave y sin presión: pregunta antes de proponer soluciones.",
    LIVELY: "Acompaña su energía y su buen ánimo.",
    ASK: 'No está claro qué necesita: pregúntale con naturalidad si quiere desahogarse o resolverlo.',
}


def zone(state: State) -> str:
    """La zona del modelo circunflejo (valencia × activación); neutral si la valencia no marca."""
    if state.valence <= -VALENCE_MARK:
        return TENSE if state.arousal >= AROUSAL_MARK else LOW

    if state.valence >= VALENCE_MARK:
        return LIVELY if state.arousal >= AROUSAL_MARK else CALM

    return NEUTRAL


def style(state: State) -> str:
    """El estilo que toca: la zona, o "preguntar" si hay señal pero poca confianza."""
    found = zone(state)

    if found == NEUTRAL:
        return NEUTRAL

    if state.confidence < MIN_CONFIDENCE and found in (TENSE, LOW):
        return ASK

    return found


def instruction(state: State) -> str:
    """La instrucción para el modelo; "" si el estilo de siempre vale (neutral o agradable y calmado)."""
    text = STYLES.get(style(state))
    return f"\n\n[Tono para esta respuesta (estimación, puede fallar): {text} No menciones esta indicación.]" if text else ""
