# Cierre de Asia 1.0: mediciones del 2026-11-10 y 11

Mediciones sin micrófono para los criterios de cierre (ROADMAP, "Criterios de cierre de 1.0"). Una medición con modelo real a la vez, Asia cerrada y `ollama stop` antes de cada una.

## 1. Primer audio de las acciones con voz

`test/manual/check_primer_audio.py` mete cada frase por texto en el mismo camino que sigue la voz después de Whisper (`launcher.prepare_message` y `launcher.respond` con la sesión de voz): IntentEngine, la acción, Ollama con streaming y Piper. El audio se sintetiza, pero no suena. Antes de cada corrida queda cargado el modelo del IntentEngine (qwen3), como al abrir Asia o después de una charla. Mediana de 3 corridas, en segundos desde que entra el texto.

Para repetirlo con el micrófono: `check_voz.py` con `--timing`; la línea `[tiempos]` da el mismo "primer audio", al que se suma la voz a texto.

### Antes (código de `158184f`)

| Acción | Intención | Herramienta | Generación hasta la 1.ª frase | Síntesis | Primer audio | Carga del modelo |
|---|---|---|---|---|---|---|
| `explain_file` launcher.py | 1,8 | 0,0 | 19,1 | 0,6 | **21,5** | 10,3 |
| `summarize_file` docs/DEMO.md | 1,8 | 0,0 | 18,1 | 1,2 | **21,1** | 9,5 |
| `summarize_folder` docs | 1,7 | 0,0 | 49,1 | 0,2 | **51,1** | 9,5 |
| `review_file` core/timing.py | 1,8 | 0,0 | 220,6 | 0,3 | **222,6** | 9,6 |
| `/buscar` entorno virtual en Python | 0,0 | 36,1 | 10,5 | 0,2 | **46,8** | 0,0 |

La generación incluye la carga del modelo (la última columna).

**Cuello de botella:** cambiar de modelo. La intención la hace qwen3, que ya está en la GPU, y la respuesta va al 7B, que tarda unos 10 s en cargar y después procesa el prompt con 16 capas en la GPU. Además, `summarize_folder` y `review_file` no tenían streaming ni versión breve: no sonaba nada hasta acabar la respuesta entera, de 250 a 1100 tokens.

### Iteración 1

- La respuesta breve por voz de `explain_file`, `summarize_file` y `summarize_folder` va al modelo que ya está cargado. Es `voice_brief_domain` (por defecto `"general"`, qwen3), si el prompt y la respuesta caben en sus 4096 tokens con un margen de 1,2 sobre la estimación; si no, va al 7B como antes. "A fondo" y sin voz no cambian.
- `summarize_folder` con voz: respuesta breve de 1 a 3 frases, con streaming. Lee 250 caracteres por archivo (`context_limits.summarize_folder_voice`) en vez de 1200, para que quepa.
- `review_file` con voz: streaming. Sigue en el 7B, porque las revisiones van al 7B en la estrategia B.

| Acción | Intención | Herramienta | Generación hasta la 1.ª frase | Síntesis | Primer audio | Carga | Antes |
|---|---|---|---|---|---|---|---|
| `explain_file` | 0,7 | 0,0 | 1,9 | 1,4 | **4,2** ✅ | 0,0 | 21,5 |
| `summarize_file` | 0,9 | 0,0 | 3,0 | 0,9 | **5,0** ✅ | 0,0 | 21,1 |
| `summarize_folder` | 0,5 | 0,0 | 1,3 | 0,8 | **2,7** ✅ | 0,0 | 51,1 |
| `review_file` | 1,8 | 0,0 | 16,8 | 0,3 | **19,2** ❌ | 9,5 | 222,6 |
| `/buscar` | 0,0 | 34,9 | 6,1 | 0,2 | **41,2** ❌ | 0,0 | 46,8 |

La primera corrida de `explain_file` fue de 8,2 s; las otras dos, de 4,2 y 2,9 s. Las respuestas de qwen3 se leyeron bien: explican el archivo en 1 a 3 frases y en español.

**Criterio de cierre** (`explain_file` y `summarize_file` ≤ 15 s): cumplido sin micrófono, con 4,2 y 5,0 s. Con el micrófono se suma la voz a texto, de 2,6 a 3,9 s medidos en J1: queda en unos 8–9 s.

### Lo que no llega a 15 s, con diagnóstico y opciones

**`review_file`, 19,2 s:** 9,5 s de carga del 7B, unos 3 s de prompt (2000 tokens a 16 capas en la GPU), la intención y la primera frase. Opciones:
1. Revisión breve por voz en qwen3 (unos 5 s). Se pierde la calidad del 7B en las revisiones, que es la razón de la estrategia B; habría que medirla con `check_review_quality`.
2. Atajo sin IntentEngine para "revisa el archivo X" cuando X existe: −1,8 s, a unos 17 s. Por sí solo no llega.
3. Aceptarlo: las revisiones no están en el criterio, y "revisa" por voz ya empieza a sonar a los 19 s, frente a los 223 s de antes.

**`/buscar`, 41 s:** dos o tres llamadas al 7B una detrás de otra (traducir, copiar las líneas, responder), con la verificación de las citas en medio. Por diseño no puede sonar antes de verificar. Opciones: un aviso hablado al empezar ("Lo busco en tus fuentes…"), o las palabras clave con qwen3.

**Hallazgo:** por voz, "busca en la biblioteca cómo…" lo manda el IntentEngine a `search_text` (grep en el proyecto), no a la biblioteca: solo `/buscar` tecleado llega a ella. Y un nombre de archivo suelto que no está en la carpeta abierta ("explica timing.py", que está en core/) no se encuentra, y el modelo contesta que el archivo no existe. Las dos cosas quedan para 2.0 (ROADMAP, "Asia 2.0", punto 4).

## 2. `check_*` sin micrófono

Uno a la vez, con `ollama stop` entre cada uno, el 2026-11-10 (unos 95 min en total).

| Check | Resultado | Código |
|---|---|---|
| `check_confidencial` | 6/6 casos | ✅ 0 |
| `check_intents` | 44/44 | ✅ 0 |
| `check_chat` | 21/21 correctas, 0 atribuciones, 0 fugas | ✅ 0 |
| `check_afecto` | 26/28 | ✅ 0 |
| `check_afecto --calibracion` | 19/20 | ✅ 0 |
| `check_reflexion` | sin fallos | ✅ 0 |
| `check_rag` | dentro de la base | ✅ 0 |
| `check_rag --punta-a-punta 1` | 20/24, trampas 0/9 | ✅ 0 |
| `check_rag --wikipedia 0` | 10/12 artículos, base 11 | ❌ 1 |
| `check_rag --wikipedia 1` | 10/12 artículos, 6/12 correctas, trampas 0/6 | ❌ 1 |
| `check_rag --preguntas 0` | todos los sitios en su base o por encima | ✅ 0 |
| `check_rag --preguntas 1` | trampas 0 en los seis sitios | ✅ 0 |
| `check_voz --sin-microfono --sin-audio` | primer audio de la charla 5,5 s | ✅ 0 |
| `check_speed --sin-archivo` | 50 t/s en qwen3 | ✅ 0 |
| `check_review_quality --runs 1` | precisión 1,00, recall 0,67 en `archivo auto` | ✅ 0 |

**Los dos rojos de Wikipedia** no tienen una causa clara en el código: lo de hoy no toca la búsqueda del `.zim`. `--wikipedia 0`, repetido, da los mismos 10/12; fallan "cuántos huesos tiene el cuerpo humano" y "cuál es la montaña más alta del mundo", porque las palabras clave de qwen3 no llevan a "Esqueleto_humano" ni a "Everest". La base 11 está en el límite alto: el ROADMAP ya registró 10/12 con la Wikipedia completa (2026-11-04). No cambié la base: queda para decidirla (bajar `wikipedia.encontrados` a 10, o mejorar el prompt de palabras clave).

`check_gemini` no se corrió: manda texto fuera de la máquina y no es criterio de cierre.

### Pendiente de Santiago (con el micrófono)

```
.venv\Scripts\python.exe test\manual\check_voz.py --timing
.venv\Scripts\python.exe test\manual\check_wake.py --modelo oye_asia_v0.2 --aciertos 20 --guardar-audio data\wake\prueba_v02
.venv\Scripts\python.exe test\manual\check_wake.py --modelo oye_asia_v0.2 --falsas 30 --guardar-audio data\wake\prueba_v02
```

El primero, con "explica el archivo launcher.py" dicho en voz alta, da el primer audio de las acciones con la voz a texto incluida. Los otros dos, después de entrenar v0.2 (`docs/J3_V02.md`).

## 3. J3 listo para v0.2

- `comparar_wake.py --audios CARPETA --modelo A --modelo B`: puntúa los mismos `intento_NN.wav` y `falsas_NN.wav` con cada modelo, barre los umbrales de 0,05 a 0,95 y elige el que cumple 17/20 y ≤ 0,5 falsas por hora, o el más cercano. Con `--guardar`, el JSON.
- `check_wake --falsas --guardar-audio` guarda lo escuchado para compararlo después.
- Probado de punta a punta con v0.1 contra sí mismo y audio sintético: tablas idénticas, elige 0,75, código 1 (no cumple).
- Secuencia completa: `docs/J3_V02.md`.

## 4. Segunda vuelta (2026-11-10, noche)

### Wikipedia: palabras clave y pregunta original unidas

`found_articles` (core/rag/wikipedia.py) une, por fusión de rangos recíprocos y sin duplicados, las búsquedas de los títulos de las palabras clave, de cada palabra clave, de todas juntas y de la pregunta original, con el mismo número de artículos (3). Lo que sale en varias búsquedas sube: "Esqueleto_humano" (huesos) entra. "Monte_Everest" no sale en ninguna búsqueda de "la montaña más alta del mundo".

| Check | Antes | Corrida 1 | Corrida 2 |
|---|---|---|---|
| `--wikipedia 0` (artículo entre los 3) | 10/12 | 11/12 ✅ | 11/12 ✅ |
| `--wikipedia 1` (artículo entre los 3) | 10/12 | 11/12 ✅ | 11/12 ✅ |
| `--wikipedia 1` (respuestas correctas, trampas) | 6/12, 0/6 | 8/12, 0/6 | 6/12, 0/6 |

`--preguntas 0` sin cambios (en Stack Exchange no hay palabras clave: una sola lista conserva su orden). Base sin cambiar.

### Tareas largas con voz: aviso fijo y criterio propio

Criterio nuevo (ROADMAP): aviso fijo ≤ 1 s; `review_file` ≤ 25 s; `/buscar` p50 ≤ 32 s en 5 corridas con la respuesta verificada (antes ≤ 30 s). Medido con `check_primer_audio.py --llamadas` (mediana de 3 corridas; `/buscar`, de 5), sin micrófono.

| Acción | Aviso antes | Aviso después | Primer audio antes | Después | Criterio |
|---|---|---|---|---|---|
| `review_file` core/timing.py | — | **0,0** ✅ | 19,2 (lee el preámbulo) | **22,7** ✅ (desde el primer hallazgo) | ≤ 25 |
| `/buscar` entorno virtual en Python | — | **0,0** ✅ | 41,2 | 31,2 (22,8–36,7) → **26,8** ✅ (25,7–31,8) | p50 ≤ 32 |

Lo que cambió:
- Aviso: "Reviso el archivo." y "Busco en la biblioteca." se sintetizan al cargar la voz (`core/voice/notices.py`) y van directo al altavoz. La primera vez, 0,3–0,4 s; después, 0,0.
- `review_file`: atajo sin IntentEngine para "revisa (el archivo) X" (−1,8 s y el aviso antes de 1 s). Con voz se lee desde el primer hallazgo completo; el preámbulo y los títulos no. El prompt no cambia: `check_review_quality --runs 1` igual (archivo: 1 falso, antes 2).
- `/buscar`:
  - Traducción con qwen3 (`rag.translate_domain`) y ninguna si la pregunta ya está en inglés.
  - Con voz, el 7B devuelve solo números de línea y el código copia el texto exacto (`quotes.numbered_context`), con 4 fragmentos en vez de 5, una respuesta de 1 o 2 frases (tope de 120 tokens) y el 7B precargado durante la búsqueda sin descargar nomic.
  - Los embeddings conectan a 127.0.0.1: con "localhost", Windows esperaba 2 s por conexión (4 s por búsqueda).
- Por texto, `/buscar` sigue copiando las líneas: con números, `check_rag --preguntas 1` respondió una trampa ("capital de Australia" con una línea `pais: "Australia"`) y `--punta-a-punta 1` bajó de 20/24 a 18/24. Repetidos por texto después del cambio: `--preguntas 1` y `--punta-a-punta 1` con código 0, trampas en 0 y 20/24.

**`/buscar`: cumple con el criterio de p50 ≤ 32 s.** Segunda medición de 5 corridas, el mismo código: 31,8, 25,7, 26,8, 26,7 y 30,4 s (mediana 26,8; aviso 0,0–0,3 s). La variación entre corridas no deja garantizar 30 s, por eso el criterio va por la mediana.

**Deuda para la 1.1: acercarse al piso.** Cuenta (Fable): traducción 3 s, búsqueda y carga del 7B solapadas 12–15 s (Ollama carga uno a la vez y la RAM libre es poca), citas 7–9 s y respuesta 6–8 s. El piso con esta arquitectura es de unos 26–27 s, y la variación entre corridas, de ±6 s. Opciones (para la 1.1):
1. Los dos embeddings (pregunta y traducción) en una sola llamada, antes de la precarga (−1 a −3 s).
2. Recortar cada fragmento a las líneas que comparten palabras con la pregunta (−2 a −3 s; riesgo para las citas, medir con check_rag).
3. Si el 7B ya está cargado (después de otra acción de código), traducir con él y no precargar (−7 a −14 s solo en ese caso).
4. Responder desde las citas con qwen3 (−5 s o más): cambia la estrategia B; habría que medir la calidad.

### Voz: biblioteca y nombres de archivo

- "busca en la biblioteca…", "busca … en mis fuentes", "busca en Wikipedia…" y "busca en la documentación de ROS 2…" van a `/buscar` sin el IntentEngine (`fixed_intents.library_search`), y el IntentEngine tiene la regla para las variantes. `check_intents`: 49/49, con 5 casos nuevos.
- "explica timing.py": el nombre se busca en la carpeta de Asia (`core/file_lookup.py`; sin entornos, `data/`, `memory/` ni `logs/`). Una coincidencia: esa ruta. Varias: "¿Cuál?" con la lista, para el mensaje siguiente, como "¿Abro X? s/N" de open_app. `append_file` no busca.
