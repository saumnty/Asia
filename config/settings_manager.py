import json
from pathlib import Path

from core.atomic_write import write_json_atomic
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

    Encima de los dos van los valores de sesión (overrides): los flags de la
    CLI (--provider, --project, --no-stream) valen solo para esa ejecución y
    no se escriben en ningún archivo. Son de la clase porque cada parte de
    Asia crea su propio SettingsManager.
    """

    overrides: dict = {}

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

        return {**data, **SettingsManager.overrides}

    @classmethod
    def set_overrides(cls, values: dict):
        cls.overrides = dict(values)

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

    def code_extensions(self) -> set[str]:
        return {ext.lower() for ext in self.get("code_extensions", [])}

    def text_extensions(self) -> set[str]:
        """Extensiones que Asia puede leer, buscar e indexar: código y texto."""
        return self.code_extensions() | {
            ext.lower() for ext in self.get("text_extensions", [])
        }

    def set(self, key, value):
        data = read_json(self.path)

        data[key] = value

        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Atómico: un corte a mitad de la escritura no deja settings.json vacío.
        write_json_atomic(self.path, data, indent=4, ensure_ascii=False)

        # Un cambio explícito del usuario ("usa gemini") gana al flag de la
        # CLI durante el resto de la sesión.
        SettingsManager.overrides.pop(key, None)
