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


def summarize_document(file_path, content, words):
    return f"""
Resume este documento (no es código) en español, en {words} palabras como máximo.

Incluye:
1. De qué trata, en una o dos frases.
2. Los puntos o secciones principales.

No hables de clases, métodos ni funciones. Si el documento está recortado,
resume solo lo que aparece.

Ruta del documento:
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


def explain_document(file_path, content, words):
    return f"""
Explica este documento (no es código) en español, en {words} palabras como máximo.

Incluye:
1. Para qué sirve el documento y a quién va dirigido.
2. Cómo está organizado (secciones principales).
3. Los puntos más importantes.
4. Qué falta o qué se podría aclarar, si algo resalta.

No hables de clases, métodos ni funciones: es un documento, no un programa.
Si el documento está recortado, explica solo lo que aparece.

Documento:
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


# --- Revisión y depuración --------------------------------------------------

def review_file(file_path, content):
    return f"""
        Actúa como revisor de código Python.

        Revisa este archivo buscando:
        1. Bugs posibles
        2. Errores de flujo
        3. Código duplicado
        4. Riesgos de devolver None
        5. Mejoras de claridad
        6. Cambios recomendados

        Archivo:
        {file_path}

        Contenido:
        {content}

        Responde en español, claro y práctico.
        """


def review_project(priority_files, per_file_report):
    return f"""
Actúa como Senior Software Architect y Debugger.

Realiza una revisión completa de la carpeta o proyecto indicado.

Archivos realmente seleccionados y leídos:
{priority_files}

Reportes individuales por archivo:
{per_file_report}

Debes generar un reporte útil, práctico y priorizado.

Incluye obligatoriamente:

## Resumen general

## Hallazgos críticos
- Archivo
- Riesgo
- Evidencia exacta
- Prioridad

## Posibles bugs
- Explica causa probable
- Archivos relacionados

## Problemas de arquitectura

## Mejoras recomendadas

## Siguiente acción recomendada

Reglas anti-alucinación:
- No inventes código.
- Solo menciona funciones, clases o líneas que aparezcan literalmente en el contexto.
- Si no viste el contenido exacto de un archivo, NO propongas código para ese archivo.
- No uses ejemplos genéricos de OpenAI, response.choices, self.client, ni chat.completions si no aparecen literalmente en el contexto.
- Si no hay evidencia suficiente, responde "sin evidencia suficiente".
- No asumas el nombre del proyecto: llama al análisis "carpeta analizada".
- No reportes bugs provenientes de herramientas de análisis salvo que el usuario pida revisar esas herramientas.

Regla crítica:
- Solo puedes mencionar archivos presentes en "Archivos realmente seleccionados y leídos".
- No menciones archivos de test, pruebas o examples si no aparecen en "Archivos realmente seleccionados y leídos".
- No uses ejemplos de buggy_calculator.py salvo que ese archivo haya sido seleccionado explícitamente.
- El reporte final solo puede usar evidencia que venga de "Reportes individuales por archivo".
- No mezcles evidencia entre archivos.
- Si un archivo no tiene problemas confirmados, no lo pongas en hallazgos críticos.

Reglas de severidad:
- No marques como crítico un riesgo de seguridad genérico si no hay ejecución remota, servidor público, credenciales expuestas o escritura peligrosa sin confirmación.
- No llames "inyección de comandos" a un prompt de LLM salvo que haya ejecución directa de comandos del sistema.
- En un asistente local, prompts de usuario no son vulnerabilidad crítica por sí solos.
- Prioriza bugs funcionales reales: retornos None, respuestas duplicadas, rutas incorrectas, archivos no encontrados, errores de provider, fallos de parseo, errores de streaming.

Reglas de evidencia:
- Usa solo los hallazgos de las secciones "Detección automática" y "Citas encontradas en el archivo".
- "Detección automática" viene de una regla determinista: inclúyelos siempre.
- "Citas encontradas en el archivo" solo significa que la línea citada existe, no que el bug esté demostrado: no digas que esos hallazgos están "confirmados por evidencia".
- Si un reporte dice que el modelo no reportó problemas y no tiene detección automática, no inventes hallazgos para ese archivo.

No resumas los hallazgos individuales.
Si un reporte por archivo tiene varios hallazgos, conserva todos.
No reduzcas varios bugs a uno solo.
"""


def detect_dead_code(raw_report):
    return f"""
Actúa como analizador senior de código Python.

El siguiente reporte fue generado mediante análisis estático básico.

Reporte automático:
{raw_report}

Tu tarea:
- Ordena los hallazgos por importancia.
- Explica por qué podrían ser código muerto.
- Aclara que no debe borrarse nada sin revisión manual.
- Distingue entre confianza alta, media y baja.
- Si el reporte dice que no se encontró código muerto, responde eso claramente.

Responde con:

## Resumen

## Posible código muerto

## Confianza

## Qué revisar manualmente

## Recomendación
"""


# --- Generación de código ---------------------------------------------------

def smart_refactor(request, file_path, content, static_findings, allowed_imports):
    return f"""
Actúa como Senior Software Engineer.

El usuario quiere refactorizar este archivo.

Solicitud:
{request}

Archivo:
{file_path}

Contenido actual:
{content}

Hallazgos estáticos:
{static_findings}

Objetivo:
Mejorar claridad, mantenibilidad, estructura y estilo SIN cambiar el comportamiento.

Responde EXACTAMENTE con:

FILE_PATH:
{file_path}

CODE:
contenido completo del archivo refactorizado

EXPLANATION:
explicación breve de los cambios

Reglas:
- No uses markdown.
- No uses triple backticks.
- No pongas ```python.
- Conserva el comportamiento actual.
- No agregues dependencias innecesarias.
- Solo puedes importar: {allowed_imports}. No inventes ni agregues otras librerías.
- No elimines funciones públicas.
- No cambies nombres públicos salvo que el usuario lo pida.
- Si el archivo ya está bien, conserva el contenido y explica que no se requieren cambios importantes.

Reglas estrictas de refactor:
- No cambies returns por exceptions.
- No cambies exceptions por returns.
- No cambies prints por raises.
- No cambies valores de retorno.
- No cambies el comportamiento observable.
- Solo puedes cambiar formato, nombres internos, comentarios, estructura interna o simplificar lógica equivalente.
"""


def generate_code(request, target_file, target_file_content, project_context, debug_context, allowed_imports):
    return f"""
Actúa como Senior Python Developer.

El usuario quiere generar o corregir código para este proyecto.

Solicitud:
{request}

Archivo objetivo detectado:
{target_file}

Contenido actual del archivo objetivo:
{target_file_content}

Contexto del proyecto:
{project_context}

Diagnóstico previo disponible:
{debug_context}

Responde EXACTAMENTE con este formato:

FILE_PATH:
ruta/del/archivo.py

CODE:
contenido completo del archivo final

EXPLANATION:
explicación breve del cambio

IMPORTANTE:
- No traduzcas FILE_PATH.
- No traduzcas CODE.
- No traduzcas EXPLANATION.
- Usa exactamente esas tres etiquetas.
- No uses markdown.
- No uses triple backticks.
- No pongas ```python.
- CODE debe contener el archivo completo final.
- Si modificas un archivo existente, conserva sus imports, clases y funciones que no deban cambiarse.
- Si usas re, agrega import re.
- Si creas una función nueva, incluye todos los imports necesarios.
- Solo puedes importar: {allowed_imports}. No inventes ni agregues otras librerías.
- Si el usuario menciona un archivo .py específico, usa ese archivo como FILE_PATH.
- Si el usuario quiere crear una tool nueva, usa una ruta dentro de tools/.
- Si el usuario quiere modificar Brain, usa core/brain.py.
- Si el usuario quiere modificar IntentEngine, usa core/intent_engine.py.
- Si no estás seguro de la ruta, usa pruebas/generated_code.py.
- Si solo propones cambios menores de tipado, formato o comentarios, dilo explícitamente como "cambio menor".
"""
