# Asia: reglas fijas del proyecto

## Git
- No hagas push. Los commits son locales; el push lo hace el usuario.
- Un commit por cambio, pytest por cambio, sin push.
- Revisa siempre el código de salida de pytest completo, sin tail.

## Pruebas
- Cada cambio de comportamiento lleva una prueba pytest con carpetas temporales.
- El intérprete del proyecto es `.venv/Scripts/python.exe`.

## Archivos protegidos
- No modifiques `config/settings.json` ni la memoria real (`memory/*.json`).
- No modifiques ni incluyas en commits `config/apps.json`.

## Instalaciones y modelos
- No instales paquetes ni descargues modelos sin pedirlo antes.
- Antes de descargar cualquier modelo, di cuáles y cuánto pesan.
- Pregunta antes de descargar cada fuente de documentación, con su tamaño.
- Con ~1.7 GB de RAM libre, no cargues dos modelos a la vez sin avisar. Excepción: `nomic-embed-text` puede convivir con el 7B durante las búsquedas.

## Configuración del modelo
- No cambies `ollama_num_ctx` por defecto sin confirmación (se queda en 16384).
- No cambies el modelo por defecto del chat sin confirmación.
- No toques `keep_alive`.
- La GPU se detecta desde Ollama 0.40.14: el 7B va con 16 capas en GPU (`num_gpu` 16). Anota tiempos, no ajustes límites por ellos.

## Secretos
- La clave de Gemini nunca debe aparecer en logs ni en prompts.

## Biblioteca (RAG)
- Además de `data/`, `memory/`, `logs/` y `config/settings.json`, respeta el `.gitignore` de cada fuente y excluye siempre `.env`, archivos de claves (`*.key`, `*.pem`, `id_rsa`…), binarios y archivos de más de 1 MB.

## Uso eficiente

### Modelo según la dificultad
- Antes de empezar un prompt, clasifica cada parte y di en una línea qué modelo hará cada una y el tiempo estimado.
- Difícil → subagente con model "fable" (o "opus" si Fable no está disponible o se agotó el límite): diseño de arquitectura, diagnósticos sin causa clara después de un intento, decisiones con varias alternativas, cambios en seguridad, confidencialidad o permisos, y la revisión crítica de un plan grande.
- Normal → Sonnet: implementar con una especificación clara, escribir pruebas, refactorizaciones acotadas.
- Mecánico → subagente con model "haiku": buscar en el código, correr pytest o scripts y resumir su salida, editar documentación con un texto dado, renombrar, validar JSON o que algo compile, armar tablas de un reporte.
- A cada subagente: un encargo autocontenido y breve (rutas, criterios de éxito, formato de respuesta corto), porque empieza sin el contexto de la sesión. No le pases archivos enteros si bastan rangos de líneas.
- Si una parte falla dos veces, sube un nivel de modelo y dilo en el reporte. Si una parte "difícil" resultó sencilla, la próxima vez clasifícala más abajo.
- Nunca uses Fable ni Opus para esperar procesos, leer salidas largas o tareas mecánicas.
- Si conviene que toda la sesión cambie de modelo, dímelo con el comando exacto (/model …) en lugar de seguir.
- En el reporte final, qué modelo hizo cada parte.

### Preguntas juntas
- Al empezar un prompt, revísalo completo y haz todas las preguntas necesarias en un solo mensaje, numeradas, cada una con tu opción recomendada. Si no respondo, usa la recomendada.
- Durante el trabajo no te detengas por dudas menores: decide lo razonable y anótalo en una sección "Decisiones tomadas" del reporte.
- Solo te detienes por: algo irreversible, instalar o descargar, archivos protegidos, privacidad, o una contradicción en el prompt. Si a mitad surgen varias dudas de ese tipo, júntalas en un mensaje.

### Ahorro de tokens
- Procesos largos (entrenamientos, transcripciones, pytest completo): en segundo plano con aviso al terminar; nada de revisar el estado cada pocos segundos.
- Lee lo justo: grep y rangos de líneas; no releas lo que ya leíste en la sesión.
- Reportes cortos: números en tablas o listas, sin repetir el prompt ni explicar lo obvio. Lo largo (salidas, análisis) va a un archivo y en el reporte solo la ruta y el resumen.
- Al terminar un prompt grande, sugiere /compact antes del siguiente.
