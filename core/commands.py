"""Comandos de sesión: una sola tabla para "/opciones", --help y el despacho.

Todos empiezan con "/". Cada comando con frase se traduce a la frase que ya
reconocen los atajos de texto (core/actions: modelos, modo confidencial,
tiempos, cambios y ejecución), que siguen valiendo como alias. Los de
sin frase (salir, carpeta, opciones) los atienden el launcher y Brain; "/proveedor"
va directo a la acción set_provider, sin el IntentEngine.

Un "/algo" que no está en la tabla no se manda al modelo: se responde con
la lista. Un texto como "/home/x/a.py" (con más barras) no cuenta como
comando.
"""
from dataclasses import dataclass

from core.actions.models import command_text

ARG = "<"


@dataclass(frozen=True)
class Command:
    group: str
    slash: str
    description: str
    example: str
    # Frase equivalente que reconocen los atajos ({arg}: lo que va tras el comando).
    phrase: str = None
    aliases: tuple = ()
    # (acción, parámetro) de Brain.HANDLERS, para comandos sin frase fija.
    action: tuple = None
    # Sin frase: "salir" (launcher), "carpeta" y "opciones" (Brain y launcher).
    special: str = None
    # Sintaxis del mensaje (@ruta, << ... FIN), no un comando.
    syntax: bool = False


COMMANDS = [
    Command("modos", "/modo normal", "archivos, adjuntos, RAG, proyecto y memoria no salen sin tu autorización",
            "/modo normal", phrase="modo normal", aliases=("modo normal",)),
    Command("modos", "/modo local", "no sale nada de esta máquina, ni lo que escribes",
            "/modo local", phrase="modo local", aliases=("modo local",)),
    Command("modos", "/modo abierto",
            "todo lo que entra al prompt sale sin pedir autorización (con secretos filtrados; "
            "lo emocional nunca sale)",
            "/modo abierto", phrase="modo abierto", aliases=("modo abierto",)),

    Command("modelos", "/modelo", "muestra los modelos en uso",
            "/modelo", phrase="que modelo estas usando", aliases=("¿qué modelo estás usando?",)),
    Command("modelos", "/modelo normal", "quita el modelo fijado en la sesión",
            "/modelo normal", phrase="vuelve al modelo normal", aliases=("vuelve al modelo normal",)),
    Command("modelos", "/modelo <dominio o nombre>",
            "fija el chat en un dominio (matemáticas, código, general) o un modelo descargado",
            "/modelo matemáticas  ·  /modelo qwen3:4b", phrase="usa el modelo {arg}",
            aliases=("usa el modelo de matemáticas", "usa el modelo qwen3:4b")),
    Command("modelos", "/proveedor <nombre>",
            'proveedor para esta sesión; para que sea permanente, edita "default_provider" '
            "en config/settings.json",
            "/proveedor gemini", action=("set_provider", "provider"),
            aliases=("cambia el provider a gemini",)),

    Command("archivos y adjuntos", "@ruta", "adjunta un archivo al mensaje (también @\"ruta con espacios\")",
            "explica @core/brain.py", syntax=True),
    Command("archivos y adjuntos", "<< ... FIN",
            "un mensaje que termina en << sigue en varias líneas hasta FIN",
            "explica esto <<  (pega el código y termina con FIN)", syntax=True),
    Command("archivos y adjuntos", "/carpeta", "carpeta desde donde llamaste a Asia",
            "/carpeta", special="carpeta", aliases=("cwd", "donde estoy", "carpeta actual")),

    Command("confidencialidad", "/enviar a gemini",
            "muestra qué saldría del último mensaje y pide confirmación (una sola vez)",
            "/enviar a gemini", phrase="envia esto a gemini", aliases=("envía esto a Gemini",)),
    Command("confidencialidad", "/confirmar envío", "envía lo preparado con /enviar a gemini",
            "/confirmar envío", phrase="confirmar envio", aliases=("confirmar envío",)),
    Command("confidencialidad", "/cancelar envío", "descarta lo preparado",
            "/cancelar envío", phrase="cancelar envio", aliases=("cancelar envío",)),
    Command("confidencialidad", "/enviados", "resumen de los últimos envíos externos (sin el texto)",
            "/enviados", phrase="que has enviado afuera", aliases=("qué has enviado afuera",)),

    Command("cambios y ejecución", "/cambio pendiente", "muestra el cambio propuesto sin aplicarlo",
            "/cambio pendiente", phrase="muestra el cambio pendiente", aliases=("muestra el cambio pendiente",)),
    Command("cambios y ejecución", "/confirmar cambio", "aplica el cambio propuesto",
            "/confirmar cambio", phrase="confirmar cambio", aliases=("confirmar cambio",)),
    Command("cambios y ejecución", "/cancelar cambio", "descarta el cambio propuesto",
            "/cancelar cambio", phrase="cancelar cambio", aliases=("cancelar cambio",)),
    Command("cambios y ejecución", "/confirmar ejecución", "ejecuta en el sandbox el código preparado",
            "/confirmar ejecución", phrase="confirmar ejecucion", aliases=("confirmar ejecución",)),
    Command("cambios y ejecución", "/cancelar ejecución", "descarta la ejecución preparada",
            "/cancelar ejecución", phrase="cancelar ejecucion", aliases=("cancelar ejecución",)),

    Command("tiempos", "/tiempos",
            "después de cada respuesta, una línea con el IntentEngine, la carga del modelo, el "
            "prompt, los tokens, tokens por segundo, el total y el modelo (como --timing)",
            "/tiempos", phrase="muestra tiempos", aliases=("muestra tiempos",)),
    Command("tiempos", "/sin tiempos", "deja de mostrar los tiempos",
            "/sin tiempos", phrase="oculta tiempos", aliases=("oculta tiempos",)),

    Command("pendientes", "/pendiente <texto>", "anota un pendiente, guardado en local",
            "/pendiente revisar el PID del Bolitabot", action=("add_task", "text")),
    Command("pendientes", "/pendientes", "muestra los pendientes abiertos, numerados",
            "/pendientes", action=("list_tasks", "text")),
    Command("pendientes", "/hecho <n>", "cierra el pendiente con ese número",
            "/hecho 2", action=("close_task", "number")),

    Command("memoria", "/revisar memoria",
            "busca entradas duplicadas o contradictorias con reglas y propone cambios uno por uno; "
            "nada cambia sin tu confirmación",
            "/revisar memoria", special="revisar_memoria",
            aliases=("revisa la memoria", "revisar memoria")),
    Command("memoria", "/revisar memoria a fondo",
            "lo mismo, y además le pregunta al modelo local (más lento y menos fiable que las reglas)",
            "/revisar memoria a fondo", special="revisar_memoria_a_fondo",
            aliases=("revisa la memoria a fondo", "revisar memoria a fondo")),

    Command("biblioteca", "/indexar <nombre> [ruta] [tipo]",
            "agrega o actualiza una fuente: proyecto, reporte o notas (por defecto, la carpeta actual)",
            "/indexar Bolitabot C:\\Robots\\bolitabot proyecto", action=("add_source", "spec")),
    Command("biblioteca", "/fuentes", "muestra las fuentes de la biblioteca",
            "/fuentes", action=("list_sources", "text")),

    Command("voz", "/voz",
            "Enter en una línea vacía escucha lo que dices; las respuestas se leen en voz alta "
            "(como --voz)",
            "/voz", phrase="activa la voz", aliases=("activa la voz",)),
    Command("voz", "/sin voz", "quita la voz y libera sus modelos",
            "/sin voz", phrase="desactiva la voz", aliases=("desactiva la voz",)),
    Command("voz", "/calibrar voz",
            "mide 3 s el ruido del cuarto (quédate en silencio) y ajusta el umbral de voz para la sesión",
            "/calibrar voz", special="calibrar", aliases=("calibra la voz", "calibrar voz")),

    Command("salir", "/opciones", "esta lista", "/opciones", special="opciones"),
    Command("salir", "/salir", "cierra Asia", "/salir", special="salir", aliases=("salir", "exit", "quit")),
]

GROUPS = list(dict.fromkeys(c.group for c in COMMANDS))


@dataclass
class Resolved:
    command: Command = None
    arg: str = ""
    unknown: str = None

    @property
    def phrase(self):
        return self.command.phrase.format(arg=self.arg) if self.command and self.command.phrase else None


def head(command: Command) -> str:
    """"/modelo <dominio o nombre>" -> "/modelo"."""
    return command.slash.split(f" {ARG}")[0]


def resolve(text: str):
    """Resolved si text es un comando "/", None si no lo es."""
    stripped = (text or "").strip()

    if not stripped.startswith("/") or "\n" in stripped:
        return None

    first = stripped.split()[0]

    # "/home/x/a.py" o "/c:\\..." es una ruta, no un comando.
    if "/" in first[1:] or "\\" in first or "." in first:
        return None

    normalized = command_text(stripped)
    commands = [c for c in COMMANDS if not c.syntax]

    for command in commands:
        if ARG not in command.slash and normalized == command_text(command.slash):
            return Resolved(command)

    for command in commands:
        if ARG in command.slash:
            prefix = command_text(head(command))

            # "/hecho" sin argumento: lo explica su acción.
            if normalized == prefix and command.action:
                return Resolved(command)

            if normalized.startswith(prefix + " "):
                # El argumento se toma del texto original (puede llevar mayúsculas).
                words = len(prefix.split())
                return Resolved(command, " ".join(stripped.split()[words:]))

    return Resolved(unknown=first)


def unknown_message(name: str) -> str:
    return f"No conozco el comando {name}. Escribe /opciones para ver los comandos."


def is_launcher_command(text: str, name: str) -> bool:
    """True si text es "/salir" o uno de sus alias (lo mismo para "carpeta")."""
    command = next(c for c in COMMANDS if c.special == name)
    resolved = resolve(text)

    if resolved and resolved.command is command:
        return True

    return command_text(text) in {command_text(a) for a in command.aliases}


def options_text() -> str:
    """La lista por grupos, con un ejemplo de cada comando."""
    lines = [
        "Comandos de sesión (empiezan con /; las frases entre paréntesis también valen).",
        "Lo que cambian dura solo la sesión; no se escribe en settings.json.",
    ]

    for group in GROUPS:
        lines.append(f"\n{group}:")

        for command in (c for c in COMMANDS if c.group == group):
            aliases = f' (también: {", ".join(chr(34) + a + chr(34) for a in command.aliases)})' if command.aliases else ""
            lines.append(f"  {command.slash}  {command.description}{aliases}")
            lines.append(f"      ej.: {command.example}")

    return "\n".join(lines)
