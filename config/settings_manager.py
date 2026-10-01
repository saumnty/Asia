import json
from pathlib import Path

from core.paths import DEFAULTS_FILE, SETTINGS_FILE


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class SettingsManager:
    """Configuración en dos niveles.

    - config/defaults.json: valores por defecto (versionado).
    - config/settings.json: cambios locales del usuario (no versionado).
      Es el único archivo que escribe set().

    Los valores locales tienen prioridad. Los diccionarios se combinan un
    nivel, así que basta con sobrescribir la clave que se quiera cambiar
    (p. ej. un solo límite de context_limits).
    """

    def __init__(self, defaults_path=DEFAULTS_FILE, path=SETTINGS_FILE):
        self.defaults_path = Path(defaults_path)
        self.path = Path(path)

    def load(self):
        data = read_json(self.defaults_path)

        for key, value in read_json(self.path).items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value

        return data

    def get(self, key, default=None):
        data = self.load()
        return data.get(key, default)

    def ignored_dirs(self, include_tests=False) -> set[str]:
        names = set(self.get("ignored_dirs", []))

        if include_tests:
            names |= set(self.get("test_dirs", []))

        return {name.lower() for name in names}

    def test_dirs(self) -> set[str]:
        return {name.lower() for name in self.get("test_dirs", [])}

    def set(self, key, value):
        data = read_json(self.path)

        data[key] = value

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )
