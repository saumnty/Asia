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


# --- Lectura, explicación y RAG ---------------------------------------------

def summarize_file(file_path, content):
    return f"""
Resume este archivo de forma clara.

Ruta del archivo:
{file_path}

Contenido:
{content}
"""


def summarize_folder(folder_path, content):
    return f"""
Resume esta carpeta/proyecto de forma clara y breve.

Carpeta:
{folder_path}

Contenido:
{content}
"""


def search_project_rag(project_name, question, rag_context):
    return f"""
Responde la pregunta del usuario usando únicamente estos fragmentos del proyecto.

Proyecto activo:
{project_name}

Pregunta:
{question}

Fragmentos encontrados:
{rag_context}

Instrucciones:
- Responde claro y breve.
- Menciona los archivos relevantes.
- Si los fragmentos no alcanzan para responder, dilo.
"""


def explain_file(file_path, content):
    return f"""
        Actúa como arquitecto de software.

        Explica este archivo.

        Incluye:

        1. Objetivo del archivo
        2. Clases principales
        3. Métodos importantes
        4. Cómo interactúa con otros componentes
        5. Posibles mejoras

        Archivo:
        {file_path}

        Contenido:
        {content}
        """


def find_references(query, raw_results):
    return f"""
        Actúa como asistente de desarrollo.

        El usuario quiere encontrar referencias de:
        {query}

        Resultados encontrados:
        {raw_results}

        Explica:
        1. En qué archivos aparece
        2. Para qué parece usarse
        3. Qué archivo parece más importante
        4. Si no hay resultados útiles, dilo claramente

        Responde breve y claro.
        """


def explain_symbol(symbol, raw_results):
    return f"""
        Actúa como asistente de desarrollo.

        El usuario quiere entender este símbolo de código:
        {symbol}

        Resultados encontrados:
        {raw_results}

        Explica:
        1. Qué parece ser: clase, función, método, variable o configuración
        2. En qué archivos aparece
        3. Qué hace según el contexto
        4. Cómo se relaciona con el proyecto
        5. Posibles mejoras o cuidado al modificarlo

        Responde claro y breve.
        """


def map_project(content):
    return f"""
        Actúa como arquitecto de software.

        Analiza este proyecto y genera:

        1. Estructura general
        2. Componentes principales
        3. Relaciones entre componentes
        4. Flujo de ejecución
        5. Resumen de arquitectura

        Contenido:
        {content}
        """


def find_dependencies(query, raw_results):
    return f"""
        Actúa como analizador de dependencias de código.

        El usuario quiere saber qué partes del proyecto dependen de:
        {query}

        Resultados encontrados:
        {raw_results}

        Explica:
        1. Qué archivos lo importan o lo usan
        2. Qué relación tienen con {query}
        3. Cuál parece ser el flujo de dependencia
        4. Qué archivo parece más importante

        Responde breve, claro y práctico.
        """
