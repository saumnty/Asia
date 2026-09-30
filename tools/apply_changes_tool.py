from pathlib import Path
from difflib import unified_diff
import json
from datetime import datetime


class ApplyChangesTool:
    name = "apply_changes"
    description = "Genera y aplica cambios en archivos solo después de confirmación."

    def __init__(self):
        self.pending_file = Path("memory/pending_change.json")
        self.backup_dir = Path("memory/backups")
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def propose_change(self, file_path: str, new_content: str):
        path = Path(file_path)

        if not path.exists():
            old_content = ""
        else:
            old_content = path.read_text(encoding="utf-8")

        diff = "\n".join(
            unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} actual",
                tofile=f"{file_path} propuesto",
                lineterm=""
            )
        )

        pending_change = {
            "file_path": file_path,
            "old_content": old_content,
            "new_content": new_content,
            "diff": diff,
            "created_at": datetime.now().isoformat(timespec="seconds")
        }

        self.pending_file.write_text(
            json.dumps(pending_change, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        return f"""
Cambio propuesto para:

{file_path}

Diff:

{diff}

Para aplicarlo escribe:
confirmar cambio

Para cancelarlo escribe:
cancelar cambio
"""

    def load_pending_change(self):
        if not self.pending_file.exists():
            return None

        try:
            return json.loads(
                self.pending_file.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            return None

    def apply_pending_change(self):
        pending_change = self.load_pending_change()

        if not pending_change:
            return "No hay ningún cambio pendiente por aplicar."

        file_path = pending_change["file_path"]
        old_content = pending_change.get("old_content", "")
        new_content = pending_change["new_content"]

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = file_path.replace("/", "__").replace("\\", "__")
            backup_path = self.backup_dir / f"{safe_name}.{timestamp}.bak"

            backup_path.write_text(
                path.read_text(encoding="utf-8"),
                encoding="utf-8"
            )

        path.write_text(new_content, encoding="utf-8")

        self.pending_file.unlink(missing_ok=True)

        return f"Cambio aplicado correctamente en: {file_path}"

    def cancel_pending_change(self):
        pending_change = self.load_pending_change()

        if not pending_change:
            return "No hay ningún cambio pendiente que cancelar."

        self.pending_file.unlink(missing_ok=True)

        return "Cambio cancelado."

    def show_pending_change(self):
        pending_change = self.load_pending_change()

        if not pending_change:
            return "No hay ningún cambio pendiente."

        return f"""
Cambio pendiente:

Archivo:
{pending_change["file_path"]}

Creado:
{pending_change.get("created_at", "desconocido")}

Diff:

{pending_change["diff"]}
"""