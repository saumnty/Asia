"""Ctrl+C en el modo interactivo: corta la respuesta o la lectura sin cerrar Asia."""
import signal

import pytest

import launcher
from config.settings_manager import SettingsManager
from core.provenance import USUARIO, Fragment, request_sources
from test_confidencial import make_brain
from test_launcher import FakeBrain, reader
from test_voice_input import session
from test_voice_reading import BlockingSpeaker


class CutRouter:
    """Escribe una frase y Ctrl+C llega mientras sigue escribiendo."""

    def __init__(self, presses=1):
        self.presses = presses
        self.calls = 0

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        self.calls += 1

        if self.calls > 1:
            on_chunk("segunda respuesta")
            return "segunda respuesta"

        on_chunk("Una frase. ")

        for _ in range(self.presses):
            signal.raise_signal(signal.SIGINT)

        on_chunk("El resto.")
        return "Una frase. El resto."


def brain_with(router, **settings):
    brain = FakeBrain(None, stream_output=True, **settings)
    brain.provider_router = router
    return brain


def test_sin_voz_corta_la_respuesta_y_vuelve_al_prompt(capsys):
    brain = brain_with(CutRouter())

    launcher.interactive_mode(brain, read=reader(["hola", "otra", "salir"]))

    out = capsys.readouterr()
    assert "(Respuesta cortada.)" in out.err
    assert "El resto." not in out.out and "segunda respuesta" in out.out
    assert out.out.rstrip().endswith("Asia apagada.")


def test_una_accion_tambien_se_corta(capsys):
    brain = FakeBrain("hecho")
    process = brain.process
    presses = iter([True])

    def interrupted(text):
        if next(presses, False):
            raise KeyboardInterrupt

        return process(text)

    brain.process = interrupted

    launcher.interactive_mode(brain, read=reader(["revisa todo", "otra", "salir"]))

    assert "(Respuesta cortada.)" in capsys.readouterr().err
    assert brain.processed == ["otra"]


def test_el_turno_cortado_no_queda_en_el_historial(capsys):
    class Interrupted:
        def complete(self, messages, on_chunk=None, **kwargs):
            on_chunk("Una frase. ")
            raise KeyboardInterrupt

    SettingsManager.set_overrides({})
    brain = make_brain()
    brain.provider_router.providers["ollama"] = Interrupted()

    with pytest.raises(KeyboardInterrupt), request_sources(Fragment(USUARIO, "hola")):
        brain.provider_router.chat("hola", on_chunk=lambda chunk: None)

    assert brain.provider_router.history == [] and brain.provider_router.history_labels == []


def test_con_voz_el_primero_corta_la_lectura_y_la_respuesta_sigue(capsys):
    voice, _ = session([])
    voice._speaker = speaker = BlockingSpeaker()
    brain = brain_with(CutRouter(), **{launcher.VOICE_SETTING: True})

    launcher.interactive_mode(brain, read=reader(["hola", "salir"]), voice=voice)

    out = capsys.readouterr()
    assert "(Lectura cortada.)" in out.err and "(Respuesta cortada.)" not in out.err
    assert "Una frase. El resto." in out.out


def test_con_voz_el_segundo_corta_la_respuesta(capsys):
    voice, _ = session([])
    voice._speaker = BlockingSpeaker()
    brain = brain_with(CutRouter(presses=2), **{launcher.VOICE_SETTING: True})

    launcher.interactive_mode(brain, read=reader(["hola", "salir"]), voice=voice)

    out = capsys.readouterr()
    assert "(Lectura cortada.)" in out.err and "(Respuesta cortada.)" in out.err
    assert "El resto." not in out.out


def test_una_sola_ejecucion_sigue_cerrando(capsys):
    brain = brain_with(CutRouter())

    with pytest.raises(KeyboardInterrupt):
        launcher.respond(brain, "hola")


def test_en_el_prompt_cierra_sin_preguntar(capsys):
    def read(prompt):
        raise KeyboardInterrupt

    launcher.interactive_mode(FakeBrain("hecho"), read=read)

    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")
