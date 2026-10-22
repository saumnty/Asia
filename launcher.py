import argparse
import sys
from pathlib import Path

# No se cambia de carpeta: los datos internos de Asia usan rutas absolutas
# (core/paths.py) y las rutas que da el usuario se resuelven contra la
# carpeta desde la que llamó a Asia.
from core.attachments import (
    STDIN_LABEL,
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
from core.path_completion import make_completer
from core.paths import PROJECT_ROOT
from core.session import Session
from core.brain import Brain

Session.set_paths(
    project_root=PROJECT_ROOT,
    user_cwd=Path.cwd(),
)

EXIT_COMMANDS = {"salir", "exit", "quit"}
CWD_COMMANDS = {"cwd", "donde estoy", "carpeta actual"}

DEFAULT_ATTACHMENT_MAX_CHARS = 20000

# Instrucción cuando solo llegan archivos (--file) sin texto.
DEFAULT_FILE_REQUEST = "Explica el contenido de los archivos adjuntos."


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


def prepare_message(brain, text, files=(), stdin_data=None):
    """Resuelve @ruta, --file y stdin. Devuelve (texto, adjuntos, use_actions).

    En el texto, cada @ruta y cada --file quedan como ruta absoluta para que
    las acciones de Brain (revisar, explicar...) encuentren el archivo.
    """
    cwd = Session.get_user_cwd()
    max_chars = brain.settings.get("attachment_max_chars", DEFAULT_ATTACHMENT_MAX_CHARS)

    text, attachments, warnings = extract_attachments(text, cwd, max_chars)
    extra, extra_warnings = file_attachments(files, cwd, max_chars)
    warnings += extra_warnings

    if extra:
        text = (text.strip() or DEFAULT_FILE_REQUEST) + " " + " ".join(
            quote_path(a.path) for a in extra
        )
        attachments += extra

    use_actions = True

    if stdin_data is not None:
        stdin_text = decode(stdin_data)

        if text.strip():
            attachments.append(make_attachment(STDIN_LABEL, stdin_text, max_chars))
            use_actions = False
        else:
            # Sin instrucción, lo que llega por stdin es el mensaje.
            text = stdin_text

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


def interactive_mode(brain=None, read=None):
    brain = brain or Brain()
    read = read or make_reader()

    print("Asia iniciada")

    try:
        while True:
            user = read("\nTú: ")

            if user.lower().strip() in EXIT_COMMANDS:
                print("Asia apagada.")
                break

            text, attachments, use_actions = prepare_message(brain, user)
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
            "Usa -- antes de un mensaje que empiece con guion."
        )
    )
    parser.add_argument("prompt", nargs="*", help="mensaje para Asia")
    parser.add_argument(
        "--file", "-f", action="append", default=[], metavar="RUTA",
        help="adjunta un archivo (se puede repetir)"
    )
    return parser


def main(argv=None, stdin=None, brain_factory=Brain):
    args = build_parser().parse_intermixed_args(argv)
    prompt = " ".join(args.prompt)
    stdin_data = read_stdin(stdin)

    if not prompt and not args.file and stdin_data is None:
        interactive_mode(brain_factory())
        return

    if prompt.lower().strip() in CWD_COMMANDS and not args.file and stdin_data is None:
        print(f"Carpeta desde donde llamaste a Asia: {Session.get_user_cwd()}")
        return

    brain = brain_factory()
    text, attachments, use_actions = prepare_message(brain, prompt, args.file, stdin_data)

    if not text.strip():
        print("No recibí ningún mensaje.", file=sys.stderr)
        return

    respond(brain, text, attachments=attachments, use_actions=use_actions)


if __name__ == "__main__":
    main()
