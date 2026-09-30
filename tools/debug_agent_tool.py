from pathlib import Path


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
    
    def review_file_deep(self, file_path: str):
        content = self.tool_registry.execute(
            "read_file",
            file_path=file_path
        )

        if not content:
            return f"No pude leer el archivo: {file_path}"
        
        static_findings = self.tool_registry.execute(
            "analyze_static",
            file_path=file_path
        )

        prompt = f"""
Actúa como Senior Debugger.

Analiza profundamente este archivo buscando errores reales y casos límite.

Archivo:
{file_path}

Contenido:
{content}

Hallazgos estáticos automáticos:
{static_findings}

Reglas:
- Debes incluir obligatoriamente una sección llamada STATIC_EVIDENCE.
- Copia ahí los hallazgos estáticos automáticos con línea, riesgo, confianza y evidencia.
- No los omitas.

Busca especialmente:
- división entre cero
- listas vacías
- valores None
- índices fuera de rango
- atributos llamados sobre None
- imports faltantes
- variables no definidas
- errores de tipos
- errores lógicos
- retornos inconsistentes

Responde con este formato:

STATIC_EVIDENCE:
hallazgos estáticos automáticos relevantes

SUMMARY:
resumen breve

BUGS_FOUND:
lista numerada

RECOMMENDED_FIXES:
correcciones concretas

FIX_REQUEST:
instrucción clara para corregir el archivo completo
"""

        return self.provider_router.ask(prompt)
    
    def review_project_files(self, file_paths: list, max_chars: int = 3000):
        if not file_paths:
            return "No hay archivos para revisar."

        full_report = ""

        for file_path in file_paths:
            content = self.tool_registry.execute(
                "read_file_preview",
                file_path=file_path,
                max_chars=max_chars
            )

            static_findings = self.tool_registry.execute(
                "analyze_static",
                file_path=file_path
            )

            prompt = f"""
Actúa como Senior Debugger.

Revisa SOLO este archivo.

Archivo:
{file_path}

Contenido:
{content}

Hallazgos estáticos:
{static_findings}

Responde EXACTAMENTE con:

FILE:
{file_path}

CONFIDENCE:
alta|media|baja

CONFIRMED_ISSUES:
problemas confirmados por evidencia real del archivo

SUSPECTED_ISSUES:
sospechas razonables, si existen

OPTIONAL_IMPROVEMENTS:
mejoras opcionales, si existen

Reglas:
- No menciones otros archivos.
- No inventes funciones.
- No mezcles evidencia de otros archivos.
- Si no hay bugs claros, dilo.
- No propongas código todavía.
- Enumera TODOS los bugs o riesgos detectados, no solo el más importante.
"""

            file_report = self.provider_router.ask(prompt)

            full_report += f"""

==============================
REPORTE POR ARCHIVO
==============================

{file_report}
"""

        return full_report