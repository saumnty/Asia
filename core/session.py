from pathlib import Path


class Session:
    project_root: Path | None = None
    user_cwd: Path = Path.cwd()

    @classmethod
    def set_paths(cls, project_root: Path, user_cwd: Path):
        cls.project_root = project_root
        cls.user_cwd = user_cwd

    @classmethod
    def get_user_cwd(cls) -> Path:
        return cls.user_cwd

    @classmethod
    def get_project_root(cls) -> Path | None:
        return cls.project_root