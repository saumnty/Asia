"""Respuesta con fuente: solo lo que dicen los fragmentos, con citas reales, o "no lo encontré"."""
import pytest

from core import prompts
from core.commands import COMMANDS, options_text
from core.prompts import NOT_FOUND
from core.rag.library import is_refusal, sources_footer
from core.rag.retriever import Hit, relevant
from test_confidencial import make_brain
from tools.rag_tool import RagTool

CONTEXT = """
--- [control/pid.py:40-55] Pid.salida ---
Fuente: Bolitabot (proyecto)
Contenido:
kp = 2

--- [control/pid.py:60-70] Pid.reinicia ---
Fuente: Bolitabot (proyecto)
Contenido:
error = 0

--- [README.md:1-8] ---
Fuente: Bolitabot (proyecto)
Contenido:
Robot.
"""


class Registry:
    def __init__(self, context=CONTEXT):
        self.context = context
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return self.context


class Router:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def ask(self, prompt, **options):
        self.prompts.append(prompt)
        return self.answer


def brain_with(answer="La ganancia es 2 [control/pid.py:40-55].", context=CONTEXT):
    brain = make_brain()
    brain.tool_registry = Registry(context)
    brain.provider_router = Router(answer)
    return brain


def test_el_prompt_exige_fragmentos_citas_y_parciales():
    prompt = prompts.search_project_rag("asia", "qué ganancia", CONTEXT)

    assert "Responde solo con lo que dicen los fragmentos" in prompt
    assert "la etiqueta [archivo:líneas]" in prompt and "[control/pid.py:40-55]" in prompt
    assert "Si la información es parcial, di qué parte está" in prompt


def test_no_lo_encontre_no_es_decision_del_modelo():
    assert NOT_FOUND not in prompts.search_project_rag("asia", "qué ganancia", CONTEXT)


def test_buscar_va_directo_sin_intent_engine():
    brain = brain_with()

    def forbidden(text):
        raise AssertionError("/buscar no pasa por el IntentEngine")

    brain.intent_engine.detect = forbidden

    answer = brain.process("/buscar qué ganancia tiene el PID en Bolitabot")

    assert answer.startswith("La ganancia es 2")
    [(action, kwargs)] = brain.tool_registry.calls
    assert action == "search_project_rag"
    assert kwargs["question"] == "qué ganancia tiene el PID en Bolitabot"
    assert brain.last_action == "search_project_rag"


def test_las_fuentes_las_pone_el_codigo_no_el_modelo():
    answer = brain_with().process("/buscar qué ganancia tiene")

    assert answer.endswith("Fuentes:\n- control/pid.py:40-55 (Pid.salida)")
    assert "README.md" not in answer


def test_la_etiqueta_gana_al_nombre_de_archivo():
    # Medido con el 7B: citaba un fragmento y mencionaba otro archivo de paso.
    footer = sources_footer(CONTEXT, "Según [README.md:1-8], la ganancia está en control/pid.py.")

    assert footer == "\n\nFuentes:\n- README.md:1-8"


def test_de_un_archivo_solo_el_fragmento_citado():
    footer = sources_footer(CONTEXT, "Se reinicia a cero [control/pid.py:60-70].")

    assert footer == "\n\nFuentes:\n- control/pid.py:60-70 (Pid.reinicia)"


def test_la_etiqueta_se_reconoce_con_raya():
    assert "README.md:1-8" in sources_footer(CONTEXT, "Es un robot [README.md:1–8].")


def test_lineas_inventadas_caen_en_el_nombre_de_archivo():
    footer = sources_footer(CONTEXT, "Es un robot [README.md:90-99].")

    assert footer == "\n\nFuentes:\n- README.md:1-8"


def test_si_no_menciona_ninguno_lista_todos_los_consultados():
    assert sources_footer(CONTEXT, "La ganancia es 2.") == (
        "\n\nFuentes:\n- control/pid.py:40-55 (Pid.salida)\n- control/pid.py:60-70 (Pid.reinicia)\n- README.md:1-8"
    )


def test_una_cita_inventada_no_llega_a_fuentes():
    footer = sources_footer(CONTEXT, "Según inventado.py, línea 3, y README.md, es 2.")

    assert "inventado.py" not in footer and "README.md" in footer


def test_sin_nada_relevante_no_llama_al_modelo():
    brain = brain_with(context=NOT_FOUND)

    assert brain.process("/buscar receta de mole") == NOT_FOUND
    assert brain.provider_router.prompts == []


@pytest.mark.parametrize("answer", ["No lo encontré en tus proyectos.", "no lo encontré en tus proyectos"])
def test_si_el_modelo_no_lo_encuentra_no_hay_fuentes(answer):
    assert sources_footer(CONTEXT, answer) == ""


@pytest.mark.parametrize(
    "answer",
    [
        "No lo encontré en tus proyectos.",
        "no lo encontre.",
        "Lo siento, no encontré esa información.",
        "No hay información sobre eso en los fragmentos.",
        "Los fragmentos proporcionados no responden la pregunta.",
        "No puedo responder con estos fragmentos.",
    ],
)
def test_negativas(answer):
    assert is_refusal(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "La ganancia es 2 [control/pid.py:40-55].",
        "No encontré el valor de ki [control/pid.py:40-55].",
        "Está kp, pero no se dice cuánto vale ki.",
        "Sin Ctrl+C no se corta nada; el hilo sigue. " * 10,
        "Se guarda si no hay información nueva, cada 3 s, en data/reflexion. " * 6,
    ],
)
def test_no_son_negativas(answer):
    assert not is_refusal(answer)


def test_buscar_sin_pregunta():
    assert "Escribe la pregunta" in brain_with().process("/buscar")


def test_en_la_tabla_de_opciones():
    assert any(c.slash == "/buscar <pregunta>" and c.group == "biblioteca" for c in COMMANDS)
    assert "/buscar <pregunta>" in options_text()


def hit(coverage):
    return Hit("doc", {}, coverage=coverage)


def test_relevante_si_algun_fragmento_tiene_las_palabras():
    assert relevant([hit(0.0), hit(0.6)], 0.3)
    assert not relevant([hit(0.2), hit(0.0)], 0.3)
    assert not relevant([], 0.3)


def test_rag_tool_dice_no_lo_encontre_si_nada_es_relevante(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [hit(0.1)])

    assert RagTool().search_project("receta de mole", "asia") == NOT_FOUND


def test_el_umbral_viene_de_config(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [hit(0.1)])
    monkeypatch.setattr("tools.rag_tool.SettingsManager", lambda: {"rag": {"min_coverage": 0.05}})

    assert RagTool().search_project("receta de mole", "asia") != NOT_FOUND
