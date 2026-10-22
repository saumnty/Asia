import io

import pytest

import launcher
from core.attachments import STDIN_LABEL
from core.session import Session


class FakeSettings:
    def __init__(self, **values):
        self.values = {"attachment_max_chars": 1000, **values}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeRouter:
    def __init__(self):
        self.calls = []

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        self.calls.append({"prompt": prompt, "history": history_prompt})
        return "respuesta del chat"


class FakeBrain:
    """process devuelve None (chat) salvo que se le dé una respuesta."""

    def __init__(self, action_response=None, **settings):
        self.settings = FakeSettings(**settings)
        self.provider_router = FakeRouter()
        self.action_response = action_response
        self.processed = []

    def process(self, text):
        self.processed.append(text)
        return self.action_response


class FakeStdin:
    def __init__(self, data=b"", tty=False):
        self.buffer = io.BytesIO(data)
        self.tty = tty

    def isatty(self):
        return self.tty


TTY = FakeStdin(tty=True)


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    return tmp_path


def run(argv, stdin=TTY, brain=None):
    brain = brain or FakeBrain()
    launcher.main(argv, stdin=stdin, brain_factory=lambda: brain)
    return brain


def test_arroba_va_a_las_acciones_con_ruta_absoluta(cwd, capsys):
    brain = run(["revisa", "a", "fondo", "@a.py"], brain=FakeBrain("reporte"))

    assert brain.processed == [f"revisa a fondo {(cwd / 'a.py').resolve()}"]
    assert brain.provider_router.calls == []
    assert capsys.readouterr().out == "reporte\n"


def test_arroba_en_chat_lleva_el_contenido(cwd, capsys):
    brain = run(["explica", "@a.py"])

    call = brain.provider_router.calls[0]
    assert "x = 1" in call["prompt"]
    assert "x = 1" not in call["history"]
    assert capsys.readouterr().out == "respuesta del chat\n"


def test_file_se_puede_repetir_y_mezclar_con_el_mensaje(cwd):
    brain = run(["compara", "--file", "a.py", "estos", "-f", "b.py"])

    assert brain.processed == [
        f"compara estos {(cwd / 'a.py').resolve()} {(cwd / 'b.py').resolve()}"
    ]
    prompt = brain.provider_router.calls[0]["prompt"]
    assert "x = 1" in prompt and "y = 2" in prompt


def test_file_sin_mensaje_usa_instruccion_por_defecto(cwd):
    brain = run(["--file", "a.py"])

    assert brain.processed[0].startswith(launcher.DEFAULT_FILE_REQUEST)


def test_stdin_con_mensaje_es_adjunto_y_va_directo_al_chat(cwd):
    brain = run(["explica", "esto"], stdin=FakeStdin("def f(): pass\n".encode()))

    assert brain.processed == []
    prompt = brain.provider_router.calls[0]["prompt"]
    assert prompt.startswith("explica esto\n\nArchivos adjuntos:")
    assert f"--- {STDIN_LABEL} ---\ndef f(): pass\n" in prompt


def test_stdin_sin_mensaje_es_el_mensaje(cwd):
    brain = run([], stdin=FakeStdin("recuerda que mi color es azul".encode()))

    assert brain.processed == ["recuerda que mi color es azul"]


def test_stdin_vacio_sin_mensaje(cwd, capsys):
    brain = run([], stdin=FakeStdin(b""))

    assert brain.processed == []
    assert "No recibí ningún mensaje." in capsys.readouterr().err


def test_avisos_van_a_stderr(cwd, capsys):
    run(["explica", "@falta.py"])

    captured = capsys.readouterr()
    assert "No encontré el archivo adjunto: falta.py" in captured.err
    assert "No encontré" not in captured.out


def test_sin_argumentos_y_con_terminal_abre_el_modo_interactivo(cwd, monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "interactive_mode", lambda brain: opened.append(brain))

    brain = run([], stdin=TTY)

    assert opened == [brain]


def test_cwd_sigue_funcionando(cwd, capsys):
    brain = run(["donde", "estoy"])

    assert brain.processed == []
    assert str(cwd) in capsys.readouterr().out


def test_modo_interactivo_resuelve_arroba(cwd, capsys):
    brain = FakeBrain()
    lines = iter(["explica @a.py", "salir"])

    launcher.interactive_mode(brain, read=lambda prompt: next(lines))

    assert "x = 1" in brain.provider_router.calls[0]["prompt"]
    assert "Asia apagada." in capsys.readouterr().out
