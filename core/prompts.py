"""Prompts de las acciones de Brain.

El texto se copió tal cual de core/brain.py en el refactor de la fase E,
incluidos los saltos de línea y la indentación de algunos (que llegan así al
modelo). test/test_brain_golden.py compara cada prompt con el que se enviaba
antes: cambiar uno es un cambio de comportamiento.
"""


# --- Memoria del proyecto ----------------------------------------------------

def summarize_and_save_project(project_name, content):
    return f"""
Crea un resumen actualizado del proyecto.

Debe incluir:
- Nombre del proyecto
- Objetivo
- Arquitectura actual
- Componentes importantes
- Estado actual
- Siguientes pasos recomendados

Proyecto:
{project_name}

Contenido:
{content}
"""


def ask_project_memory(project_name, project_summary, question):
    return f"""
Responde la pregunta usando el resumen guardado del proyecto.

Proyecto:
{project_name}

Resumen guardado:
{project_summary}

Pregunta:
{question}
"""
