from pathlib import Path

from config.settings_manager import SettingsManager
from core.paths import iter_files
from tools.apply_changes_tool import ApplyChangesTool


class FileTool:
    def __init__(self, apply_changes_tool=None):
        # Carpeta desde la que se llamó a Asia: las rutas relativas que da el
        # usuario se resuelven contra ella.
        self.base_dir = Path.cwd()
        self.settings = SettingsManager()
        self.apply_changes_tool = apply_changes_tool or ApplyChangesTool()

    def is_inside_base_dir(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.base_dir.resolve())

    def propose_write(self, path: Path, new_content: str, reason: str):
        """Deja la escritura como cambio pendiente ("confirmar cambio")."""
        diff_message = self.apply_changes_tool.propose_change(
            file_path=str(path),
            new_content=new_content
        )

        return f"{reason}\n{diff_message}"

    def create_file(self, file_path: str, content: str = ""):
        path = Path(file_path)

        if not path.is_absolute():
            path = self.base_dir / path

        # Las rutas las decide el LLM: fuera de la carpeta del usuario solo
        # se escribe después de una confirmación explícita.
        if not self.is_inside_base_dir(path):
            return self.propose_write(
                path,
                content,
                f"{path.resolve()} está fuera de la carpeta actual "
                f"({self.base_dir}). No lo escribiré sin confirmación."
            )

        if path.exists():
            return self.propose_write(
                path,
                content,
                f"{path} ya existe. No lo sobrescribiré sin confirmación."
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return f"Archivo creado: {path}"

    def read_file(self, file_path: str):
        path = Path(file_path)

        if not path.is_absolute():
            path = self.base_dir / path

        if not path.exists():
            return f"No encontré el archivo: {path}"

        return path.read_text(encoding="utf-8", errors="ignore")

    def list_folder(self, folder_path: str = "."):
        path = Path(folder_path)

        if not path.is_absolute():
            path = self.base_dir / path

        if not path.exists():
            return f"No encontré la carpeta: {path}"

        items = []

        for item in path.iterdir():
            kind = "carpeta" if item.is_dir() else "archivo"
            items.append(f"- {item.name} ({kind})")

        return "\n".join(items)

    def append_file(self, file_path: str, content: str):
        path = Path(file_path)

        if not path.is_absolute():
            path = self.base_dir / path

        if not path.exists():
            return f"No encontré el archivo: {path}"

        if not self.is_inside_base_dir(path):
            old_content = path.read_text(encoding="utf-8")

            return self.propose_write(
                path,
                old_content + "\n" + content,
                f"{path.resolve()} está fuera de la carpeta actual "
                f"({self.base_dir}). No lo modificaré sin confirmación."
            )

        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + content)

        return f"Archivo actualizado: {path}"

    def search_files(self, query: str, folder_path: str = "."):
        base_path = Path(folder_path)

        if not base_path.is_absolute():
            base_path = self.base_dir / base_path

        if not base_path.exists():
            return f"No encontré la carpeta: {base_path}"

        ignored_dirs = self.settings.ignored_dirs()

        results = []

        for path in iter_files(base_path, ignored_dirs):
            if query.lower() in path.name.lower():
                results.append(str(path))

        if not results:
            return f"No encontré archivos que coincidan con: {query}"

        return "\n".join(results[:30])
    
    def search_text(self, query: str, folder_path: str = "."):
        base_path = Path(folder_path)

        if not base_path.is_absolute():
            base_path = self.base_dir / base_path

        if not base_path.exists():
            return f"No encontré la carpeta: {base_path}"

        ignored_dirs = self.settings.ignored_dirs()
        allowed_extensions = self.settings.text_extensions()

        results = []

        for path in iter_files(base_path, ignored_dirs):
            if path.suffix.lower() not in allowed_extensions:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for line_number, line in enumerate(content.splitlines(), start=1):
                if query.lower() in line.lower():
                    results.append(
                        f"{path}:{line_number}: {line.strip()}"
                    )

        if not results:
            return f"No encontré texto que coincida con: {query}"

        return "\n".join(results[:50])
    
    def read_file_preview(self, file_path: str, max_chars: int = 3000):
        content = self.read_file(file_path)

        if content.startswith("No encontré"):
            return content

        if len(content) <= max_chars:
            return content

        return content[:max_chars] + "\n\n... [archivo recortado]"

    def read_folder_context(self, folder_path: str = ".", max_files: int = 10, max_chars_per_file: int = 1500):
        base_path = Path(folder_path)

        if not base_path.is_absolute():
            base_path = self.base_dir / base_path

        if not base_path.exists():
            return f"No encontré la carpeta: {base_path}"

        ignored_dirs = self.settings.ignored_dirs()
        allowed_extensions = self.settings.text_extensions()

        files = []

        for path in iter_files(base_path, ignored_dirs):
            if path.suffix.lower() in allowed_extensions:
                files.append(path)

                if len(files) >= max_files:
                    break

        files = files[:max_files]

        chunks = []

        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if len(content) > max_chars_per_file:
                content = content[:max_chars_per_file] + "\n... [archivo recortado]"

            try:
                relative_path = path.relative_to(self.base_dir)
            except ValueError:
                relative_path = path

            chunks.append(
                f"\n--- Archivo: {relative_path} ---\n{content}"
            )

        if not chunks:
            return f"No encontré archivos legibles en: {base_path}"

        return "\n".join(chunks)