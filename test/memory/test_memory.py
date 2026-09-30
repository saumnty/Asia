import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from memory.memory_manager import MemoryManager

memory = MemoryManager()

data = memory.load()
data["nombre"] = "Santiago"
memory.save(data)

print(memory.load())