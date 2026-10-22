"""Ejecución en el sandbox: preparar, confirmar y cancelar (ver tools/sandbox.py)."""
from pathlib import Path

from tools.sandbox import SandboxRunner, format_result, sandbox_import_problems


# Confirmar o cancelar una ejecución en el sandbox se reconoce por texto
# exacto, sin el IntentEngine: nada se ejecuta por una mala interpretación.
RUN_CONFIRM_PHRASES = {"confirmar ejecución", "confirmar ejecucion", "confirmo ejecución", "confirmo ejecucion"}
RUN_CANCEL_PHRASES = {"cancelar ejecución", "cancelar ejecucion"}


def normalized_command(text) -> str:
    return " ".join((text or "").lower().split()).strip(" .!¡")


class SandboxActions:
    HANDLERS = {
        "run_sandbox": "handle_run_sandbox",
    }

    def sandbox(self):
        return SandboxRunner(
            timeout=self.settings.get("sandbox_timeout", 20),
            max_output=self.settings.get("sandbox_max_output", 4000)
        )

    def prepare_run(self, label, script_name, code):
        """Deja lista una ejecución en el sandbox; corre con "confirmar ejecución"."""
        if not script_name.lower().endswith(".py"):
            return f"Solo ejecuto archivos .py en el sandbox ({script_name} no lo es)."

        problems = sandbox_import_problems(code)

        if problems:
            listed = "\n".join(f"- {problem}" for problem in problems)
            return (
                f"No ejecuto {label}: el sandbox solo tiene la biblioteca estándar "
                f"y este código importa:\n{listed}\n"
                "Fallaría con ModuleNotFoundError. Asia no instala paquetes en el sandbox."
            )

        self.pending_run.save(label, script_name, code)
        lines = len(code.splitlines())

        return (
            f"Ejecución preparada: {label} ({lines} líneas).\n"
            f"Correrá en un venv desechable solo con la biblioteca estándar, en una "
            f"carpeta temporal, sin stdin y con un límite de "
            f"{self.settings.get('sandbox_timeout', 20)} s.\n"
            "Ojo: el sandbox aísla paquetes, no el sistema. El código corre con tus "
            "permisos y puede leer o modificar tus archivos y usar la red.\n"
            'Escribe "confirmar ejecución" para correrlo o "cancelar ejecución".'
        )

    def confirm_run(self):
        pending = self.pending_run.load()

        if not pending:
            return "No hay ninguna ejecución pendiente."

        # Se borra antes de correr: si Asia se cae a mitad, no se repite sola.
        self.pending_run.clear()
        runner = self.sandbox()
        result = runner.run(pending["code"], pending["script_name"])

        return format_result(pending["label"], result, runner.timeout)

    def cancel_run(self):
        if not self.pending_run.load():
            return "No hay ninguna ejecución pendiente."

        self.pending_run.clear()
        return "Ejecución cancelada."

    def handle_run_sandbox(self, text, params):
        file_path = params.get("file_path")

        if file_path:
            path = Path(file_path)

            if not path.is_file():
                return f"No encontré el archivo: {file_path}"

            return self.prepare_run(str(path), path.name, path.read_text(encoding="utf-8"))

        pending_change = self.tool_registry.get_apply_changes_tool().load_pending_change()

        if not pending_change:
            return (
                "No hay un cambio pendiente que probar. Indica el archivo, por "
                "ejemplo: ejecuta @script.py en el sandbox."
            )

        target = pending_change["file_path"]
        return self.prepare_run(
            f"cambio pendiente para {target}", Path(target).name, pending_change["new_content"]
        )
