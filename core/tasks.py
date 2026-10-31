"""Pendientes del usuario (fase R): /pendiente, /pendientes y /hecho.

Se guardan en data/reflexion/pendientes.json, solo en local y con escritura
atómica. Los cerrados se conservan con su fecha: /hecho no borra nada. Cada
pendiente lleva la etiqueta de origen "usuario" porque lo escribió él.
"""
import json
from datetime import datetime

from core import paths
from core.atomic_write import write_json_atomic
from core.provenance import USUARIO


class TaskList:
    def __init__(self, path=None):
        self.path = path or paths.TASKS_FILE

    def load(self) -> list:
        if not self.path.exists():
            return []

        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, tasks):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, tasks)

    def add(self, text: str) -> dict:
        tasks = self.load()
        task = {
            "texto": text,
            "origen": USUARIO,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "hecho": None,
        }
        tasks.append(task)
        self.save(tasks)
        return task

    def open_tasks(self) -> list:
        return [task for task in self.load() if not task["hecho"]]

    def close(self, number: int):
        """Cierra el pendiente con ese número en open_tasks(). None si no existe."""
        tasks = self.load()
        still_open = [task for task in tasks if not task["hecho"]]

        if not 1 <= number <= len(still_open):
            return None

        task = still_open[number - 1]
        task["hecho"] = datetime.now().isoformat(timespec="seconds")
        self.save(tasks)
        return task


def numbered(tasks) -> str:
    return "\n".join(f"{i}. {task['texto']}" for i, task in enumerate(tasks, 1))
