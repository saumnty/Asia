import json
import re
import sys

from config.settings_manager import SettingsManager
from core import timing
from core.confidential import is_local_mode, is_open_mode, ollama_is_external, only_user
from core.interruptible import call as interruptible_call
from core.provenance import NEVER_EXPORT, current_fragments, labels_of, local_labels
from core.audit import log_external_send
from core.secrets_filter import redact_messages
from providers.ollama_models import drop_client, strip_think, think_kwargs, unload_others
from providers.ollama_provider import ollama_options


# Prompt del IntentEngine. Texto fijo: Ollama reutiliza su caché entre mensajes.
# core/voice/vocabulary.py saca de aquí los verbos de las órdenes.
INTENT_PROMPT = """
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
run_sandbox,

Formato exacto:
{"action": "<una de las acciones disponibles>", "params": {...}}

Reglas generales:
- Si el mensaje no pide ninguna acción, usa chat.
- No inventes información ni rutas: usa solo las que escribió el usuario. Conserva el valor escrito por el usuario.
- folder_path es "." si el usuario habla del proyecto sin nombrar una carpeta.
- request es el mensaje del usuario copiado tal cual, sin agregar ni quitar nada.

Memoria:
- "recuerda que", "guarda que", "mi X es" -> remember. "cuál es mi X", "cómo se llama mi X" -> recall. "borra", "olvida", "elimina" un dato -> forget.
- Usa SIEMPRE estas keys: universidad, proyecto, nombre.
- Otras keys: en minúsculas y con guion bajo en vez de espacios (color_favorito).

Archivos y proyecto:
- Abrir una aplicación -> open_app.
- "lista la carpeta", "muestra archivos" -> list_folder.
- "explica", "explícame" o "qué hace" un archivo -> explain_file. "resume" un archivo -> summarize_file.
- Una clase, función o método -> explain_symbol. Dónde se usa algo -> find_references. Quién lo importa o depende de él -> find_dependencies.

Revisar sin modificar:
- Revisar un archivo -> review_file. Encontrar todos los bugs, analizar a fondo o revisar profundamente un archivo -> review_file_deep.
- "revisa", "analiza", "audita" o "encuentra bugs" sobre una carpeta o el proyecto -> review_project. Si pide "sin síntesis", "sin resumen" o "solo los reportes por archivo", agrega "synthesis": false.
- "encuentra por qué...", "por qué aparece...", "por qué falla..." o buscar la causa de un bug sin decir en qué archivo está -> debug_project (solo diagnostica, no modifica).

Modificar código:
- Refactorizar, limpiar, mejorar estilo, ordenar, simplificar o hacer más mantenible un archivo, sin cambiar su comportamiento -> smart_refactor.
- Corregir, arreglar, reparar o modificar un archivo concreto, o generar código nuevo -> generate_code.
- Arreglar o corregir un bug sin decir en qué archivo está, buscando en varios archivos -> debug_project.
- Ejecutar, correr o probar un script o el cambio pendiente -> run_sandbox. Sin archivo, params vacío: se prueba el cambio pendiente.

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

Usuario: agrega al archivo pruebas/hola.txt el texto desde Asia
{"action":"append_file","params":{"file_path":"pruebas/hola.txt","content":"desde Asia"}}

Usuario: lista la carpeta tools
{"action":"list_folder","params":{"folder_path":"tools"}}

Usuario: busca archivos llamados hola
{"action":"search_files","params":{"query":"hola","folder_path":"."}}

Usuario: busca la palabra Ollama dentro del proyecto
{"action":"search_text","params":{"query":"Ollama","folder_path":"."}}

Usuario: muéstrame un resumen del archivo core/brain.py
{"action":"read_file_preview","params":{"file_path":"core/brain.py"}}

Usuario: resume el archivo core/brain.py
{"action":"summarize_file","params":{"file_path":"core/brain.py"}}

Usuario: resume la carpeta core
{"action":"summarize_folder","params":{"folder_path":"core"}}

Usuario: resume el proyecto y guarda el resumen
{"action":"summarize_and_save_project","params":{"folder_path":"."}}

Usuario: según mi proyecto, qué falta hacer?
{"action":"ask_project_memory","params":{"question":"qué falta hacer"}}

Usuario: actualiza el proyecto: ToolRegistry ya está implementado y funcionando
{"action":"update_project_memory","params":{"note":"ToolRegistry ya está implementado y funcionando"}}

Usuario: qué provider estás usando?
{"action":"show_settings","params":{}}

Usuario: cambia el provider a ollama
{"action":"set_provider","params":{"provider":"ollama"}}

Usuario: cambia al proyecto PT
{"action":"set_active_project","params":{"project_name":"pt"}}

Usuario: qué proyecto está activo?
{"action":"show_active_project","params":{}}

Usuario: busca con rag dónde está el provider router
{"action":"search_project_rag","params":{"question":"dónde está el provider router"}}

Usuario: indexa la carpeta core
{"action":"index_project_rag","params":{"project_path":"core"}}

Usuario: explícame tools/file_tool.py
{"action":"explain_file","params":{"file_path":"tools/file_tool.py"}}

Usuario: dónde se usa ProviderRouter
{"action":"find_references","params":{"query":"ProviderRouter","folder_path":"."}}

Usuario: explica la clase Brain
{"action":"explain_symbol","params":{"symbol":"Brain","folder_path":"."}}

Usuario: muéstrame la arquitectura del proyecto
{"action":"map_project","params":{"folder_path":"."}}

Usuario: quién importa ProviderRouter
{"action":"find_dependencies","params":{"query":"ProviderRouter","folder_path":"."}}

Usuario: revisa core/brain.py
{"action":"review_file","params":{"file_path":"core/brain.py"}}

Usuario: analiza a fondo pruebas/buggy_calculator.py
{"action":"review_file_deep","params":{"file_path":"pruebas/buggy_calculator.py"}}

Usuario: revisa la carpeta pruebas
{"action":"review_project","params":{"folder_path":"pruebas"}}

Usuario: encuentra posibles causas del bug Asia None
{"action":"debug_project","params":{"issue":"encuentra posibles causas del bug Asia None","folder_path":"."}}

Usuario: revisa el proyecto sin resumen, solo los reportes de cada archivo
{"action":"review_project","params":{"folder_path":".","synthesis":false}}

Usuario: busca código muerto
{"action":"detect_dead_code","params":{"folder_path":"."}}

Usuario: refactoriza tools/file_tool.py
{"action":"smart_refactor","params":{"file_path":"tools/file_tool.py","request":"refactoriza tools/file_tool.py"}}

Usuario: mejora core/utils/text_utils.py sin cambiar su comportamiento
{"action":"smart_refactor","params":{"file_path":"core/utils/text_utils.py","request":"mejora core/utils/text_utils.py sin cambiar su comportamiento"}}

Usuario: corrige core/utils/text_utils.py para que ya no tenga errores
{"action":"generate_code","params":{"request":"corrige core/utils/text_utils.py para que ya no tenga errores"}}

Usuario: arregla tools/file_tool.py
{"action":"generate_code","params":{"request":"arregla tools/file_tool.py"}}

Usuario: genera una función para limpiar texto
{"action":"generate_code","params":{"request":"genera una función para limpiar texto"}}

Usuario: arregla el bug Asia None
{"action":"debug_project","params":{"issue":"arregla el bug Asia None","folder_path":"."}}

Usuario: prueba el cambio pendiente
{"action":"run_sandbox","params":{}}

Usuario: corre pruebas/buggy_calculator.py en el sandbox
{"action":"run_sandbox","params":{"file_path":"pruebas/buggy_calculator.py"}}

Usuario: confirmar cambio
{"action":"apply_change","params":{}}

Usuario: cancelar cambio
{"action":"cancel_change","params":{}}

Usuario: muestra el cambio pendiente
{"action":"show_pending_change","params":{}}
"""


class IntentEngine:
    def __init__(self):
        self.settings = SettingsManager()
        self._client = None

    @property
    def client(self):
        """Cliente de Ollama. Se importa al primer uso: la librería tarda ~2 s en cargar."""
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.settings.get("ollama_host"))

        return self._client

    @client.setter
    def client(self, client):
        self._client = client

    def cancel(self):
        """Ctrl+C: cierra la conexión para que Ollama deje de generar."""
        drop_client(self)

    def preload(self):
        """Carga intent_model en Ollama sin prompt, para que el primer mensaje no espere la carga.

        No envía contenido. Si Ollama no responde no pasa nada; otro error
        (p. ej. el modelo no está descargado) se avisa por stderr.
        """
        model = self.settings.get("intent_model")

        # Aquí, en el hilo de la precarga: la librería carga mientras se
        # escribe el primer mensaje. Si ese mensaje llega antes, espera a que termine.
        import httpx

        try:
            unload_others(self.client, model, self.settings)
            # Una llamada sin prompt solo carga el modelo (keep_alive no se toca).
            # Con el mismo num_ctx que las llamadas reales: sin él Ollama lo
            # carga con 4096 y la primera llamada lo vuelve a cargar (~20 s).
            self.client.generate(model=model, options={"num_ctx": self.settings.get("ollama_num_ctx")})
        except (ConnectionError, httpx.HTTPError):
            return
        except Exception as e:
            print(f"[Aviso] No pude precargar {model} en Ollama: {e}", file=sys.stderr)

    def detect(self, text: str) -> dict:
        system_prompt = INTENT_PROMPT

        # Si Ollama no responde, se trata como chat: el provider configurado
        # (que puede no ser Ollama) contestará o mostrará el error.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        # Con Ollama en otra máquina, el mensaje sale de aquí: solo si es
        # exportable y no estamos en modo local (fase G). Si no, chat: el
        # router aplicará la política y lo dirá.
        if ollama_is_external(self.settings):
            labels = labels_of(current_fragments() or only_user(text))

            open_mode = is_open_mode(self.settings)
            blocked = labels & NEVER_EXPORT or local_labels(labels, self.settings) and not open_mode

            if is_local_mode(self.settings) or blocked:
                return {"action": "chat", "params": {}}

            messages, secrets = redact_messages(messages)
            authorization = "modo abierto" if open_mode else "exportable"
            log_external_send("ollama", self.settings.get("intent_model"), labels, messages, authorization, len(secrets))

        try:
            model = self.settings.get("intent_model")

            def ask_model(emit):
                unload_others(self.client, model, self.settings)
                # Sin razonamiento: con think el modelo tarda más y escribe antes
                # del JSON (qwen3).
                return self.client.chat(
                    model=model,
                    messages=messages,
                    options=ollama_options(self.settings, messages, temperature=0),
                    **think_kwargs(self.client, model, False)
                )

            response = interruptible_call(ask_model, cancel=self.cancel)
        except Exception:
            return {"action": "chat", "params": {}}

        timing.intent_metrics(response)
        content = strip_think(response["message"]["content"]).strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)

        if not match:
            return {"action": "chat", "params": {}}

        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"action": "chat", "params": {}}