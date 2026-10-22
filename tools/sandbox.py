"""Ejecución de código en un venv desechable, solo con la biblioteca estándar.

Para qué sirve: comprobar que un script corre (ModuleNotFoundError, errores de
sintaxis, excepciones) sin tocar el entorno de Asia ni el del usuario. Cada
ejecución crea un venv nuevo (python -m venv --without-pip: no descarga nada
y no hay pip con el que instalar) en una carpeta temporal y lo borra al
terminar.

Qué NO aísla: un venv separa paquetes, no el sistema. El código corre con los
permisos del usuario y puede leer o borrar archivos y usar la red. Se reduce
el riesgo, pero no es un sandbox de seguridad, por eso Brain pide
"confirmar ejecución" antes de correr nada:
- carpeta de trabajo temporal con solo el script;
- python -I (sin variables PYTHON*, sin site del usuario, sin la carpeta del
  script en sys.path);
- entorno mínimo: sin claves de API ni otras variables del usuario;
- sin stdin y con límite de tiempo; al vencer se mata el árbol de procesos.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.atomic_write import write_json_atomic
from core.paths import PENDING_RUN_FILE
from tools.import_check import STDLIB, extract_imports


# Variables que Windows necesita para que Python arranque y use sockets.
WINDOWS_ENV_KEYS = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")


@dataclass
class RunResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    seconds: float


def sandbox_import_problems(code: str) -> list[str]:
    """Imports que fallarán en el sandbox: solo tiene la biblioteca estándar
    y el script (no el resto del proyecto)."""
    try:
        imports = extract_imports(code)
    except SyntaxError:
        # Se ejecuta igual: el traceback de Python es el mejor reporte.
        return []

    return [
        f"línea {line}: import {module}"
        for module, line in imports
        if module not in STDLIB
    ]


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"

    return venv_dir / "bin" / "python"


def minimal_env(work_dir: Path) -> dict:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TEMP": str(work_dir),
        "TMP": str(work_dir),
        "TMPDIR": str(work_dir),
        "HOME": str(work_dir),
        "USERPROFILE": str(work_dir),
        "PATH": os.defpath,
    }

    if os.name == "nt":
        env.update({key: os.environ[key] for key in WINDOWS_ENV_KEYS if key in os.environ})
        env["PATH"] = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32")

    return env


def kill_tree(process: subprocess.Popen):
    """Mata el proceso y sus hijos (un script puede lanzar otros)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)

    process.kill()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    return text[:max_chars] + f"\n... [salida recortada: {len(text)} caracteres]"


class SandboxRunner:
    def __init__(self, timeout: float = 20, max_output: int = 4000, base_python: str = sys.executable):
        self.timeout = timeout
        self.max_output = max_output
        self.base_python = base_python

    def create_venv(self, venv_dir: Path):
        subprocess.run(
            [self.base_python, "-m", "venv", "--without-pip", str(venv_dir)],
            check=True, capture_output=True, timeout=120
        )

    def run(self, code: str, script_name: str = "script.py") -> RunResult:
        root = Path(tempfile.mkdtemp(prefix="asia_sandbox_"))

        try:
            venv_dir = root / "venv"
            work_dir = root / "trabajo"
            work_dir.mkdir()
            self.create_venv(venv_dir)

            script = work_dir / Path(script_name).name
            script.write_text(code, encoding="utf-8")

            return self.execute(venv_python(venv_dir), script, work_dir)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def execute(self, python: Path, script: Path, work_dir: Path) -> RunResult:
        options = {}

        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True

        start = time.monotonic()
        process = subprocess.Popen(
            [str(python), "-I", str(script)],
            cwd=work_dir,
            env=minimal_env(work_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **options
        )

        try:
            stdout, stderr = process.communicate(timeout=self.timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            kill_tree(process)
            stdout, stderr = process.communicate()
            timed_out = True

        def text(data):
            return truncate(data.decode("utf-8", errors="replace").replace("\r\n", "\n"), self.max_output)

        return RunResult(
            returncode=None if timed_out else process.returncode,
            stdout=text(stdout),
            stderr=text(stderr),
            timed_out=timed_out,
            seconds=time.monotonic() - start,
        )


def format_result(label: str, result: RunResult, timeout: float) -> str:
    if result.timed_out:
        status = f"se detuvo al pasar el límite de {timeout:g} s"
    else:
        status = f"código de salida {result.returncode}"

    parts = [f"Resultado del sandbox ({label}): {status}, {result.seconds:.1f} s."]

    for name, output in (("stdout", result.stdout), ("stderr", result.stderr)):
        if output.strip():
            parts += [f"--- {name} ---", output.rstrip()]

    if not (result.stdout.strip() or result.stderr.strip()):
        parts.append("(sin salida)")

    return "\n".join(parts)


class PendingRun:
    """Ejecución preparada que espera "confirmar ejecución".

    Se guarda en un archivo (como el cambio pendiente) para que pueda
    confirmarse en otra llamada a jarvis. Guarda una copia del código: se
    ejecuta exactamente lo que se mostró, aunque el archivo cambie después.
    """

    def __init__(self, path=PENDING_RUN_FILE):
        self.path = Path(path)

    def save(self, label: str, script_name: str, code: str):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, {
            "label": label,
            "script_name": script_name,
            "code": code,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def load(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def clear(self):
        self.path.unlink(missing_ok=True)
