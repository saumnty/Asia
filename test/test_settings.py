import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from config.settings_manager import SettingsManager

settings = SettingsManager()

print(
    settings.get(
        "default_provider"
    )
)