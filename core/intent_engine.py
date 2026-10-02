import json
import re
import ollama

from config.settings_manager import SettingsManager
from providers.ollama_provider import ollama_options


class IntentEngine:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = ollama.Client(host=self.settings.get("ollama_host"))

    def detect(self, text: str) -> dict:
        system_prompt = """
Eres un motor de intenciones. NO eres asistente conversacional.

Responde ÚNICAMENTE con JSON válido.
No expliques.
No pidas disculpas.
No agregues texto fuera del JSON.

Acciones disponibles:
remember, 
recall, 
forget, 
open_app, 
create_file, 
read_file, 
list_folder, 
append_file, 
search_files, 
search_text, 
read_file_preview, 
summarize_file, 
chat, 
summarize_folder, 
summarize_and_save_project, 
ask_project_memory,
update_project_memory,
show_settings,
set_provider,
search_project_rag,
index_project_rag,
set_active_project,
show_active_project,
explain_file,
find_references,
explain_symbol,
map_project,
find_dependencies,
review_file,
review_project,
detect_dead_code,
generate_code,
apply_change,
cancel_change,
show_pending_change,
debug_project,
review_file_deep,
smart_refactor,

Formato exacto:
{
  "action": "remember|recall|forget|open_app|create_file|read_file|list_folder|chat",
  "params": {}
}

Reglas:
- Si el usuario dice "recuerda que", "guarda que", "mi X es", usa remember.
- Si pregunta "cuál es mi X", "cómo se llama mi X", usa recall.
- Si dice "borra", "olvida", "elimina", usa forget.
- Para universidad, usa SIEMPRE key: "universidad".
- Para proyecto, usa SIEMPRE key: "proyecto".
- Para nombre, usa SIEMPRE key: "nombre".
- No inventes información.
- Conserva el valor escrito por el usuario.
- Si el usuario pide abrir una aplicación, usa open_app.
- Si el usuario pide arreglar, corregir, depurar, investigar o encontrar la causa de un bug en varios archivos, usa debug_project.
- Si solo pide revisar un archivo sin modificarlo, usa review_file.
- Si el usuario pide corregir, modificar, refactorizar, mejorar o reparar un archivo específico, usa generate_code independientemente de la extensión del archivo.
- Si el usuario pide encontrar todos los bugs, analizar a fondo o revisar profundamente un archivo específico, usa review_file_deep.
- Si el usuario dice "lista la carpeta" o "muestra archivos", usa list_folder.
- Si el usuario dice "revisa", "analiza", "audita" o "encuentra bugs" sobre una carpeta/proyecto, usa review_project.
- Si el usuario pide refactorizar, limpiar, mejorar estilo, ordenar, simplificar o hacer más mantenible un archivo específico, usa smart_refactor.

Ejemplos:
Usuario: recuerda que mi universidad es la Universidad Autónoma Metropolitana (UAM)
{"action":"remember","params":{"key":"universidad","value":"Universidad Autónoma Metropolitana (UAM)"}}

Usuario: cuál es mi universidad?
{"action":"recall","params":{"key":"universidad"}}

Usuario: borra mi universidad
{"action":"forget","params":{"key":"universidad"}}

Usuario: explícame Python
{"action":"chat","params":{}}

Usuario: abre chrome
{"action":"open_app","params":{"app_name":"chrome"}}

Usuario: crea un archivo pruebas/hola.txt con el texto hola mundo
{"action":"create_file","params":{"file_path":"pruebas/hola.txt","content":"hola mundo"}}

Usuario: lee pruebas/hola.txt
{"action":"read_file","params":{"file_path":"pruebas/hola.txt"}}

Usuario: lista la carpeta tools
{"action":"list_folder","params":{"folder_path":"tools"}}

Usuario: recuerda que mi proyecto se llama Asia
{"action":"remember","params":{"key":"proyecto","value":"Asia"}}

Usuario: cuál es mi proyecto?
{"action":"recall","params":{"key":"proyecto"}}

Usuario: agrega al archivo pruebas/hola.txt el texto desde Asia
{"action":"append_file","params":{"file_path":"pruebas/hola.txt","content":"desde Asia"}}

Usuario: busca archivos llamados hola
{"action":"search_files","params":{"query":"hola","folder_path":"."}}

Usuario: busca hola.txt en pruebas
{"action":"search_files","params":{"query":"hola.txt","folder_path":"pruebas"}}

Usuario: busca la palabra Ollama dentro del proyecto
{"action":"search_text","params":{"query":"Ollama","folder_path":"."}}

Usuario: busca MemoryManager en la carpeta memory
{"action":"search_text","params":{"query":"MemoryManager","folder_path":"memory"}}

Usuario: muéstrame un resumen del archivo core/brain.py
{"action":"read_file_preview","params":{"file_path":"core/brain.py"}}

Usuario: resume el archivo core/brain.py
{"action":"summarize_file","params":{"file_path":"core/brain.py"}}

Usuario: explícame el archivo tools/file_tool.py
{"action":"summarize_file","params":{"file_path":"tools/file_tool.py"}}

Usuario: resume la carpeta core
{"action":"summarize_folder","params":{"folder_path":"core"}}

Usuario: dame un resumen del proyecto
{"action":"summarize_folder","params":{"folder_path":"."}}

Usuario: resume el proyecto y guarda el resumen
{"action":"summarize_and_save_project","params":{"folder_path":"."}}

Usuario: según mi proyecto, qué falta hacer?
{"action":"ask_project_memory","params":{"question":"qué falta hacer"}}

Usuario: qué sabes del proyecto Asia?
{"action":"ask_project_memory","params":{"question":"qué sabes del proyecto Asia"}}

Usuario: actualiza el proyecto: ToolRegistry ya está implementado y funcionando
{"action":"update_project_memory","params":{"note":"ToolRegistry ya está implementado y funcionando"}}

Usuario: qué provider estás usando?
{"action":"show_settings","params":{}}

Usuario: cambia el provider a ollama
{"action":"set_provider","params":{"provider":"ollama"}}

Usuario: busca en el proyecto dónde se maneja gemini
{"action":"search_project_rag","params":{"question":"dónde se maneja gemini"}}

Usuario: busca con rag dónde está el provider router
{"action":"search_project_rag","params":{"question":"dónde está el provider router"}}

Usuario: usando rag dime dónde se configura ollama
{"action":"search_project_rag","params":{"question":"dónde se configura ollama"}}

Usuario: indexa el proyecto
{"action":"index_project_rag","params":{"project_path":"."}}

Usuario: reindexa el proyecto
{"action":"index_project_rag","params":{"project_path":"."}}

Usuario: indexa la carpeta core
{"action":"index_project_rag","params":{"project_path":"core"}}

Usuario: cambia al proyecto PT
{"action":"set_active_project","params":{"project_name":"pt"}}

Usuario: cambia al proyecto Asia
{"action":"set_active_project","params":{"project_name":"asia"}}

Usuario: cambia al proyecto Kabal
{"action":"set_active_project","params":{"project_name":"kabal"}}

Usuario: qué proyecto está activo?
{"action":"show_active_project","params":{}}

Usuario: proyecto activo
{"action":"show_active_project","params":{}}

Usuario: explica core/brain.py
{"action":"explain_file","params":{"file_path":"core/brain.py"}}

Usuario: qué hace providers/provider_router.py
{"action":"explain_file","params":{"file_path":"providers/provider_router.py"}}

Usuario: explícame tools/file_tool.py
{"action":"explain_file","params":{"file_path":"tools/file_tool.py"}}

Usuario: quién usa MemoryManager
{"action":"find_references","params":{"query":"MemoryManager","folder_path":"."}}

Usuario: dónde se usa ProviderRouter
{"action":"find_references","params":{"query":"ProviderRouter","folder_path":"."}}

Usuario: busca referencias de default_provider
{"action":"find_references","params":{"query":"default_provider","folder_path":"."}}

Usuario: dónde aparece cmd_vel
{"action":"find_references","params":{"query":"cmd_vel","folder_path":"."}}

Usuario: explica la clase ProviderRouter
{"action":"explain_symbol","params":{"symbol":"ProviderRouter","folder_path":"."}}

Usuario: explica la clase Brain
{"action":"explain_symbol","params":{"symbol":"Brain","folder_path":"."}}

Usuario: qué hace la función process
{"action":"explain_symbol","params":{"symbol":"process","folder_path":"."}}

Usuario: explica el método index_project
{"action":"explain_symbol","params":{"symbol":"index_project","folder_path":"."}}

Usuario: mapea el proyecto
{"action":"map_project","params":{"folder_path":"."}}

Usuario: muéstrame la arquitectura del proyecto
{"action":"map_project","params":{"folder_path":"."}}

Usuario: dame un mapa del proyecto
{"action":"map_project","params":{"folder_path":"."}}

Usuario: quién importa ProviderRouter
{"action":"find_dependencies","params":{"query":"ProviderRouter","folder_path":"."}}

Usuario: quién depende de MemoryManager
{"action":"find_dependencies","params":{"query":"MemoryManager","folder_path":"."}}

Usuario: dónde se importa RagTool
{"action":"find_dependencies","params":{"query":"RagTool","folder_path":"."}}

Usuario: qué archivos usan chromadb
{"action":"find_dependencies","params":{"query":"chromadb","folder_path":"."}}

Usuario: revisa core/brain.py
{"action":"review_file","params":{"file_path":"core/brain.py"}}

Usuario: detecta errores en providers/provider_router.py
{"action":"review_file","params":{"file_path":"providers/provider_router.py"}}

Usuario: analiza tools/rag_tool.py
{"action":"review_file","params":{"file_path":"tools/rag_tool.py"}}

Usuario: revisa todo el proyecto
{"action":"review_project","params":{"folder_path":"."}}

Usuario: encuentra problemas en el proyecto
{"action":"review_project","params":{"folder_path":"."}}

Usuario: audita el proyecto
{"action":"review_project","params":{"folder_path":"."}}

Usuario: encuentra posibles causas del bug Asia None
{"action":"review_project","params":{"folder_path":"."}}

Usuario: revisa por qué aparece Asia None
{"action":"review_project","params":{"folder_path":"."}}

Usuario: revisa todo el proyecto y encuentra por qué aparece Asia None
{"action":"review_project","params":{"folder_path":"."}}

Usuario: detecta bugs en el proyecto
{"action":"review_project","params":{"folder_path":"."}}

Usuario: busca código muerto
{"action":"detect_dead_code","params":{"folder_path":"."}}

Usuario: detecta funciones no usadas
{"action":"detect_dead_code","params":{"folder_path":"."}}

Usuario: encuentra imports innecesarios
{"action":"detect_dead_code","params":{"folder_path":"."}}

Usuario: qué archivos parecen abandonados
{"action":"detect_dead_code","params":{"folder_path":"."}}

Usuario: genera una clase ProjectPathManager
{"action":"generate_code","params":{"request":"genera una clase ProjectPathManager"}}

Usuario: crea una tool para leer archivos JSON
{"action":"generate_code","params":{"request":"crea una tool para leer archivos JSON"}}

Usuario: genera una función para limpiar texto
{"action":"generate_code","params":{"request":"genera una función para limpiar texto"}}

Usuario: crea código para listar proyectos guardados
{"action":"generate_code","params":{"request":"crea código para listar proyectos guardados"}}

Usuario: confirmar cambio
{"action":"apply_change","params":{}}

Usuario: aplicar cambio
{"action":"apply_change","params":{}}

Usuario: cancelar cambio
{"action":"cancel_change","params":{}}

Usuario: muestra el cambio pendiente
{"action":"show_pending_change","params":{}}

Usuario: corrige core/utils/text_cleaner.py para que ya no tenga errores
{"action":"generate_code","params":{"request":"corrige core/utils/text_cleaner.py para que ya no tenga errores"}}

Usuario: arregla tools/file_tool.py
{"action":"generate_code","params":{"request":"arregla tools/file_tool.py"}}

Usuario: modifica core/utils/text_utils.py para manejar None
{"action":"generate_code","params":{"request":"modifica core/utils/text_utils.py para manejar None"}}

Usuario: arregla el bug Asia None
{"action":"debug_project","params":{"issue":"arregla el bug Asia None","folder_path":"."}}

Usuario: encuentra y corrige el bug del brain
{"action":"debug_project","params":{"issue":"encuentra y corrige el bug del brain","folder_path":"."}}

Usuario: busca en archivos relevantes y arregla el error del provider
{"action":"debug_project","params":{"issue":"busca en archivos relevantes y arregla el error del provider","folder_path":"."}} 

Usuario: revisa profundamente pruebas/buggy_calculator.py
{"action":"review_file_deep","params":{"file_path":"pruebas/buggy_calculator.py"}}

Usuario: analiza a fondo pruebas/buggy_calculator.py
{"action":"review_file_deep","params":{"file_path":"pruebas/buggy_calculator.py"}}

Usuario: encuentra todos los bugs de pruebas/buggy_calculator.py
{"action":"review_file_deep","params":{"file_path":"pruebas/buggy_calculator.py"}}

Usuario: revisa la carpeta pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: analiza la carpeta pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: revisa el proyecto pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: audita la carpeta pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: encuentra bugs en la carpeta pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: refactoriza tools/file_tool.py
{"action":"smart_refactor","params":{"file_path":"tools/file_tool.py","request":"refactoriza tools/file_tool.py"}}

Usuario: mejora core/utils/text_utils.py sin cambiar su comportamiento
{"action":"smart_refactor","params":{"file_path":"core/utils/text_utils.py","request":"mejora core/utils/text_utils.py sin cambiar su comportamiento"}}

Usuario: limpia pruebas/buggy_calculator.py
{"action":"smart_refactor","params":{"file_path":"pruebas/buggy_calculator.py","request":"limpia pruebas/buggy_calculator.py"}}
"""

        # Si Ollama no responde, se trata como chat: el provider configurado
        # (que puede no ser Ollama) contestará o mostrará el error.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        try:
            response = self.client.chat(
                model=self.settings.get("intent_model"),
                messages=messages,
                options=ollama_options(self.settings, messages, temperature=0)
            )
        except Exception:
            return {"action": "chat", "params": {}}

        content = response["message"]["content"].strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)

        if not match:
            return {"action": "chat", "params": {}}

        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"action": "chat", "params": {}}