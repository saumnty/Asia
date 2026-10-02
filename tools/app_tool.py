import json
import os
import re
import shutil
import subprocess

from core.paths import APPS_FILE
from tools.app_resolver import find_start_app


# "explorer.exe shell:AppsFolder\<AppID>" (o solo "shell:AppsFolder\<AppID>").
APPS_FOLDER_PATTERN = re.compile(
    r"^\s*(?:explorer(?:\.exe)?\s+)?shell:AppsFolder\\(?P<app_id>\S+)\s*$",
    re.IGNORECASE
)


def launch(entry: str):
    """Abre una entrada de apps.json sin pasar por un shell.

    Así ningún carácter del texto (&, |, ;) se interpreta como otro comando.
    """
    match = APPS_FOLDER_PATTERN.match(entry)

    if match:
        subprocess.Popen([
            "explorer.exe",
            f"shell:AppsFolder\\{match.group('app_id')}"
        ])
        return

    # Nombre de programa ("chrome", "code") o ruta: Windows lo resuelve por
    # PATH o por "App Paths", sin interpretar el texto como un comando.
    os.startfile(shutil.which(entry) or entry)


class AppTool:
    def __init__(self, config_file=APPS_FILE):
        self.config_file = config_file

    def load_apps(self):
        if not self.config_file.exists():
            return {}

        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_apps(self, apps):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=4)

    def open_app(self, app_name: str):
        """Abre una app de apps.json o del menú Inicio (Get-StartApps).

        El nombre lo extrae el LLM, así que nunca se ejecuta como comando:
        si no corresponde a una app conocida, no se abre nada.
        """
        if not isinstance(app_name, str) or not app_name.strip():
            return "No encontré qué aplicación abrir."

        apps = self.load_apps()
        app_key = app_name.lower().strip()

        command = apps.get(app_key)

        if not command:
            found = find_start_app(app_key)

            if found:
                command = f"explorer.exe shell:AppsFolder\\{found['appid']}"
                apps[app_key] = command
                self.save_apps(apps)

        if not command:
            return (
                f"No encontré la aplicación '{app_name}'. "
                f"Puedes agregarla en config/apps.json."
            )

        try:
            launch(command)
            return f"Abriendo {app_name}."
        except Exception as e:
            return f"No pude abrir {app_name}. Error: {e}"
