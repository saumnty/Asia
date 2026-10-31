"""/pendiente, /pendientes y /hecho (core/tasks.py). Sin modelo."""
from core.tasks import TaskList, numbered

UNREADABLE = "No pude leer los pendientes (data/reflexion/pendientes.json): {error}. No toqué el archivo."


class TaskActions:
    HANDLERS = {
        "add_task": "handle_add_task",
        "list_tasks": "handle_list_tasks",
        "close_task": "handle_close_task",
    }

    def handle_add_task(self, text, params):
        task = params.get("text", "").strip()

        if not task:
            return "Escribe el pendiente: /pendiente <texto>."

        try:
            TaskList().add(task)
        except ValueError as e:
            return UNREADABLE.format(error=e)

        return f"Anotado: {task}"

    def handle_list_tasks(self, text, params):
        try:
            tasks = TaskList().open_tasks()
        except ValueError as e:
            return UNREADABLE.format(error=e)

        return f"Pendientes:\n{numbered(tasks)}" if tasks else "No hay pendientes abiertos."

    def handle_close_task(self, text, params):
        number = params.get("number", "").strip()

        if not number.isdigit():
            return "Di qué número: /hecho <n> (los números salen en /pendientes)."

        try:
            task = TaskList().close(int(number))
        except ValueError as e:
            return UNREADABLE.format(error=e)

        if task is None:
            return f"No hay un pendiente {number}. Los números salen en /pendientes."

        return f"Hecho: {task['texto']}"
