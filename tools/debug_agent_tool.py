from pathlib import Path

from tools.review_findings import FINDING_FORMAT, HONESTY_RULES, numbered, render_report


class DebugAgentTool:
    name = "debug_project"
    description = "Investiga bugs buscando archivos relevantes y genera contexto para proponer fixes."

    def __init__(self, tool_registry, provider_router):
        self.tool_registry = tool_registry
        self.provider_router = provider_router

    def debug_project(self, issue: str, folder_path: str = "."):
        searches = [
            issue,
            "return None",
            "print(",
            "provider_router.ask",
            "brain.process",
            "generate_code",
            "apply_change",
        ]

        evidence = []

        for query in searches:
            result = self.tool_registry.execute(
                "search_text",
                query=query,
                folder_path=folder_path
            )

            evidence.append(f"\n--- Búsqueda: {query} ---\n{result}")

        context = self.tool_registry.execute(
            "read_folder_context",
            folder_path=folder_path,
            max_files=25,
            max_chars_per_file=1200
        )

        prompt = f"""
Actúa como DebugAgent senior para este proyecto Python.

Problema reportado:
{issue}

Evidencia encontrada:
{''.join(evidence)}

Contexto del proyecto:
{context}

Tu tarea:
1. Identifica archivos sospechosos.
2. Explica la causa más probable.
3. NO propongas modificar archivos todavía.
4. NO inventes cambios.
5. Si no tienes evidencia suficiente, dilo claramente.
6. Prioriza archivos de entrada/salida como main.py, core/brain.py, providers/provider_router.py y tools/tool_registry.py si el bug menciona respuestas None, duplicadas o impresión en terminal.

Responde con:

SUMMARY:
resumen breve del bug

SUSPECT_FILES:
archivos sospechosos con motivo

LIKELY_CAUSE:
causa más probable

RECOMMENDED_NEXT_STEP:
qué archivo revisar o corregir primero
"""

        return self.provider_router.ask(prompt)
    
    # Las heurísticas de analyze_static (p. ej. "posible índice fuera de rango"
    # en cada df[col]) no entran en estos prompts: el modelo las repetía como
    # hallazgos y sus citas sí existen, así que pasaban la verificación.
    def review_file_deep(self, file_path: str, show_unverified: bool = False):
        content = self.tool_registry.execute(
            "read_file",
            file_path=file_path
        )

        if not content or content.startswith("No encontré"):
            return f"No pude leer el archivo: {file_path}"

        prompt = f"""
Actúa como Senior Debugger.

Analiza profundamente este archivo buscando errores reales y casos límite.

Archivo:
{file_path}

Contenido (cada línea empieza con su número):
{numbered(content)}

Busca especialmente:
- datos que se pierden o quedan corruptos si algo falla a la mitad
- colecciones vacías y valores None
- errores lógicos y retornos inconsistentes
- excepciones capturadas que ocultan un fallo

{HONESTY_RULES}

{FINDING_FORMAT}
"""

        response = self.provider_router.ask(prompt, review=True)

        return render_report(file_path, response, content, show_unverified)

    def review_project_files(self, file_paths: list, max_chars: int = 3000, show_unverified: bool = False):
        if not file_paths:
            return "No hay archivos para revisar."

        full_report = ""

        for file_path in file_paths:
            content = self.tool_registry.execute(
                "read_file_preview",
                file_path=file_path,
                max_chars=max_chars
            )

            prompt = f"""
Actúa como Senior Debugger.

Revisa SOLO este archivo.

Archivo:
{file_path}

Contenido (cada línea empieza con su número):
{numbered(content)}

{HONESTY_RULES}
- No menciones otros archivos.
- No propongas código todavía.

{FINDING_FORMAT}
"""

            response = self.provider_router.ask(prompt, review=True)
            file_report = render_report(file_path, response, content, show_unverified)

            full_report += f"""

==============================
REPORTE POR ARCHIVO
==============================

{file_report}
"""

        return full_report