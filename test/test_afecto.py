"""Núcleo afectivo, versión 0 (core/afecto): estimación, suavizado, política, comandos y que nunca sale."""
import json
from datetime import datetime, timedelta

import pytest

import launcher
from config.settings_manager import SettingsManager
from core.actions.affect import affect_command
from core.afecto import AFFECT_SETTING, AffectCore, affect_enabled
from core.afecto.estado import Estimate, State, faded, smoothed
from core.afecto.estimacion import estimate_prompt, parse_estimate
from core.afecto.nucleo import is_correction
from core.afecto.politica import ASK, CALM, LIVELY, LOW, NEUTRAL, TENSE, instruction, style, zone
from test_confidencial import FakeProvider, make_brain

NOW = datetime(2026, 11, 4, 18, 0, 0)


def answer(valence, arousal, label="frustrado", confidence=0.8):
    return json.dumps({"valencia": valence, "activacion": arousal, "etiqueta": label, "importancia": 0.7,
                       "bloqueo": 0.6, "control": 0.3, "urgencia": 0.5, "confianza": confidence})


def fake_ask(reply):
    asked = []

    def ask(prompt, domain="code", max_tokens=None):
        asked.append((prompt, domain, max_tokens))
        return reply

    ask.asked = asked
    return ask


# --- Estimación -------------------------------------------------------------------

def test_lee_el_json_y_acota_los_valores():
    found = parse_estimate("Claro: " + answer(-1.7, 0.6) + " listo")

    assert (found.valence, found.arousal, found.label, found.confidence) == (-1.0, 0.6, "frustrado", 0.8)
    assert found.appraisal == {"importancia": 0.7, "bloqueo": 0.6, "control": 0.3, "urgencia": 0.5}


def test_sin_json_no_hay_confianza():
    assert parse_estimate("no sé").confidence == 0.0 and parse_estimate("{roto").confidence == 0.0


def test_el_prompt_es_corto_y_fijo():
    prompt = estimate_prompt("estoy harto")

    assert prompt.endswith("Mensaje:\nestoy harto") and len(prompt) < 900


# --- Suavizado ------------------------------------------------------------------------

def test_sin_estado_anterior_vale_la_estimacion():
    state = smoothed(State(), Estimate(-0.6, 0.5, "frustrado", {}, 0.8), NOW, 3.0)

    assert (state.valence, state.arousal, state.confidence) == (-0.6, 0.5, 0.8)
    assert state.updated == "2026-11-04T18:00:00"


def test_el_estado_viejo_se_desvanece_con_las_horas():
    old = State(-0.8, 0.6, 0.8, "frustrado", {}, (NOW - timedelta(hours=3)).isoformat())

    assert faded(old, NOW, 3.0).confidence == pytest.approx(0.4)
    # Un mensaje contento, con el enojo de hace 3 horas a la mitad.
    state = smoothed(old, Estimate(0.6, 0.4, "contento", {}, 0.8), NOW, 3.0)
    assert state.valence == pytest.approx((0.4 * -0.8 + 0.8 * 0.6) / 1.2, abs=1e-3) and state.label == "contento"


def test_un_mensaje_sin_senal_apenas_mueve_el_estado():
    old = State(-0.8, 0.6, 0.8, "frustrado", {}, NOW.isoformat())

    state = smoothed(old, Estimate(0.0, 0.0, "neutral", {}, 0.05), NOW, 3.0)

    assert state.valence < -0.7 and state.label == "frustrado"


# --- Política ---------------------------------------------------------------------------

@pytest.mark.parametrize("valence, arousal, expected", [
    (-0.7, 0.6, TENSE), (-0.6, -0.4, LOW), (0.7, 0.6, LIVELY), (0.6, -0.3, CALM), (0.1, 0.8, NEUTRAL),
])
def test_las_zonas(valence, arousal, expected):
    assert zone(State(valence, arousal, 0.8)) == expected


def test_con_poca_confianza_pregunta():
    assert style(State(-0.5, 0.5, 0.2)) == ASK and "desahogarse o resolverlo" in instruction(State(-0.5, 0.5, 0.2))


def test_cada_estilo_su_instruccion():
    assert "valida primero" in instruction(State(-0.7, 0.6, 0.8)) and "un solo paso" in instruction(State(-0.7, 0.6, 0.8))
    assert "pregunta antes de proponer" in instruction(State(-0.6, -0.4, 0.8))
    assert "Acompaña su energía" in instruction(State(0.7, 0.6, 0.8))
    assert instruction(State(0.6, -0.3, 0.8)) == "" and instruction(State(0.0, 0.0, 0.9)) == ""


# --- AffectCore ----------------------------------------------------------------------------

def core_at(tmp_path, **afecto):
    settings = {"afecto": {"activo": True, "vida_media_horas": 3, **afecto}}
    return AffectCore(type("S", (), {"get": lambda self, key, default=None: settings.get(key, default)})(),
                      path=tmp_path / "afecto" / "estado.json", now=lambda: NOW)


def test_observa_y_guarda_en_local(tmp_path):
    core = core_at(tmp_path)
    ask = fake_ask(answer(-0.7, 0.6))

    state = core.observe("ya van tres horas con este error y nada funciona", ask)

    assert zone(state) == TENSE and ask.asked[0][1] == "general"
    assert json.loads((tmp_path / "afecto" / "estado.json").read_text(encoding="utf-8"))["valence"] == -0.7


def test_la_correccion_reemplaza_la_estimacion(tmp_path):
    core = core_at(tmp_path)
    core.observe("ya van tres horas con este error", fake_ask(answer(-0.7, 0.6)))

    state = core.correct("no, solo estoy concentrado", fake_ask(answer(0.1, 0.3, "concentrado", 0.5)))

    assert state.corrected and state.label == "concentrado" and state.confidence == 0.9
    assert "lo que me dijiste" in core.describe(core.state())


def test_borrar_el_estado(tmp_path):
    core = core_at(tmp_path)
    core.observe("estoy harto", fake_ask(answer(-0.7, 0.6)))

    assert core.clear() and not core.clear() and core.state() == State()
    assert core.describe(core.state()) == "No tengo ninguna estimación de tu estado."


@pytest.mark.parametrize("text, expected", [
    ("no, solo estoy concentrado", True),
    ("no estoy enojado, estoy cansado", True),
    ("en realidad estoy bien", True),
    ("no, estoy usando Python 3.11", False),
    ("estoy concentrado en el PID", False),
])
def test_la_correccion_del_usuario(text, expected):
    assert is_correction(text) is expected


def test_apagado_por_defecto_y_por_sesion():
    assert not affect_enabled(SettingsManager())

    SettingsManager.set_overrides({AFFECT_SETTING: True})
    assert affect_enabled(SettingsManager())
    assert affect_command("no, solo estoy concentrado", SettingsManager()) == "corregir"

    SettingsManager.set_overrides({})
    assert affect_command("no, solo estoy concentrado", SettingsManager()) is None


# --- En el chat ------------------------------------------------------------------------------

class AffectOllama(FakeProvider):
    """Contesta el JSON a la estimación y texto al chat."""

    def __init__(self, estimate_reply):
        super().__init__("ollama")
        self.estimate_reply = estimate_reply

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False, max_tokens=None):
        if "Estima cómo se siente" in messages[-1]["content"]:
            self.received.append(messages)
            return self.estimate_reply

        return super().complete(messages, on_chunk, review, model, think, max_tokens)


@pytest.fixture
def affect_brain(tmp_path, monkeypatch):
    from core import paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    SettingsManager.set_overrides({AFFECT_SETTING: True, "default_provider": "gemini"})
    brain = make_brain()
    brain.provider_router.providers["ollama"] = AffectOllama(answer(-0.7, 0.6))
    return brain


def test_el_tono_va_al_final_del_mensaje_y_solo_en_local(affect_brain, capsys):
    launcher.respond(affect_brain, "ya van tres horas con este error y nada funciona")

    router = affect_brain.provider_router
    chat = router.providers["ollama"].received[-1]
    assert "valida primero" in chat[-1]["content"] and chat[-1]["content"].rstrip().endswith("]")
    # Con gemini por defecto: el turno es emocional y no sale, ni la estimación.
    assert router.providers["gemini"].received == []
    assert "emocional" in router.history_labels


def test_apagado_no_estima_ni_cambia_el_prompt(affect_brain):
    SettingsManager.set_overrides({"default_provider": "ollama"})

    launcher.respond(affect_brain, "ya van tres horas con este error")

    received = affect_brain.provider_router.providers["ollama"].received
    assert len(received) == 1 and "Tono para esta respuesta" not in received[0][-1]["content"]


def test_estado_muestra_la_hipotesis(affect_brain):
    launcher.respond(affect_brain, "ya van tres horas con este error y nada funciona")

    shown = affect_brain.process("muestra el estado")

    assert "Hipótesis" in shown and "frustrado" in shown and "desagradable y agitado" in shown


# --- check_afecto, con modelo simulado ----------------------------------------------

def test_check_afecto_cuenta_aciertos_y_estilos(tmp_path, capsys):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent / "manual"))
    import check_afecto

    replies = {TENSE: answer(-0.7, 0.6), LOW: answer(-0.6, -0.5), LIVELY: answer(0.8, 0.7),
               CALM: answer(0.6, -0.4), NEUTRAL: answer(0.0, 0.0, "neutral", 0.1)}
    by_text = {text: replies[expected] for expected, text in check_afecto.CASES}

    rows = check_afecto.measure(lambda prompt, domain="code", max_tokens=None: by_text[prompt.rsplit("\n", 1)[-1]], tmp_path)
    check_afecto.report(rows)

    assert len(rows) == 28 and all(row["acierto"] for row in rows)
    assert {row["estilo"] for row in rows if row["esperada"] == NEUTRAL} == {NEUTRAL}
    assert "Total: 28/28" in capsys.readouterr().out


def test_los_comandos_con_barra(affect_brain):
    assert "No tengo ninguna estimación" in affect_brain.process("/estado")
    assert "desactivado" in affect_brain.process("/afecto off") and not affect_enabled(SettingsManager())
    assert "activado" in affect_brain.process("/afecto on") and affect_enabled(SettingsManager())
    assert "No había" in affect_brain.process("/afecto borrar")


def test_con_el_7b_estima_con_el_7b_sin_recargar_qwen3(affect_brain):
    from core.model_selection import model_for

    ollama = affect_brain.provider_router.providers["ollama"]
    models = []
    complete = ollama.complete
    ollama.complete = lambda messages, **options: models.append(options.get("model")) or complete(messages, **options)
    SettingsManager.set_overrides({**SettingsManager.overrides, "forced_domain": "code"})

    launcher.respond(affect_brain, "ya van tres horas con este error y nada funciona")

    # La estimación y la respuesta, con el mismo modelo: el de código.
    assert models == [model_for(SettingsManager(), "code")] * 2
