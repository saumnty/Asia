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
| — | Ventana de contexto de Ollama configurable (`ollama_num_ctx`, 16384) y aviso cuando un prompt no cabe. Antes se recortaban en silencio la síntesis de `review_project` y `generate_code` (ver "Alucinación en revisiones largas"). | `0b5b5c61` |
| — | `review_project`: excluye carpetas de herramientas (`.github`) al seleccionar y corrige reglas del prompt de síntesis que apuntaban a secciones inexistentes. | `985e02ec`, `f3c0eb9a` |
| 4. Limpieza | Borrados los archivos vacíos, `core/llm.py` y `core/utils/text_cleaner.py` (queda `text_utils.clean_text`). `review_project` ya no calcula `static_report`. `requirements.txt` con 4 paquetes; `pytest` en `requirements-dev.txt`. `test/` pasa a pytest con carpetas temporales; los scripts que usan Ollama o Gemini quedan en `test/manual/`. Copia vieja archivada en `C:\Projects\JARVIS-IA-main\Asia-archivo.zip` (la carpeta sigue sin borrar). | `254dc3cd` |
| — | `review_project` sin síntesis: devuelve los reportes por archivo sin llamar al LLM si el mensaje dice "sin síntesis"/"por archivo", si el IntentEngine manda `synthesis: false` o con `review_project_synthesis: false` en config (default `true`). `smart_refactor` rechaza los archivos protegidos antes de llamar al LLM. | `284c1bdc` |
| B2. Hallazgos falsos | `review_file_deep` y `review_project_files`: cada hallazgo con línea, cita y claim; la cita se verifica sin LLM, se corrige la línea y se descartan citas inexistentes y repetidos. Solo se muestra "VERIFICADO (cita encontrada)", salvo que se pida "muestra todo". `analyze_static` sale de esos prompts. `ollama_temperature`/`ollama_repeat_penalty` solo en revisiones. Banco de calidad en `test/manual/` (ver "Alucinación en revisiones largas"). | `b4b288c3`, `65b68774`, `be698d1a` |
| B3. Truncado determinista | La etiqueta pasa a "Citas encontradas en el archivo (análisis del modelo, no verificado)". `tools/write_safety.py`: regla con `ast`, sin LLM, que avisa si un script lee un archivo y luego lo abre con `"w"` sin respaldo ni temporal; va en la sección "Detección automática". Caso negativo `guardar_seguro.py` en el banco. | `46469f71`, `eae58942` |
| — | Escritura atómica de `memory.json` (`MemoryManager.save`) y `settings.json` (`SettingsManager.set`): temporal en la misma carpeta + `os.replace` (`core/atomic_write.py`). Un fallo a medias deja el original intacto. Mismo formato byte a byte. | `5127354e` |
| — | Escritura atómica también en `config/apps.json` (`save_apps`), resúmenes de proyecto (`save_project_summary`) y `pending_change.json`. `write_text_atomic` en `core/atomic_write.py`; `write_json_atomic` la reutiliza. | `b40e8a44` |
| C. CLI tipo chat | Adjuntos con `@ruta` (o `@"ruta con espacios"`), `--file` repetible y stdin (`Get-Content a.py \| jarvis "explica esto"`), con límite `attachment_max_chars` y aviso al recortar; las acciones reciben la ruta absoluta y el chat el contenido; el historial guarda el mensaje sin el contenido. Autocompletado de rutas al escribir `@` (`prompt_toolkit`). Flags `--provider`, `--project` y `--no-stream` solo para esa ejecución (`SettingsManager.overrides`, no escriben `settings.json`). Multilínea en modo interactivo: mensaje que termina en `<<`, cierre con `FIN`. | `af003d2a`, `4f25b229` |
| — | Fallos de la fase C encontrados en PowerShell real: (1) el multilínea no funcionaba con un pegado real, porque `prompt_toolkit` entrega el pegado entero en una lectura y `FIN` dentro del pegado no cerraba el bloque. Las pruebas simulaban líneas escritas una a una; ahora hay pruebas con una `PromptSession` real y bracketed paste. (2) El IntentEngine inventa rutas (`path/to/your/file.py`, `ruta/al/archivo`) y la acción intentaba leerlas: ahora solo se usan rutas que salen del mensaje; si no, se pide la ruta o se trata como chat. | `26bd6a13`, `9a762c0f` |
| — | Un `@adjunto` que no existe no se envía al modelo: aviso con sugerencias de nombres parecidos de la carpeta (`@mod` → `moda.py`) y vuelta al prompt; código de salida 1 en una sola ejecución. | `f502c43b` |
| D. Código generado | Asia no ejecutaba código generado: el chequeo de imports va en `generate_code` y `smart_refactor` antes de proponer el cambio. Imports extraídos con `ast` y comprobados con `find_spec` contra la lista permitida (stdlib, módulos locales, `requirements.txt` del proyecto, `allowed_imports`, imports que el archivo ya tenía); si falla se pide una reescritura, y si sigue fallando no se propone. Sandbox: venv desechable con `--without-pip` (solo stdlib, sin descargas), `python -I`, carpeta temporal, entorno mínimo y límite de tiempo; solo con comando explícito y "confirmar ejecución". Nunca `pip install`. | `ee2ca2cd`, `04025f94` |
| E. Refactor de Brain | Prueba de caracterización primero (77 casos con el prompt exacto, las llamadas y la respuesta de cada acción; `test/golden/brain_process.json`). `Brain.process` pasa de ~1000 líneas de `if action ==` a un despacho por `HANDLERS` con las acciones en `core/actions/` (memoria, exploración, revisión, código, sandbox) y los prompts en `core/prompts.py`, copiados por script y comprobados idénticos; el golden pasó sin regenerar en los 5 commits. Atajos de texto exacto, sin IntentEngine, para confirmar/cancelar/mostrar el cambio pendiente; `jarvis salir` ya no crea Brain. Prompt del IntentEngine de 368 a 214 líneas con las reglas contradictorias resueltas: 14 de 14 mensajes con la misma acción (`test/manual/check_intents.py`). | `5b81711e`, `af9d66b5`, `7888d66d`, `79a09479`, `985aec71`, `eefdbca9`, `19ed2810`, `9dd3b2d0` |
| — | Multilínea, encontrado en la comprobación manual de la fase E: si se pegaba justo después de `<<` sin pulsar Enter, el código quedaba en la misma línea que `<<`, no se reconocía el bloque y el mensaje entero iba al IntentEngine (elegía `explain_file` con una ruta inventada, `promedio_y_mayor.py`). Ahora cuenta como bloque si la misma lectura trae `FIN`; un bloque con instrucción nunca pasa por las acciones. El texto pegado o de stdin va al chat como "Texto incluido en el mensaje (no es un archivo)", separado de "Archivos adjuntos". | `9f7d1e3c` |
| — | "encuentra por qué…" va a `debug_project` (antes `review_project` con síntesis sobre todo el proyecto: más de 15 minutos). `debug_project` armaba ~19 500 tokens y Ollama descartaba el principio del prompt; ahora usa `tools/debug_context.py`: archivos de código sin carpetas de pruebas, ordenados por términos del problema y coincidencias, agregados mientras quepan en min(`ollama_num_ctx` − reserva, `context_limits.debug_project_tokens`=6000); los omitidos se nombran en el reporte. El problema va al principio y al final del prompt. El reporte dice "Diagnóstico NO verificado" y las citas de EVIDENCIA se comprueban con `locate_quote` (las inexistentes, marcadas como descartadas). C:\Asia con Ollama real: 56 s y ~5 900 tokens; con el tope solo en `num_ctx` eran 330 s y el modelo no seguía el formato. `check_intents.py`: 13 de 14 iguales (cambia solo el mensaje buscado). | `efe038df` |
| — | Multilínea con `FIN` al final de la última línea de código (`return resultado FIN`, pegado tras `explica esto << `): no se reconocía el bloque y Asia pedía la ruta. Ahora `FIN` tras un espacio cierra el bloque si es la última palabra de la lectura (se quita del contenido); una variable `FIN` en medio del pegado no lo corta. Un mensaje de varias líneas sin ruta válida (código pegado sin `<<`) va al chat en lugar de pedir la ruta: en código, `FILE_WORDS` veía nombres de archivo en `self.x` y las acciones de archivo sin `file_path` respondían "Necesito la ruta del archivo". | `d5a6d210` |
| — | `debug_project`: cada archivo va como fragmentos numerados alrededor de las coincidencias (±3 líneas, primero las del problema) dentro de los mismos 1200 caracteres, en lugar de su principio. El verificador acepta también `ruta:línea: cita` y la cita en la línea siguiente a `ruta:línea`, formatos que el modelo usa a menudo. Opciones de revisión (temperatura baja). C:\Asia: 63 s, 2 citas encontradas y 1 inventada descartada. | `ae499002` |
| — | Arreglos de la tanda de pruebas manuales: (1) `SIN_HALLAZGOS` escrito después de un hallazgo ya no se filtra al reporte de "revisa a fondo". (2) El aviso de "Ejecución preparada" muestra el código numerado (hasta 40 líneas, con aviso si se recorta) antes de pedir "confirmar ejecución". (3) Si el chequeo de imports hace reescribir el código, la explicación empieza con qué librería usaba y cuál la sustituye ("usaba superjson_mega (no está instalado)… ahora usa json"). (4) `debug_project` sin ninguna cita verificada empieza con "Ninguna evidencia se pudo verificar: el diagnóstico es probablemente especulativo" y etiqueta sus secciones como especulativas. | `1de54649`, `763a6d34`, `7d9f5e47`, `d21455ac` |
| F. Multi-modelo (parte 1) | Modelo por llamada, `models_by_domain`, dominio por palabras clave, modelo pegajoso en el chat, `--model` para la sesión (solo modelos ya descargados) y un modelo de Ollama en memoria a la vez (`ollama_one_model_at_a_time`). Sin modelos nuevos todavía: los tres dominios usan `qwen2.5-coder:7b`, así que el comportamiento no cambia. Probado con Ollama real: con `nomic-embed-text` cargado, el chat lo descargó antes de cargar qwen. | `1231b36b` |
| F. Multi-modelo (partes 2 y 3) | Razonamiento solo en `math` (`think_domains`); `math` con `qwen3:4b` (Thinking-2507). Clasificador de dominio que no manda código a `math`. `check_intents.py` con 28 mensajes y acción esperada. `open_app` tolerante a nombres aproximados (`notebook` → Bloc de notas) y con aclaración si no coincide nada. Comandos para ver y cambiar el modelo en la sesión. qwen3:4b-instruct medido y descartado para el IntentEngine (rompía `open_app`). | `91dab1d3`, `d0a093e8`, `07957ee7`, `f8b986df`, `b64c07b6`, `fccf75bd` |
| G. Modo confidencial | Inventario de las salidas (proveedor principal, fallback, Ollama remoto). Etiquetas de procedencia por petición (`core/provenance.py`): usuario, memoria (`external_allow_memory`, por defecto false), archivo, adjunto, rag, proyecto y emocional (nunca sale). El router no envía contenido local a un proveedor externo: responde el modelo local con aviso, o dice qué pasó si no hay uno; el fallback automático nunca lo lleva; memoria, proyecto y turnos locales del historial se quitan de lo que sale; rutas absolutas por el nombre del archivo. "envía esto a Gemini" + "confirmar envío" o `--allow-external` autorizan una vez, sin guardarse. "modo local"/"modo normal". Ollama fuera de localhost cuenta como externo salvo `trusted_local_hosts`. "cambia el provider" solo para la sesión. Filtro de secretos (`external_secret_policy`: redact/block) y la clave de Gemini fuera de prompts y errores. Bitácora `logs/external_audit.jsonl` sin texto y "qué has enviado afuera". Pruebas (a)-(f) y `test/manual/check_confidencial.py` (6 de 6). | `10e19aa2`, `2689b185`, `774a9308`, `97a2471d`, `9bb4d9da` |
| — | `open_app` guarda las apps que encuentra en el menú Inicio en `config/apps_learned.json` (en `.gitignore`) en lugar de `config/apps.json`, que dejaba el repositorio con cambios. Lee los dos; si una clave está en ambos, gana `apps.json`. Lo que ya había en `apps.json` no se movió. | `14006850` |
| — | `--timing`, "/tiempos" y "/sin tiempos" (alias "muestra tiempos" y "oculta tiempos"): después de cada respuesta, una línea por stderr con el IntentEngine, la carga del modelo (`load_duration`), el prompt (`prompt_eval`), los tokens generados, tokens por segundo, el total y proveedor/modelo; con Gemini, el total y el proveedor. Valor de sesión, apagado por defecto (`core/timing.py`). | `be89ee6d` |
| — | Modo abierto ("/modo abierto" o "modo abierto", solo la sesión; `open_mode_default` en `defaults.json`, false): sale todo lo que entra al prompt sin pedir autorización (archivos, adjuntos, RAG, proyecto, memoria e historial) y sin reemplazar rutas. Siguen el filtro de secretos y la bitácora (autorización "modo abierto"); lo emocional nunca sale. Aviso una vez al activarlo. El prompt muestra "Tú [abierto]:" (y "Tú [local]:" en modo local). | `8aa68c5f` |
| — | Comandos de sesión con "/" en una sola tabla (`core/commands.py`), de la que salen "/opciones" y `--help`: modos, modelos (`/modelo`, `/proveedor`), archivos y adjuntos (`/carpeta`), confidencialidad, cambios y ejecución, tiempos y salir, con un ejemplo cada uno. Las frases de antes ("modo local", "vuelve al modelo normal"...) siguen como alias. Un "/algo" desconocido no va al modelo. El arranque muestra modelo, modo y "Escribe /opciones para ver los comandos". | `66b259ef` |
| — | Aceleración con los números de `--timing` (ver "Velocidad" más abajo): la línea de tiempos muestra también el IntentEngine por dentro (tokens de prompt, `prompt_eval`, generados, carga) y `test/manual/check_speed.py` mide una sesión real; ruta rápida sin IntentEngine para la charla clara (`core/fast_chat.py`; `check_intents.py` con 12 casos de charla, 39 de 39 iguales); plantilla de documento para `explain_file`/`summarize_file` con `.md`, `.txt`, `.json`… y tope de la respuesta (`answer_limits`, `num_predict`) con aviso si se corta; "¿Quisiste decir @X?" + "sí" reenvía el mensaje corregido; `stream_output` true por defecto. | `7a65647f`, `904526ba`, `94f5787d`, `ae1a2015`, `62929ae2`, `f04bf65f` |

## Próximas fases

### Pendientes menores

- "Proyecto activo" es solo un nombre; asociarle una ruta permitiría limitar la escritura al proyecto y no solo a la carpeta actual (detectado en la fase 3).
- Las respuestas de `debug_project` y la de archivo protegido de `generate_code` llegan al usuario con 12 espacios de indentación en cada línea (heredado de cómo estaban escritas; se conservó en el refactor de la fase E por ser comportamiento).
- "muéstrame un resumen del archivo X" va a `read_file_preview` (las primeras líneas), no a `summarize_file`. Se dejó así en la fase E para no cambiar la acción.
- `remember`, `recall` y `forget` sin `key` caen al chat sin aviso.
- El diagnóstico de `debug_project` sigue siendo superficial: con "Asia None" señala `launcher.py` y `brain.process` devolviendo `None`, sin llegar a la causa real del bug de la fase 1 (el streaming, ya corregido). En C:\Asia, `tools/debug_context.py` sale entre los primeros archivos porque contiene las búsquedas fijas y "Asia None" en sus comentarios: es ruido propio de este repositorio.
- `open_app` responde "Abriendo notebook." con el nombre que extrajo el modelo. Debería decir el nombre resuelto ("Abriendo bloc de notas.").
- La salida no tolera erratas: "salior" va al IntentEngine en lugar de cerrar. Aplicar a "/salir" y sus alias (`core/commands.py`) la misma tolerancia que a los nombres de apps.
- ~~Flag `--timing`~~ (hecho, ver la tabla). La aceleración se decide con los números de `--timing` en uso real: primera tanda hecha (ver "Velocidad").

### Velocidad

Medido con `test/manual/check_speed.py` (una sesión, `qwen2.5-coder:7b`, `num_ctx` 16384), total por mensaje:

| Mensaje | Sesión del usuario (antes) | Línea base (`7a65647f`) | Después (`ae1a2015`) |
|---|---|---|---|
| "hola" | 30,4 s (intención 23,5) | 29,8 s (intención 23,8: 15,8 de carga del modelo) | 4,9 s, sin IntentEngine (20,1 s si el modelo no estaba cargado) |
| "qué es un grafo bipartito" | 47,8 s (intención 21,3) | 30,8 s (intención 5,0) | 27,2–33,1 s, sin IntentEngine |
| "si" | 30,4 s (intención 21,8) | 7,5 s (intención 4,7) | 2,4–4,4 s, sin IntentEngine |
| "explica @ROADMAP.md" | 217 s (1072 tokens) | 110,4 s (533 tokens) | 35,8 s (154 tokens) |

- La sospecha de la caché no se confirmó: el prompt del IntentEngine tiene 2083–2090 tokens reales y, ya cargado el modelo, se procesa en 0,2–0,9 s cuando Ollama lo tiene en caché y en 3,9–4,6 s cuando no. No explica los ~21 s por mensaje de la sesión del usuario; esos números coinciden con una recarga del modelo antes de cada mensaje (15,8 s de carga + 4,6 s de prompt en la línea base). La línea de tiempos ahora muestra la carga del IntentEngine para confirmarlo. Por eso no se recortó el prompt del IntentEngine ni se le puso `num_predict` (genera 10–20 tokens).
- Pendiente: averiguar qué descarga el modelo entre mensajes en una sesión interactiva (¿`keep_alive` de 5 minutos entre mensajes espaciados?). Si es eso, un `keep_alive` más largo lo evitaría, a cambio de dejar 5,8 GB ocupados.
- Lo que más pesa ahora es la generación (5–7 t/s, el 7B corre 59 % en CPU): una respuesta de 200 tokens son ~30 s.
- Recarga del 7B en la sesión del usuario: con la línea de tiempos nueva, la intención está en 4,3–4,4 s con carga 0,0; los 13 s de carga solo aparecen en el primer mensaje, con el modelo descargado. No es `nomic-embed-text`: solo `search_project_rag` e `index_project_rag` llaman a embeddings, y tres mensajes por el IntentEngine con `ollama ps` antes y después dejaron solo el 7B cargado.

**Segunda tanda** (`e725c0b2`, `8b1267d0`, `01e5545a`, `eda6453b`, y el recordatorio de brevedad): precarga del modelo del IntentEngine al abrir el modo interactivo (en un hilo, con el mismo `num_ctx`: sin él Ollama lo cargaba con 4096 y la primera llamada lo recargaba, 20 s); atajos sin IntentEngine para "abre X" y consultas fijas (`core/fixed_intents.py`; `check_intents.py` 44 de 44 iguales); chat breve por defecto (2 a 5 frases, recordatorio al final del mensaje, `answer_limits.chat`: 350 tokens o 1500 si se pide detalle; sin tope con razonamiento) y sin inventar datos. Medido con `check_speed.py --descargar --espera 15` (modelo descargado y 15 s hasta el primer mensaje):

| Mensaje | Antes | Después |
|---|---|---|
| "abre el bloc de notas" (primero) | 21,3 s (intención 21,1: 13,2 de carga) | 0,2 s (atajo; el modelo se carga mientras se escribe) |
| "muestra el proyecto activo" | 2,5 s (intención) | 0,0 s (atajo) |
| "qué es un grafo bipartito" | 28,6 s (160 tokens) | 14,6 s (81 tokens, 2 frases) |

**Fase I, ejecutable nativo** (`07cb95b9`, `55081129`, `320f6d41`): `pyproject.toml` con el entry point `jarvis = launcher:main`, instalado con `pip install -e .` en el `.venv`; `jarvis.exe` copiado a `C:\Tools`, sin tocar el PATH (`.exe` gana a `.bat`). La carpeta actual, los flags, stdin y el código de salida no cambian. Cambiar el contenido de `C:\Tools\jarvis.bat` no servía: con cualquier `.bat` en la cadena sigue el S/N. Librerías pesadas al primer uso: `google.genai` al usar Gemini, `chromadb` y `requests` con RAG, `ollama` al primer uso del cliente, que en el modo interactivo es el hilo de precarga.

| Arranque (mediana) | Antes (`.bat`) | `.exe` solo | `.exe` y carga diferida |
|---|---|---|---|
| `jarvis --help` | 10,01 s | 9,67 s | 0,91 s |
| Modo interactivo, hasta el primer prompt | 10,39 s | — | 0,88 s |

Ctrl+C, comprobado con una consola real y `jarvis.exe`: sin voz corta la respuesta en ~0,2 s y vuelve al prompt, sin dejar el turno en el historial; con voz, el primero corta la lectura y el segundo la respuesta (~0,1 s); en el prompt vacío cierra con código 0, sin S/N. El mensaje siguiente al corte responde normal.

- ~~La primera carga de la voz de Piper tarda ~9 s, detiene los tokens ~7,5 s y retrasa Ctrl+C.~~ Hecho (`b63a9506`): la voz se precarga en un hilo con `/voz` o `--voz` (3,6 s, mientras se escribe). La primera frase pasó de 9,2 a 1,8 s, sin huecos de más de 0,7 s entre tokens. Medido con el 7B al 100 % en CPU; repetir con la GPU.
- Pendiente: `jarvis "mensaje"` (una sola ejecución) sigue cerrando con Ctrl+C.
- ~~En Windows Ctrl+C no interrumpe la espera del socket~~ Hecho: la llamada al modelo va en otro hilo (`core/interruptible.py`, desde el router y el IntentEngine; también cubre Gemini) y Ctrl+C cierra la conexión. Corta en ~0,1 s también durante la intención y con el modelo cargándose (antes, hasta 65 s en CPU). El turno cortado no queda en el historial.
- Límite de Ollama: cerrar la conexión no detiene el prompt que ya está procesando. El mensaje siguiente espera a que termine (medido en CPU, con el modelo recién cargado: 99 s de intención con 12 s de carga). Con tokens saliendo sí para al instante. Repetir con la GPU, donde ese prompt tarda ~4 s.

## Fases futuras (diseño pendiente)

### Multi-modelo según tipo de tarea

**Objetivo:** usar varios modelos de Ollama según la naturaleza del prompt. Por ejemplo, `qwen2.5-coder:7b` para código, un modelo de razonamiento destilado (tipo `deepseek-r1`) para matemáticas/física y un generalista para conversación e inglés.

**Punto de partida:** desde la fase 2 los modelos ya no están en el código: `ollama_model`, `intent_model` y `embedding_model` viven en `config/defaults.json`.

**Hecho (`1231b36b`):** modelo por llamada (`OllamaProvider.complete(..., model=)`, `ProviderRouter.ask(..., domain=)`); `models_by_domain` en config (los tres en `qwen2.5-coder:7b` hasta descargar otros); dominio por reglas de palabras clave (`core/model_selection.py`, opción 2: sin llamadas extra ni cambios al prompt del IntentEngine); modelo pegajoso en el chat (cambia si otro dominio se sostiene 2 mensajes); `--model` para la sesión, comprobando que esté descargado; `ollama_one_model_at_a_time`: antes de cada llamada se descargan los demás modelos cargados.

**Medido con `qwen3:4b` (2026-10-23, `d0a093e8`, `07957ee7`):** la etiqueta `qwen3:4b` de Ollama es Qwen3-4B **Thinking-2507**: siempre razona; `think=False` ni `/no_think` lo apagan (el razonamiento sale como texto: 1312 tokens ante "di hola"). Sirve para math (tren: "10:00" correcto en 96 s, 11,4 t/s) pero no para el IntentEngine ni el chat general. Con `num_ctx` 16384 ocupa 5,4 GB y corre 56 % en CPU; con 8192, 4,2 GB y 19,6 t/s; con 4096, 3,5 GB y 25,6 t/s (aún 34 % en CPU). Cambiar `num_ctx` entre llamadas recarga el modelo. Línea base del IntentEngine con `qwen2.5-coder:7b` en 28 mensajes: 27 de 28 correctos, 21,3 s la primera llamada y 3,1 s por mensaje cargado. Clasificador de dominio corregido para código con palabras de matemáticas (`91dab1d3`).

**Medido con `qwen3:4b-instruct-2507-q4_K_M` (2,5 GB, `f8b986df`):** no razona (`think=False` respetado, sin `<think>`). IntentEngine, 28 mensajes: 28 de 28 acciones correctas (7B: 27), 6,6 s la primera llamada y 2,8 s cargado (7B: 21,3 y 3,1). Pero en parámetros es peor: "abre el bloc de notas" da `notebook` o `blocknote`, inestable entre corridas, y Asia no encuentra la app (con "Bloc de notas" sí); además agrega texto inventado al `request` de "corrige X". Por eso el IntentEngine sigue en `qwen2.5-coder:7b`. Chat en español (5 de charla, 3 de código): respuestas más claras y largas, a 12 t/s contra 8 del 7B; el 7B confundió "Asia" con el continente; qwen3 inventó el título de un libro. `math` usa `qwen3:4b` (Thinking) con razonamiento: "3x + 7 = 22" en 84 s desde `ProviderRouter.chat`, sin `<think>` en la respuesta.

**`num_ctx` (generación, memoria, % en CPU):**

| num_ctx | qwen2.5-coder:7b | qwen3:4b-instruct | qwen3:4b (Thinking) | Prompts que no caben (con 1024 de reserva) |
|---|---|---|---|---|
| 16384 | 7,0 t/s · 5,8 GB · 59 % | 9,2 t/s · 5,4 GB · 56 % | 11,4 t/s · 5,4 GB · 56 % | ninguno |
| 8192 | 7,0 t/s · 5,4 GB · 58 % | 11,5 t/s · 4,2 GB · 45 % | 19,6 t/s · 4,2 GB · 45 % | `generate_code` (~10 000 tokens estimados, ~7 800 reales) |
| 4096 | 7,2 t/s · 5,2 GB · 55 % | 16,8 t/s · 3,5 GB · 34 % | 25,6 t/s · 3,5 GB · 34 % | todos salvo `explain_file` y el IntentEngine |

Prompts más grandes medidos en C:\Asia (tokens estimados por Asia; los reales son ~78 %): `generate_code` 10 017, chat con adjunto de 20 000 caracteres 6 942 (sin historial), síntesis de `review_project` 6 239 (15 archivos con 5 hallazgos cada uno), `debug_project` 5 970 (se ajusta solo al límite), `smart_refactor` 5 907 (`launcher.py`; lee el archivo entero, sin límite), `review_file_deep` 5 345, `explain_file` 2 556, IntentEngine 2 478. Con el 7B, bajar `num_ctx` casi no acelera: pesa el modelo, no el contexto.

**Decidido (2026-10-23):** `ollama_num_ctx` se queda en 16384 (con el 7B bajar el contexto no acelera y `generate_code` dejaría de caber). El IntentEngine y el chat siguen en `qwen2.5-coder:7b`; `qwen3:4b` solo para `math`. `qwen3:4b-instruct-2507-q4_K_M` quedó descargado sin uso (2,5 GB; se puede borrar con `ollama rm`).

**Hecho, parte 3 (`fccf75bd`):** "¿qué modelo estás usando?", "usa el modelo de matemáticas" (o de código, general), "usa el modelo <nombre:tag>" y "vuelve al modelo normal", reconocidos por texto sin el IntentEngine; duran solo la sesión y dicen qué modelo falta si no está descargado. `--help` documenta `--model` y estos comandos.

**Qué falta:**
- El IntentEngine con qwen3 instruct necesitaría reglas o ejemplos para que copie `app_name` y `request` tal cual; habría que volver a medir los dos modelos. `open_app` ya tolera `notebook`/`blocknote` (`b64c07b6`).
- Con un modelo a la vez, cada mensaje de `math` carga qwen3 tras el IntentEngine (7B), y el siguiente vuelve a cargar el 7B: unos 10 a 15 s por cambio.
- El embedder del RAG (`nomic-embed-text`) no descarga los demás antes de cargarse: pesa 274 MB, pero con poca RAM convendría también.

**Trade-off a documentar en el diseño:**
- Cambiar de modelo en Ollama no es instantáneo: hay que descargar uno de la VRAM y cargar otro (segundos con un 7B, más con modelos grandes). Ollama mantiene el último modelo cargado unos minutos (`keep_alive`).
- Si `intent_model` y el modelo de respuesta son distintos, cada mensaje puede provocar dos cargas. Hoy los dos son `qwen2.5-coder:7b`, así que no hay recarga.
- Regla de diseño: elegir el modelo al empezar una conversación y mantenerlo mientras siga activa ("modelo pegajoso"); cambiar solo si el dominio cambia claramente y de forma sostenida, o si el usuario lo pide.

**Primer caso concreto: la síntesis de `review_project`.** Con la entrada completa, `qwen2.5-coder:7b` hace buenas revisiones por archivo pero malas síntesis (ver "Alucinación en revisiones largas"). Opciones:
1. Un modo de `review_project` que devuelva los reportes por archivo sin síntesis final. No requiere otro modelo; es lo más barato y lo que mejor funcionó en las pruebas. Hecho en `284c1bdc` ("revisa el proyecto sin síntesis").
2. Usar un modelo más capaz solo para el paso de síntesis. Encaja con "modelo por llamada", pero paga una recarga al terminar las revisiones por archivo. Antes de elegir el modelo, medir con la revisión de `practica2` ya documentada: ¿menciona el bug de `cancelar()`? ¿evita las afirmaciones falsas sobre versiones y Spring?

### RAG más allá de código

Dos colecciones nuevas en ChromaDB, separadas de las de proyectos. Usar un prefijo reservado (p. ej. `asia__`) para que no choquen con nombres de proyecto.

- **Historial de conversaciones** (`asia__chat`): indexar cada intercambio usuario/asistente para recuperar contexto pasado por similitud, más allá de los 20 mensajes del historial en memoria. A definir: cuándo se indexa (al terminar cada respuesta), metadatos (fecha, proyecto activo), retención y cómo borrar. Contiene datos personales: no debe entrar en las tools de análisis ni en los índices de proyectos.
- **Base de conocimiento manual** (`asia__knowledge`): material que el usuario indexa a mano (fórmulas, apuntes, reglas de la universidad), con un comando explícito para agregar o eliminar fuentes y metadatos de origen para poder citarlas. Objetivo: reducir alucinaciones en **datos puntuales verificables**. No mejora el razonamiento: eso depende del modelo, no del dataset.

### Alucinación en revisiones largas

**Observaciones:**
- *Antes de `d432d338` (confirmado):* reportes de "línea 1 vacía / error de sintaxis" en archivos Java de `practica2`. Causa: el analizador estático aplicaba el parser de Python a `.java` y el LLM tomaba ese error como evidencia. Corregido.
- *Observado por el usuario, sin registro:* `EstadoTicket.java` reportado como vacío aunque `read_file_preview` entregaba el contenido completo. Sin marca de tiempo para saber si fue antes o después del fix. Si se repite con el fix aplicado, se atribuye a pérdida de coherencia del modelo (`qwen2.5-coder:7b`) en revisiones largas.

- *Confirmado (recorte de contexto):* la síntesis de `review_project` afirmó que `asignar()`, `cerrar()` y `cancelar()` de `SistemaDeTickets.java` "no realizan validaciones necesarias", aunque los tres validan sus parámetros con `IllegalArgumentException`. Datos:
  - El archivo tiene 2798 caracteres, por debajo del corte de 3000 de `review_project_file`: el modelo lo vio entero.
  - La revisión individual de ese archivo (895 tokens, sin recorte) fue precisa: reconoce las validaciones de `null` y señala lo que sí falta. `asignar()` y `cerrar()` no comprueban el estado actual del ticket, y `cancelar()` nunca llama a `Ticket.cancelado()` ni a `repo.actualizar()`.
  - Ollama cargaba el modelo con `num_ctx=4096` (`ollama ps`). La síntesis medía 4628–4770 tokens y Ollama la recortó a 2050, descartando el principio: el encabezado y la mayoría de los reportes por archivo (log: `truncating input prompt limit=2050 prompt=4770 keep=4 new=2050`). La frase vaga salió de una síntesis hecha con el 43% de la evidencia.
  - `generate_code` sufría lo mismo (4114 tokens → 2050), perdiendo la petición del usuario y el archivo objetivo.
  - Corregido en `0b5b5c61`: `ollama_num_ctx=16384` y aviso cuando un prompt no cabe. Con ese valor, los cuatro prompts medidos (síntesis, `generate_code`, `map_project`, IntentEngine) se procesan completos.

- *Confirmado (límite del modelo, con la entrada completa):* nueva revisión de `practica2` con `num_ctx=16384`. La síntesis se procesó entera (4859/4859 tokens, sin recortes en el log de Ollama) y ya no repitió lo de "no realizan validaciones". Aun así, el reporte final:
  - afirmó que JUnit 6.0.3 y Mockito 5.22.0 son "versiones obsoletas" (prioridad alta), juzgando según lo que el modelo conocía al entrenarse;
  - recomendó `@Repository` en un proyecto que no usa Spring;
  - marcó como problema que la interfaz `Reloj` "no tiene implementación", aunque es una dependencia inyectada (en los tests es `@Mock`);
  - **omitió el bug real más importante**: `cancelar()` nunca cambia el estado del ticket, algo que la revisión individual sí había detectado;
  - cerró con "los hallazgos son confirmados por evidencia".

  Conclusión: con la entrada completa, `qwen2.5-coder:7b` elige mal qué hallazgos importan y mezcla conocimiento genérico que no aplica. Ya no es un problema de contexto, sino de la capacidad del modelo para sintetizar.

- *Confirmado (B2, `moda.py` y `eliminar.py` de practica6):* hallazgos falsos (`KeyError` imposibles), repetidos, líneas incorrectas y "CONFIRMED" sobre hipótesis; omitió el bug real (`open(..., "w")` trunca el original y un fallo a medias lo deja corrupto). Parte venía de Asia: `analyze_static` marcaba cada `df[col]` como "posible índice fuera de rango" (9 veces en `moda.py`, la línea 25 cuatro) y el prompt de `review_file_deep` obligaba a copiarlo.

  Banco: `test/manual/check_review_quality.py` (verdad conocida en `test/manual/casos/verdad.json`; `--rescore` recalifica sin Ollama). 3 corridas × 2 casos, 3 bugs reales esperados por corrida:

  | Modo | Precisión antes → después | Recall antes → después | Falsos conocidos |
  |---|---|---|---|
  | `deep` | 0,06 (1/16) → 0,09 (2/23) | 0,11 (1/9) → 0,22 (2/9) | 9 → 1 |
  | `archivo` | 0,00 (0/14) → 0,00 (0/6) | 0,00 (0/9) → 0,00 (0/9) | 10 → 1 |

  Conclusión: los falsos conocidos casi desaparecen, pero el truncado no se detectó en ninguna corrida y la mayoría de lo reportado sigue siendo especulativo (excepciones de `loadarff` "no capturadas" que sí están dentro del `try`, límites de memoria). Los ejemplos negativos del prompt salen de los mismos casos del banco, así que la baja de falsos conocidos es en parte por construcción. Con la verificación de citas solo se filtran citas inventadas: un claim falso con cita real pasa.

  *B3, regla determinista de truncado* (3 corridas × 3 casos; el caso nuevo `guardar_seguro.py` no tiene bugs reales esperados):

  | Modo | Parte | Precisión | Recall |
  |---|---|---|---|
  | `deep` | total | 0,30 (10/33) | 1,00 (9/9) |
  | `deep` | modelo | 0,15 (4/27) | 0,33 (3/9) |
  | `deep` | automática | 1,00 (6/6) | 0,67 (6/9) |
  | `archivo` | total | 0,41 (7/17) | 0,78 (7/9) |
  | `archivo` | modelo | 0,09 (1/11) | 0,11 (1/9) |
  | `archivo` | automática | 1,00 (6/6) | 0,67 (6/9) |

  La regla detecta el truncado en las 12 revisiones de `moda.py`/`eliminar.py` y no avisa en ninguna de las 6 de `guardar_seguro.py`. El modelo sigue sin detectar el truncado por su cuenta; lo que aporta es la columna con todos los valores faltantes de `moda.py` (en `deep`, 3 de 3). El prompt del modelo no cambió en B3: la diferencia en sus números frente a B2 es variación entre corridas. Recall 0,67 de la regla = 6 de los 9 reales esperados; los 3 restantes son `moda_vacia`, que no es de escritura.

  La misma regla marcó dos archivos de Asia: `MemoryManager.save` y `SettingsManager.set` leían el JSON y lo reescribían con `"w"`. Corregido en `5127354e` con escritura atómica.

  Otros sitios con el mismo patrón, corregidos en `b40e8a44`: `save_apps` (`config/apps.json`), `save_project_summary` (resumen `.md`) y `pending_change.json`. Se deja como está `apply_pending_change` (`tools/apply_changes_tool.py`), que reescribe el archivo del usuario con `write_text` pero guarda antes un respaldo en `memory/backups/`.

  Límite de la regla: no distingue funciones ni ámbitos. Compara rutas por nombre de variable y ordena por número de línea, así que da falsos positivos cuando dos funciones usan el mismo nombre (`test/test_atomic_write.py:61`) y falsos negativos cuando la lectura está definida después de la escritura.

  Hallazgo de la evaluación: con "si no hay problemas responde solo SIN_HALLAZGOS" al final del prompt, el modelo respondía eso el 100% de las veces (16/16, con y sin ejemplos ni temperatura). Pedir un análisis previo lo evita. También ignora el formato de bloques y escribe listas markdown; el parser acepta ambos.

**Corregido durante esa evaluación** (causas que no eran del modelo):
- `985e02ec`: los scripts de `.github/` entraban en la selección desde que se unificaron las extensiones, y empataban en prioridad con el código. Ahora `review_ignored_dirs` los excluye al elegir qué revisar.
- `f3c0eb9a`: dos reglas del prompt de síntesis mencionaban secciones "ARCHIVO SELECCIONADO" que no existían en el prompt.

**Contexto:** desde la fase 1, cada revisión por archivo es una llamada independiente (`ProviderRouter.ask`, sin historial), así que no hay "memoria" que se degrade entre archivos.

**Uso recomendado mientras tanto:** para revisiones que importan, usar "revisa a fondo X.java" (`review_file_deep`, un archivo por llamada) en vez de "revisa el proyecto completo". Los reportes por archivo fueron los más precisos en todas las pruebas.

**Pendiente:**
- Modelo distinto para la síntesis: ver "Multi-modelo según tipo de tarea". El modo sin síntesis ya existe (`284c1bdc`).
- Proyectos más grandes que `practica2` pueden superar 16384 tokens en la síntesis (unos 30 reportes). El aviso por stderr lo detecta; si pasa seguido, habrá que procesar en lotes.

### CLI: pendientes

Hecho en la fase C (`af003d2a`, `4f25b229`): `@ruta`, autocompletado, stdin, `--file`, varios adjuntos con límite y aviso, flags y multilínea. Falta:

- Imágenes desde el portapapeles y `@ruta.png`: ver "Extras: imágenes en la terminal".
- PDF y texto largo vía RAG en vez de recortar.
- ~~**Fase I (Asia 1.0):** reemplazar `jarvis.bat` por un ejecutable nativo, para evitar el "¿Desea terminar el trabajo por lotes (S/N)?" de Windows al interrumpir con Ctrl+C.~~ Hecho, ver "Velocidad" y el README. `jarvis.bat` se mantiene por un tiempo como respaldo: para volver a él, borrar `C:\Tools\jarvis.exe`.
- stdin: si Asia se lanza sin terminal y con un stdin abierto que nunca se cierra (no una tubería real), la lectura espera indefinidamente. Si pasa, agregar un flag `--no-stdin`.

### Generación de código con verificación

Ciclo: planear -> generar -> ejecutar en sandbox -> verificar -> reparar, con criterios de aceptación objetivos (pruebas tipo omegaUp, entorno simulado, tarea descompuesta). Caso de regresión: el modelo de Hodgkin-Huxley.

**Librerías inventadas u obsoletas** (bug observado):
- Una librería que no existe se detecta al ejecutar (`ModuleNotFoundError`). Una API que existe pero cambió solo se detecta si una prueba la ejercita.
- Riesgo de seguridad (*slopsquatting*): nunca hacer `pip install` automático de lo que el modelo inventó. Solo lista permitida o confirmación del usuario.
- Pasos, de menor a mayor costo:
  1. ~~Extraer los imports con `ast` y comprobar `importlib.util.find_spec`; si falta alguno, pedir reescritura.~~ Hecho en `ee2ca2cd`, antes de proponer el cambio (Asia no ejecuta el código generado por su cuenta).
  2. ~~Lista permitida de dependencias dentro del prompt.~~ Hecho en `ee2ca2cd`.
  3. ~~Sandbox en un venv desechable.~~ Hecho en `04025f94`: solo stdlib, comando explícito y confirmación. Un venv aísla paquetes, no el sistema: el código corre con los permisos del usuario.
  4. Fijar versiones en el prompt cuando la API cambie entre versiones.
  5. Indexar la documentación de las librerías usadas en `asia__knowledge`.
- Pendiente del sandbox: código que use paquetes (pandas, numpy) no se puede probar, porque instalar en el venv desechable descargaría de PyPI. Opciones: `--system-site-packages` (ve los paquetes de Asia, sin descargar) o instalar con confirmación del usuario. Tampoco hay aislamiento real de archivos ni de red; para eso haría falta un contenedor o un usuario restringido.

### Confidencialidad

Hecho en la fase G (ver la tabla). Pendientes:
- Con Ollama en otra máquina (fuera de `trusted_local_hosts`), el IntentEngine recibe lo tecleado con las rutas absolutas: hacen falta para que las acciones encuentren los archivos.
- "envía esto a Gemini" reenvía solo el último prompt: en una acción de varias llamadas (`review_project`) es la síntesis. Para esas, `--allow-external`.
- La respuesta de un envío autorizado no se agrega al historial del chat.
- La procedencia es por petición, no por carácter: si una acción lee un archivo, todo su prompt cuenta como local aunque use una parte. Peca de restrictiva.
- El filtro de secretos es por patrones: en código da falsos positivos (`token = obtener()`) y no reconoce secretos sin formato conocido.
- Con Ollama remoto no confiable, el RAG no indexa ni busca; no hay forma de autorizarlo una vez.
- La etiqueta "emocional" existe pero todavía nada la produce (ver "Afecto y cognición social" en Extras).

### Voz y avatar

**J1, voz en la terminal (hecho):** `core/voice/` es una capa de entrada y salida; el cerebro no cambia. Con `/voz` (o `--voz`), Enter en una línea vacía escucha (sounddevice, 16 kHz mono; Silero VAD tramo a tramo con el ONNX que trae faster-whisper, sin el paquete `silero-vad` ni PyTorch); termina con 800 ms de silencio o con otro Enter. faster-whisper `small` siempre en CPU int8 (`beam_size` 5: igual de rápido que 1 y acierta más). Lo entendido se muestra como tecleado y lleva la etiqueta "usuario". Las respuestas se muestran enteras y se lee su texto normal con Piper (`es_MX-claude-high`), sin código, tablas, rutas ni markdown ("te dejo el código en pantalla"). Motores elegidos por config (`voice` en `defaults.json`); el audio no se guarda. `/sin voz` libera los modelos. Paquetes en `requirements-voice.txt`; modelos y voces en `data/models` y `data/voices` (no versionados). Commits: `af14fd52`, `3ccb0f5b`, `b8a31257`, `e9763b0f`, `49ef551a`, `37f519c3`.

- RAM con el 7B cargado: 2 132 MB libres; con Whisper small y la voz, 1 748 MB (ocupan ~380 MB).
- Latencias (`test/manual/check_voz.py --sin-microfono`, frases generadas con Piper): voz a texto 2,5–2,7 s por frase de 2,4–2,9 s (4,6 s la primera, con la carga de Whisper); texto a voz 0,2–1,9 s de generación para 1,8–27 s de audio. Una respuesta de 110 tokens son ~27 s de lectura.
- Con voz sintética, Whisper entendió "Vuestra el proyecto activo" y "¡Que ves un grafo bipartito!": las rutas rápidas no lo reconocen y decide el IntentEngine.

**J1, ajustes tras la prueba con voz real (hecho):** con el micrófono de la laptop Whisper entendió "sobre el blog de notas" (iba al chat y respondía 64–85 s de audio sobre blogs), "Moisture el proyecto activo" y "rootmap.md".
- Vocabulario de Asia como `initial_prompt` de Whisper (`core/voice/vocabulary.py`): verbos de las órdenes (sacados del prompt del IntentEngine, atajos y comandos; primero los más usados), apps de `apps.json` y `apps_learned.json`, proyectos y `voice.stt_vocabulary`. Hasta 400 caracteres. Con voz sintética corrige "bloc de notas", "ROADMAP" y "Bolitabot"; "grafo bipartito" sigue mal. Cuesta ~0,5–0,9 s más de voz a texto. `check_voz.py --transcribir` compara con y sin. Commit `59ca9776`.
- Brevedad en voz: el recordatorio de "2 a 5 frases" sí se aplicaba; el 7B respondía con una lista de 5 puntos de varias frases (201–284 tokens). En modo voz: "1 a 3 frases, en un solo párrafo, sin listas" y `answer_limits.chat.voice_tokens` (150); el aviso de recorte no se lee. "Sobre el blog de notas": de 147–284 a 44–97 tokens. A veces el 7B igual se alarga (143 tokens en una corrida del grafo). Commit `a344cb60`.
- VAD: a Whisper solo le llega la voz con 0,3 s de margen (antes, también la espera tras el Enter y el silencio final: así una frase corta daba 7,4 s de audio); la frase empieza con 96 ms seguidos de voz (`min_speech_ms`). Con ruido blanco el VAD no pasa de 0,12, así que el ruido no parece ser la causa. `/calibrar voz` mide 3 s de ruido y sube el umbral para la sesión si hace falta; `--timing` muestra "de X s grabados" si se grabó mucho más que la voz. Commit `0b06ca87`.
- Si con voz real sigue fallando: el modelo `medium` (más lento) o sumar palabras a `voice.stt_vocabulary`.

**J2, frase por frase e interrupción (hecho):** `core/voice/reading.py`. Cada frase completa del streaming (nunca dentro de un bloque de código ni de una fila de tabla) se genera en un hilo y suena en otro, en orden; la respuesta sigue sonando al volver al prompt. Enter (mientras escribe o al mandar otra línea), Ctrl+C (corta la lectura, no Asia) o volver a escuchar cortan la lectura y vacían la cola. "Te dejo el código en pantalla" se dice una vez al final. `--timing` añade "primer audio".
- Hasta el primer audio, desde que termina la frase dicha (`check_voz.py --sin-microfono`, con altavoz): "qué es un grafo bipartito" 15,8 s → 9,1 s; "sobre el blog de notas" 29,6 s → 10,2 s (con la brevedad en voz); "cuéntame un chiste" 11,2 s → 9,3 s (respuesta de una frase: casi todo es la intención y el modelo). Voz a texto aparte: 2,7 → 3,1 s.

**J3, palabra de activación:** "Hey Jarvis" de openWakeWord para las pruebas; después, "Oye Asia" entrenada. En 1.0 se prueba con el micrófono de la laptop a distancia corta; la activación a distancia queda para cuando haya un micrófono externo.

**J4, servicio en segundo plano:** Asia escuchando sin la terminal abierta (bandeja del sistema o servicio), con el mismo modo confidencial.

**Voz propia de Piper:** ver "Voz propia" en Extras.

**Licencias de voz:** `piper-tts` 1.3+ es GPL-3.0 (vale para uso personal). Si algún día se distribuye Asia, la alternativa es el Piper anterior con licencia MIT (rhasspy/piper, hasta 1.2). Voces descargadas: `es_MX-claude-high` (datos Apache-2.0), `es_MX-ald-medium` (Unlicense) y `es_ES-sharvard-medium` (CC BY 3.0, exige atribución). `ald` y `sharvard` se afinaron desde `lessac`, cuyos datos probablemente son de uso no comercial: revisarlo antes de distribuir.

**Pendiente:**
- Canal de estado local (Flask-SocketIO) para que el avatar reaccione a hablar, pensar y escuchar.
- Avatar: perro bóxer.

### Biblioteca de conocimiento offline (fase H, Asia 1.0)

Antes "Wikipedia offline". Va por capas, y cada fuente lleva su etiqueta para poder citarla:

1. Proyectos propios (repos, reportes, notas) con el RAG actual: primera capa, la más útil. Hecha, ver abajo.
2. Documentación técnica offline (ROS 2, Gazebo, Python, MATLAB), empaquetada para Kiwix o convertida con zimit. En esta capa (Asia 1.0), la búsqueda por palabras pasa a SQLite FTS5, con los tokens ya pasados por el stemmer, en lugar de reconstruir BM25 en cada búsqueda. Hace falta para las fuentes grandes (Wikipedia, Stack Overflow).
3. Wikipedia en español e inglés: herramienta offline con Kiwix/ZIM, separada del RAG de proyectos.
4. Preguntas y respuestas (Stack Overflow, Robotics Stack Exchange).

- Búsqueda: la de texto de Kiwix encuentra los artículos y los embeddings se usan solo dentro de ellos, sin indexar todo.
- Regla en el prompt: responder con lo que dice la fuente y decir "no lo encontré" si no está.

**Capa 1, proyectos propios (hecho):** commits `a3953a4a` (benchmark y lotes), `df964630` (fuentes y exclusiones), `8b387639` (troceado e incremental), `1cb51f31` (híbrida), `2826f8f9` (respuesta con fuente).
- Fuentes: cada una es una colección con nombre y tipo (proyecto, reporte, notas), en `data/biblioteca/fuentes.json`. `/indexar <nombre> [ruta] [tipo]`, `/fuentes` y `/buscar <pregunta>`. Busca en todas, salvo "en <fuente>".
- Nunca entran `data/`, `memory/`, `logs/` ni `config/settings.json` de Asia, secretos (`.env`, `*.key`, `*.pem`, `id_rsa`...), binarios, archivos de más de 1 MB ni lo que ignore el `.gitignore` de la fuente (`core/rag/exclusions.py`). Antes entraban los modelos de Whisper (83 % de los fragmentos) y `memory/`.
- Troceado: Python por funciones y métodos con `ast`, `.md` y `.tex` por secciones, el resto por bloques; cada fragmento lleva delante dónde vive. Un hash por archivo reindexa solo lo que cambió.
- Búsqueda: embeddings con los prefijos de nomic y BM25 propio con raíces del español (`snowballstemmer`), fusionados por posición (RRF), con 2 fragmentos por archivo como mucho.
- Respuesta: solo con los fragmentos y citándolos. "Fuentes:" la pone el código, no el modelo. Si la cobertura de la pregunta en los fragmentos no llega a `rag.min_coverage` (0,3), dice "No lo encontré en tus proyectos." sin llamar al modelo. La distancia de los embeddings no sirve para esto (se solapan) y la puntuación de BM25 tampoco (depende del tamaño de la colección).

Aciertos con `test/manual/check_rag.py` (20 preguntas sobre C:\Asia, archivo correcto en 1.º / top 3 / top 5):

| Paso | Total | Concepto (12) | Documento (2) | Nombre (6) |
|---|---|---|---|---|
| Línea base | 8 / 13 / 16 | 4 / 6 / 8 | 1 / 2 / 2 | 3 / 5 / 6 |
| Fuentes y prefijos | 10 / 15 / 16 | 4 / 7 / 8 | 1 / 2 / 2 | 5 / 6 / 6 |
| Troceado | 10 / 12 / 14 | 3 / 4 / 6 | 1 / 2 / 2 | 6 / 6 / 6 |
| Híbrida y tope por archivo | 13 / 16 / 19 | 5 / 8 / 11 | 2 / 2 / 2 | 6 / 6 / 6 |
| Raíces del español | 12 / 15 / 20 | 4 / 7 / 12 | 2 / 2 / 2 | 6 / 6 / 6 |

"No lo encontré": 5 de 5 preguntas sin respuesta y 0 de 20 falsos rechazos, con una muestra pequeña: cobertura hasta 0,16 sin respuesta y desde 0,41 con ella. Vigilar en uso real. Eso mide el filtro por cobertura, no al modelo.

"No lo encontré" solo lo decide el código: el prompt ya no lo ofrece y, si el modelo se niega con material, se muestran los 3 mejores fragmentos sin volver a llamarlo. Punta a punta con el 7B real (`check_rag.py --punta-a-punta 2`, 8 preguntas, sobre el texto del modelo; no mide si lo que dice es correcto):

| Configuración | Corrida | Responde | Cita el archivo | s/pregunta |
|---|---|---|---|---|
| Antes, 5 fragmentos | 1 | 8/8 | 7/8 | 63 |
| | 2 | 6/8 | 4/8 | 22 |
| Después, 5 fragmentos | 1 | 8/8 | 7/8 | 79 |
| | 2 | 8/8 | 7/8 | 29 |
| Después, 3 fragmentos | 1 | 8/8 | 8/8 | 36 |
| | 2 | 8/8 | 8/8 | 26 |

Se quedan 5 fragmentos: con 3 el archivo correcto queda fuera en 4 de las 20 preguntas de la búsqueda, y con 5 en 1.

Ese prompt inventaba: en 4 preguntas trampa (pasan el filtro, sin respuesta en C:\Asia), 5 de 8 respuestas afirmaban algo falso con cita real. Por eso la respuesta va en dos pasos (`core/rag/quotes.py`): el modelo copia las líneas que responden o escribe NINGUNA; el código comprueba que existan con `locate_quote`, el de la revisión de código; el modelo responde solo con ellas y debajo van siempre las líneas verificadas, por archivo y juntando las seguidas, con el texto del archivo. Sin líneas verificadas: "No encontré una respuesta directa. Esto es lo más relevante:" con los 3 mejores fragmentos. La cobertura sigue decidiendo "No lo encontré".

| Citas verificadas | Corrida | Responde | Cita el archivo | Trampas respondidas | s/pregunta |
|---|---|---|---|---|---|
| Primer prompt | 1 | 6/8 | 5/8 | 0/4 | 68 |
| | 2 | 4/8 | 3/8 | 0/4 | 20 |
| Con regla para nombres | 1 | 7/8 | 4/8 | 0/4 | 29 |
| | 2 | 8/8 | 8/8 | 0/4 | 35 |

Sobre una copia del índice sin `check_rag.py` ni los fragmentos con las trampas: si no, el modelo podría "citar" la pregunta misma.

La redacción también se comprueba: una etiqueta que no esté entre las verificadas, o un nombre de código que no aparezca en los fragmentos (entre comillas invertidas, en un bloque, snake_case o camelCase), la invalida y solo se muestran las líneas, con un aviso. Si no llega a una frase o es solo una línea de código, se trata como NINGUNA.

| Redacción comprobada | Corrida | Responde | Inválidas | Cita el archivo | Trampas respondidas | s/pregunta |
|---|---|---|---|---|---|---|
| Primera regla | 1 | 4/8 | 2 | 4/8 | 0/4 | 76 |
| | 2 | 6/8 | 0 | 6/8 | 0/4 | 31 |
| Sin falsas alarmas | 1 | 8/8 | 0 | 8/8 | 0/4 | 50 |
| | 2 | 6/8 | 0 | 5/8 | 0/4 | 39 |

Las 2 inválidas de la primera regla eran falsas alarmas (`os.replace()` y PowerShell). Ninguna corrida con el 7B ha cazado aún un nombre inventado: eso solo está probado en pytest.

Tiempos en CPU, solo como referencia (repetir con la GPU; no se ajustó nada por ellos): índice completo de 994 fragmentos, 423 s; incremental de 6 archivos, 29 s; consulta, 2,5 s, y `/buscar` entero, 45–110 s.

Pendientes:
- Medir con la GPU si `nomic-embed-text` junto al 7B le quita VRAM (389 MB en CPU); hoy conviven para no recargar en cada pregunta.
- La redacción no se comprueba frase a frase, solo sus nombres y citas: con nombres reales puede decir algo falso (dijo que `drop_client` llama a `cancel`, y es al revés).
- "Responde" no es "responde bien": una frase real copiada ("Llamadas al modelo que Ctrl+C corta al momento") pasa como respuesta.
- NINGUNA sale a veces con preguntas válidas, al azar: 2 de 16 en la última medición.
- "Cómo se cifra la contraseña" y las otras trampas dependen de que el 7B escriba NINGUNA: la cobertura no las separa. Una línea real que no responde pasaría la verificación.
- Un archivo sin fragmentos (`__init__.py` vacío) no guarda hash y `/indexar` lo cuenta como reindexado cada vez. No embebe nada; solo infla la cifra.
- El troceado solo no ayuda: sin el tope por archivo, las secciones del ROADMAP acapararon los resultados.
- BM25 se reconstruye en cada búsqueda con todos los documentos: se resuelve con SQLite FTS5 en la capa 2.

Conocimiento, pendientes generales:

- Knowledge Manager: destilar lo aprendido de proveedores externos, deduplicar y reindexar en una base global.
- Indexación incremental del RAG por hash y calibración de umbrales del retriever.
- Detección de código muerto por AST y auto-fix desde el diagnóstico de `DebugAgent`.

### Reflexión y proactividad (fase R, Asia 1.0)

Alcance en 1.0 (hecho): solo dentro de la sesión, sin proceso en segundo plano (eso es J4, en 2.0). Commits: `84813165`, `e76574ea`, `fac62387`, `c355a084`. Prueba manual: `test/manual/check_reflexion.py`, con carpetas temporales.
- Resumen al abrir Asia: la sesión anterior en 1–2 frases y los pendientes abiertos; si no hay nada, no muestra nada. Solo lee `data/reflexion/`, sin modelo (1,3 ms).
- `/pendiente <texto>` para anotar pendientes, `/pendientes` para verlos y `/hecho <n>` para cerrarlos, en `data/reflexion/pendientes.json` con escritura atómica y origen "usuario". Los cerrados se conservan con su fecha.
- Resumen de la sesión: 2–3 frases con el Ollama local, a partir de lo pedido, el principio de cada respuesta, las acciones y los envíos de la bitácora. Se actualiza en segundo plano tras cada respuesta (`SessionSummarizer`): espera `reflection.summary_idle_s` (3 s), a que acabe la lectura en voz y a que el modelo en uso sea el suyo, y un mensaje nuevo lo cancela. Al salir, si está al día, sale al instante; si no, muestra "Guardando resumen… (Ctrl+C para saltar)" hasta `reflection.summary_timeout_s` (30 s). Si no llega o se pulsa Ctrl+C, se guarda la lista de acciones. Nunca va a un proveedor externo ni a un Ollama en otra máquina. Los comandos de sesión no cuentan; una sesión sin mensajes conserva el resumen anterior.
- `/revisar memoria`: propone cada caso, y solo se borra con 1 o 2; cualquier otra respuesta deja las dos. Por defecto, solo reglas (claves casi iguales, valores iguales); con "a fondo", también el modelo local, del que solo valen claves que existen.

Tiempos con el 7B al 100 % en CPU, solo como referencia (repetir con la GPU; `summary_timeout_s` y los topes no se ajustaron con ellos): `/revisar memoria a fondo` 14,6–24 s con la memoria de prueba de 8 entradas. Resumen en segundo plano: al día 17,5 s después de la última respuesta, y salir tarda 0,0 s (antes 8,8–21,1 s). Cancelar un resumen en marcha añade ~3 s al mensaje siguiente (5,3 s frente a 2,4 s): cerrar la conexión no recupera lo que Ollama tenía en caché.

Por eso `/revisar memoria` usa solo reglas y el modelo queda en `/revisar memoria a fondo`: las reglas encontraron los 2 casos que les tocaban; el 7B encontró `ciudad`/`vivo_en` (contradicción que las reglas no ven) en 1 de 4 intentos y llamó "duplicada" a UAM/UNAM.

Pendiente: medir de nuevo `/revisar memoria a fondo` con la GPU (`check_reflexion.py`) antes de decidir si se queda.

El monólogo interno y la reflexión nocturna siguen sin fecha, en 2.0 (ver "Posibles pendientes sin fecha").

### Extras

**Imágenes en la terminal.** La terminal no pasa imágenes con Ctrl+V.
- Comando `/pegar` (se agrega a la tabla de `core/commands.py`): lee la imagen del portapapeles con `PIL.ImageGrab.grabclipboard()` (Pillow ya está instalado), la guarda en una carpeta temporal y la adjunta al mensaje.
- `@ruta.png` (y otros formatos de imagen) como adjunto, igual que los archivos de texto.
- Primera opción, para capturas de texto (errores, código, enunciados): OCR local con Tesseract. No necesita modelo de visión.
- Segunda etapa: modelo de visión local (`gemma3:4b` o `qwen2.5vl:3b`). Antes de elegir, medir el costo de recarga con 4 GB de VRAM: con un solo modelo en memoria a la vez (`ollama_one_model_at_a_time`), cada imagen descarga el 7B y lo vuelve a cargar después. Preguntar antes de descargar.
- Modo confidencial: las imágenes llevan la etiqueta "adjunto", así que son locales por defecto (ni la imagen ni el texto del OCR salen sin autorización).

**Cambio de modelo seguro.**
- Perfil por modelo en la configuración: contexto, si razona, si ve imágenes y ajustes de prompt propios (por ejemplo, el recordatorio de brevedad al final). Asia lee el perfil en vez de suponer.
- Comando de evaluación: corre con un modelo candidato los intents (`check_intents`), el benchmark de revisión (`check_review_quality`) y las pruebas de velocidad (`check_speed`), y da una tabla contra el modelo actual: aciertos, errores, velocidad.
- Los modelos abiertos (Gemma, Qwen, Llama, etc.) entran por Ollama; Claude y otros, solo por API, con un proveedor nuevo de una clase y siempre pasando por el modo confidencial.

**Especialistas internos** (no varios asistentes separados).
- Un orquestador manda cada mensaje a un especialista (prompt + modelo + herramientas), todos con la misma memoria, biblioteca de conocimiento y barrera de confidencialidad. `models_by_domain` es la primera versión.
- Verificación cruzada (uno genera, otro revisa) solo en tareas importantes, porque duplica el tiempo.
- Con el servidor (L), los especialistas podrían ser servicios separados en la red.

**Control y estimación.**
- Estimar el ruido de fondo del micrófono y ajustar el umbral del VAD (ampliar `/calibrar voz` para que sea automático).
- Control automático de ganancia del micrófono para la palabra de activación a distancia (2.0, cuando haya un micrófono externo). En 1.0, J3 se prueba con el micrófono de la laptop a distancia corta.
- Filtro de Kalman o bayesiano para el estado emocional en la fase de afecto, para que un solo mensaje no cambie la estimación.
- Regla: no usar un controlador donde una regla simple basta.

**Asia → ROS 2 → Bolitabot.** Control jerárquico: Asia entiende la orden y publica objetivos de alto nivel en un tópico de ROS 2; el controlador del robot (punto desplazado, PID) cierra el lazo en el dispositivo. El LLM nunca va dentro del lazo de control.

**Voz propia.** Fine-tuning de Piper en Colab a partir de una voz en español; el `.onnx` y su `.onnx.json` se dejan en `data/voices/` y se elige con `voice.tts_voice`, sin cambiar código.
- Permiso: la voz es de una persona que dio permiso; audios y modelo son solo de uso privado y se borran si lo pide.
- Preparar los audios: juntar todos, separar por origen, limpiar (Demucs, DeepFilterNet con moderación), cortar y transcribir con Whisper.
- Con 15–30 min limpios, fine-tuning directo de Piper en Colab; con menos, generar frases sintéticas con XTTS-v2 y entrenar Piper con ellas.
- La voz base del fine-tuning debe coincidir en género y acento con la final.

**SQLite como almacenamiento** (Asia 2.0), por partes.
- Historial completo de sesiones con búsqueda ("¿qué hablamos del PID la semana pasada?"). Base para R y para la fase de afecto.
- Memoria con fecha, origen y etiqueta de confidencialidad por entrada, para poder exportar lo inofensivo y retener lo sensible. Resuelve que hoy `memory.json` no tenga etiquetas por entrada. Hacerlo antes de la fase de afecto.
- Pendientes, bitácora y tiempos: migrarlos solo cuando se toquen por otro motivo.
- Se quedan en JSON: `settings.json`, `defaults.json` y `apps.json`, pequeños y editables a mano. Los vectores siguen en ChromaDB.
- Comandos para exportar y ver los datos, para no perder la comodidad de leer un JSON.
- `sqlite3` de Python, sin instalar nada, con transacciones para los hilos en segundo plano.

**Afecto y cognición social** (fase de afecto).
- Biblioteca de casos del usuario: situación → cómo la leyó → opciones → tono elegido y por qué → resultado. Anonimizar a terceros.
- Perfil de principios sacado de los casos, revisable por el usuario.
- Control de tono: elegir entre variantes; más adelante, DPO o LoRA.
- Evaluación con casos apartados que el sistema no vio.
- Reglas: todo local con la etiqueta "emocional"; sin adulación; no es terapeuta; el usuario puede ver, corregir y borrar lo que Asia cree de su estado; lo que simula "pensamiento" se documenta como simulación.

**Tareas grandes.**
- Bucle de agente: planear, dividir en tareas pequeñas, hacer una, verificar (pruebas, sandbox, simulación), corregir, siguiente. El plan se guarda en un archivo para retomarlo.
- Con el 7B: el usuario planea y Asia ejecuta y verifica cada paso.
- Modo híbrido: un modelo externo planea (con autorización o en modo abierto) y el local ejecuta los pasos simples.
- Con más VRAM (14–32B), planear en local. Medir con la evaluación de "Cambio de modelo seguro" antes de confiarle planes largos.
- El usuario sigue decidiendo el diseño; puntos de confirmación antes de cambios grandes.

**MCP** (implementación natural de la fase N).
- Asia como cliente MCP: conectar servidores existentes (archivos, GitHub, calendario) en lugar de programar cada integración.
- Lista de servidores permitidos; nada se conecta solo.
- Niveles de permiso por herramienta: leer libre; escribir, enviar o borrar siempre con confirmación mostrando qué va a hacer.
- Lo que devuelve una herramienta es dato, nunca instrucción, con su propia etiqueta en el modo confidencial (protección contra inyección de instrucciones desde páginas, correos o issues).
- Bitácora de cada llamada a herramientas.
- Empezar solo con lectura y abrir escritura poco a poco.
- Asia como servidor MCP: exponer sus acciones locales a Claude u otro cliente, con la barrera de confidencialidad aplicada.
- Candidato: AutoCAD (Windows). Revisar si hay servidor MCP existente o construir uno con su API (COM, .NET o AutoLISP). Reglas: trabajar siempre sobre una copia del dibujo, confirmar cada cambio y empezar por lectura (capas, bloques, medidas).

### Servidor y acceso remoto, siempre disponible (fase L)

Va después de los extras.
- Medir el uso real de RAM/VRAM antes de comprar el Jetson Orin Nano Super (8 GB de RAM soldada).
- Portar a ARM64 y revisar requisitos del Jetson.
- Tailscale para acceso remoto, con modo reducido en conexiones lentas.
- Respaldos de `memory/memory.json`, `memory/projects/`, `data/chroma/` y `data/reflexion/`.

### Posibles pendientes sin fecha

- Monólogo interno y reflexión nocturna (continuación de R, en 2.0).
- Casco o dispositivo ponible con Asia por Tailscale.

### Orden de trabajo

**Meta Asia 1.0 (objetivo: diciembre de 2026):**

1. Voz completa: J2 (hecho) y J3.
2. Reflexión y proactividad (R), solo dentro de la sesión: hecho.
3. Ejecutable nativo (I): hecho (`jarvis.bat` queda como respaldo por un tiempo).
4. Biblioteca de conocimiento offline (H).

**Asia 2.0 (todo lo demás), en este orden:**

1. Estabilizar el modelo actual con uso real.
2. ~~Fase 4 (limpieza) y revisión sin síntesis.~~ Hecho (`254dc3cd`, `284c1bdc`).
3. Cambio entre modelos. ~~Ver y cambiar el modelo por comando, `--model`, `models_by_domain`.~~ Hecho (`1231b36b`, `fccf75bd`). Falta lo de "Qué falta" en "Multi-modelo según tipo de tarea".
4. Voz: J4 y voz propia.
5. Avatar.
6. Extras: imágenes en la terminal, cambio de modelo seguro, especialistas internos, control y estimación, Asia → ROS 2 → Bolitabot, SQLite como almacenamiento, afecto y cognición social, tareas grandes y MCP.
7. Jetson, servidor y uso remoto (siempre disponible).
