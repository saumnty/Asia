"""Núcleo afectivo, versión 0 (fase de afecto): un módulo sustituible.

Todo lo emocional de Asia es una simulación funcional: una estimación del
estado de quien escribe (valencia y activación, de -1 a 1, con confianza) que
solo cambia el tono de la respuesta. No es un diagnóstico ni Asia siente nada.

Interfaz (lo que usa el resto de Asia; otro núcleo puede cumplirla igual):

- AffectCore.observe(texto, ask) -> State: estima el mensaje con el modelo
  local (ask de ProviderRouter, dominio "general": qwen3) y lo suaviza con el
  estado anterior, que se desvanece con las horas.
- AffectCore.recent() -> State: el último estado, desvanecido, sin llamar al modelo
  (cuando responde el 7B: estimar con qwen3 lo recargaría y con el 7B tarda 8 s).
- AffectCore.instruction(state) -> str: la instrucción de tono para el final
  del prompt del chat ("" si no hace falta), según policy.py.
- AffectCore.correct(texto, ask), state(), clear(): la corrección del usuario
  ("no, solo estoy concentrado"), /estado y borrar el estado.

Datos en formato abierto (JSON) en data/afecto/estado.json, solo en local. Lo
que sale de aquí lleva la etiqueta "emocional" (core/provenance.py): nunca sale
hacia un proveedor externo, ni con autorización. Apagado por defecto
(afecto.activo en config/defaults.json).
"""
from core.afecto.nucleo import AFFECT_SETTING, AffectCore, affect_enabled

__all__ = ["AFFECT_SETTING", "AffectCore", "affect_enabled"]
