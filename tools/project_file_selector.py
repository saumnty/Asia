from pathlib import Path


class ProjectFileSelector:

    def __init__(self):

        self.ignored_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "memory",
            "backups",
            "chroma_db",
            ".pytest_cache"
        }

        self.supported_extensions = {
            ".py",
            ".js",
            ".ts",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".m",
            ".dart",
            ".yaml",
            ".yml",
            ".json",
            ".sdf",
            ".urdf",
            ".launch",
            ".sh"
        }

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

        for file in root.rglob("*"):

            if not file.is_file():
                continue

            normalized_parts = [
                part.lower()
                for part in file.parts
            ]

            if any(
                part in self.ignored_dirs
                for part in normalized_parts
            ):
                continue

            # Ignorar pruebas cuando revisamos TODO el proyecto
            if reviewing_entire_project:

                if (
                    "pruebas" in normalized_parts
                    or "test" in normalized_parts
                    or "tests" in normalized_parts
                    or file.name.startswith("test_")
                ):
                    continue

            if (
                file.suffix.lower() not in self.supported_extensions
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
            if file.suffix.lower() in {
                ".py",
                ".js",
                ".ts",
                ".java",
                ".c",
                ".cpp",
                ".m",
                ".dart"
            }:
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