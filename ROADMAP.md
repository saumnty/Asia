# Roadmap de Asia

Estado del proyecto y trabajo pendiente. Cada fase completada indica sus commits
para poder revisar o revertir los cambios.

## Completado

| Fase | Contenido | Commits |
|---|---|---|
| 1. Bugs | Streaming que devolvía `None` ("Asia: None"), `generate_code` roto, historial de chat sin límite y mezclado con prompts internos, Gemini sin key impedía arrancar, colecciones RAG con nombres inválidos, reindexado que no actualizaba, manejo de errores. | `d16ec0d4` |
| 2. Configuración | `config/defaults.json` (versionado) + `config/settings.json` (local). Rutas absolutas para datos internos (`core/paths.py`); las rutas del usuario se resuelven contra su carpeta actual. Una sola fuente para el proyecto activo. | `8641e54a` |
| — | El analizador estático solo aplica el parser de Python a `.py`. | `d432d338` |
| 3. Seguridad | `open_app` sin `shell=True` ni texto libre; escritura fuera de la carpeta actual y `create_file` sobre archivos existentes pasan por "confirmar cambio"; archivos protegidos comparados por ruta resuelta. | `aaef0db5`, `1bf8ff24`, `b6e9c7dc`, `69ebf064` |
| — | Proyectos no Python: carpetas de build/IDE ignoradas sin recorrerlas (`target`, `build`, `.gradle`, `.m2`, `bin`, `obj`…) y una sola lista de extensiones para seleccionar, buscar, leer e indexar. | `946c1443` |

## Próximas fases

### Fase 4: Limpieza

- Borrar archivos vacíos: `core/router.py`, `core/state.py`, `interfaces/cli.py`, `interfaces/gui.py`, `server/server.py`, `providers/openai_provider.py`, `memory/pending_change.py`, `memory/preferences.json` (JSON inválido).
- Borrar `core/llm.py` (sin uso; tiene el modelo escrito a mano).
- Unificar `core/utils/text_cleaner.py` y `core/utils/text_utils.py` (misma función `clean_text`, comportamientos distintos).
- `review_project` calcula `static_report` y no lo usa.
- `requirements.txt`: reducir los 170 paquetes heredados a los que usa el código (`ollama`, `chromadb`, `requests`, `google-genai`).
- Convertir `test/` en tests de `pytest` con carpetas temporales. Hoy `test_memory.py` y `test_project_memory.py` escriben en la memoria real (el segundo sobrescribe `memory/projects/asia.md`).
- Archivar la copia vieja en `C:\Projects\JARVIS-IA-main\Asia` (ya no la usa `C:\Tools\jarvis.bat`).

### Fase 5: Refactor de Brain

- `Brain.process` es un único método de ~1000 líneas con más de 30 `if action == ...`: pasar a un diccionario de handlers y sacar los prompts a un módulo.
- Atajos sin LLM para comandos fijos (salir, confirmar/cancelar cambio, mostrar cambio pendiente).
- Recortar el prompt del IntentEngine (~350 líneas por mensaje) y resolver reglas que se contradicen ("corrige/mejora" apunta a `generate_code`, `smart_refactor` y `debug_project`).
- Pendientes menores detectados en la fase 3:
  - `smart_refactor` no aplica la lista de archivos protegidos (solo `generate_code` lo hace).
  - "Proyecto activo" es solo un nombre; asociarle una ruta permitiría limitar la escritura al proyecto y no solo a la carpeta actual.

## Fases futuras (diseño pendiente)

### Multi-modelo según tipo de tarea

**Objetivo:** usar varios modelos de Ollama según la naturaleza del prompt. Por ejemplo, `qwen2.5-coder:7b` para código, un modelo de razonamiento destilado (tipo `deepseek-r1`) para matemáticas/física y un generalista para conversación e inglés.

**Punto de partida:** desde la fase 2 los modelos ya no están en el código: `ollama_model`, `intent_model` y `embedding_model` viven en `config/defaults.json`. Queda `core/llm.py` (sin uso, se elimina en la fase 4).

**Qué falta:**
- Parametrizar el modelo por llamada: `OllamaProvider.complete(messages, model=...)` y `ProviderRouter.ask/chat(..., model=...)`, con el valor de config como default.
- Un mapa `dominio -> modelo` en config (`"models_by_domain": {"code": ..., "math": ..., "general": ...}`).
- Un clasificador de dominio que decida el modelo **antes** de cargarlo. Opciones, de más barata a más cara:
  1. Que el IntentEngine devuelva también un campo `domain` en el mismo JSON que ya genera (sin llamadas extra).
  2. Reglas por palabras clave como primer filtro.
  3. Un modelo clasificador pequeño dedicado.

**Trade-off a documentar en el diseño:**
- Cambiar de modelo en Ollama no es instantáneo: hay que descargar uno de la VRAM y cargar otro (segundos con un 7B, más con modelos grandes). Ollama mantiene el último modelo cargado unos minutos (`keep_alive`).
- Si `intent_model` y el modelo de respuesta son distintos, cada mensaje puede provocar dos cargas. Hoy los dos son `qwen2.5-coder:7b`, así que no hay recarga.
- Regla de diseño: elegir el modelo al empezar una conversación y mantenerlo mientras siga activa ("modelo pegajoso"); cambiar solo si el dominio cambia claramente y de forma sostenida, o si el usuario lo pide.

### RAG más allá de código

Dos colecciones nuevas en ChromaDB, separadas de las de proyectos. Usar un prefijo reservado (p. ej. `asia__`) para que no choquen con nombres de proyecto.

- **Historial de conversaciones** (`asia__chat`): indexar cada intercambio usuario/asistente para recuperar contexto pasado por similitud, más allá de los 20 mensajes del historial en memoria. A definir: cuándo se indexa (al terminar cada respuesta), metadatos (fecha, proyecto activo), retención y cómo borrar. Contiene datos personales: no debe entrar en las tools de análisis ni en los índices de proyectos.
- **Base de conocimiento manual** (`asia__knowledge`): material que el usuario indexa a mano (fórmulas, apuntes, reglas de la universidad), con un comando explícito para agregar o eliminar fuentes y metadatos de origen para poder citarlas. Objetivo: reducir alucinaciones en **datos puntuales verificables**. No mejora el razonamiento: eso depende del modelo, no del dataset.

### Alucinación en revisiones largas

**Observaciones:**
- *Antes de `d432d338` (confirmado):* reportes de "línea 1 vacía / error de sintaxis" en archivos Java de `practica2`. Causa: el analizador estático aplicaba el parser de Python a `.java` y el LLM tomaba ese error como evidencia. Corregido.
- *Observado por el usuario, sin registro:* `EstadoTicket.java` reportado como vacío aunque `read_file_preview` entregaba el contenido completo. Sin marca de tiempo para saber si fue antes o después del fix. Si se repite con el fix aplicado, se atribuye a pérdida de coherencia del modelo (`qwen2.5-coder:7b`) en revisiones largas.

**Hipótesis a verificar antes de diseñar:**
- Desde la fase 1, cada revisión por archivo es una llamada independiente (`ProviderRouter.ask`, sin historial), así que no hay "memoria" que se degrade entre archivos.
- El prompt final de `review_project` concatena todos los reportes por archivo y puede superar la ventana de contexto que Ollama usa por defecto (`num_ctx`). Si es así, Ollama recorta el prompt **sin avisar** y el modelo trabaja con información parcial. Comprobarlo midiendo los tokens del prompt y probando con `num_ctx` explícito en `options`.

**Opciones a evaluar:**
- Procesar en lotes más pequeños (p. ej. 5 archivos por síntesis) y combinar los resúmenes.
- Exponer un modo explícito "archivo por archivo" para revisiones críticas, sin síntesis final.
- Configurar `num_ctx` según el tamaño del prompt.

### CLI enriquecida

- Modo multilínea para pegar bloques largos de código, terminado con `FIN` en una línea sola.
- Entrada por stdin/pipes: `Get-Content archivo.py | jarvis "explica esto"`.
- Análisis directo de un archivo: `jarvis "analiza archivo.py"`, con la ruta resuelta contra la carpeta del usuario (`Session.get_user_cwd()`). Las tools de archivos ya resuelven rutas relativas contra esa carpeta desde la fase 2; lo que falta es un camino directo que no dependa de que el IntentEngine acierte la acción.
- Flags: `--project`, `--provider`, `--no-stream`.
- Reemplazar `jarvis.bat` por un ejecutable nativo, para evitar el "¿Desea terminar el trabajo por lotes (S/N)?" de Windows al interrumpir con Ctrl+C.
