from core.atomic_write import write_text_atomic
from core.paths import PROJECTS_DIR


class ProjectMemory:
    def __init__(self, projects_dir=PROJECTS_DIR):
        self.projects_dir = projects_dir
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _project_path(self, project_name: str):
        safe_name = project_name.lower().strip().replace(" ", "_")
        return self.projects_dir / f"{safe_name}.md"

    def save_project_summary(self, project_name: str, content: str):
        path = self._project_path(project_name)

        # Atómico: un corte a mitad no pierde el resumen anterior.
        write_text_atomic(path, content)

        return path

    def load_project_summary(self, project_name: str):
        path = self._project_path(project_name)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    
    def summary_date(self, project_name: str):
        """Fecha de la última vez que se guardó el resumen (la del archivo); None si no hay."""
        from datetime import date

        path = self._project_path(project_name)
        return date.fromtimestamp(path.stat().st_mtime) if path.exists() else None

    def append_project_note(self, project_name: str, note: str):
        path = self._project_path(project_name)

        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n## Nota nueva\n")
            f.write(note)

        return path

# Un resumen de más días que esto se marca como posiblemente desactualizado.
STALE_DAYS = 30


def age_notice(saved, today=None) -> str:
    """La fecha del resumen del proyecto y, si es viejo, el aviso y cómo rehacerlo; "" sin fecha."""
    if saved is None:
        return ""

    from datetime import date

    days = ((today or date.today()) - saved).days

    if days <= STALE_DAYS:
        return f"Resumen del proyecto guardado el {saved.isoformat()}."

    return (
        f"Resumen del proyecto guardado el {saved.isoformat()} (hace {days} días): puede estar desactualizado. "
        "Para rehacerlo: «resume el proyecto y guarda el resumen»."
    )
