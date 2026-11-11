from pathlib import Path
from difflib import unified_diff
import hashlib
import json
import re
from datetime import datetime

from core.atomic_write import write_text_atomic
from core.paths import BACKUPS_DIR, PENDING_CHANGE_FILE, PROJECT_ROOT


def file_hash(path):
    """sha256 del archivo, o None si no existe."""
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class ApplyChangesTool:
    name = "apply_changes"
    description = "Genera y aplica cambios en archivos solo después de confirmación."

    def __init__(self, pending_file=PENDING_CHANGE_FILE, backup_dir=BACKUPS_DIR):
        self.pending_file = pending_file
        self.backup_dir = backup_dir
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        # True si el último "confirmar cambio" no escribió porque el archivo había cambiado.
        self.stale = False

    def propose_change(self, file_path: str, new_content: str, target=None):
        # target: dónde está el archivo, si no es file_path (volver a proponer desde otra carpeta).
        path = Path(target or file_path)

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

        # Se guarda la ruta absoluta: el cambio puede confirmarse desde otra
        # carpeta (p. ej. en otra llamada a asia).
        pending_change = {
            "file_path": file_path,
            "absolute_path": str(path.resolve()),
            # Cómo estaba el archivo al proponer: si al confirmar es otro, no se escribe encima.
            "old_hash": file_hash(path),
            "old_content": old_content,
            "new_content": new_content,
            "diff": diff,
            "created_at": datetime.now().isoformat(timespec="seconds")
        }

        # Atómico: un corte a mitad no deja un pending_change.json inválido.
        write_text_atomic(
            self.pending_file,
            json.dumps(pending_change, indent=2, ensure_ascii=False)
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

    def pending_path(self, pending_change) -> Path:
        absolute_path = pending_change.get("absolute_path")

        if absolute_path:
            return Path(absolute_path)

        # Cambios guardados antes de la fase 2: se crearon con la carpeta de
        # trabajo en la raíz de Asia.
        path = Path(pending_change["file_path"])
        return path if path.is_absolute() else PROJECT_ROOT / path

    def changed_since_proposal(self, pending_change) -> bool:
        """True si el archivo ya no es el que se vio al proponer el cambio (o no existía y ahora sí, o al revés)."""
        path = self.pending_path(pending_change)

        if "old_hash" in pending_change:
            return file_hash(path) != pending_change["old_hash"]

        # Cambios pendientes de antes del hash: se compara con el texto guardado.
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        return current != pending_change.get("old_content", "")

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

        path = self.pending_path(pending_change)

        # Si el archivo cambió desde la propuesta, no se escribe encima: se pierde lo que se le añadió.
        self.stale = self.changed_since_proposal(pending_change)

        if self.stale:
            return (
                f"El archivo cambió desde la propuesta: {file_path}. No escribí nada.\n\n"
                "¿Vuelvo a proponer el cambio con el archivo actual? s/N\n\n"
                "[Si no, el cambio sigue pendiente: «cancelar cambio» lo descarta.]"
            )

        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r"[\\/:]+", "__", file_path).strip("_")
            backup_path = self.backup_dir / f"{safe_name}.{timestamp}.bak"

            backup_path.write_text(
                path.read_text(encoding="utf-8"),
                encoding="utf-8"
            )

        path.write_text(new_content, encoding="utf-8")

        self.pending_file.unlink(missing_ok=True)

        return f"Cambio aplicado correctamente en: {file_path}"

    def repropose_pending_change(self):
        """El mismo cambio, con el diff y el hash del archivo como está ahora."""
        pending_change = self.load_pending_change()
        self.stale = False

        if not pending_change:
            return "No hay ningún cambio pendiente que volver a proponer."

        return self.propose_change(
            pending_change["file_path"], pending_change["new_content"], target=self.pending_path(pending_change)
        )

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