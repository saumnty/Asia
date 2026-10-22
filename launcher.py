import argparse
import sys
from collections import deque
from pathlib import Path

# No se cambia de carpeta: los datos internos de Asia usan rutas absolutas
# (core/paths.py) y las rutas que da el usuario se resuelven contra la
# carpeta desde la que llamó a Asia.
from core.attachments import (
    STDIN_LABEL,
    MissingAttachment,
    build_chat_prompt,
    decode,
    extract_attachments,
    file_attachments,
    history_prompt,
    make_attachment,
    quote_path,
    read_stdin,
    truncation_warnings,
)
from config.settings_manager import SettingsManager
from core.path_completion import make_completer
from core.paths import PROJECT_ROOT
from core.session import Session
from core.brain import Brain
from providers.provider_router import ProviderRouter

Session.set_paths(
    project_root=PROJECT_ROOT,
    user_cwd=Path.cwd(),
)

EXIT_COMMANDS = {"salir", "exit", "quit"}
CWD_COMMANDS = {"cwd", "donde estoy", "carpeta actual"}

DEFAULT_ATTACHMENT_MAX_CHARS = 20000

# Instrucción cuando solo llegan archivos (--file) sin texto.
DEFAULT_FILE_REQUEST = "Explica el contenido de los archivos adjuntos."

# Modo multilínea del modo interactivo: "explica esto <<", líneas, "FIN".
MULTILINE_START = "<<"
MULTILINE_END = "FIN"
PASTED_LABEL = "texto pegado"


def warn(messages):
    for message in messages:
        print(message, file=sys.stderr)


def respond(brain, text, prefix="", attachments=(), use_actions=True):
    """Procesa un mensaje e imprime la respuesta.

    Si Brain no reconoce una acción (devuelve None), el mensaje se trata
    como conversación normal con el provider, con el contenido de los
    adjuntos. use_actions=False va directo al chat (p. ej. contenido por
    stdin, que no tiene una ruta que una acción pueda leer).
    """
    print(prefix, end="", flush=True)

    try:
        response = brain.process(text) if use_actions else None

        if response is not None:
            print(response)
            return

        prompt = build_chat_prompt(text, attachments)
        history = history_prompt(text, attachments)

        if brain.settings.get("stream_output", False):
            brain.provider_router.chat(
                prompt,
                on_chunk=lambda chunk: print(chunk, end="", flush=True),
                history_prompt=history
            )
            print()
            return

        print(brain.provider_router.chat(prompt, history_prompt=history))
    except Exception as e:
        print(f"Error inesperado: {e}")


def prepare_message(brain, text, files=(), block=None, block_label=STDIN_LABEL):
    """Resuelve @ruta, --file y un bloque de texto (stdin o pegado con <<).

    Devuelve (texto, adjuntos, use_actions). En el texto, cada @ruta y cada
    --file quedan como ruta absoluta para que las acciones de Brain (revisar,
    explicar...) encuentren el archivo.

    Si un adjunto no existe devuelve None: el mensaje no se envía (el modelo
    respondería sobre un archivo que no vio) y el aviso sugiere nombres
    parecidos de la carpeta.
    """
    cwd = Session.get_user_cwd()
    max_chars = brain.settings.get("attachment_max_chars", DEFAULT_ATTACHMENT_MAX_CHARS)

    text, attachments, warnings = extract_attachments(text, cwd, max_chars)
    extra, extra_warnings = file_attachments(files, cwd, max_chars)
    warnings += extra_warnings

    if any(isinstance(w, MissingAttachment) for w in warnings):
        warn(warnings + ["Mensaje no enviado: corrige la ruta y vuelve a intentarlo."])
        return None

    if extra:
        text = (text.strip() or DEFAULT_FILE_REQUEST) + " " + " ".join(
            quote_path(a.path) for a in extra
        )
        attachments += extra

    use_actions = True

    if block is not None:
        if text.strip():
            attachments.append(make_attachment(block_label, block, max_chars))
            use_actions = False
        else:
            # Sin instrucción, el bloque (stdin o pegado) es el mensaje.
            text = block

    warn(warnings + truncation_warnings(attachments))

    return text, attachments, use_actions


def make_reader():
    """input() con autocompletado de @ruta si prompt_toolkit está disponible.

    Sin terminal (p. ej. salida redirigida) o sin prompt_toolkit, input().
    """
    if not sys.stdin.isatty():
        return input

    try:
        from prompt_toolkit import PromptSession

        session = PromptSession(
            completer=make_completer(Session.get_user_cwd),
            complete_while_typing=True
        )
    except Exception:
        return input

    return session.prompt


class MessageReader:
    """Lee mensajes del modo interactivo, de una línea o en bloque (<< ... FIN).

    Una lectura puede traer varias líneas: con prompt_toolkit, un pegado
    (bracketed paste) llega entero en una sola llamada, con sus saltos de
    línea; con input() llega línea por línea. Por eso cada lectura se parte en
    líneas y las que sobran quedan para lo siguiente: así FIN cierra el bloque
    aunque venga dentro del mismo pegado.
    """

    def __init__(self, read):
        self.read = read
        self.pending = deque()

    def next_line(self, prompt):
        if not self.pending:
            chunk = self.read(prompt).replace("\r\n", "\n").replace("\r", "\n")
            lines = chunk.split("\n")

            # El salto final de un pegado no es una línea vacía más.
            if len(lines) > 1 and lines[-1] == "":
                lines.pop()

            self.pending.extend(lines)

        return self.pending.popleft()

    def next_message(self):
        """Devuelve (texto, bloque), con bloque None si no es un mensaje con <<.

        Si la primera línea termina en << (con o sin espacios al final), lo que
        sigue hasta una línea con FIN sola es el bloque y lo escrito antes de
        << es la instrucción. Si no, y llegaron más líneas en la misma lectura
        (un pegado sin <<), todo el pegado es un solo mensaje.
        """
        first = self.next_line("\nTú: ")
        stripped = first.rstrip()

        if not stripped.endswith(MULTILINE_START):
            rest = list(self.pending)
            self.pending.clear()
            return "\n".join([first, *rest]), None

        instruction = stripped[: -len(MULTILINE_START)].rstrip()
        lines = []

        while True:
            try:
                current = self.next_line("... ")
            except EOFError:
                break

            if current.strip() == MULTILINE_END:
                break

            lines.append(current)

        return instruction, "\n".join(lines)


def interactive_mode(brain=None, read=None):
    brain = brain or Brain()
    read = read or make_reader()

    print("Asia iniciada")
    print(f"(Para pegar varias líneas termina el mensaje con {MULTILINE_START} y cierra con {MULTILINE_END}.)")

    messages = MessageReader(read)

    try:
        while True:
            user, block = messages.next_message()

            if block is None and user.lower().strip() in EXIT_COMMANDS:
                print("Asia apagada.")
                break

            prepared = prepare_message(brain, user, block=block, block_label=PASTED_LABEL)

            # None: un adjunto no existe; el aviso ya se mostró y se vuelve al prompt.
            if prepared is None or not prepared[0].strip():
                continue

            text, attachments, use_actions = prepared
            respond(brain, text, prefix="\nAsia: ", attachments=attachments, use_actions=use_actions)

    except (KeyboardInterrupt, EOFError):
        print("\nAsia apagada.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description=(
            "Asia, asistente local. Sin mensaje abre el modo interactivo. "
            "Adjunta archivos con @ruta dentro del mensaje o con --file; "
            "también acepta contenido por stdin (Get-Content a.py | jarvis \"explica esto\"). "
            "En el modo interactivo, un mensaje que termina en << sigue en varias "
            "líneas hasta una línea con FIN. "
            "Usa -- antes de un mensaje que empiece con guion."
        )
    )
    parser.add_argument("prompt", nargs="*", help="mensaje para Asia")
    parser.add_argument(
        "--file", "-f", action="append", default=[], metavar="RUTA",
        help="adjunta un archivo (se puede repetir)"
    )
    parser.add_argument(
        "--provider", metavar="NOMBRE",
        help="provider solo para esta ejecución (no cambia settings.json)"
    )
    parser.add_argument(
        "--project", metavar="NOMBRE",
        help="proyecto activo solo para esta ejecución (no cambia settings.json)"
    )
    parser.add_argument(
        "--no-stream", action="store_true",
        help="muestra la respuesta completa al final en vez de en streaming"
    )
    return parser


def session_overrides(args, parser) -> dict:
    """Valores de los flags, normalizados igual que set_provider y set_active_project."""
    settings = SettingsManager()
    overrides = {}

    if args.provider:
        name = args.provider.lower().strip()
        name = settings.get("provider_aliases", {}).get(name, name)

        if name not in ProviderRouter.provider_factories:
            available = ", ".join(ProviderRouter.provider_factories)
            parser.error(f"provider no disponible: {args.provider} (disponibles: {available})")

        overrides["default_provider"] = name

    if args.project:
        name = args.project.lower().strip()
        overrides["active_project"] = settings.get("project_aliases", {}).get(name, name)

    if args.no_stream:
        overrides["stream_output"] = False

    return overrides


def main(argv=None, stdin=None, brain_factory=Brain):
    """Devuelve el código de salida: 1 si un adjunto no existe, 0 si no."""
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)
    SettingsManager.set_overrides(session_overrides(args, parser))

    prompt = " ".join(args.prompt)
    stdin_data = read_stdin(stdin)

    if not prompt and not args.file and stdin_data is None:
        interactive_mode(brain_factory())
        return

    if prompt.lower().strip() in CWD_COMMANDS and not args.file and stdin_data is None:
        print(f"Carpeta desde donde llamaste a Asia: {Session.get_user_cwd()}")
        return

    # "jarvis salir" no tiene nada que hacer: no se crea Brain ni se llama al modelo.
    if prompt.lower().strip() in EXIT_COMMANDS and not args.file and stdin_data is None:
        print("Asia apagada.")
        return

    brain = brain_factory()
    block = decode(stdin_data) if stdin_data is not None else None
    prepared = prepare_message(brain, prompt, args.file, block)

    if prepared is None:
        return 1

    text, attachments, use_actions = prepared

    if not text.strip():
        print("No recibí ningún mensaje.", file=sys.stderr)
        return

    respond(brain, text, attachments=attachments, use_actions=use_actions)


if __name__ == "__main__":
    sys.exit(main())
