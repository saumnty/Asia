"""Frases de la redacción: cada una lleva su etiqueta y se comprueba contra sus propias líneas."""
import pytest

from core import prompts
from core.rag.quotes import (
    BAD_TAG,
    NOT_DEFINED,
    UNKNOWN_FIGURE,
    UNKNOWN_NAME,
    Quote,
    check_draft,
    draft_sentences,
    sentence_problems,
)
from test_rag_answer import QUOTED, brain_with

KP = Quote("control/pid.py", 41, "Pid.salida", "    self.kp   =   2.5")
ERROR = Quote("control/pid.py", 61, "Pid.reinicia", "    self.error = 0")
VERIFIED = [KP, ERROR]


def kinds(sentence, quotes=VERIFIED):
    return {kind for kind, _ in sentence_problems(sentence, quotes)}


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("Uno [a.py:1]. Dos [a.py:2].", ["Uno [a.py:1].", "Dos [a.py:2]."]),
        ("Uno. [a.py:1] Dos. [a.py:2]", ["Uno [a.py:1].", "Dos [a.py:2]."]),
        ("Uno. [a.py:1] [a.py:2] Dos.", ["Uno [a.py:1] [a.py:2].", "Dos."]),
        ("Uno.\n[a.py:1]\nDos.", ["Uno\n[a.py:1].", "Dos."]),
        ("La línea [a.py:1] dice algo. Dos.", ["La línea [a.py:1] dice algo.", "Dos."]),
        ("Vale 0.7 m/s [a.py:1]. Dos.", ["Vale 0.7 m/s [a.py:1].", "Dos."]),
        ("1. Abre [a.py:1].\n2. Guarda [a.py:2].", ["1. Abre [a.py:1].", "2. Guarda [a.py:2]."]),
        ("La ganancia es 2. Luego sube.", ["La ganancia es 2.", "Luego sube."]),
        ("- Uno. Dos.", ["- Uno.", "Dos."]),
        ("Usa esto:\n```bash\nls. -a\n```\n[a.py:1]\nDos.", ["Usa esto:\n```bash\nls. -a\n```\n[a.py:1]", "Dos."]),
    ],
)
def test_frases(answer, expected):
    assert draft_sentences(answer) == expected


@pytest.mark.parametrize(
    "sentence",
    [
        "La ganancia es 2.5 [control/pid.py:41].",
        "La ganancia es 2.5 [control/pid.py:40-41].",
        "La ganancia es 2.5 [control/pid.py:41–42].",
        "Se reinicia a 0 [control/pid.py:61].",
        "Lo dice `control/pid.py:41` con `self.kp   =   2.5`.",
        "Está en `salida` [control/pid.py:41].",
        "Lo cuenta self.kp, en la línea 41 [control/pid.py:41].",
        "Un ejemplo [control/pid.py:41]:\n```python\nself.kp = 2.5\n```",
        "Lo cita a mano en PowerShell con JSON [control/pid.py:41].",
    ],
)
def test_una_frase_que_coincide_con_su_linea_vale(sentence):
    assert sentence_problems(sentence, VERIFIED) == []


def test_una_cita_sin_linea_vale_con_su_archivo():
    assert sentence_problems("Lo dice uno [viejo.py].", [Quote("viejo.py", None, "", "uno")]) == []


@pytest.mark.parametrize(
    "sentence, kind",
    [
        ("La ganancia es 2.5.", BAD_TAG),
        ("La ganancia es 2.5 [control/pid.py:50].", BAD_TAG),
        ("La ganancia es 2.5 [otro.py:41].", BAD_TAG),
        ("La ganancia es 2.5 [control/pid.py:41] y sale de [control/pid.py:50].", BAD_TAG),
        ("Se calcula con `calcula_pid()` [control/pid.py:41].", UNKNOWN_NAME),
        ("Se calcula con calcula_pid [control/pid.py:41].", UNKNOWN_NAME),
        ("Se calcula con calculaPid [control/pid.py:41].", UNKNOWN_NAME),
        ("Está en [otro.py] [control/pid.py:41].", UNKNOWN_NAME),
        ('Se abre en modo "w" [control/pid.py:41].', UNKNOWN_FIGURE),
        ("Un ejemplo [control/pid.py:41]:\n```python\ndef otra():\n```", UNKNOWN_NAME),
        ("La ganancia es 3.5 [control/pid.py:41].", UNKNOWN_FIGURE),
        ("Se repite cada 2.5 segundos [control/pid.py:41].", UNKNOWN_FIGURE),
        ("`salida` se define en [control/pid.py:41].", NOT_DEFINED),
    ],
)
def test_una_frase_que_no_coincide_con_su_linea_no_vale(sentence, kind):
    assert kind in kinds(sentence)


def test_los_nombres_se_comprueban_contra_sus_lineas_y_no_contra_las_demas():
    # self.error existe en los fragmentos y está verificada, pero esta frase cita otra línea.
    assert kinds("Usa `self.error` [control/pid.py:41].") == {UNKNOWN_NAME}
    assert kinds("Usa `self.error` [control/pid.py:61].") == set()


def test_los_numeros_se_comprueban_contra_sus_lineas():
    assert kinds("El valor es 0 [control/pid.py:41].") == {UNKNOWN_FIGURE}


def test_la_unidad_vale_si_la_dice_la_linea():
    seconds = [Quote("a.py", 1, "", "ESPERA = 3  # segundos"), Quote("a.py", 2, "", "timeout_s = 3")]

    assert sentence_problems("Espera 3 segundos [a.py:1].", seconds) == []
    assert sentence_problems("Espera 3 segundos [a.py:2].", seconds) == []


def test_una_definicion_vale_en_la_linea_que_define():
    lines = [
        Quote("a.py", 1, "", "def drop_client(owner):"),
        Quote("a.py", 2, "", "class Pid:"),
        Quote("a.py", 3, "", "v_max = 0.7;"),
        Quote("a.yaml", 1, "", "ros_topic_name: chatter"),
    ]

    assert sentence_problems("`drop_client()` se define aquí [a.py:1].", lines) == []
    assert sentence_problems("La clase `Pid` está definida aquí [a.py:2].", lines) == []
    assert sentence_problems("El límite está definido en v_max [a.py:3].", lines) == []
    assert sentence_problems("Se define `ros_topic_name` [a.yaml:1].", lines) == []


# Los tres casos reales: lo que el 7B escribió, contra las líneas reales del repositorio.
CLOSE = Quote("core/atomic_write.py", 3, "", 'open(ruta, "w") vacía el archivo al abrirlo; si el proceso se interrumpe a')
WRITE = Quote("core/atomic_write.py", 15, "", "def write_text_atomic(path, text: str, encoding=\"utf-8\"):")
CALL = Quote("providers/ollama_provider.py", 83, "OllamaProvider.chat", "        drop_client(self)")
IDLE = Quote("core/reflection.py", 35, "", "DEFAULT_SUMMARY_IDLE = 3")


def test_el_modo_w_sin_cita_no_pasa():
    assert kinds('Para escribir un archivo sin dejarlo a medias, debes abrirlo con el modo "w".', [CLOSE]) == {BAD_TAG}


def test_el_modo_w_citando_otra_linea_no_pasa_limpio():
    assert UNKNOWN_FIGURE in kinds('Debes abrirlo con el modo "w" [core/atomic_write.py:15].', [WRITE])


def test_el_modo_w_citando_la_linea_que_lo_nombra_si_pasa():
    # El límite: la línea dice lo contrario, pero el código no entiende frases, solo nombres.
    assert kinds('Debes abrirlo con el modo "w" [core/atomic_write.py:3].', [CLOSE]) == set()


def test_una_llamada_no_es_una_definicion():
    sentence = "La función `drop_client` se define en el archivo `providers/ollama_provider.py` [providers/ollama_provider.py:83]."

    assert kinds(sentence, [CALL]) == {NOT_DEFINED}


def test_una_mencion_de_la_llamada_si_pasa():
    assert kinds("Aquí se llama a `drop_client` [providers/ollama_provider.py:83].", [CALL]) == set()


def test_cada_3_segundos_no_pasa():
    assert kinds("El resumen se actualiza cada 3 segundos [core/reflection.py:35].", [IDLE]) == {UNKNOWN_FIGURE}


def test_el_numero_sin_unidad_si_pasa():
    assert kinds("El valor por defecto es 3 [core/reflection.py:35].", [IDLE]) == set()


DRAFT = (
    "La ganancia es 2.5 [control/pid.py:41]. Además es muy estable. Vale 9 [control/pid.py:41]. "
    "Lo calcula `calcula_pid` [control/pid.py:41]."
)


def test_solo_se_elimina_un_nombre_que_no_esta_en_sus_lineas():
    shown, uncited, removed = check_draft(DRAFT, VERIFIED)

    assert shown == [
        "La ganancia es 2.5 [control/pid.py:41].",
        "Además es muy estable. (sin cita)",
        "Vale 9 [control/pid.py:41]. (sin cita)",
    ]
    assert [sentence for sentence, _ in uncited] == ["Además es muy estable.", "Vale 9 [control/pid.py:41]."]
    assert [sentence for sentence, _ in removed] == ["Lo calcula `calcula_pid` [control/pid.py:41]."]


@pytest.mark.parametrize(
    "sentence",
    [
        "Sale de una etiqueta rara [69].",
        "Sale de otra línea [control/pid.py:90].",
        'Muestra "Guardando resumen" [control/pid.py:41].',
        "`salida` se define aquí [control/pid.py:41].",
    ],
)
def test_lo_dudoso_se_muestra_marcado(sentence):
    assert check_draft(sentence, VERIFIED)[0] == [f"{sentence} (sin cita)"]


def test_la_marca_de_un_bloque_de_codigo_va_debajo():
    assert check_draft("Usa esto:\n```\nself.kp = 2.5\n```", VERIFIED)[0] == ["Usa esto:\n```\nself.kp = 2.5\n```\n(sin cita)"]


def test_sin_etiqueta_un_nombre_inventado_se_elimina():
    assert check_draft("Lo calcula `calcula_pid`.", VERIFIED)[0] == []
    assert check_draft("Lo calcula calcula_pid.", VERIFIED)[0] == []


def test_sin_etiqueta_un_nombre_de_las_lineas_verificadas_se_muestra_marcado():
    assert check_draft("Lo usa `self.error`.", VERIFIED)[0] == ["Lo usa `self.error`. (sin cita)"]


def test_con_una_etiqueta_mala_un_nombre_inventado_se_elimina():
    assert check_draft("Lo calcula `calcula_pid` [control/pid.py:90].", VERIFIED)[0] == []


@pytest.mark.parametrize(
    "tag",
    ["[README.md:289, 290]", "[README.md:289,290]", "[README.md:1, 289-290]", "`README.md:289, 290`", "[README.md:289–290, 400]"],
)
def test_etiquetas_con_varias_lineas(tag):
    lines = [Quote("README.md", 289, "", "topic_name: chatter"), Quote("README.md", 290, "", "ros_type: x")]

    assert sentence_problems(f"Usa `topic_name` y `ros_type` {tag}.", lines) == []


def test_las_varias_lineas_se_cuentan_una_a_una():
    lines = [Quote("README.md", 289, "", "topic_name: chatter"), Quote("README.md", 300, "", "ros_type: x")]

    assert sentence_problems("Usa `ros_type` [README.md:289, 290].", lines) == [(UNKNOWN_NAME, "ros_type")]


def test_una_etiqueta_con_varias_lineas_sigue_a_su_frase():
    assert draft_sentences("Uno. [a.py:1, 2] Dos.") == ["Uno [a.py:1, 2].", "Dos."]


def test_primero_las_lineas_y_despues_el_resumen():
    answer = brain_with(QUOTED, "La ganancia es 2.5 [control/pid.py:41]. Además es muy estable.").process("/buscar qué ganancia")

    assert answer.index(prompts.VERIFIED_LINES) < answer.index(prompts.UNVERIFIED_SUMMARY)
    assert answer.endswith(
        f"{prompts.UNVERIFIED_SUMMARY}\n\nLa ganancia es 2.5 [control/pid.py:41].\nAdemás es muy estable. (sin cita)"
    )


def test_el_titulo_es_el_pedido():
    assert prompts.UNVERIFIED_SUMMARY == "Resumen del modelo (no verificado)"


def test_sin_frases_validas_por_un_nombre_solo_se_muestran_las_lineas_con_el_aviso():
    answer = brain_with(QUOTED, "La ganancia se calcula con `calcula_pid()` [control/pid.py:41].").process("/buscar qué ganancia")

    assert answer == (
        "Estas son las líneas que responden; no incluyo explicación porque mencionaba nombres que no aparecen en tu código."
        f"\n\n{prompts.VERIFIED_LINES}\n\ncontrol/pid.py:41 (Pid.salida)\n  self.kp   =   2.5"
    )


def test_sin_etiquetas_todo_el_resumen_queda_marcado():
    answer = brain_with(QUOTED, "La ganancia del control es bastante alta.").process("/buscar qué ganancia")

    assert answer.endswith(f"{prompts.UNVERIFIED_SUMMARY}\n\nLa ganancia del control es bastante alta. (sin cita)")


def test_una_negativa_con_lineas_sigue_mostrando_los_fragmentos():
    answer = brain_with(QUOTED, "drop_client").process("/buscar qué ganancia")

    assert answer.startswith(prompts.NO_DIRECT_ANSWER)


def test_el_prompt_pide_la_etiqueta_tras_cada_frase():
    prompt = prompts.answer_from_quotes("qué ganancia", "[a.py:1] kp = 2")

    assert "Después de cada frase" in prompt and "se marcan como sin cita" in prompt


def test_una_respuesta_parcial_conserva_lo_que_tiene_etiqueta():
    answer = brain_with(QUOTED, "Está kp, pero no se dice cuánto vale ki [control/pid.py:41].").process("/buscar qué ganancia")

    assert "Está kp" in answer
