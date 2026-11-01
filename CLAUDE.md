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
- La GPU sigue sin detectarse: anota tiempos, no ajustes límites por ellos.

## Secretos
- La clave de Gemini nunca debe aparecer en logs ni en prompts.

## Biblioteca (RAG)
- Además de `data/`, `memory/`, `logs/` y `config/settings.json`, respeta el `.gitignore` de cada fuente y excluye siempre `.env`, archivos de claves (`*.key`, `*.pem`, `id_rsa`…), binarios y archivos de más de 1 MB.
