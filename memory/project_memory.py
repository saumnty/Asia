from pathlib import Path


class ProjectMemory:
    def __init__(self):
        self.projects_dir = Path("memory/projects")
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _project_path(self, project_name: str):
        safe_name = project_name.lower().strip().replace(" ", "_")
        return self.projects_dir / f"{safe_name}.md"

    def save_project_summary(self, project_name: str, content: str):
        path = self._project_path(project_name)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return path

    def load_project_summary(self, project_name: str):
        path = self._project_path(project_name)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    
    def append_project_note(self, project_name: str, note: str):
        path = self._project_path(project_name)

        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n## Nota nueva\n")
            f.write(note)

        return path