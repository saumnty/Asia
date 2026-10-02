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

**Primer caso concreto: la síntesis de `review_project`.** Con la entrada completa, `qwen2.5-coder:7b` hace buenas revisiones por archivo pero malas síntesis (ver "Alucinación en revisiones largas"). Opciones:
1. Un modo de `review_project` que devuelva los reportes por archivo sin síntesis final. No requiere otro modelo; es lo más barato y lo que mejor funcionó en las pruebas.
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

**Corregido durante esa evaluación** (causas que no eran del modelo):
- `985e02ec`: los scripts de `.github/` entraban en la selección desde que se unificaron las extensiones, y empataban en prioridad con el código. Ahora `review_ignored_dirs` los excluye al elegir qué revisar.
- `f3c0eb9a`: dos reglas del prompt de síntesis mencionaban secciones "ARCHIVO SELECCIONADO" que no existían en el prompt.

**Contexto:** desde la fase 1, cada revisión por archivo es una llamada independiente (`ProviderRouter.ask`, sin historial), así que no hay "memoria" que se degrade entre archivos.

**Uso recomendado mientras tanto:** para revisiones que importan, usar "revisa a fondo X.java" (`review_file_deep`, un archivo por llamada) en vez de "revisa el proyecto completo". Los reportes por archivo fueron los más precisos en todas las pruebas.

**Pendiente:**
- Modo sin síntesis y modelo distinto para la síntesis: ver "Multi-modelo según tipo de tarea".
- Proyectos más grandes que `practica2` pueden superar 16384 tokens en la síntesis (unos 30 reportes). El aviso por stderr lo detecta; si pasa seguido, habrá que procesar en lotes.

### CLI enriquecida

- Modo multilínea para pegar bloques largos de código, terminado con `FIN` en una línea sola.
- Entrada por stdin/pipes: `Get-Content archivo.py | jarvis "explica esto"`.
- Análisis directo de un archivo: `jarvis "analiza archivo.py"`, con la ruta resuelta contra la carpeta del usuario (`Session.get_user_cwd()`). Las tools de archivos ya resuelven rutas relativas contra esa carpeta desde la fase 2; lo que falta es un camino directo que no dependa de que el IntentEngine acierte la acción.
- Flags: `--project`, `--provider`, `--no-stream`.
- Reemplazar `jarvis.bat` por un ejecutable nativo, para evitar el "¿Desea terminar el trabajo por lotes (S/N)?" de Windows al interrumpir con Ctrl+C.
