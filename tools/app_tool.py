import json
import subprocess

from core.paths import APPS_FILE
from tools.app_resolver import find_start_app


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
        apps = self.load_apps()
        app_key = app_name.lower().strip()

        command = apps.get(app_key)

        if not command:
            found = find_start_app(app_key)

            if found:
                command = found["command"]
                apps[app_key] = command
                self.save_apps(apps)

        if not command:
            command = app_key

        try:
            subprocess.Popen(command, shell=True)
            return f"Abriendo {app_name}."
        except Exception as e:
            return f"No pude abrir {app_name}. Error: {e}"