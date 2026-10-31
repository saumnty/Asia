"""/revisar memoria: reglas, modelo simulado y confirmación uno por uno, con memoria temporal."""
import json

import pytest

import launcher
from core.brain import REVIEW_ONLY_INTERACTIVE
from core.commands import COMMANDS, options_text
from core.memory_review import (
    CONTRADICTION,
    DUPLICATE,
    Proposal,
    find_proposals,
    parse_model_answer,
    rule_proposals,
)
from memory.memory_manager import MemoryManager
from test_confidencial import make_brain
from test_launcher import FakeBrain, reader


class ModelRouter:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def get_provider(self, name):
        return self

    def complete(self, messages, max_tokens=None):
        self.prompts.append(messages[0]["content"])

        if isinstance(self.answer, Exception):
            raise self.answer

        return self.answer

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        return "respuesta"


def session(tmp_path, data, model_answer="[]", **settings):
    brain = FakeBrain("hecho", **settings)
    brain.memory = MemoryManager(tmp_path / "memory.json")
    brain.memory.save(data)
    brain.provider_router = ModelRouter(model_answer)
    return brain


def review_prompts(brain):
    """Sin el resumen de la sesión, que también pasa por el modelo simulado."""
    return [p for p in brain.provider_router.prompts if "Revisa estas entradas" in p]


def run(brain, lines, command="/revisar memoria"):
    launcher.interactive_mode(brain, read=reader([command, *lines, "salir"]))
    return brain.memory.load()


# --- Detectar ----------------------------------------------------------------------

def test_clave_casi_igual_con_el_mismo_valor_es_duplicada():
    assert rule_proposals({"color_favorito": "Amarillo", "mi color favorito": "amarillo"}) == [
        Proposal("color_favorito", "mi color favorito", DUPLICATE)
    ]


def test_clave_casi_igual_con_otro_valor_es_contradictoria():
    assert rule_proposals({"universidad": "UAM", "mi_universidad": "UNAM"}) == [
        Proposal("universidad", "mi_universidad", CONTRADICTION)
    ]


def test_un_valor_dentro_del_otro_no_es_contradiccion():
    memory = {"universidad": "Universidad Autónoma Metropolitana (UAM)", "la_universidad": "UAM"}

    assert rule_proposals(memory)[0].kind == DUPLICATE


def test_mismo_valor_con_claves_distintas_es_duplicada():
    assert rule_proposals({"nombre": "Santiago", "apodo": "santiago"})[0].kind == DUPLICATE


def test_datos_distintos_no_dan_nada():
    memory = {"nombre": "Santiago", "proyecto": "Asia", "universidad": "UAM", "color_favorito": "amarillo"}

    assert rule_proposals(memory) == []


def test_del_modelo_solo_valen_claves_que_existen():
    memory = {"ciudad": "CDMX", "vivo_en": "Puebla"}
    answer = """Claro: [{"a": "ciudad", "b": "vivo_en", "tipo": "contradictoria"},
                {"a": "ciudad", "b": "inventada", "tipo": "duplicada"},
                {"a": "ciudad", "b": "ciudad", "tipo": "duplicada"},
                {"a": "ciudad", "b": "vivo_en", "tipo": "rara"}, "basura"]"""

    assert parse_model_answer(answer, memory) == [Proposal("ciudad", "vivo_en", CONTRADICTION)]


@pytest.mark.parametrize("answer", ["", "no hay", "[roto", '{"a": 1}', None])
def test_una_respuesta_rara_del_modelo_no_da_nada(answer):
    assert parse_model_answer(answer, {"a": 1, "b": 2}) == []


def test_reglas_y_modelo_sin_repetir_el_par():
    memory = {"universidad": "UAM", "mi_universidad": "UNAM", "ciudad": "CDMX", "vivo_en": "Puebla"}
    answer = json.dumps([
        {"a": "mi_universidad", "b": "universidad", "tipo": "contradictoria"},
        {"a": "ciudad", "b": "vivo_en", "tipo": "contradictoria"},
    ])

    found, used = find_proposals(memory, lambda messages: answer, 5)

    assert used is True
    assert [(p.first, p.second) for p in found] == [("universidad", "mi_universidad"), ("ciudad", "vivo_en")]


def test_si_el_modelo_falla_quedan_las_reglas():
    def broken(messages):
        raise ConnectionError

    found, used = find_proposals({"universidad": "UAM", "mi_universidad": "UNAM"}, broken, 5)

    assert len(found) == 1 and used is False


# --- Confirmar uno por uno ---------------------------------------------------------

MEMORY = {"universidad": "UAM", "mi_universidad": "UNAM", "color": "azul", "color_": "azul"}


def test_cada_cambio_necesita_confirmacion(tmp_path, capsys):
    brain = session(tmp_path, dict(MEMORY))

    assert run(brain, ["2", "1"]) == {"universidad": "UAM", "color_": "azul"}

    out = capsys.readouterr().out
    assert "1 de 2. Entradas contradictorias:" in out and "2 de 2. Entradas duplicadas:" in out
    assert "2. mi_universidad: UNAM" in out and "Revisión terminada: 2 entradas borradas." in out


@pytest.mark.parametrize("answers", [["n", "n"], ["", ""], ["sí", "ok"], ["borra", "todo"]])
def test_sin_un_1_o_un_2_no_cambia_nada(tmp_path, answers):
    assert run(session(tmp_path, dict(MEMORY)), answers) == MEMORY


def test_s_termina_y_no_toca_el_resto(tmp_path):
    assert run(session(tmp_path, dict(MEMORY)), ["s"]) == MEMORY


def test_el_modelo_nunca_cambia_nada_por_si_solo(tmp_path):
    answer = json.dumps([{"a": "ciudad", "b": "vivo_en", "tipo": "contradictoria"}])
    memory = {"ciudad": "CDMX", "vivo_en": "Puebla"}
    brain = session(tmp_path, dict(memory), answer)

    assert run(brain, ["n"], "/revisar memoria a fondo") == memory
    assert "CDMX" in brain.provider_router.prompts[0]


@pytest.mark.parametrize("command", ["/revisar memoria", "revisa la memoria"])
def test_por_defecto_no_usa_el_modelo(tmp_path, capsys, command):
    brain = session(tmp_path, dict(MEMORY))

    run(brain, ["n", "n"], command)

    assert review_prompts(brain) == []
    # Solo avisa si se pidió a fondo y el modelo no estuvo.
    assert "Revisé solo con reglas" not in capsys.readouterr().err


@pytest.mark.parametrize("command", ["/revisar memoria a fondo", "revisa la memoria a fondo"])
def test_a_fondo_pregunta_al_modelo(tmp_path, command):
    answer = json.dumps([{"a": "ciudad", "b": "vivo_en", "tipo": "contradictoria"}])
    brain = session(tmp_path, {"ciudad": "CDMX", "vivo_en": "Puebla"}, answer)

    run(brain, ["n"], command)

    assert len(review_prompts(brain)) == 1


def test_ctrl_c_en_la_pregunta_termina_sin_cambiar_nada(tmp_path, capsys):
    brain = session(tmp_path, dict(MEMORY))
    lines = iter(["/revisar memoria", KeyboardInterrupt, "salir"])

    def read(prompt):
        line = next(lines)

        if line is KeyboardInterrupt:
            raise KeyboardInterrupt

        return line

    launcher.interactive_mode(brain, read=read)

    assert brain.memory.load() == MEMORY
    assert "Revisión terminada: 0 entradas borradas." in capsys.readouterr().out


def test_si_una_ya_se_borro_no_pregunta_por_ella(tmp_path, capsys):
    data = {"color": "azul", "color_": "azul", "colorr": "azul"}

    remaining = run(session(tmp_path, data), ["2", "1"])

    assert remaining == {"colorr": "azul"}
    assert "Revisión terminada: 2 entradas borradas." in capsys.readouterr().out


def test_sin_casos_lo_dice(tmp_path, capsys):
    run(session(tmp_path, {"nombre": "Santiago"}), [])

    assert "No encontré entradas duplicadas ni contradictorias." in capsys.readouterr().out


def test_ollama_en_otra_maquina_no_recibe_la_memoria(tmp_path, capsys):
    brain = session(tmp_path, dict(MEMORY), ollama_host="http://10.0.0.9:11434")

    run(brain, ["n", "n"], "/revisar memoria a fondo")

    assert brain.provider_router.prompts == []
    assert "Revisé solo con reglas" in capsys.readouterr().err


def test_fuera_del_modo_interactivo_lo_explica():
    assert make_brain().process("/revisar memoria") == REVIEW_ONLY_INTERACTIVE
    assert make_brain().process("revisa la memoria") == REVIEW_ONLY_INTERACTIVE
    assert make_brain().process("/revisar memoria a fondo") == REVIEW_ONLY_INTERACTIVE


def test_en_la_tabla_de_opciones():
    assert any(c.slash == "/revisar memoria" and c.group == "memoria" for c in COMMANDS)
    assert any(c.slash == "/revisar memoria a fondo" and c.group == "memoria" for c in COMMANDS)
    assert "/revisar memoria" in options_text() and "/revisar memoria a fondo" in options_text()
