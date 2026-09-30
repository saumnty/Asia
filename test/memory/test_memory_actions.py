import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from memory.memory_manager import MemoryManager

memory = MemoryManager()

memory.remember(
    "proyecto",
    "Asia"
)

print(
    memory.recall("proyecto")
)