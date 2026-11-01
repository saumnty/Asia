"""/indexar y /fuentes: la biblioteca de conocimiento (core/rag/library.py)."""
import shlex

from core.rag.glossary import glossary_path, read_glossary
from core.rag.library import KINDS, Library

NAMED_ONLY = "solo-nombrada"
USAGE = (
    f"Uso: /indexar <nombre> [ruta] [tipo] [url] [licencia] [{NAMED_ONLY}]. El tipo es {', '.join(KINDS)}. "
    "En la url, {} es la ruta del archivo sin extensión: https://docs.ros.org/en/jazzy/{}.html. "
    f"Con {NAMED_ONLY}, la fuente solo se consulta con \"en <fuente>\"."
)
GLOSSARY_EXAMPLE = '{"punto desplazado": ["x_front", "y_front"]}'


def parse_source(spec: str):
    """(nombre, ruta, tipo, url, licencia, opciones) de "/indexar", o None si no se entiende.

    Sin ruta ni tipo, None: los conserva la fuente que ya exista.
    """
    try:
        words = shlex.split(spec, posix=False)
    except ValueError:
        return None

    words = [word.strip('"') for word in words]
    options = {"named_only": True} if NAMED_ONLY in words else {}
    words = [word for word in words if word != NAMED_ONLY]
    url_at = next((i for i, word in enumerate(words) if word.lower().startswith("http")), None)
    url, license = "", ""

    if url_at is not None:
        url, license = words[url_at], " ".join(words[url_at + 1:])
        words = words[:url_at]

        if "{}" not in url:
            return None

    if not words or len(words) > 3:
        return None

    name, rest = words[0], words[1:]
    kind = rest.pop().lower() if rest and rest[-1].lower() in KINDS else None

    if len(rest) > 1:
        return None

    return name, rest[0] if rest else None, kind, url, license, options


class LibraryActions:
    HANDLERS = {
        "add_source": "handle_add_source",
        "list_sources": "handle_list_sources",
        "show_glossary": "handle_show_glossary",
    }

    def handle_show_glossary(self, text, params):
        name = params.get("source", "").strip()
        source = Library().get(name)

        if source is None:
            return f"No conozco la fuente '{name}'. Mira /fuentes." if name else "Uso: /glosario <fuente>."

        path = glossary_path(source.name)

        try:
            glossary = read_glossary(source.name)
        except (ValueError, TypeError) as error:
            return f"No puedo leer {path}: {error}"

        if not glossary:
            return f"{source.name} no tiene glosario. Si lo quieres, créalo a mano en {path}:\n{GLOSSARY_EXAMPLE}"

        lines = [f"- {term} = {', '.join(values)}" for term, values in glossary.items()]
        return f"Glosario de {source.name} ({path}):\n" + "\n".join(lines)

    def handle_add_source(self, text, params):
        parsed = parse_source(params.get("spec", ""))

        if parsed is None:
            return USAGE

        name, path, kind, url, license, options = parsed

        return self.tool_registry.execute(
            "index_project_rag",
            project_path=path,
            project_name=name,
            kind=kind,
            url=url,
            license=license,
            **options
        )

    def handle_list_sources(self, text, params):
        sources = Library().all()

        if not sources:
            return "Aún no hay fuentes. Agrega una con /indexar <nombre> [ruta] [tipo]."

        lines = [
            f"- {s.name} ({s.kind}{', solo si se nombra' if s.named_only else ''}): {s.fragments} fragmentos, "
            f"{s.url or s.path}, indexada {s.indexed.replace('T', ' ')[:16]}"
            for s in sources
        ]
        return "Fuentes:\n" + "\n".join(lines)
