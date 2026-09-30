import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from memory.project_memory import ProjectMemory

project_memory = ProjectMemory()

project_memory.save_project_summary(
    "Asia",
    """# Proyecto Asia

Asia es el nuevo asistente local tipo Jarvis.

## Objetivo
Crear un asistente modular con Ollama local, memoria persistente, tools, providers y futuro RAG.

## Estado actual
- Ollama funcionando.
- Provider Router funcionando.
- Brain funcionando.
- MemoryManager funcionando.
- Intent Engine funcionando.
"""
)

print(project_memory.load_project_summary("Asia"))