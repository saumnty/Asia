import json
from pathlib import Path


class SettingsManager:

    def __init__(self):
        self.path = Path("config/settings.json")

    def load(self):
        if not self.path.exists():
            return {}

        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get(self, key, default=None):
        data = self.load()
        return data.get(key, default)

    def set(self, key, value):
        data = self.load()

        data[key] = value

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )