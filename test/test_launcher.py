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


from config.settings_manager import SettingsManager


def test_flags_valen_solo_para_la_sesion(cwd):
    run(["--provider", "Olama", "--project", "BolitaBot", "--no-stream", "hola"])

    # Aliases de config/defaults.json: olama -> ollama, bolitabot -> pt.
    assert SettingsManager.overrides == {
        "default_provider": "ollama",
        "active_project": "pt",
        "stream_output": False,
    }


def test_sin_flags_no_hay_overrides(cwd):
    SettingsManager.set_overrides({"stream_output": False})

    run(["hola"])

    assert SettingsManager.overrides == {}


def test_provider_desconocido_es_error_de_uso(cwd, capsys):
    with pytest.raises(SystemExit) as error:
        run(["--provider", "openai", "hola"])

    assert error.value.code == 2
    assert "provider no disponible: openai (disponibles: ollama, gemini)" in capsys.readouterr().err


def test_no_stream_hace_que_respond_no_use_streaming(cwd):
    class StreamRouter(FakeRouter):
        def chat(self, prompt, on_chunk=None, history_prompt=None):
            self.calls.append({"stream": on_chunk is not None})
            return "ok"

    class SettingsBrain(FakeBrain):
        def __init__(self):
            super().__init__()
            self.settings = SettingsManager()
            self.provider_router = StreamRouter()

    brain = SettingsBrain()
    SettingsManager.set_overrides({"stream_output": True})
    launcher.respond(brain, "hola")

    run(["--no-stream", "hola"], brain=brain)

    assert brain.provider_router.calls == [{"stream": True}, {"stream": False}]


def reader(lines):
    lines = iter(lines)
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return next(lines)

    read.prompts = prompts
    return read


def test_multilinea_con_instruccion_es_adjunto_y_va_al_chat(cwd):
    brain = FakeBrain()
    read = reader(["explica esto <<", "def f():", "    return 1", "FIN", "salir"])

    launcher.interactive_mode(brain, read=read)

    assert brain.processed == []
    prompt = brain.provider_router.calls[0]["prompt"]
    assert "--- texto pegado ---\ndef f():\n    return 1\n--- fin de texto pegado ---" in prompt
    assert read.prompts == ["\nTú: ", "... ", "... ", "... ", "\nTú: "]


def test_multilinea_sin_instruccion_es_el_mensaje(cwd):
    brain = FakeBrain()

    launcher.interactive_mode(brain, read=reader(["<<", "recuerda que", "mi color es azul", "FIN", "salir"]))

    assert brain.processed == ["recuerda que\nmi color es azul"]


def test_multilinea_salir_dentro_del_bloque_no_sale(cwd):
    brain = FakeBrain()

    launcher.interactive_mode(brain, read=reader(["<<", "salir", "FIN", "salir"]))

    assert brain.processed == ["salir"]


def test_multilinea_fin_solo_si_esta_solo_en_la_linea(cwd):
    text, block = launcher.MessageReader(reader(["<<", "x = 'FIN'", "  FIN  "])).next_message()

    assert (text, block) == ("", "x = 'FIN'")


def test_multilinea_eof_cierra_el_bloque(cwd):
    def read(prompt, lines=iter(["analiza <<", "a = 1"])):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    assert launcher.MessageReader(read).next_message() == ("analiza", "a = 1")


def test_linea_vacia_no_llama_a_asia(cwd):
    brain = FakeBrain()

    launcher.interactive_mode(brain, read=reader(["", "   ", "salir"]))

    assert brain.processed == []


# Pegado real: con prompt_toolkit un pegado (bracketed paste) llega entero en
# una sola lectura, con sus saltos de línea. Antes, FIN dentro del pegado no
# cerraba el bloque y la lectura se quedaba esperando.
PASTED_CODE = "def f(x):\r\n\r\n    if x:\r\n        return 1\r\n    return 0\r\n"
EXPECTED_BLOCK = "def f(x):\n\n    if x:\n        return 1\n    return 0"


def chunks(values):
    """read() que devuelve cada valor tal cual (puede traer varias líneas)."""
    values = iter(values)

    def read(prompt):
        try:
            return next(values)
        except StopIteration:
            raise EOFError

    return read


@pytest.mark.parametrize(
    "reads, expected",
    [
        # "explica <<" escrito; el código y FIN pegados de una vez.
        (["explica esto <<", PASTED_CODE + "FIN"], [("explica esto", EXPECTED_BLOCK)]),
        # Todo pegado de una vez, incluida la instrucción.
        (["explica esto <<\r\n" + PASTED_CODE + "FIN\r\n"], [("explica esto", EXPECTED_BLOCK)]),
        # << con espacios al final; FIN escrito aparte.
        (["explica esto <<   ", PASTED_CODE, "FIN"], [("explica esto", EXPECTED_BLOCK)]),
        # Lo que viene después de FIN en el mismo pegado es el mensaje siguiente.
        (["revisa <<", PASTED_CODE + "FIN\r\nsalir"], [("revisa", EXPECTED_BLOCK), ("salir", None)]),
        # Un pegado de varias líneas sin << es un solo mensaje.
        ([PASTED_CODE], [(EXPECTED_BLOCK, None)]),
    ],
)
def test_bloque_con_pegados_de_varias_lineas(reads, expected):
    messages = launcher.MessageReader(chunks(reads))

    assert [messages.next_message() for _ in expected] == expected


def prompt_toolkit_messages(keys, count):
    """Mensajes leídos por una PromptSession real a la que se le envía keys."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        session = PromptSession(input=pipe, output=DummyOutput())
        messages = launcher.MessageReader(session.prompt)
        return [messages.next_message() for _ in range(count)]


PASTE_START, PASTE_END = "\x1b[200~", "\x1b[201~"


@pytest.mark.parametrize(
    "keys, expected",
    [
        (
            "explica esto <<\r" + PASTE_START + PASTED_CODE + "FIN" + PASTE_END + "\r",
            [("explica esto", EXPECTED_BLOCK)],
        ),
        (
            PASTE_START + "explica esto <<\r\n" + PASTED_CODE + "FIN\r\n" + PASTE_END + "\r",
            [("explica esto", EXPECTED_BLOCK)],
        ),
        (
            "revisa <<   \r" + PASTE_START + PASTED_CODE + PASTE_END + "\rFIN\rsalir\r",
            [("revisa", EXPECTED_BLOCK), ("salir", None)],
        ),
    ],
)
def test_bloque_con_pegado_real_en_prompt_toolkit(keys, expected):
    assert prompt_toolkit_messages(keys, len(expected)) == expected
