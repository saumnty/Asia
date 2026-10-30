import argparse
import re
import sys
import textwrap
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
from core import timing
from core.confidential import LOCAL_MODE, OPEN_MODE, current_mode
from core.provenance import ADJUNTO, USUARIO, Fragment, request_sources
from core.paths import PROJECT_ROOT
from providers.ollama_models import full_name, installed_models as ollama_installed_models
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
# FIN como última palabra de una línea ("return x FIN").
TRAILING_END = re.compile(rf"\s+{MULTILINE_END}\s*$")
PASTED_LABEL = "texto pegado"


def warn(messages):
    for message in messages:
        print(message, file=sys.stderr)


def respond(brain, text, prefix="", attachments=(), use_actions=True, text_label=USUARIO):
    """Procesa un mensaje e imprime la respuesta.

    Si Brain no reconoce una acción (devuelve None), el mensaje se trata
    como conversación normal con el provider, con el contenido de los
    adjuntos. use_actions=False va directo al chat (p. ej. contenido por
    stdin, que no tiene una ruta que una acción pueda leer).

    El texto y los adjuntos quedan registrados con su procedencia
    (core/provenance.py) para que el router no los mande afuera sin
    autorización.
    """
    print(prefix, end="", flush=True)

    sources = [Fragment(text_label, text)] + [Fragment(ADJUNTO, a.content) for a in attachments]

    # Con --timing o "/tiempos", una línea de tiempos al final (por stderr,
    # para no mezclarla con la respuesta si la salida va a un archivo). Si
    # el mensaje los activa o los quita, esa vez no se muestra.
    if not timing.enabled(brain.settings):
        with request_sources(*sources):
            respond_in_context(brain, text, attachments, use_actions)
        return

    with timing.measure_request() as timings, request_sources(*sources):
        respond_in_context(brain, text, attachments, use_actions)

    if timing.enabled(brain.settings):
        print(timing.summary(timings), file=sys.stderr)


def respond_in_context(brain, text, attachments, use_actions):
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

    También devuelve la etiqueta del texto (core/provenance.py): "usuario",
    salvo que el mensaje sea un bloque pegado o stdin sin instrucción, que
    es "adjunto".

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
    text_label = USUARIO

    if block is not None:
        if text.strip():
            attachments.append(make_attachment(block_label, block, max_chars))
            use_actions = False
        else:
            # Sin instrucción, el bloque (stdin o pegado) es el mensaje.
            text = block
            text_label = ADJUNTO

    warn(warnings + truncation_warnings(attachments))

    return text, attachments, use_actions, text_label


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

    def __init__(self, read, prompt=lambda: "\nTú: "):
        self.read = read
        self.prompt = prompt
        self.pending = deque()

    def closes_read(self, remainder=None):
        """True si lo que queda de la lectura actual cierra un bloque: una
        línea FIN sola, o FIN como última palabra de la última línea."""
        lines = list(self.pending) or [remainder or ""]
        return any(line.strip() == MULTILINE_END for line in lines) or bool(TRAILING_END.search(lines[-1]))

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
        sigue hasta el cierre es el bloque y lo escrito antes de << es la
        instrucción. Cierra una línea FIN sola o FIN al final de la última
        línea de una lectura, tras un espacio ("return x FIN"): así una
        variable FIN en medio de un pegado no corta el bloque.

        Si se pegó justo después de << sin pulsar Enter, el bloque empieza en
        la misma línea: cuenta si la misma lectura trae el cierre (así
        "x = 1 << 3" en un pegado sigue siendo código). Si no, y llegaron más
        líneas en la misma lectura (un pegado sin <<), todo el pegado es un
        solo mensaje.
        """
        first = self.next_line(self.prompt())
        stripped = first.rstrip()
        marker = first.find(MULTILINE_START)

        if stripped.endswith(MULTILINE_START):
            instruction = stripped[: -len(MULTILINE_START)].rstrip()
        elif marker != -1 and self.closes_read(first[marker + len(MULTILINE_START):]):
            instruction = first[:marker].rstrip()
            # El resto de la línea es la primera del bloque; los espacios de
            # "<< " antes del pegado no son parte del código.
            self.pending.appendleft(first[marker + len(MULTILINE_START):].lstrip(" "))
        else:
            rest = list(self.pending)
            self.pending.clear()
            return "\n".join([first, *rest]), None

        lines = []

        while True:
            try:
                current = self.next_line("... ")
            except EOFError:
                break

            if current.strip() == MULTILINE_END:
                break

            # FIN como última palabra solo cierra en la última línea leída.
            end = TRAILING_END.search(current) if not self.pending else None

            if end:
                lines.append(current[:end.start()])
                break

            lines.append(current)

        return instruction, "\n".join(lines)


def user_prompt(settings) -> str:
    """"Tú: ", o "Tú [abierto]: " / "Tú [local]: " si el modo confidencial no es el normal."""
    mode = current_mode(settings)
    return f"\nTú [{mode}]: " if mode in {OPEN_MODE, LOCAL_MODE} else "\nTú: "


def interactive_mode(brain=None, read=None):
    brain = brain or Brain()
    read = read or make_reader()

    print("Asia iniciada")
    print(f"(Para pegar varias líneas termina el mensaje con {MULTILINE_START} y cierra con {MULTILINE_END}.)")

    messages = MessageReader(read, prompt=lambda: user_prompt(brain.settings))

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

            text, attachments, use_actions, text_label = prepared
            respond(
                brain, text, prefix="\nAsia: ", attachments=attachments,
                use_actions=use_actions, text_label=text_label
            )

    except (KeyboardInterrupt, EOFError):
        print("\nAsia apagada.")


MODEL_HELP = """modelos:
  El chat elige el modelo según el tema (models_by_domain en config: código,
  matemáticas o general) y lo mantiene mientras siga la conversación. Las
  acciones de código usan el de código. En el modo interactivo:
    ¿qué modelo estás usando?        muestra los modelos en uso
    usa el modelo de matemáticas     fija el chat en ese dominio (también: de código, general)
    usa el modelo qwen3:4b           fija un modelo descargado para todo
    vuelve al modelo normal          quita lo fijado
  Lo que se cambia dura solo la sesión; no se escribe en settings.json.

modo confidencial:
  Archivos, adjuntos (@ruta, --file, stdin, << ... FIN), RAG, resumen del
  proyecto y memoria no salen hacia un proveedor externo (Gemini, u Ollama en
  otra máquina) sin autorización: responde el modelo local y lo avisa.
    envía esto a Gemini     muestra qué saldría del último mensaje; luego "confirmar envío"
    modo local              no sale nada, ni lo que escribes; "modo normal" lo quita
    modo abierto            sale todo lo que entra al prompt (archivos, adjuntos, RAG,
                            proyecto, memoria, historial, con rutas) sin pedir
                            autorización; siguen el filtro de secretos y la bitácora y
                            lo emocional nunca sale. Solo la sesión; "modo normal" lo quita
    qué has enviado afuera  resumen de los últimos envíos externos
  --allow-external autoriza los envíos de esa ejecución, confirmando cada uno.

tiempos:
  --timing, "/tiempos" (o "muestra tiempos") y "/sin tiempos" (o "oculta tiempos"):
  después de cada respuesta, una línea con el IntentEngine, la carga del modelo,
  el prompt, los tokens generados, tokens por segundo, el total y el modelo.

proveedor:
  "cambia el provider a gemini" y --provider valen solo para la sesión. Para
  que sea permanente, edita "default_provider" en config/settings.json.
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="jarvis",
        # El epílogo va con su formato (RawDescription); la descripción se
        # reajusta a mano.
        description=textwrap.fill(
            "Asia, asistente local. Sin mensaje abre el modo interactivo. "
            "Adjunta archivos con @ruta dentro del mensaje o con --file; "
            "también acepta contenido por stdin (Get-Content a.py | jarvis \"explica esto\"). "
            "En el modo interactivo, un mensaje que termina en << sigue en varias "
            "líneas hasta una línea con FIN (o FIN al final de la última línea). "
            "Usa -- antes de un mensaje que empiece con guion."
        ),
        epilog=MODEL_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter
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
    parser.add_argument(
        "--model", metavar="NOMBRE",
        help="modelo de Ollama (p. ej. qwen3:4b) para el chat y las acciones de "
             "esta ejecución; debe estar descargado, Asia no descarga modelos. "
             "No cambia settings.json"
    )
    parser.add_argument(
        "--timing", action="store_true",
        help="después de cada respuesta muestra los tiempos: IntentEngine, carga del modelo, "
             "prompt, tokens generados, tokens por segundo, total y modelo usado"
    )
    parser.add_argument(
        "--allow-external", action="store_true",
        help="autoriza en esta ejecución que contenido local (archivos, adjuntos...) "
             "salga a un proveedor externo; cada envío se confirma en la terminal "
             "y la autorización no se guarda"
    )
    return parser


def confirm_external(summary):
    """Confirmación de --allow-external: True, False o "all" (todos en esta ejecución)."""
    print(f"\n[Modo confidencial] {summary}", file=sys.stderr)

    if not sys.stdin or not sys.stdin.isatty():
        print("No se puede confirmar sin una terminal: no se envió.", file=sys.stderr)
        return False

    try:
        answer = input("¿Enviar? [s = sí, una vez / t = todos en esta ejecución / N = no]: ")
    except EOFError:
        return False

    answer = answer.strip().lower()
    return "all" if answer == "t" else answer in {"s", "si", "sí"}


def installed_models():
    """Modelos descargados en Ollama, o None si Ollama no responde."""
    return ollama_installed_models(SettingsManager().get("ollama_host"))


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

    if args.allow_external:
        overrides["allow_external"] = True

    if args.timing:
        overrides[timing.SETTING] = True

    if args.model:
        # Se comprueba que esté descargado: Asia nunca descarga modelos.
        installed = installed_models()

        if installed is not None and full_name(args.model) not in {full_name(m) for m in installed}:
            parser.error(
                f"el modelo {args.model} no está descargado en Ollama "
                f"(descargados: {', '.join(installed) or 'ninguno'})"
            )

        overrides["forced_model"] = args.model

    return overrides


def with_confirmation(brain):
    """--allow-external confirma cada envío externo en la terminal."""
    router = getattr(brain, "provider_router", None)

    if router is not None and hasattr(router, "confirm"):
        router.confirm = confirm_external

    return brain


def main(argv=None, stdin=None, brain_factory=Brain):
    """Devuelve el código de salida: 1 si un adjunto no existe, 0 si no."""
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)
    SettingsManager.set_overrides(session_overrides(args, parser))

    prompt = " ".join(args.prompt)
    stdin_data = read_stdin(stdin)

    if not prompt and not args.file and stdin_data is None:
        interactive_mode(with_confirmation(brain_factory()))
        return

    if prompt.lower().strip() in CWD_COMMANDS and not args.file and stdin_data is None:
        print(f"Carpeta desde donde llamaste a Asia: {Session.get_user_cwd()}")
        return

    # "jarvis salir" no tiene nada que hacer: no se crea Brain ni se llama al modelo.
    if prompt.lower().strip() in EXIT_COMMANDS and not args.file and stdin_data is None:
        print("Asia apagada.")
        return

    brain = with_confirmation(brain_factory())
    block = decode(stdin_data) if stdin_data is not None else None
    prepared = prepare_message(brain, prompt, args.file, block)

    if prepared is None:
        return 1

    text, attachments, use_actions, text_label = prepared

    if not text.strip():
        print("No recibí ningún mensaje.", file=sys.stderr)
        return

    respond(brain, text, attachments=attachments, use_actions=use_actions, text_label=text_label)


if __name__ == "__main__":
    sys.exit(main())
