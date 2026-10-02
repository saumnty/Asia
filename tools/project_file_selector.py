from pathlib import Path

from config.settings_manager import SettingsManager
from core.paths import has_ignored_part, is_private_data, iter_files


class ProjectFileSelector:

    def __init__(self):

        self.settings = SettingsManager()

        self.priority_names = {
            "main.py",
            "app.py",
            "server.py",
            "main.cpp",
            "main.c",
            "index.js",
            "package.json",
            "settings.json",
            "CMakeLists.txt",
            "Dockerfile"
        }

        self.priority_dirs = {
            "src",
            "core",
            "tools",
            "providers",
            "app",
            "server",
            "config",
            "scripts",
            "controllers",
            "models",
            "services"
        }

    def select_files(
        self,
        folder_path: str = ".",
        max_files: int = 15
    ):

        root = Path(folder_path)

        if not root.exists():
            return []

        candidates = []

        reviewing_entire_project = Path(folder_path).resolve() == Path(".").resolve()

        # review_ignored_dirs: carpetas de herramientas (.github, ...) que no
        # son código del proyecto. Solo se excluyen al elegir qué revisar; si
        # se pide revisar esa carpeta directamente, es la raíz y sí se recorre.
        ignored_dirs = self.settings.ignored_dirs() | {
            name.lower() for name in self.settings.get("review_ignored_dirs", [])
        }
        test_dirs = self.settings.test_dirs()
        # Las mismas extensiones que search_text y read_folder_context: todo
        # lo que se selecciona para revisar también se puede buscar y leer.
        supported_extensions = self.settings.text_extensions()
        code_extensions = self.settings.code_extensions()

        for file in iter_files(root, ignored_dirs):

            normalized_parts = [
                part.lower()
                for part in file.parts
            ]

            if is_private_data(file):
                continue

            # Ignorar pruebas cuando revisamos TODO el proyecto
            if reviewing_entire_project:

                if (
                    has_ignored_part(file, root, test_dirs)
                    or file.name.startswith("test_")
                ):
                    continue

            if (
                file.suffix.lower() not in supported_extensions
                and file.name not in self.priority_names
            ):
                continue

            score = 0

            # Entrypoints importantes
            if file.name in self.priority_names:
                score += 50

            # Carpetas relevantes
            if any(
                part in self.priority_dirs
                for part in normalized_parts
            ):
                score += 30

            # Código fuente
            if file.suffix.lower() in code_extensions:
                score += 20

            # Penalizar tests (si no fueron excluidos)
            if (
                "test" in normalized_parts
                or "tests" in normalized_parts
                or file.name.startswith("test_")
            ):
                score -= 20

            try:
                size = file.stat().st_size

                # Penalizar archivos gigantes
                if size > 80_000:
                    score -= 20

            except OSError:
                pass

            candidates.append((score, file))

        candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        return [
            str(file).replace("\\", "/")
            for _, file in candidates[:max_files]
        ]