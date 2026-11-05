"""La estimación de un mensaje con el modelo local: prompt corto y fijo, respuesta en JSON."""
import json
import re

from core.afecto.estado import APPRAISAL, Estimate, clamp

# qwen3 responde el JSON en una línea; con margen para la etiqueta.
ESTIMATE_TOKENS = 120
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def estimate_prompt(text: str) -> str:
    return f"""Estima cómo se siente quien escribe este mensaje. Responde solo con JSON, sin explicar:
{{"valencia": 0, "activacion": 0, "etiqueta": "neutral", "importancia": 0, "bloqueo": 0, "control": 0, "urgencia": 0, "confianza": 0}}

- valencia: de -1 (desagradable) a 1 (agradable).
- activacion: de -1 (calmado, cansado) a 1 (agitado, con energía).
- etiqueta: una palabra (frustrado, triste, contento, entusiasmado, concentrado, neutral...).
- importancia, bloqueo, control, urgencia: de 0 a 1, cómo ve la persona su situación.
- confianza: de 0 a 1; baja si el mensaje no dice nada de cómo se siente.

Mensaje:
{text}"""


def parse_estimate(answer: str) -> Estimate:
    """El JSON de la respuesta, con los valores acotados; sin JSON válido, una estimación sin confianza."""
    match = JSON_OBJECT.search(answer or "")

    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}

    if not isinstance(data, dict):
        data = {}

    return Estimate(
        valence=clamp(data.get("valencia", 0)),
        arousal=clamp(data.get("activacion", data.get("activación", 0))),
        label=str(data.get("etiqueta") or "neutral").strip().lower()[:30],
        appraisal={name: clamp(data.get(name, 0), 0.0, 1.0) for name in APPRAISAL},
        confidence=clamp(data.get("confianza", 0), 0.0, 1.0),
    )


def estimate(text: str, ask) -> Estimate:
    """ask: ProviderRouter.ask, con el modelo de charla (qwen3)."""
    return parse_estimate(ask(estimate_prompt(text), domain="general", max_tokens=ESTIMATE_TOKENS))
