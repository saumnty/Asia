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

## Próximas fases

### Pendientes menores

- "Proyecto activo" es solo un nombre; asociarle una ruta permitiría limitar la escritura al proyecto y no solo a la carpeta actual (detectado en la fase 3).
- Las respuestas de `debug_project` y la de archivo protegido de `generate_code` llegan al usuario con 12 espacios de indentación en cada línea (heredado de cómo estaban escritas; se conservó en el refactor de la fase E por ser comportamiento).
- "muéstrame un resumen del archivo X" va a `read_file_preview` (las primeras líneas), no a `summarize_file`. Se dejó así en la fase E para no cambiar la acción.
- `remember`, `recall` y `forget` sin `key` caen al chat sin aviso.
- "encuentra por qué aparece Asia None" hace `review_project` con síntesis sobre todo C:\Asia: 15 archivos × ~750 tokens a ~7 t/s, más de 15 minutos. `debug_project` tarda 68 s, pero su prompt (~19 500 tokens estimados) no cabe en `ollama_num_ctx=16384`: Ollama descarta el principio (instrucciones y problema) y el diagnóstico no menciona el bug. Opción por decidir antes de implementar.

## Fases futuras (diseño pendiente)

### Multi-modelo según tipo de tarea

**Objetivo:** usar varios modelos de Ollama según la naturaleza del prompt. Por ejemplo, `qwen2.5-coder:7b` para código, un modelo de razonamiento destilado (tipo `deepseek-r1`) para matemáticas/física y un generalista para conversación e inglés.

**Punto de partida:** desde la fase 2 los modelos ya no están en el código: `ollama_model`, `intent_model` y `embedding_model` viven en `config/defaults.json`.

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

- Imágenes desde el portapapeles (`:pegar`): la terminal no pasa imágenes con Ctrl+V. `PIL.ImageGrab.grabclipboard()` (Pillow ya está instalado) guardaría la imagen en una carpeta temporal para adjuntarla. Requiere un modelo con visión (ver "Multi-modelo"); hoy no hay ninguno descargado, así que se deja para después de la fase F.
- PDF y texto largo vía RAG en vez de recortar.
- Reemplazar `jarvis.bat` por un ejecutable nativo, para evitar el "¿Desea terminar el trabajo por lotes (S/N)?" de Windows al interrumpir con Ctrl+C.
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

- Modo solo-local (ningún dato sale a proveedores externos).
- Modo que entrega a proveedores externos únicamente contexto de memoria, sin código.
- Registro de auditoría de lo que sale hacia afuera.

### Voz y avatar

- Voz local: reconocimiento con faster-whisper y síntesis con Piper (voz femenina).
- Canal de estado local (Flask-SocketIO) para que el avatar reaccione a hablar, pensar y escuchar.
- Avatar: perro bóxer.

### Conocimiento offline

- Herramienta de Wikipedia offline con Kiwix/ZIM, separada del RAG de proyectos.
- Knowledge Manager: destilar lo aprendido de proveedores externos, deduplicar y reindexar en una base global.
- Indexación incremental del RAG por hash y calibración de umbrales del retriever.
- Detección de código muerto por AST y auto-fix desde el diagnóstico de `DebugAgent`.

### Servidor y acceso remoto

- Medir el uso real de RAM/VRAM antes de comprar el Jetson Orin Nano Super (8 GB de RAM soldada).
- Portar a ARM64 y revisar requisitos del Jetson.
- Tailscale para acceso remoto, con modo reducido en conexiones lentas.
- Respaldos de `memory/memory.json`, `memory/projects/` y `data/chroma/`.

### Orden de trabajo

1. Estabilizar el modelo actual con uso real.
2. Fase 4 (limpieza) y revisión sin síntesis.
3. Cambio entre modelos.
4. Wikipedia offline.
5. Voz.
6. Avatar.
7. Jetson, servidor y uso remoto.
