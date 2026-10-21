"""Regla determinista (ast, sin LLM): leer un archivo y reescribirlo con "w".

open(ruta, "w") vacía el archivo al abrirlo, antes de escribir nada. Si el
script leyó ese mismo archivo antes, un fallo a medias de la escritura (una
excepción, Ctrl+C, disco lleno) deja el original vacío o incompleto y ya no
hay de dónde recuperarlo. qwen2.5-coder:7b no detectó este bug en ninguna
corrida del banco de calidad (test/manual), por eso se revisa en código.

No se avisa si antes de la escritura hay una copia de respaldo del archivo
(shutil.copy*) o una escritura a otro archivo (temporal), ni si el modo no
trunca ("a", "r+").
"""
import ast


# Llamadas que leen el archivo de su primer argumento: open(x), json.load no
# (recibe el archivo abierto), arff.loadarff(x), pd.read_csv(x), np.loadtxt(x)...
READ_PREFIXES = ("read", "load")
PATH_READ_METHODS = {"read_text", "read_bytes"}
PATH_WRITE_METHODS = {"write_text", "write_bytes"}
BACKUP_FUNCTIONS = {"copy", "copy2", "copyfile"}
TEMP_FUNCTIONS = {"NamedTemporaryFile", "mkstemp", "TemporaryFile"}


def call_name(node: ast.Call) -> str:
    func = node.func

    if isinstance(func, ast.Attribute):
        return func.attr

    if isinstance(func, ast.Name):
        return func.id

    return ""


def open_mode(node: ast.Call) -> str:
    """Modo de un open(ruta, modo) o Path(ruta).open(modo); "r" por defecto."""
    is_path_open = isinstance(node.func, ast.Attribute)
    mode_index = 0 if is_path_open else 1

    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)

    if len(node.args) > mode_index and isinstance(node.args[mode_index], ast.Constant):
        return str(node.args[mode_index].value)

    return "r"


def path_receiver(node: ast.Call):
    """Para Path(x).metodo() o p.metodo(), la expresión de la ruta."""
    receiver = node.func.value

    if isinstance(receiver, ast.Call) and call_name(receiver) == "Path" and receiver.args:
        return receiver.args[0]

    return receiver


class PathKeys:
    """Identifica rutas iguales: nombre_archivo y "vote.arff" son la misma si
    nombre_archivo = "vote.arff" se asigna una sola vez en el archivo."""

    def __init__(self, tree):
        assigned = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(node.value)

        self.constants = {
            name: values[0].value
            for name, values in assigned.items()
            if len(values) == 1
            and isinstance(values[0], ast.Constant)
            and isinstance(values[0].value, str)
        }

    def key(self, node) -> str:
        if isinstance(node, ast.Name) and node.id in self.constants:
            return repr(self.constants[node.id])

        if isinstance(node, ast.Constant):
            return repr(node.value)

        return ast.unparse(node)


def file_events(tree, keys: PathKeys) -> list[dict]:
    """Lecturas, escrituras, respaldos y temporales, en orden de línea."""
    events = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = call_name(node)
        is_method = isinstance(node.func, ast.Attribute)
        path = None
        kind = None

        if name == "open":
            path = path_receiver(node) if is_method else (node.args[0] if node.args else None)
            mode = open_mode(node)

            if "w" in mode:
                kind = "truncating_write"
            elif "r" in mode and "+" not in mode:
                kind = "read"
        elif is_method and name in PATH_READ_METHODS:
            path, kind = path_receiver(node), "read"
        elif is_method and name in PATH_WRITE_METHODS:
            path, kind = path_receiver(node), "truncating_write"
        elif name in BACKUP_FUNCTIONS and node.args:
            path, kind = node.args[0], "backup"
        elif name in TEMP_FUNCTIONS:
            kind = "temp"
        elif name.lower().startswith(READ_PREFIXES) and node.args:
            path, kind = node.args[0], "read"

        if kind:
            events.append({
                "kind": kind,
                "key": keys.key(path) if path is not None else None,
                "line": node.lineno,
                "path": ast.unparse(path) if path is not None else "",
            })

    return sorted(events, key=lambda event: event["line"])


def find_truncating_rewrites(content: str) -> list[dict]:
    """Escrituras con "w" sobre un archivo que el script leyó antes.

    Devuelve [{"line", "quote", "claim"}], el mismo formato que los hallazgos
    del modelo. Si el código no es Python válido, devuelve [].
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    lines = content.splitlines()
    events = file_events(tree, PathKeys(tree))
    findings = []

    for index, event in enumerate(events):
        if event["kind"] != "truncating_write":
            continue

        before = events[:index]
        reads = [e for e in before if e["kind"] == "read" and e["key"] == event["key"]]

        if not reads:
            continue

        protected = any(
            (e["kind"] == "backup" and e["key"] == event["key"])
            or e["kind"] == "temp"
            or (e["kind"] == "truncating_write" and e["key"] != event["key"])
            for e in before
        )

        if protected:
            continue

        findings.append({
            "line": event["line"],
            "quote": lines[event["line"] - 1].strip(),
            "claim": (
                f"Reescribe {event['path']} en modo \"w\" después de leerlo "
                f"(línea {reads[0]['line']}). \"w\" vacía el archivo antes de "
                "escribir: si algo falla a la mitad, el original queda vacío o "
                "corrupto. Escribe primero a un archivo temporal y reemplaza "
                "con os.replace."
            ),
        })

    return findings
