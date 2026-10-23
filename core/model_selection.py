"""Qué modelo de Ollama usa cada llamada (fase F, multi-modelo).

- models_by_domain (config): dominio -> modelo. Sin entrada, ollama_model.
- Las acciones internas (revisar, generar, explicar código) son "code".
- El chat clasifica cada mensaje con reglas de palabras clave, sin llamar a
  un modelo: una llamada extra costaría más que lo que ahorra.
- Modelo pegajoso: el chat mantiene el modelo de su primer mensaje y solo
  cambia si otro dominio aparece en SWITCH_AFTER mensajes seguidos, porque
  cada cambio es una recarga en Ollama.
- forced_model (flag --model) fija el modelo de toda la sesión.
"""
import re

DOMAINS = ("code", "math", "general")

CODE_WORDS = re.compile(
    r"```|\w+\(\)|\b\w+\.(py|js|ts|java|cs|cpp|go|rs|sql|json)\b|"
    r"\b(def|class|import|return|python|java|javascript|typescript|sql|regex|git|api|"
    r"c[oó]digo|funci[oó]n|m[eé]todo|variable|bug|excepci[oó]n|traceback|"
    r"compila\w*|script|programa\w*|"
    # Estructuras y librerías: "el promedio de una lista", "un DataFrame de pandas".
    r"listas?|arrays?|arreglos?|diccionarios?|tuplas?|bucles?|loops?|print|range|len|"
    r"pandas|numpy|dataframes?|html|css|consola|terminal|librer[ií]as?)\b|"
    r"\bc\+\+|\bc#|"
    # Sintaxis: llamadas a función salvo las de matemáticas (sen(x), f(x)),
    # métodos (np.mean), +=, ==, ** y "for x in".
    r"\b(?!(?:sen|sin|cos|tan|log|ln|exp|sqrt|ra[ií]z)\()[A-Za-z_]\w+\(|"
    r"\b\w+\.\w+\(|[+\-*/]=|==|\*\*|\bfor\s+\w+\s+in\b",
    re.IGNORECASE,
)

MATH_WORDS = re.compile(
    r"\d+(\.\d+)?\s*[\^*/+\-=]\s*\d+|"
    r"\b(ecuaci[oó]n|ecuaciones|integral\w*|derivad\w*|deriva|l[ií]mite|matri(z|ces)|vector\w*|"
    r"probabilidad\w*|estad[ií]stic\w*|teorema|demuestra|demostraci[oó]n|f[ií]sica|"
    r"velocidad|aceleraci[oó]n|fuerza|energ[ií]a|calcula|resuelve|ra[ií]z|logaritmo\w*|"
    r"seno|coseno|tangente|porcentaje|[aá]lgebra|geometr[ií]a)\b",
    re.IGNORECASE,
)

# Mensajes seguidos de otro dominio para que el chat cambie de modelo.
SWITCH_AFTER = 2


def classify_domain(text: str) -> str:
    """"code" si hay señales de código (aunque también haya de matemáticas:
    "calcula la media en python" es código), "math", o "general"."""
    if CODE_WORDS.search(text):
        return "code"

    if MATH_WORDS.search(text):
        return "math"

    return "general"


def model_for(settings, domain: str) -> str:
    forced = settings.get("forced_model")

    if forced:
        return forced

    by_domain = settings.get("models_by_domain") or {}
    return by_domain.get(domain) or settings.get("ollama_model")


def thinks(settings, domain) -> bool:
    """Modo de razonamiento solo en think_domains (por defecto "math"): en el
    resto alarga la respuesta sin mejorarla, y en el IntentEngine rompería
    el JSON."""
    return domain in (settings.get("think_domains") or [])


class StickyModel:
    """Modelo del chat a lo largo de una sesión."""

    def __init__(self):
        self.domain = None
        self.candidate = None
        self.streak = 0

    def choose(self, text: str, settings) -> str:
        domain = classify_domain(text)

        if self.domain is None or model_for(settings, domain) == model_for(settings, self.domain):
            # Primer mensaje, o el cambio no carga otro modelo: es gratis.
            self.domain = domain
            self.candidate, self.streak = None, 0
        elif domain == self.candidate:
            self.streak += 1
        else:
            self.candidate, self.streak = domain, 1

        if self.candidate and self.streak >= SWITCH_AFTER:
            self.domain = self.candidate
            self.candidate, self.streak = None, 0

        return model_for(settings, self.domain)
