"""Respuesta con fuente: solo lo que dicen los fragmentos, con citas reales, o "no lo encontré"."""
import pytest

from core import prompts
from core.commands import COMMANDS, options_text
from core.prompts import NOT_FOUND
from core.rag.library import is_refusal
from core.rag.quotes import Quote, best_fragments, verify_quotes
from core.rag.retriever import Hit, relevant
from test_confidencial import make_brain
from tools.rag_tool import RagTool

CONTEXT = """
--- [control/pid.py:40-55] Pid.salida ---
Fuente: Bolitabot (proyecto)
Contenido:
control/pid.py · Pid.salida
def salida(self):
    self.kp   =   2.5
    return self.kp * self.error

--- [control/pid.py:60-70] Pid.reinicia ---
Fuente: Bolitabot (proyecto)
Contenido:
control/pid.py · Pid.reinicia
def reinicia(self):
    self.error = 0

--- [README.md:1-8] ---
Fuente: Bolitabot (proyecto)
Contenido:
README.md
Un robot que balancea una bolita.
"""
QUOTED = "[control/pid.py:40-55] self.kp = 2.5\n[inventado.py:1-9] esta linea no existe en nada"
ANSWER = "La ganancia es 2 [control/pid.py:41]."


class Registry:
    def __init__(self, context=CONTEXT):
        self.context = context
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return self.context


class Router:
    """Contesta en orden: primero la extracción, luego la respuesta."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def ask(self, prompt, **options):
        self.prompts.append(prompt)
        return self.answers.pop(0)


def brain_with(*answers, context=CONTEXT):
    brain = make_brain()
    brain.tool_registry = Registry(context)
    brain.provider_router = Router(*(answers or (QUOTED, ANSWER)))
    return brain


def test_la_extraccion_pide_copiar_o_ninguna():
    prompt = prompts.extract_quotes("qué ganancia", CONTEXT)

    assert "textualmente" in prompt and "NINGUNA" in prompt and "[control/pid.py:40-55]" in prompt
    assert "qué ganancia" in prompt


def test_la_extraccion_sabe_que_hacer_con_un_nombre_suelto():
    assert "solo un nombre de función, clase o variable" in prompts.extract_quotes("SentenceSplitter", CONTEXT)


def test_la_respuesta_solo_ve_las_lineas():
    prompt = prompts.answer_from_quotes("qué ganancia", "[a.py:1] kp = 2")

    assert "únicamente estas líneas" in prompt and "[a.py:1] kp = 2" in prompt
    assert "Fuente:" not in prompt


def test_no_lo_encontre_no_es_decision_del_modelo():
    assert NOT_FOUND not in prompts.extract_quotes("qué ganancia", CONTEXT)
    assert NOT_FOUND not in prompts.answer_from_quotes("qué ganancia", "[a.py:1] kp = 2")


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


def test_la_cita_se_verifica_normalizando_espacios():
    [quote] = verify_quotes("[control/pid.py:40-55] self.kp = 2.5", CONTEXT)

    assert quote == Quote("control/pid.py:41", "Pid.salida", "self.kp = 2.5")


def test_una_linea_que_no_existe_se_descarta():
    assert verify_quotes("[control/pid.py:40-55] self.kp = 3.5", CONTEXT) == []
    assert verify_quotes("[inventado.py:1-9] esta linea no existe en nada", CONTEXT) == []


def test_ninguna_no_deja_citas():
    assert verify_quotes("NINGUNA", CONTEXT) == []


def test_se_descarta_el_texto_alrededor_de_las_citas():
    response = "Estas son las líneas:\n- [README.md:1-8] `Un robot que balancea una bolita.`\nEspero que sirva."

    assert [q.cite for q in verify_quotes(response, CONTEXT)] == ["README.md:1"]


def test_vale_el_fragmento_donde_esta_de_verdad():
    [quote] = verify_quotes("[README.md:1-8] self.error = 0", CONTEXT)

    assert quote.cite == "control/pid.py:61"


def test_una_cita_sin_etiqueta_tambien_se_busca():
    assert [q.cite for q in verify_quotes("self.error = 0", CONTEXT)] == ["control/pid.py:61"]


def test_la_linea_que_dice_donde_vive_no_es_cita():
    assert verify_quotes("[control/pid.py:40-55] control/pid.py · Pid.salida", CONTEXT) == []


def test_una_cita_repetida_cuenta_una_vez():
    assert len(verify_quotes("[README.md:1-8] Un robot que balancea\n[README.md:1-8] Un robot que balancea", CONTEXT)) == 1


def test_el_modelo_responde_solo_con_las_verificadas():
    brain = brain_with()

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer == ANSWER + "\n\nFuentes:\n- control/pid.py:41 (Pid.salida)"
    assert "[control/pid.py:41] self.kp = 2.5" in brain.provider_router.prompts[1]
    assert "inventado" not in brain.provider_router.prompts[1]


def test_fuentes_sale_de_las_lineas_y_no_de_lo_que_diga_el_modelo():
    answer = brain_with(QUOTED, "Lo dice README.md y otros.py [otros.py:1].").process("/buscar qué ganancia")

    assert answer.endswith("Fuentes:\n- control/pid.py:41 (Pid.salida)")
    assert "- README.md" not in answer


@pytest.mark.parametrize("extracted", ["NINGUNA", "[inventado.py:1-9] esta linea no existe en nada", "La ganancia es 3."])
def test_sin_lineas_verificadas_no_hay_respuesta_del_modelo(extracted):
    brain = brain_with(extracted)

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer.startswith(prompts.NO_DIRECT_ANSWER)
    assert "[control/pid.py:40-55] Pid.salida\ndef salida" in answer and "[README.md:1-8]\nUn robot" in answer
    assert "control/pid.py · Pid.salida" not in answer
    assert "Fuentes:" not in answer and len(brain.provider_router.prompts) == 1


def test_sin_nada_relevante_no_llama_al_modelo():
    brain = brain_with(context=NOT_FOUND)

    assert brain.process("/buscar receta de mole") == NOT_FOUND
    assert brain.provider_router.prompts == []


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


@pytest.mark.parametrize("refusal", [NOT_FOUND, "Los fragmentos no responden la pregunta."])
def test_si_se_niega_con_lineas_verificadas_muestra_los_fragmentos(refusal):
    brain = brain_with(QUOTED, refusal)

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer.startswith(prompts.NO_DIRECT_ANSWER) and NOT_FOUND not in answer
    assert len(brain.provider_router.prompts) == 2


def test_los_mejores_son_tres_y_cortos():
    context = "".join(f"\n--- [a{i}.py:1-9] ---\nFuente: x (proyecto)\nContenido:\na{i}.py\n{'z' * 700}\n" for i in range(5))

    shown = best_fragments(context)

    assert "[a2.py:1-9]" in shown and "[a3.py:1-9]" not in shown
    assert shown.count("…") == 3 and "z" * 601 not in shown


def test_una_respuesta_parcial_se_conserva():
    answer = brain_with(QUOTED, "Está kp, pero no se dice cuánto vale ki [control/pid.py:41].").process("/buscar qué ganancia")

    assert answer.startswith("Está kp") and "Fuentes:" in answer


def test_pide_los_fragmentos_configurados(monkeypatch):
    monkeypatch.setattr("core.actions.explore.RAG_FRAGMENTS", 3)
    brain = brain_with()

    brain.process("/buscar qué ganancia tiene")

    assert brain.tool_registry.calls[0][1]["n_results"] == 3


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
