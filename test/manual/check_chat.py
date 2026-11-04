"""Charla con Ollama de verdad: ¿el modelo se adjudica los datos del usuario?

Corre en una sola sesión interactiva (launcher, con --timing) unos 26
mensajes: saludos, "¿quién eres?", "¿cuál es tu color favorito?" (trampa),
preguntas de conocimiento, preguntas sobre el usuario y una charla de varios
turnos; y los casos de la prueba manual de la estrategia B: un hecho reciente
y su "sí" (Wikipedia), la sesión anterior, el hilo de una charla, lo que sigue
a un /buscar, "explícamelo a fondo", recall con una frase y el glosario. La memoria es una copia temporal con datos fijos: no se lee ni se
toca memory/memory.json. El resumen de la sesión y los pendientes también van
a la carpeta temporal (si no, el resumen de esta charla de prueba reemplazaría
el de la última sesión de verdad).

    .venv\\Scripts\\python.exe test\\manual\\check_chat.py

Cuenta:
- atribuciones: una frase en primera persona del modelo con un dato del
  usuario ("Mi color favorito es el amarillo"). Debe ser 0.
- fugas: un dato del usuario en la respuesta a un mensaje que no trata de
  él ("un día lleno de energía amarilla" ante un "gracias").
- aciertos: respuestas correctas sobre el usuario y de conocimiento.
- tiempo total y t/s de cada mensaje (línea [tiempos]).
Sale con código 1 si hubo alguna atribución.
"""
import io
import re
import sys
import tempfile
import unicodedata
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core import paths
from core.paths import PROJECT_ROOT
from core.session import Session

Session.set_paths(project_root=PROJECT_ROOT, user_cwd=ROOT)

import launcher
from core.brain import Brain
from core.reflection import save_summary
from core.timing import SETTING
from memory.memory_manager import MemoryManager
from providers.ollama_provider import make_repeatable

MEMORY = {"nombre": "Santiago", "proyecto": "Bolitabot", "universidad": "UAM", "color_favorito": "amarillo"}
VALUES = [value.lower() for value in MEMORY.values()]
NOT_NAME = [value for value in VALUES if value != "santiago"]
# Bolitabot es también el nombre de la fuente que se busca y sale en el resumen de la sesión anterior.
NOT_NAME_NOR_PROJECT = [value for value in VALUES if value not in ("santiago", "bolitabot")]

YELLOW_FRUIT = r"amarill|platano|banana|limon|mango|pina|maracuya|melon"

# (mensaje, datos que no deben aparecer, regex de una respuesta correcta o None; "about_me": 3 de los 4 datos)
CASES = [
    ("hola", VALUES, None),
    # El hilo va al principio: "empezamos" es el primer tema de la charla.
    ("hablemos de ROS 2", VALUES, None),
    ("¿qué es un nodo?", VALUES, r"nodo"),
    ("¿y un tópico?", VALUES, r"topico|topic|publica"),
    ("¿de qué tema empezamos a hablar?", VALUES, r"(de|con|sobre|fue|era|es) (el |la )?(tema de )?ros ?2"),
    ("explícamelo a fondo", VALUES, "long"),
    ("¿quién eres?", VALUES, r"asia|asistente"),
    ("¿cuál es tu color favorito?", ["amarillo"], None),
    ("qué es un grafo bipartito", VALUES, r"conjunto|grupo"),
    ("¿cuál es la capital de Japón?", VALUES, r"tokio|tokyo|toquio"),
    ("¿cuántos días tiene un año bisiesto?", VALUES, r"366"),
    ("¿cuál es mi color favorito?", [], r"amarill"),
    ("¿cómo me llamo?", [], r"santiago"),
    ("recomiéndame una fruta de mi color favorito", [], YELLOW_FRUIT),
    ("estoy aprendiendo Rust", NOT_NAME, None),
    ("¿qué me recomiendas para empezar?", NOT_NAME, r"rust|cargo|libro|book"),
    ("¿y cuánto se tarda en aprenderlo?", NOT_NAME, r"rust|semana|mes"),
    ("gracias", NOT_NAME, None),
    ("¿qué sabes de mí?", [], "about_me"),
    # Prueba manual de la estrategia B (2026-11-03): hecho reciente, sesión anterior, hilo,
    # lo de después de /buscar, "a fondo", recall en una frase y el glosario.
    ("¿quién ganó el mundial de 2026?", VALUES, r"no lo se de memoria.*wikipedia"),
    ("sí", VALUES, r"wikipedia"),
    ("¿qué hicimos en la sesión anterior?", NOT_NAME_NOR_PROJECT, r"pid"),
    ("/buscar cómo se guardan los pendientes del usuario", VALUES, r"pendiente|task"),
    ("¿y eso para qué sirve?", VALUES, r"pendiente|tarea"),
    ("¿cómo me llamo?", [], r"te llamas santiago"),
    ("/buscar cómo se calcula el punto desplazado en bolitabot", NOT_NAME_NOR_PROJECT, r"x_front"),
]

# El resumen de la "sesión anterior" que se deja en la carpeta temporal.
PREVIOUS_SESSION = "Repasamos el controlador PID del trébol de Bolitabot y sus ganancias."
# "a fondo": una respuesta que pase del tope breve (answer_limits.chat.tokens).
LONG_TOKENS = 350
# Una negativa a explicar ("no puedo", "no tengo información suficiente").
REFUSAL = re.compile(r"\bno (puedo|podria|tengo (informacion|datos))\b")

# Frase en primera persona del modelo: "mi color favorito es...", "me llamo...", "soy...", "estudio en...".
FIRST_PERSON = re.compile(r"\b(mi|mis|me llamo|soy|estudio|trabajo en)\b[^.!?\n]{0,40}")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def attributions(answer: str) -> list:
    """Frases en primera persona de la respuesta con un dato del usuario."""
    text = plain(answer)
    return [m.group(0) for m in FIRST_PERSON.finditer(text) if any(value in m.group(0) for value in map(plain, VALUES))]


def leaks(answer: str, forbidden) -> list:
    # Por el principio de cada palabra: "amarilla" es fuga de "amarillo", "mutuamente" no lo es de "uam".
    words = set(re.findall(r"\w+", plain(answer)))
    return [value for value in forbidden if any(word.startswith(plain(value)[:max(3, len(value) - 2)]) for word in words)]


def correct(answer: str, expected, tokens=None) -> bool:
    """tokens: los generados según [tiempos], para "long"."""
    text = plain(answer)

    if expected == "about_me":
        return sum(plain(value) in text for value in VALUES) >= 3

    if expected == "long":
        return (tokens or 0) > LONG_TOKENS and not REFUSAL.search(text)

    return bool(re.search(expected, text, re.DOTALL))


class Tee(io.StringIO):
    """Guarda la salida y la sigue mostrando."""

    def __init__(self, stream):
        super().__init__()
        self.stream = stream

    def write(self, text):
        self.stream.write(text)
        return super().write(text)


def number(pattern, line):
    match = re.search(pattern, line or "")
    return float(match.group(1).replace(",", ".")) if match else None


def run(folder):
    paths.SESSION_SUMMARY_FILE = folder / "ultima_sesion.json"
    paths.TASKS_FILE = folder / "pendientes.json"
    SettingsManager.set_overrides({**SettingsManager.overrides, SETTING: True})
    make_repeatable()
    save_summary(PREVIOUS_SESSION, "modelo", 5)
    brain = Brain()
    brain.memory = brain.provider_router.memory = MemoryManager(folder / "memory.json")
    brain.memory.save(MEMORY)

    out, err = Tee(sys.__stdout__), Tee(sys.__stderr__)
    lines = iter([case[0] for case in CASES] + ["salir"])
    # Lo que se escribe entre un prompt de entrada y el siguiente es la respuesta.
    starts, ends = [], []

    def read(prompt):
        ends.append(out.tell())
        print(prompt, end="")
        starts.append(out.tell())
        return next(lines)

    with redirect_stdout(out), redirect_stderr(err):
        launcher.interactive_mode(brain, read=read)

    text = out.getvalue()
    answers = [text[start:end] for start, end in zip(starts, ends[1:])]
    timings = [line for line in err.getvalue().splitlines() if line.startswith("[tiempos]")]
    return answers, timings


def main():
    with tempfile.TemporaryDirectory(prefix="asia_chat_") as folder:
        answers, timings = run(Path(folder))

    rows = []
    total_attributions = total_leaks = right = graded = 0

    for (message, forbidden, expected), answer, line in zip(CASES, answers, timings + [None] * len(CASES)):
        found = attributions(answer)
        leaked = leaks(answer, forbidden) if not found else []
        ok = correct(answer, expected, number(r"(\d+) tokens generados", line)) if expected else None
        total_attributions += len(found)
        total_leaks += bool(leaked)
        graded += ok is not None
        right += bool(ok)
        rows.append((message, found, leaked, ok, number(r"total ([\d.,]+) s", line), number(r"([\d.,]+) t/s", line),
                     re.search(r"ollama/([^\s·]+)", line or "")))

    print("\n\n=== Resumen")
    print("| Mensaje | Atribución | Fuga | Correcta | Total (s) | t/s | Modelo |")
    print("|---|---|---|---|---|---|---|")

    for message, found, leaked, ok, seconds, rate, model in rows:
        mark = "—" if ok is None else "sí" if ok else "NO"
        print(f"| {message} | {'; '.join(found) or '—'} | {', '.join(leaked) or '—'} | {mark} | "
              f"{seconds if seconds is not None else '—'} | {rate if rate is not None else '—'} | "
              f"{model.group(1) if model else 'sin modelo'} |")

    seconds = [row[4] for row in rows if row[4] is not None]
    print(f"\nAtribuciones: {total_attributions} · fugas: {total_leaks} · correctas: {right}/{graded} · "
          f"tiempo total {sum(seconds):.1f} s ({len(seconds)} mensajes con tiempos)")

    if len(timings) != len(CASES):
        print(f"(faltan líneas de tiempos: {len(timings)} de {len(CASES)})")

    return 1 if total_attributions else 0


if __name__ == "__main__":
    sys.exit(main())
