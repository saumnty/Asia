"""Respuesta con fuente: solo lo que dicen los fragmentos, con citas reales, o "no lo encontré"."""
import pytest

from core import prompts
from core.commands import COMMANDS, options_text
from core.prompts import NOT_FOUND
from core.rag.library import is_refusal
from core.rag.quotes import Quote, best_fragments, draft_problems, is_thin, verified_lines, verify_quotes
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

    assert quote == Quote("control/pid.py", 41, "Pid.salida", "    self.kp   =   2.5")


def test_se_muestra_la_linea_del_archivo_y_no_la_copia_del_modelo():
    [quote] = verify_quotes("[README.md:1-8] Un robot quebalancea una bolita.", CONTEXT)

    assert quote.text == "Un robot que balancea una bolita."


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

    assert answer == f"{ANSWER}\n\n{prompts.VERIFIED_LINES}\n\ncontrol/pid.py:41 (Pid.salida)\n  self.kp   =   2.5"
    assert "[control/pid.py:41] self.kp   =   2.5" in brain.provider_router.prompts[1]
    assert "inventado" not in brain.provider_router.prompts[1]


def quote(path, line, text, label=""):
    return Quote(path, line, label, text)


def test_junta_las_lineas_seguidas():
    shown = verified_lines([quote("a.py", 41, "    b = 2"), quote("a.py", 40, "    a = 1"), quote("a.py", 42, "    c = 3")])

    assert shown == f"{prompts.VERIFIED_LINES}\n\na.py:40-42\n  a = 1\n  b = 2\n  c = 3"


def test_las_lineas_salteadas_van_en_tramos_aparte():
    shown = verified_lines([quote("a.py", 40, "uno", "f"), quote("a.py", 45, "dos", "f")])

    assert "a.py:40 (f)\n  uno\n\na.py:45 (f)\n  dos" in shown


def test_agrupa_por_archivo():
    shown = verified_lines([quote("a.py", 1, "uno"), quote("b.py", 1, "otro"), quote("a.py", 2, "dos")])

    assert shown.index("a.py:1-2") < shown.index("b.py:1")
    assert "a.py:1" not in shown.partition("b.py:1")[2]


def test_una_cita_sin_linea():
    assert "viejo.py\n  uno" in verified_lines([quote("viejo.py", None, "uno")])


@pytest.mark.parametrize("extracted", ["NINGUNA", "[inventado.py:1-9] esta linea no existe en nada", "La ganancia es 3."])
def test_sin_lineas_verificadas_no_hay_respuesta_del_modelo(extracted):
    brain = brain_with(extracted)

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer.startswith(prompts.NO_DIRECT_ANSWER)
    assert "[control/pid.py:40-55] Pid.salida\ndef salida" in answer and "[README.md:1-8]\nUn robot" in answer
    assert "control/pid.py · Pid.salida" not in answer
    assert prompts.VERIFIED_LINES not in answer and len(brain.provider_router.prompts) == 1


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


VERIFIED = [Quote("control/pid.py", 41, "Pid.salida", "    self.kp   =   2.5"), Quote("control/pid.py", 42, "Pid.salida", "x")]


@pytest.mark.parametrize(
    "answer",
    [
        "La ganancia es 2 [control/pid.py:41].",
        "La ganancia es 2 [control/pid.py:41-42].",
        "La ganancia es 2 [control/pid.py:41–42].",
        "La calcula `salida` con `self.kp   =   2.5` y `self.error`.",
        "Está en [control/pid.py], en `reinicia`.",
        "La ganancia sale de self.kp, en un robot.",
        "Un robot, para la ganancia:\n```python\nself.kp = 2.5\n```",
    ],
)
def test_una_redaccion_con_nombres_reales_vale(answer):
    assert draft_problems(answer, VERIFIED, CONTEXT) == []


@pytest.mark.parametrize(
    "answer, problem",
    [
        ("La ganancia es 2 [control/pid.py:50].", "[control/pid.py:50]"),
        ("La ganancia es 2 [control/pid.py:43-50].", "[control/pid.py:43-50]"),
        ("La ganancia es 2 [otro.py:41].", "[otro.py:41]"),
        ("Está en [otro.py].", "otro.py"),
        ("Se calcula con `calcula_pid()`.", "calcula_pid()"),
        ("Se calcula con calcula_pid sobre el error.", "calcula_pid"),
        ("Se calcula con calculaPid sobre el error.", "calculaPid"),
        ("Lo hace `SessionPid` sobre el error.", "SessionPid"),
        ("Un ejemplo:\n```python\ndef atomic_write(ruta, contenido):\n    pass\n```", "def atomic_write(ruta, contenido):"),
    ],
)
def test_una_redaccion_con_nombres_inventados_no_vale(answer, problem):
    assert problem in draft_problems(answer, VERIFIED, CONTEXT)


def test_un_rango_vale_si_toca_una_linea_verificada():
    # Medido con el 7B: [ollama_models.py:135-141] con líneas sueltas verificadas dentro.
    assert draft_problems("La ganancia es 2 [control/pid.py:30-41].", VERIFIED, CONTEXT) == []
    assert draft_problems("La ganancia es 2 [control/pid.py:42-55].", VERIFIED, CONTEXT) == []


def test_una_cita_entre_comillas_invertidas_es_una_cita():
    # Medido con el 7B: `README.md:48` invalidaba una respuesta correcta por "nombre desconocido".
    assert draft_problems("Lo dice `control/pid.py:41` y ya.", VERIFIED, CONTEXT) == []
    assert draft_problems("Lo dice `control/pid.py:90` y ya.", VERIFIED, CONTEXT) == ["`control/pid.py:90`"]


def test_un_rango_que_solapa_no_salva_un_nombre_inventado():
    problems = draft_problems("Lo hace `calcula_pid()` [control/pid.py:41-50].", VERIFIED, CONTEXT)

    assert problems == ["calcula_pid()"]


def test_una_cita_de_un_fragmento_que_no_se_verifico_no_vale():
    # Existe en los fragmentos, pero el modelo no la copió.
    assert draft_problems("Se reinicia [control/pid.py:61].", VERIFIED, CONTEXT) == ["[control/pid.py:61]"]


def test_una_etiqueta_entre_comillas_invertidas_se_trata_como_etiqueta():
    assert draft_problems("Está en `[control/pid.py:41]`.", VERIFIED, CONTEXT) == []


def test_las_palabras_normales_no_son_identificadores():
    assert draft_problems("El filtro de secretos corre antes del envío, según Ollama y JSON.", VERIFIED, CONTEXT) == []


def test_un_nombre_de_producto_no_es_un_identificador():
    # Medido con el 7B: invalidaba la respuesta correcta de jarvis.bat.
    assert draft_problems("Ejecuta este comando en PowerShell y luego en ChromaDB.", VERIFIED, CONTEXT) == []


def test_una_llamada_sin_argumentos_nombra_lo_que_el_codigo_llama_con_ellos():
    # Medido con el 7B: `os.replace()` en la redacción, os.replace(tmp, path) en el código.
    context = CONTEXT + "\n--- [a.py:1-3] ---\nFuente: x (proyecto)\nContenido:\na.py\nos.replace(tmp, path)\n"

    assert draft_problems("Reemplaza con `os.replace()` y listo.", VERIFIED, context) == []
    assert "os.rename()" in draft_problems("Reemplaza con `os.rename()` y listo.", VERIFIED, context)


def test_con_nombres_inventados_solo_se_muestran_las_lineas():
    brain = brain_with(QUOTED, "La ganancia se calcula con `calcula_pid()` [control/pid.py:41].")

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer == (
        "Estas son las líneas que responden; no incluyo explicación porque mencionaba nombres que no aparecen en tu código."
        f"\n\n{prompts.VERIFIED_LINES}\n\ncontrol/pid.py:41 (Pid.salida)\n  self.kp   =   2.5"
    )
    assert "calcula_pid" not in answer


@pytest.mark.parametrize(
    "answer",
    [
        "",
        "drop_client",
        "[providers/ollama_provider.py:83] drop_client",
        "[core/atomic_write.py:11] import tempfile",
        "[a.py:1] def drop_client(owner):",
        "[a.py:1] self.kp = 2.5",
        "[a.py:1] return self.kp * self.error + self.ki",
        "`self.kp = 2.5`",
        "```python\nimport os\n```",
    ],
)
def test_redaccion_casi_vacia(answer):
    assert is_thin(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "La ganancia es 2 [control/pid.py:41].",
        "La función `drop_client` se define en [a.py:130].",
        "[core/interruptible.py:1] Llamadas al modelo que Ctrl+C corta al momento.",
        "Los pasos son estos:\n1. Abre el archivo.\n2. Guarda.",
        "Si no hay conexión, reintenta tres veces.",
    ],
)
def test_una_frase_no_es_casi_vacia(answer):
    assert not is_thin(answer)


def test_redaccion_casi_vacia_se_trata_como_ninguna():
    brain = brain_with(QUOTED, "[control/pid.py:41] self.kp = 2.5")

    answer = brain.process("/buscar qué ganancia tiene")

    assert answer.startswith(prompts.NO_DIRECT_ANSWER)
    assert prompts.VERIFIED_LINES not in answer


def test_una_respuesta_parcial_se_conserva():
    answer = brain_with(QUOTED, "Está kp, pero no se dice cuánto vale ki [control/pid.py:41].").process("/buscar qué ganancia")

    assert answer.startswith("Está kp") and prompts.VERIFIED_LINES in answer


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


def hit(coverage, distance=None):
    return Hit("doc", {}, coverage=coverage, distance=distance)


def test_tambien_pasa_si_un_fragmento_esta_muy_cerca():
    # Medido en Bolitabot: el código dice x_front, la pregunta "punto desplazado".
    assert relevant([hit(0.19, 391.5)], 0.3, 392.0)
    assert not relevant([hit(0.19, 392.5)], 0.3, 392.0)


def test_una_cobertura_suficiente_no_necesita_distancia():
    assert relevant([hit(0.5, 490.0)], 0.3, 392.0)


def test_un_fragmento_que_solo_salio_por_palabras_no_tiene_distancia():
    assert not relevant([hit(0.1, None)], 0.3, 392.0)


def test_sin_umbral_de_distancia_solo_cuenta_la_cobertura():
    assert not relevant([hit(0.1, 1.0)], 0.3)


def test_el_umbral_de_distancia_viene_de_config(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [hit(0.1, 300.0)])

    assert RagTool().search_project("algo", "asia") != NOT_FOUND

    monkeypatch.setattr("tools.rag_tool.SettingsManager", lambda: {"rag": {"max_distance": 200.0}})

    assert RagTool().search_project("algo", "asia") == NOT_FOUND


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
