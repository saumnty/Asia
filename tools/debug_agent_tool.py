from pathlib import Path

from config.settings_manager import SettingsManager
from providers.provider_router import SYSTEM_PROMPT
from tools.debug_context import (
    SPECULATIVE_WARNING,
    build_debug_context,
    context_note,
    mark_speculative,
    verify_citations,
)
from tools.review_findings import FINDING_FORMAT, HONESTY_RULES, numbered, render_report
from tools.write_safety import find_truncating_rewrites

TRUNCATED_PREVIEW_MARK = "... [archivo recortado]"

# Un problema más largo no deja sitio para los archivos.
MAX_ISSUE_CHARS = 2000

UNVERIFIED_DIAGNOSIS = (
    "Diagnóstico NO verificado: es el análisis del modelo. Solo las citas de "
    "EVIDENCIA se comprobaron contra los archivos."
)


def debug_prompt(issue: str, evidence: str, context: str) -> str:
    # El problema va al principio y se repite al final: si Ollama recortara
    # el principio del prompt, el final se conserva.
    return f"""
Actúa como DebugAgent senior para este proyecto Python.

Problema reportado:
{issue}

Evidencia encontrada (líneas con ruta:línea):
{evidence}

Archivos más relacionados con el problema (ordenados por coincidencias):
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

EVIDENCIA:
una línea por cada línea de código en que te basas, con el formato
ruta | línea copiada literalmente del archivo

RECOMMENDED_NEXT_STEP:
qué archivo revisar o corregir primero

Recuerda: el problema reportado es: {issue}
"""


class DebugAgentTool:
    name = "debug_project"
    description = "Investiga bugs buscando archivos relevantes y genera contexto para proponer fixes."

    def __init__(self, tool_registry, provider_router):
        self.tool_registry = tool_registry
        self.provider_router = provider_router

    def debug_project(self, issue: str, folder_path: str = "."):
        """Diagnóstico de un bug: una llamada al LLM, sin modificar archivos.

        El contexto entra en ollama_num_ctx (ver tools/debug_context.py) y
        las citas de EVIDENCIA se comprueban contra los archivos; el resto
        del diagnóstico no está verificado y el reporte lo dice.
        """
        base = Path(folder_path)

        if not base.is_absolute():
            base = Path.cwd() / base

        if not base.exists():
            return f"No encontré la carpeta: {base}"

        issue = issue[:MAX_ISSUE_CHARS]

        def render(evidence, context):
            return debug_prompt(issue, evidence, context)

        ctx = build_debug_context(issue, base, SettingsManager(), render, system_chars=len(SYSTEM_PROMPT))
        # Opciones de revisión (temperatura baja): con las del chat el formato
        # de EVIDENCIA cambiaba de una ejecución a otra.
        response = self.provider_router.ask(ctx.prompt, review=True)

        # Sin ninguna cita encontrada, el aviso va primero y las secciones se
        # etiquetan como especulativas: no se presentan como un diagnóstico.
        diagnosis, speculative = mark_speculative(verify_citations(response, ctx.files))
        header = f"{SPECULATIVE_WARNING}\n{UNVERIFIED_DIAGNOSIS}" if speculative else UNVERIFIED_DIAGNOSIS

        return f"{header}\n{context_note(ctx)}\n\n{diagnosis}"
    
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

        return render_report(
            file_path, response, content, show_unverified,
            auto_findings=self.automatic_findings(file_path, content)
        )

    def automatic_findings(self, file_path: str, content: str) -> list[dict]:
        """Avisos de reglas deterministas (sin LLM); solo para Python.

        Se analiza el archivo completo: si content es una vista previa
        recortada, ast no podría parsearlo.
        """
        if Path(file_path).suffix.lower() != ".py":
            return []

        if content.rstrip().endswith(TRUNCATED_PREVIEW_MARK):
            content = self.tool_registry.execute("read_file", file_path=file_path)

        return find_truncating_rewrites(content)

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
            file_report = render_report(
                file_path, response, content, show_unverified,
                auto_findings=self.automatic_findings(file_path, content)
            )

            full_report += f"""

==============================
REPORTE POR ARCHIVO
==============================

{file_report}
"""

        return full_report