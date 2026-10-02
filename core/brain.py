from memory.memory_manager import MemoryManager
from core.intent_engine import IntentEngine
from tools.tool_registry import ToolRegistry
from providers.provider_router import ProviderRouter
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from core.paths import PROJECT_ROOT
from pathlib import Path
import os
import re


# Archivos de Asia que generate_code nunca propone reescribir.
PROTECTED_FILES = [
    PROJECT_ROOT / "core" / "brain.py",
    PROJECT_ROOT / "core" / "intent_engine.py",
    PROJECT_ROOT / "tools" / "tool_registry.py",
]


def normalized_path(path) -> str:
    # normcase: en Windows "CORE\Brain.py" y "core/brain.py" son el mismo archivo.
    return os.path.normcase(str(Path(path).resolve()))


def is_protected_file(file_path: str) -> bool:
    """Compara rutas resueltas, no texto: "./core/brain.py", "core\\brain.py"
    o la ruta absoluta apuntan al mismo archivo protegido. Un core/brain.py de
    otro proyecto (otra carpeta actual) no está protegido.
    """
    target = normalized_path(file_path)
    return any(target == normalized_path(protected) for protected in PROTECTED_FILES)


def parse_code_response(response):
    """Extrae FILE_PATH, CODE y EXPLANATION de una respuesta del LLM.

    Devuelve (file_path, code, explanation), o None si no hay sección CODE.
    file_path es None si el LLM no lo incluyó.
    """
    file_match = re.search(
        r"FILE_PATH:\s*(.*?)\s*CODE:",
        response,
        re.DOTALL
    )

    file_path = file_match.group(1).strip() if file_match else None

    code_start = response.find("CODE:")

    if code_start == -1:
        return None

    explanation_pos = response.find("EXPLANATION:")
    explanation_label = "EXPLANATION:"

    if explanation_pos == -1:
        explanation_pos = response.find("EXPLANACIÓN:")
        explanation_label = "EXPLANACIÓN:"

    if explanation_pos == -1:
        code_text = response[code_start + len("CODE:"):]
        explanation = ""
    else:
        code_text = response[code_start + len("CODE:"):explanation_pos]
        explanation = response[
            explanation_pos + len(explanation_label):
        ].strip()

    code = code_text.strip()
    code = code.replace("```python", "")
    code = code.replace("```", "")
    code = code.strip()

    return file_path, code, explanation


class Brain:
    def __init__(self):
        self.memory = MemoryManager()
        self.intent_engine = IntentEngine()
        self.provider_router = ProviderRouter()
        self.tool_registry = ToolRegistry(self.provider_router)
        self.project_memory = ProjectMemory()
        self.settings = SettingsManager()
        self.last_debug_report = None

    def limit(self, name):
        """Límite de contexto configurado en context_limits (settings)."""
        return self.settings.get("context_limits")[name]

    def active_project(self):
        return self.settings.get("active_project").lower().strip()

    def process(self, text):
        """Ejecuta la acción detectada en el texto.

        Devuelve None si el mensaje es conversación normal (acción "chat" o
        no reconocida); en ese caso quien llama debe usar provider_router.chat.
        """
        intent = self.intent_engine.detect(text)

        action = intent.get("action")
        params = intent.get("params")

        if not isinstance(params, dict):
            params = {}

        key = params.get("key")
        value = params.get("value")

        if action == "remember" and key and value:
            self.memory.remember(key, value)
            return f"Entendido. Recordaré que {key} es {value}."

        if action == "recall" and key:
            result = self.memory.recall(key)

            if result:
                return f"{key}: {result}"

            return f"No tengo guardado ningún dato para: {key}."

        if action == "forget" and key:
            deleted = self.memory.forget(key)

            if deleted:
                return f"Listo. Olvidé el dato: {key}."

            return f"No tenía guardado ningún dato para: {key}."

        if action == "summarize_file":
            file_path = params.get("file_path")

            if not file_path:
                return "Necesito la ruta del archivo para resumirlo."

            content = self.tool_registry.execute(
                "read_file_preview",
                file_path=file_path,
                max_chars=self.limit("summarize_file")
            )

            prompt = f"""
Resume este archivo de forma clara.

Ruta del archivo:
{file_path}

Contenido:
{content}
"""

            return self.provider_router.ask(prompt)

        if action == "summarize_folder":
            folder_path = params.get("folder_path", ".")

            content = self.tool_registry.execute(
                "read_folder_context",
                folder_path=folder_path,
                **self.limit("summarize_folder")
            )

            prompt = f"""
Resume esta carpeta/proyecto de forma clara y breve.

Carpeta:
{folder_path}

Contenido:
{content}
"""

            return self.provider_router.ask(prompt)

        if action == "summarize_and_save_project":
            folder_path = params.get("folder_path", ".")
            project_name = self.active_project()

            content = self.tool_registry.execute(
                "read_folder_context",
                folder_path=folder_path,
                **self.limit("save_project_summary")
            )

            prompt = f"""
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

            summary = self.provider_router.ask(prompt)

            self.project_memory.save_project_summary(
                project_name,
                summary
            )

            return f"Resumen actualizado y guardado para el proyecto {project_name}."

        if action == "ask_project_memory":
            question = params.get("question", text)
            project_name = self.active_project()
            project_summary = self.project_memory.load_project_summary(project_name)

            if not project_summary:
                return f"No tengo resumen guardado para el proyecto {project_name}."

            prompt = f"""
Responde la pregunta usando el resumen guardado del proyecto.

Proyecto:
{project_name}

Resumen guardado:
{project_summary}

Pregunta:
{question}
"""

            return self.provider_router.ask(prompt)

        if action == "update_project_memory":
            note = params.get("note")

            if not note:
                return "Necesito una nota para actualizar la memoria del proyecto."

            project_name = self.active_project()

            self.project_memory.append_project_note(
                project_name,
                note
            )

            return f"Memoria del proyecto {project_name} actualizada."

        if action == "show_settings":
            provider = self.settings.get("default_provider")
            fallback = self.settings.get("fallback_provider")
            stream = self.settings.get("stream_output", False)
            model = self.settings.get(f"{provider}_model")

            return (
                f"Provider actual: {provider}\n"
                f"Modelo: {model}\n"
                f"Fallback: {fallback}\n"
                f"Streaming: {stream}\n"
                f"Proyecto activo: {self.active_project()}"
            )

        if action == "set_provider":
            provider = params.get("provider")

            if not provider:
                return "Necesito saber qué provider quieres usar."

            provider = provider.lower().strip()

            aliases = self.settings.get("provider_aliases", {})
            provider = aliases.get(provider, provider)

            if provider not in self.provider_router.provider_factories:
                return f"Provider no disponible todavía: {provider}"

            self.settings.set("default_provider", provider)

            return f"Provider cambiado a: {provider}"

        if action == "set_active_project":
            project_name = params.get("project_name")

            if not project_name:
                return "Necesito saber a qué proyecto quieres cambiar."

            project_name = project_name.lower().strip()

            aliases = self.settings.get("project_aliases", {})
            project_name = aliases.get(project_name, project_name)

            self.settings.set("active_project", project_name)

            return f"Proyecto activo cambiado a: {project_name}"

        if action == "show_active_project":
            return f"Proyecto activo: {self.active_project()}"

        if action == "index_project_rag":
            project_path = params.get("project_path", ".")
            project_name = self.active_project()

            return self.tool_registry.execute(
                "index_project_rag",
                project_path=project_path,
                project_name=project_name
            )

        if action == "search_project_rag":
            question = params.get("question", text)
            project_name = self.active_project()

            rag_context = self.tool_registry.execute(
                "search_project_rag",
                question=question,
                project_name=project_name,
                n_results=5
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)

        if action == "explain_file":
            file_path = params.get("file_path")

            if not file_path:
                return "Necesito la ruta del archivo."

            content = self.tool_registry.execute(
                "read_file_preview",
                file_path=file_path,
                max_chars=self.limit("explain_file")
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "find_references":
            query = params.get("query")
            folder_path = params.get("folder_path", ".")

            if not query:
                return "Necesito saber qué referencia quieres buscar."

            raw_results = self.tool_registry.execute(
                "search_text",
                query=query,
                folder_path=folder_path
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "explain_symbol":
            symbol = params.get("symbol")
            folder_path = params.get("folder_path", ".")

            if not symbol:
                return "Necesito saber qué clase, función o método quieres explicar."

            raw_results = self.tool_registry.execute(
                "search_text",
                query=symbol,
                folder_path=folder_path
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "map_project":

            folder_path = params.get("folder_path", ".")

            content = self.tool_registry.execute(
                "read_folder_context",
                folder_path=folder_path,
                **self.limit("map_project")
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "find_dependencies":
            query = params.get("query")
            folder_path = params.get("folder_path", ".")

            if not query:
                return "Necesito saber qué dependencia, clase o módulo quieres buscar."

            raw_results = self.tool_registry.execute(
                "search_text",
                query=query,
                folder_path=folder_path
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "review_file":
            file_path = params.get("file_path")

            if not file_path:
                return "Necesito la ruta del archivo para revisarlo."

            content = self.tool_registry.execute(
                "read_file_preview",
                file_path=file_path,
                max_chars=self.limit("review_file")
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "review_project":

            folder_path = params.get("folder_path", ".")

            static_report = self.tool_registry.execute(
                "analyze_folder_static",
                folder_path=folder_path,
                max_files=40
            )

            priority_files = self.tool_registry.execute(
                "select_project_files",
                folder_path=folder_path,
                max_files=self.limit("review_project_files")
            )

            per_file_report = self.tool_registry.execute(
                "review_project_files",
                file_paths=priority_files,
                max_chars=self.limit("review_project_file")
            )

            prompt = f"""
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

## Confianza del reporte
Indica si los hallazgos son:
- Confirmados por evidencia
- Sospechas razonables
- Mejoras opcionales

No resumas los hallazgos individuales.
Si un reporte por archivo contiene varios CONFIRMED_ISSUES o SUSPECTED_ISSUES, conserva todos.
No reduzcas varios bugs a uno solo.
"""

            return self.provider_router.ask(prompt)
        
        if action == "detect_dead_code":
            folder_path = params.get("folder_path", ".")

            raw_report = self.tool_registry.execute(
                "detect_dead_code",
                folder_path=folder_path
            )

            prompt = f"""
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

            return self.provider_router.ask(prompt)
        
        if action == "debug_project":
            issue = params.get("issue", text)
            folder_path = params.get("folder_path", ".")

            debug_report = self.tool_registry.execute(
                "debug_project",
                issue=issue,
                folder_path=folder_path
            )

            self.last_debug_report = debug_report

            return f"""
            Diagnóstico de depuración:

            {debug_report}

            Si quieres que proponga un cambio automático, escribe algo como:

            genera el fix para el archivo principal usando este diagnóstico
            """
        
        if action == "review_file_deep":
            file_path = params.get("file_path")

            if not file_path:
                return "Necesito la ruta del archivo para revisarlo profundamente."

            debug_report = self.tool_registry.execute(
                "review_file_deep",
                file_path=file_path
            )

            self.last_debug_report = debug_report

            return debug_report
        
        if action == "smart_refactor":
            file_path = params.get("file_path")
            request = params.get("request", text)

            if not file_path:
                return "Necesito la ruta del archivo para refactorizarlo."

            if not Path(file_path).is_file():
                return f"No encontré el archivo: {file_path}"

            content = self.tool_registry.execute(
                "read_file",
                file_path=file_path
            )

            static_findings = self.tool_registry.execute(
                "analyze_static",
                file_path=file_path
            )

            prompt = f"""
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

            response = self.provider_router.ask(prompt)

            parsed = parse_code_response(response)

            if not parsed:
                return f"No pude extraer CODE.\n\nRespuesta recibida:\n{response}"

            # Se ignora el FILE_PATH que devuelva el LLM: el refactor siempre
            # se aplica al archivo que pidió el usuario.
            _, code, explanation = parsed

            def normalize_code(value):
                return "\n".join(
                    line.rstrip()
                    for line in value.strip().splitlines()
                )

            if normalize_code(content) == normalize_code(code):
                return f"No se requieren cambios reales en {file_path}."
            
            forbidden_changes = [
                ("return None", "raise "),
                ("print(", "raise "),
            ]

            for old_pattern, new_pattern in forbidden_changes:

                if old_pattern in content and new_pattern in code:
                    return (
                        "Refactor rechazado automáticamente.\n\n"
                        "El cambio modifica el comportamiento observable "
                        "del programa (prints/returns/excepciones)."
                    )

            apply_tool = self.tool_registry.get_apply_changes_tool()

            diff_message = apply_tool.propose_change(
                file_path=file_path,
                new_content=code
            )

            return f"""
{explanation}

{diff_message}
"""
        
        if action == "generate_code":
            request = params.get("request", text)
            
            debug_context = ""

            if self.last_debug_report and (
                "bug" in request.lower()
                or "bugs" in request.lower()
                or "diagnóstico" in request.lower()
                or "diagnostico" in request.lower()
                or "detectados" in request.lower()
            ):
                debug_context = self.last_debug_report

            target_file = None
            target_match = re.search(r"([\w./\\-]+\.[a-zA-Z0-9]+)", request)

            if target_match:
                target_file = target_match.group(1).replace("\\", "/")

            project_context = self.tool_registry.execute(
                "read_folder_context",
                folder_path=".",
                **self.limit("generate_code_project")
            )

            target_file_content = ""

            if target_file and Path(target_file).exists():
                target_file_content = self.tool_registry.execute(
                    "read_file_preview",
                    file_path=target_file,
                    max_chars=self.limit("generate_code_file")
                )

            prompt = f"""
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
- Si el usuario menciona un archivo .py específico, usa ese archivo como FILE_PATH.
- Si el usuario quiere crear una tool nueva, usa una ruta dentro de tools/.
- Si el usuario quiere modificar Brain, usa core/brain.py.
- Si el usuario quiere modificar IntentEngine, usa core/intent_engine.py.
- Si no estás seguro de la ruta, usa pruebas/generated_code.py.
- Si solo propones cambios menores de tipado, formato o comentarios, dilo explícitamente como "cambio menor".
"""

            response = self.provider_router.ask(prompt)

            parsed = parse_code_response(response)

            if not parsed:
                return f"No pude extraer CODE.\n\nRespuesta recibida:\n{response}"

            file_path, code, explanation = parsed

            # Si el usuario nombró un archivo existente, el cambio va a ese
            # archivo aunque el LLM devuelva otra ruta.
            if target_file and Path(target_file).is_file():
                file_path = target_file

            if not file_path:
                return f"No pude extraer FILE_PATH.\n\nRespuesta recibida:\n{response}"

            forbidden_changes = [
                ("return None", "raise "),
                ("print(", "raise "),
            ]

            old_content = ""

            if Path(file_path).exists():
                old_content = Path(file_path).read_text(encoding="utf-8").strip()

            new_code = code

            for old_pattern, new_pattern in forbidden_changes:

                if old_pattern in old_content and new_pattern in new_code:
                    return (
                        "Refactor rechazado automáticamente.\n\n"
                        "El cambio modifica el comportamiento observable "
                        "del programa (prints/returns/excepciones)."
                    )

            if "re." in code and "import re" not in code:
                code = "import re\n\n" + code

            if not file_path or not code:
                return f"Faltan datos para proponer el cambio.\n\nRespuesta recibida:\n{response}"
            
            if is_protected_file(file_path):
                return f"""
            Asia generó un cambio para un archivo protegido:

            {file_path}

            Por seguridad no lo aplicaré automáticamente todavía.
            Primero revisa el cambio manualmente o pide modificar un archivo menos crítico.
            """

            if old_content == code.strip():
                return f"No se requieren cambios en {file_path}."

            apply_tool = self.tool_registry.get_apply_changes_tool()

            diff_message = apply_tool.propose_change(
                file_path=file_path,
                new_content=code
            )

            return f"""
{explanation}

{diff_message}
"""
        
        if action == "apply_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.apply_pending_change()

        if action == "cancel_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.cancel_pending_change()
        
        if action == "show_pending_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.show_pending_change()

        if action in [
            "open_app",
            "create_file",
            "read_file",
            "list_folder",
            "append_file",
            "search_files",
            "search_text",
            "read_file_preview"
        ]:
            return self.tool_registry.execute(action, **params)

        # "chat" o acción no reconocida: conversación normal. El launcher la
        # envía a provider_router.chat (con memoria, historial y streaming).
        return None