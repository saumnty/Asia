import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from core.atomic_write import write_json_atomic
from core.paths import APPS_FILE, APPS_LEARNED_NAME
from tools.app_resolver import clarification, close_app, find_start_app, resolve_known_app


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
    def __init__(self, config_file=APPS_FILE, learned_file=None):
        self.config_file = Path(config_file)
        # Las apps que se encuentran en el menú Inicio se guardan aparte
        # (apps_learned.json, en .gitignore): apps.json es del repositorio y
        # aprenderlas ahí lo dejaba con cambios sin commitear.
        self.learned_file = Path(learned_file) if learned_file else self.config_file.with_name(APPS_LEARNED_NAME)

    def load_apps(self):
        if not self.config_file.exists():
            return {}

        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_apps(self, apps):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        # Atómico: un corte a mitad de la escritura no deja apps.json vacío.
        write_json_atomic(self.config_file, apps, ensure_ascii=False, indent=4)

    def load_learned(self):
        """Apps aprendidas del menú Inicio; {} si el archivo falta o está roto."""
        try:
            with open(self.learned_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

        return data if isinstance(data, dict) else {}

    def learn(self, key, command):
        learned = self.load_learned()
        learned[key] = command
        self.learned_file.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.learned_file, learned, ensure_ascii=False, indent=4)

    def known_apps(self):
        """apps.json y las aprendidas; si una clave está en los dos, gana apps.json."""
        return {**self.load_learned(), **self.load_apps()}

    def open_app(self, app_name: str):
        """Abre una app de apps.json o del menú Inicio (Get-StartApps).

        El nombre lo extrae el LLM, así que nunca se ejecuta como comando:
        si no corresponde a una app conocida, no se abre nada.
        """
        if not isinstance(app_name, str) or not app_name.strip():
            return "No encontré qué aplicación abrir."

        apps = self.known_apps()
        app_key = app_name.lower().strip()

        # Primero el nombre exacto o una variante conocida ("notebook"), luego
        # el menú Inicio y, al final, un nombre casi igual de apps.json: así
        # "notepad++", si está instalado, no se abre como "notepad".
        known = resolve_known_app(app_name, apps)
        command = apps.get(known) if known else None

        if not command:
            found = find_start_app(app_key)

            if found:
                command = f"explorer.exe shell:AppsFolder\\{found['appid']}"
                apps[app_key] = command
                self.learn(app_key, command)

        if not command:
            close = close_app(app_name, apps)
            command = apps.get(close) if close else None

        if not command:
            return clarification(app_name, apps)

        try:
            launch(command)
            return f"Abriendo {app_name}."
        except Exception as e:
            return f"No pude abrir {app_name}. Error: {e}"
