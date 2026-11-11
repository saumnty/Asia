# Diseño del motor de permisos (Asia 2.0 y M)

Estado: borrador de diseño, 2026-11-11. Nada de esto está implementado salvo
lo que se describe en la sección 1 ("Lo que ya existe"). Todo lo demás es
propuesta y se marca como tal.

Alcance: el motor que decide, antes de cada acción de Asia o de M (el agente
de varios pasos), si la acción se hace, se pregunta o se niega; cómo se
registra la decisión; cómo se deshace; y cómo se aplica a un delegado
(OpenCode o Claude Code).

---

## 1. Lo que ya existe (1.0)

Hoy no hay un motor de permisos: hay confirmaciones sueltas, cada una con su
frase fija y su archivo de pendiente. Todas se reconocen por texto exacto, sin
el IntentEngine, para que una mala clasificación no aplique nada.

| Acción (código) | Qué pide hoy | Dónde | Pendiente guardado |
|---|---|---|---|
| `generate_code`, `smart_refactor` → `apply_change` | diff y "confirmar cambio" / "cancelar cambio" / "muestra el cambio pendiente" | `tools/apply_changes_tool.py`, `SHORTCUT_ACTIONS` en `core/brain.py` | `memory/pending_change.json` |
| `create_file` | nada si es nuevo y está dentro de la carpeta actual; si existe o está fuera, pasa a cambio pendiente | `tools/file_tool.py` (`is_inside_base_dir`, `propose_write`) | el mismo cambio pendiente |
| `append_file` | fuera de la carpeta actual, "no lo modificaré sin confirmación"; no busca el nombre en subcarpetas (`LOOKUP_ACTIONS = FILE_ACTIONS - {"append_file"}`) | `tools/file_tool.py`, `core/brain.py` | — |
| `run_sandbox` | muestra el código (40 líneas) y pide "confirmar ejecución" / "cancelar ejecución" | `core/actions/sandbox.py`, `tools/sandbox.py` | `memory/pending_run.json` |
| `open_app` | nombre exacto: abre; aproximado: "¿Abro X? s/N" (escrito o dicho); se olvida en el mensaje siguiente | `tools/app_tool.py`, `app_confirmation` en `core/brain.py` | en memoria (`AppTool.pending`) |
| Envío externo (Gemini u Ollama no confiable) | con contenido local: "envía esto a Gemini" → resumen de tipos y caracteres → "confirmar envío" (una vez) | `core/confidential.py`, `core/actions/confidential.py` | en sesión |
| `--allow-external` (CLI) | "¿Enviar? [s = sí, una vez / t = todos en esta ejecución / N = no]"; sin terminal, no envía | `launcher.py` (`confirm_external`) | — |
| Búsqueda en Wikipedia ofrecida | "¿Lo busco en Wikipedia? Responde «sí»" | `offer_wikipedia`, `is_affirmative` | `offered_search` |
| "salior" (casi salir) | "¿Quieres salir? (s/N)" | `launcher.py` | — |

Otras piezas que el motor debe reutilizar, no reemplazar:

- **Modo confidencial (fase G):** modos `local`, `normal` y `abierto`
  (`confidential_mode`, de sesión). Etiquetas de procedencia en
  `core/provenance.py`: `usuario`, `publica`, `memoria`, `archivo`,
  `adjunto`, `rag`, `proyecto`, `desconocido` (lo que llega sin etiqueta) y
  `emocional` (`NEVER_EXPORT`: nunca sale). Herencia de la más restrictiva
  (`RESTRICTIVENESS`). Rutas absolutas reemplazadas por el nombre en lo que
  sale (salvo modo abierto). `trusted_local_hosts` vacía por defecto.
- **Filtro de secretos:** `core/secrets_filter.py` (`redact`,
  `redact_messages`), aplicado en el router y en el IntentEngine. Por
  patrones: falsos positivos en código y no ve secretos sin formato conocido.
- **Bitácora de envíos externos:** `core/audit.py` →
  `logs/external_audit.jsonl`: fecha, proveedor, modelo, tipos, caracteres,
  SHA-256 de lo enviado, autorización, secretos redactados, respuesta. Nunca
  el texto. Consulta: "qué has enviado afuera".
- **Copias previas:** `apply_pending_change` copia el archivo a
  `memory/backups/<ruta>.<fecha>.bak` antes de escribir. No hay comando para
  restaurarla.
- **Sandbox:** venv desechable `--without-pip`, `python -I`, entorno mínimo
  sin claves, sin stdin, `sandbox_timeout` (20 s), mata el árbol al vencer.
  Lo dice el propio módulo: no aísla archivos ni red.
- **`write_safety`:** regla `ast` que avisa de leer y reescribir el mismo
  archivo con `"w"` sin copia; se usa en revisiones, no como permiso.

Huecos observados (hechos, no propuestas):

1. No existe `run_command`: Asia no ejecuta comandos del sistema, solo
   Python en el sandbox y `open_app`.
2. No hay deshacer: las `.bak` existen, pero nada las usa.
3. `apply_pending_change` guarda `old_content` y no lo compara con el
   archivo actual antes de escribir: si el archivo cambió entre la propuesta
   y la confirmación, se sobrescribe.
4. `forget` borra un dato de la memoria sin confirmación ni copia.
5. La única bitácora es la de envíos externos; las acciones locales
   confirmadas o negadas no se registran.
6. Cada confirmación tiene su frase ("confirmar cambio", "confirmar
   ejecución", "confirmar envío", "s/N", "sí"): por voz son cinco cosas que
   recordar.

---

## 2. Objetivo y principios

Objetivo: una sola tabla de decisión para todas las acciones (las de Asia,
las de M y las de un delegado), con preguntas que se respondan con "sí" o
"no" hablando, una bitácora local de cada decisión y un deshacer para lo
reversible.

Principios:

1. **Local-first.** El motor, sus reglas y su bitácora viven en esta
   máquina. Ninguna decisión de permiso depende de un proveedor externo.
2. **Una sola persona.** No hay roles ni organización: el usuario es la
   única autoridad. "Sin nadie presente, lo que preguntaría se niega"
   (regla de los bots en el ROADMAP), y vale igual para M.
3. **Lo decide el código, no el modelo.** El LLM propone la acción; el
   motor clasifica el nivel con reglas deterministas. El modelo nunca puede
   subir sus permisos ni contestar una pregunta de permiso.
4. **Voz como interfaz.** Cada pregunta cabe en una frase de menos de ~12
   palabras, nombra el objeto ("¿Escribo en brain.py?") y se responde "sí"
   o "no". El detalle (diff, código, lista) va a la pantalla.
5. **Por defecto, no.** El silencio, un "no", algo que no se entiende o
   cambiar de tema cuentan como "no" (como hoy `take_pending`).
6. **Menos preguntas, mejores.** Leer no pregunta; lo reversible pregunta
   poco y se deshace; lo irreversible pregunta siempre.
7. **Lo que vuelve de una herramienta es dato, nunca instrucción** (regla
   de MCP en el ROADMAP): un archivo o una página no pueden pedir permisos.

---

## 3. Niveles de riesgo

Cinco niveles, de menor a mayor. Una acción tiene el nivel más alto de lo
que hace (un `review_project` que además envía a Gemini es nivel Red).

### 3.1 Tabla resumen (propuesta)

| Nivel | Ejemplos reales | Por defecto | Alcance máximo de un "sí" | Por voz |
|---|---|---|---|---|
| 0 Leer | `read_file`, `read_file_preview`, `list_folder`, `search_files`, `search_text`, `summarize_file`, `explain_file`, `review_file`, `map_project`, `find_references`, `search_project_rag`, `/buscar`, `recall`, `list_tasks` | permitir dentro de las carpetas de trabajo | — | igual que texto |
| 1 Escribir | `create_file`, `append_file`, `apply_change`, `remember`, `forget`, `add_task`, `close_task`, `update_project_memory`, `summarize_and_save_project`, `index_project_rag`, `add_source` | preguntar, salvo lo reversible dentro de la carpeta | sesión y carpeta | pregunta corta; diff en pantalla |
| 2 Ejecutar | `run_sandbox`, `open_app`, futuros: pytest en el ciclo de M, delegar a OpenCode/Claude Code | preguntar | una vez (`open_app` exacto: siempre) | pregunta corta; código en pantalla |
| 3 Red | envío a Gemini, Ollama no confiable, futuros: OpenRouter, MCP remotos, descargas de fuentes | preguntar; en modo local, negar | una vez (dominio o proveedor: sesión) | solo con lo que sale resumido en voz |
| 4 Dinero | futuros: créditos de OpenRouter, servicios de pago de los bots | preguntar siempre, con importe | una vez, nunca más | no se confirma solo por voz |

### 3.2 Leer (nivel 0)

- No pregunta dentro de: la carpeta actual, el proyecto activo
  (`set_active_project`) y las fuentes de la biblioteca.
- Pregunta (propuesta): fuera de esas carpetas, como `external_directory`
  de OpenCode. "¿Leo una carpeta fuera del proyecto, Descargas? Sí o no."
- Niega siempre, sin preguntar: `.env`, `*.key`, `*.pem`, `id_rsa*`,
  `config/settings.json` como contenido para el modelo, binarios y archivos
  de más de 1 MB (las mismas exclusiones que la biblioteca en `CLAUDE.md`).
- Lo leído queda etiquetado (`archivo`, `rag`…): leer es libre, pero lo
  leído no sale libre (ver sección 4).

### 3.3 Escribir (nivel 1)

- No pregunta (propuesta): crear un archivo nuevo dentro de la carpeta
  actual (como hoy), `remember`, `add_task`, `close_task`: todos con
  deshacer.
- Pregunta: sobrescribir (`apply_change`, `create_file` sobre uno
  existente), escribir fuera de la carpeta, `forget`, `index_project_rag`
  de una fuente nueva.
- Niega siempre: archivos protegidos (`config/settings.json`,
  `config/apps.json`, `memory/*.json` salvo por las acciones de memoria), la
  carpeta `.git`, y cualquier ruta que resuelva fuera por un enlace.
- Antes de escribir, comprobar que el archivo no cambió desde la propuesta
  (hueco 3): si cambió, se vuelve a proponer.
- Alcance de un "sí": una vez, o "en esta carpeta durante la sesión" para M
  ("sí a todo en `core/`").

### 3.4 Ejecutar (nivel 2)

- Pregunta siempre, mostrando qué se ejecuta: hoy `run_sandbox` ya lo hace.
- `open_app` con nombre exacto de `config/apps.json`: no pregunta (como
  hoy). Aproximado: "¿Abro X? s/N" (como hoy).
- Para M (propuesta): una lista corta de comandos permitidos sin preguntar
  dentro del proyecto (`pytest`, `ruff check`, `python -m py_compile`), con
  el intérprete del `.venv`. Cualquier otro, pregunta. `pip install`, nunca
  sin pregunta propia (regla de *slopsquatting* del ROADMAP).
- Alcance: una vez. Para la lista permitida, sesión.

### 3.5 Red (nivel 3)

- Incluye todo envío a un proveedor externo (ya cubierto por la fase G),
  descargas (modelos, fuentes de documentación: `CLAUDE.md` exige preguntar
  con el tamaño) y, en el futuro, `webfetch` o MCP remotos.
- Pregunta: siempre que salga contenido no exportable; con solo `usuario` y
  `publica`, en modo normal, sale (como hoy).
- En modo local: niega sin preguntar. En modo abierto: permite el contenido
  pero sigue preguntando por descargas y por dominios nuevos.
- Alcance: una vez para contenido; "este dominio en la sesión" para
  consultas públicas (propuesta).
- Voz: antes de pedir el sí, decir qué sale en una frase: "Saldrían 2
  archivos, 3 400 caracteres, a Gemini. ¿Lo envío?".

### 3.6 Dinero (nivel 4)

- Cualquier acción con costo conocido o posible (créditos, APIs de pago).
- Pregunta siempre, con importe estimado y límite restante; nunca se
  recuerda la respuesta.
- Por voz: Asia puede preguntar, pero la confirmación es por texto (propuesta;
  ver decisión abierta 4). Whisper confunde "sí" con "si" condicional.
- Sin nadie presente: se niega.

### 3.7 Una sola respuesta (propuesta)

"sí" / "no" para todo (`AFFIRMATIVE` y `DONT_OPEN`), con las frases de hoy
como sinónimos; en niveles 3 y 4 el "sí" solo vale justo tras la pregunta.

---

## 4. Interacción con el modo confidencial

Regla: el nivel de una acción es el máximo entre su nivel propio y el que le
da el contenido que mueve.

| Contenido (etiqueta) | Nunca sale | Efecto en el nivel |
|---|---|---|
| `emocional` | nunca, ni con autorización ni en modo abierto | cualquier acción que lo mande fuera: negada sin preguntar |
| `desconocido` | sin autorización | como local (lo que llega sin etiqueta no sale) |
| `archivo`, `adjunto`, `rag`, `proyecto` | sin autorización de una vez | una lectura (0) que lo enviaría pasa a Red (3) |
| `memoria` | salvo `external_allow_memory` | se quita de lo que sale |
| `usuario`, `publica` | — | sin cambio |

Además:

- **Modo local:** todo nivel 3 se niega; el motor no pregunta (no hay "sí"
  que valga hasta "modo normal").
- **Delegar a Claude Code = enviar a un proveedor externo** (Anthropic).
  Delegar a OpenCode con un modelo de Ollama local es local; con un
  proveedor de nube, externo. El motor trata la delegación como nivel 3
  cuando el delegado usa un modelo externo, y aplica las etiquetas del
  proyecto: un proyecto marcado confidencial no se delega a uno externo.
- **Secretos:** la clave de Gemini y cualquier credencial nunca entran a un
  prompt, a una bitácora ni al entorno de un delegado.
- **Qué ve el log:** tipos de contenido, caracteres, hash SHA-256 y nombre
  de archivo sin ruta absoluta; nunca el texto. Igual que
  `logs/external_audit.jsonl` hoy.

---

## 5. Bitácora de decisiones (propuesta)

Archivo nuevo: `logs/permisos.jsonl`, una línea por decisión. La de envíos
externos (`logs/external_audit.jsonl`) sigue igual; cada decisión de nivel 3
enlaza con su entrada por el hash.

| Campo | Ejemplo | Nota |
|---|---|---|
| `fecha` | `2026-11-11T18:02:31` | ISO, segundos |
| `sesion` | id corto de la sesión | para agrupar |
| `origen` | `asia`, `M`, `opencode`, `claude-code`, `bot:<nombre>` | quién pidió la acción |
| `accion` | `apply_change` | nombre real del handler o herramienta |
| `parametros` | `{"archivo": "brain.py", "lineas": "+12 -3"}` | resumidos: nombres sin ruta absoluta, tamaños; nunca contenido |
| `nivel` | `escribir` | 0–4 |
| `etiquetas` | `["archivo"]` | procedencia del contenido |
| `decision` | `permitir`, `preguntar→si`, `preguntar→no`, `negar` | |
| `decidio` | `regla:<id>`, `usuario:voz`, `usuario:texto`, `sin-respuesta` | el modelo nunca aparece como quien decide un permiso |
| `alcance` | `una vez`, `sesion`, `carpeta:core/`, `siempre` | |
| `deshacer` | id de la copia previa o `null` | para `/deshacer` |
| `sha256` | hash de lo enviado o escrito | permite comprobar sin guardar |

Nunca se guarda: claves, tokens, contenido de archivos, texto tecleado de
etiqueta local, nada `emocional`. Los parámetros pasan por
`secrets_filter.redact` antes de escribirse. La consulta sería "qué has
hecho hoy" o `/permisos log`, como "qué has enviado afuera" hoy. Un futuro
clasificador aparecería como `regla:clasificador`, con su versión.

---

## 6. Deshacer

| Acción | Reversible | Cómo (propuesta) |
|---|---|---|
| `apply_change`, `create_file` sobre uno existente | sí | copia previa en `memory/backups/` (ya existe) |
| `create_file` nuevo | sí | borrar el archivo creado, si no cambió después |
| `append_file` | sí | copia previa, o recortar al tamaño anterior |
| mover / renombrar (futuro, M) | sí | mover de vuelta, si el origen sigue libre |
| `remember`, `forget`, `add_task`, `close_task` | sí | copia previa del JSON afectado |
| `index_project_rag`, `add_source` | parcial | quitar la fuente del índice; no recupera el tiempo |
| `run_sandbox`, comandos de M | no | el efecto fuera del venv no se conoce |
| `open_app` | no (inocuo) | — |
| Envío externo, descargas | no | lo enviado queda bajo la política del proveedor |
| Dinero | no | — |

Cómo se ofrece:

- Tras cada escritura reversible, la respuesta termina con "Puedes decir
  «deshaz eso»." (por voz, solo la primera vez en la sesión).
- "deshaz eso" / `/deshacer`: revierte la última acción reversible de la
  sesión, previa pregunta "¿Deshago el cambio en brain.py? Sí o no.".
- `/deshacer 3`: las tres últimas, en orden inverso (idea de "deshacer por
  instantáneas" del ROADMAP).
- Si el archivo cambió después de la acción, no se revierte a ciegas: se
  propone como cambio pendiente con su diff.
- Para lo irreversible, el motor lo dice antes de preguntar: "Esto no se
  puede deshacer. ¿Lo envío?".
- Las copias previas se borran a los 30 días (propuesta; hoy no se borran).

---

## 7. Delegación a OpenCode o Claude Code

M delega "la programación grande" (CONTEXTO, Asia 2.0). El delegado es un
proceso aparte con su propio motor de permisos; Asia no puede vigilar cada
llamada, así que fija las reglas antes y audita después.

### 7.1 Qué hereda y qué no

| Aspecto | Regla propuesta |
|---|---|
| Carpeta | `cwd` = raíz del proyecto activo; nada fuera (`external_directory: deny` en OpenCode; sin `--add-dir` en Claude Code) |
| Leer | permitido dentro del proyecto, salvo `.env`, claves, `config/settings.json`, `memory/`, `logs/`, `data/` |
| Escribir | permitido dentro del proyecto, en una rama de git propia (`asia/delegado-<fecha>`), nunca en `main` directamente |
| Ejecutar | solo la lista permitida (pytest, ruff, py_compile con el `.venv`); el resto, negado |
| Red | negada: `webfetch`, `websearch`, `curl`, `pip install`, `git push` |
| Dinero | negado |
| Secretos | entorno mínimo como el del sandbox: sin la clave de Gemini ni otras variables |
| Archivos protegidos | `config/settings.json`, `config/apps.json`, `memory/*.json`: negados |
| Commits | locales, nunca push (regla de `CLAUDE.md`) |

El delegado no recibe más permisos que los que Asia tiene en esa sesión
(mínimo privilegio): si Asia está en modo local, no se delega a Claude Code.

### 7.2 Cómo se pasan las reglas (propuesta)

- Asia genera un archivo de configuración temporal por delegación, con las
  reglas de 7.1 traducidas al formato del delegado, y lo pasa al lanzarlo:
  - OpenCode: reglas `permissions` (V2) o `permission` (V1) con `deny` para
    `webfetch`, `websearch`, `external_directory` y `shell` salvo
    patrones permitidos; `edit` permitido en el proyecto.
  - Claude Code: `permissions.deny` y `permissions.allow`, modo `dontAsk`
    (todo lo que preguntaría se niega), sin `bypassPermissions`, y un hook
    `PreToolUse` de Asia que niega lo protegido y registra cada llamada.
- Las instrucciones del proyecto (`CLAUDE.md`, `AGENTS.md` o el `ASIA.md`
  propuesto en el ROADMAP) se le pasan como texto, pero no sustituyen a las
  reglas: Claude Code documenta que las instrucciones no cambian lo que la
  herramienta permite.

### 7.3 Auditoría

- Antes: árbol de trabajo limpio (si no, se pregunta) y rama propia.
- Durante: el hook (Claude Code) o el registro de la sesión (OpenCode) van a
  `logs/permisos.jsonl` con `origen: claude-code` u `opencode`.
- Después: Asia muestra `git diff --stat` contra la rama de partida, corre
  pytest completo (revisando el código de salida, sin `tail`) y resume en
  voz: "Cambió 4 archivos, las pruebas pasan. ¿Lo dejo en la rama?".
- Deshacer la delegación entera: borrar la rama (pregunta propia).

### 7.4 Si el delegado pide un permiso

1. En modo no interactivo (`dontAsk` o equivalente) la petición se niega y
   queda registrada; el delegado sigue o termina.
2. Al terminar, Asia lista lo negado: "Pidió red 2 veces y `pip install
   numpy` una vez. ¿Quieres permitir alguno y repetir?".
3. Si el usuario dice que sí, Asia relanza con esa regla añadida solo para
   esa delegación. Nunca se reenvía la pregunta en vivo por voz a mitad de
   una tarea (propuesta; ver decisión abierta 6).

---

## 8. Comparación con OpenCode y Claude Code

Consultado el 2026-11-11 (ver Fuentes).

| Idea | OpenCode | Claude Code | Asia toma | Por qué |
|---|---|---|---|---|
| Efectos `allow` / `ask` / `deny` | sí, por acción y patrón | sí, reglas por herramienta | sí | el mismo vocabulario sirve para traducir a ambos delegados |
| Precedencia | la última regla que coincide gana | `deny` → `ask` → `allow`, sin importar especificidad | la de Claude Code | más difícil de equivocarse: un `deny` amplio no lo abre una excepción |
| Patrones | `*`, `?`, sin distinguir mayúsculas en Windows | glob tipo gitignore para rutas, `domain:` para web | rutas tipo glob y dominio | suficiente para una persona |
| Fuera del proyecto | `external_directory` (por defecto permitido) | directorios de trabajo + `additionalDirectories` | sí, pero por defecto preguntar | Asia toca más carpetas personales que un editor de código |
| Respuestas a una pregunta | `once`, `always` (se guarda como regla del proyecto), `reject` | "sí", "sí y no preguntes más" (sesión o permanente según la herramienta) | una vez y sesión; "siempre" solo por texto | "siempre" por voz es demasiado fácil de decir sin querer |
| Modos | agentes `plan`, `build`… con reglas propias | `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions` | un modo "plan" para M (solo leer y proponer) y el `dontAsk` para lo desatendido | encaja con "sin nadie presente, se niega" |
| Modo sin preguntas | allow total por defecto en la base | `bypassPermissions`, solo en contenedores | no | no hay contenedor en Windows; el riesgo es real |
| Clasificador | — | modo `auto` con clasificador | no (por ahora) | con el 7B local no es fiable; el motor queda determinista |
| Hooks | plugins con acciones propias | `PreToolUse` puede negar, forzar pregunta o permitir, sin saltarse un `deny` | sí, como punto de auditoría para delegar a Claude Code | permite registrar cada llamada del delegado |
| Políticas que solo restringen | `policies` (solo convierten en `deny`) | ajustes gestionados (`managed settings`) | sí, como lista fija de lo protegido | los archivos protegidos de `CLAUDE.md` no deben poder abrirse con una regla |
| Sandbox del SO | — | Seatbelt (macOS), bubblewrap (Linux/WSL2); no en Windows nativo | no en 1.x; revisar en Ubuntu/Jetson | Asia corre en Windows; el sandbox de Asia es un venv y lo dice |
| `.env` | pregunta antes de leer `*.env` | — (se configura con reglas) | negar siempre | regla ya fijada en `CLAUDE.md` |

---

## 9. Decisiones abiertas

Recomendada en **negrita**; si no hay respuesta, se usa esa.

| # | Decisión | Opciones | Razón de la recomendada |
|---|---|---|---|
| 1 | Dónde viven las reglas | a) en `config/defaults.json` · **b) archivo nuevo `config/permisos.json`, con valores por defecto en el código** · c) solo en código | se revisa aparte y no toca `config/settings.json` |
| 2 | Escritura reversible dentro de la carpeta | a) preguntar siempre, como `apply_change` hoy · **b) no preguntar si hay copia previa; sí al sobrescribir** · c) no preguntar nunca dentro | menos preguntas por voz sin perder nada |
| 3 | Frase de confirmación | a) una frase por tipo, como hoy · **b) "sí"/"no" para todo, con las frases actuales como sinónimos** · c) "sí" en 1–2 y "confirmo" en 3–4 | una sola respuesta por voz sin romper la costumbre |
| 4 | Dinero por voz | a) basta un "sí" · **b) pregunta por voz, confirmación solo por texto** · c) prohibido hasta tener control de gastos | un error de Whisper no debe costar dinero |
| 5 | Alcance "siempre" | a) no existe · **b) solo por texto, niveles 0–2, visible y revocable con `/permisos`** · c) también por voz | por voz se dice por error y no se ve |
| 6 | Delegado que pide un permiso a mitad de tarea | a) reenviar la pregunta en vivo · **b) negar, registrar y ofrecer relanzar al terminar** · c) abortar la delegación | una pregunta en vivo por voz llega sin contexto |
| 7 | Delegar a Claude Code con código del proyecto | a) libre · **b) como envío externo: una pregunta por delegación, hash en bitácora, negado en modo local** · c) solo en modo abierto | coherente con la fase G: el código sale a Anthropic |
| 8 | Bitácora: uno o dos archivos | a) todo en `logs/permisos.jsonl` · **b) dos archivos enlazados por hash** · c) migrar ya a SQLite | no rompe "qué has enviado afuera"; SQLite cuando se toque |
| 9 | Archivo cambiado entre propuesta y confirmación (hueco 3) | a) sobrescribir, como hoy · **b) comparar con `old_content` y volver a proponer** · c) combinar automáticamente | es el único caso actual que pierde trabajo sin aviso |
| 10 | Leer fuera de las carpetas de trabajo | a) permitir, como OpenCode · **b) preguntar una vez por carpeta y sesión** · c) negar | Descargas o Documentos son legítimos, pero el usuario debe enterarse |

---

## Fuentes

Consultadas el 2026-11-11:

- OpenCode, Permissions: https://opencode.ai/docs/permissions/
  (reglas `permissions` V2 / `permission` V1, efectos, patrones, orden
  "la última gana", `external_directory`, respuestas `once`/`always`/
  `reject`, `policies`, valores por defecto por agente).
- Claude Code, Configure permissions:
  https://code.claude.com/docs/en/permissions (modos, orden
  deny → ask → allow, reglas por herramienta, `additionalDirectories`,
  hooks `PreToolUse`, ajustes gestionados).
- Claude Code, Sandboxing: https://code.claude.com/docs/en/sandboxing
  (archivos, red con lista de dominios, Seatbelt/bubblewrap, sin soporte en
  Windows nativo).

No verificado el 2026-11-11 (de memoria, comprobar antes de implementar):

- Los flags exactos para lanzar sin interfaz y con una configuración
  temporal: en Claude Code, `-p`, `--permission-mode`, `--settings`,
  `--allowedTools` / `--disallowedTools`; en OpenCode, `opencode run` y la
  variable o el flag para indicar un archivo de configuración.
- Cómo registra OpenCode cada llamada a herramientas en una sesión no
  interactiva (para la auditoría de 7.3).
