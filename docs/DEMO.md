# Demo de Asia 1.0 (2–3 min): lista para grabarla

Para grabar la pantalla con el audio del sistema y el micrófono. Marca cada casilla: antes de grabar, en la pasada de prueba y en la grabación. Cada bloque dice qué hacer, qué decir y qué tiene que verse. Los tiempos son orientativos.

Revisada contra el código del 2026-11-10: los comandos, los mensajes y la configuración que se citan existen tal cual.

## Antes de grabar

- [ ] Cerrar lo que use la GPU o mucha RAM. `ollama ps` vacío.
- [ ] Terminal grande, con letra legible, abierta en `C:\Asia`. Los archivos que se nombran por voz se buscan desde la carpeta donde se abrió Asia.
- [ ] Palabra de activación:
  - Si "Oye Asia" ya pasó sus criterios (`docs/J3_V02.md`), en `config/defaults.json` → `voice` van `wake_word`, `wake_label` y `wake_threshold`.
  - Si no, se queda "Hey Jarvis", y en el guion se dice "Hey Jarvis" donde pone "Oye Asia".
- [ ] `stream_output` en true (es el valor por defecto en `config/defaults.json`).
- [ ] La fuente de `/buscar` indexada: `/fuentes` muestra la documentación de ROS 2.
- [ ] No mostrar `memory/` ni `/revisar memoria`: tienen datos personales.
- [ ] Una pasada de prueba completa fuera de cámara. Sirve también para que Ollama cargue los modelos.

## Guion

### 0:00–0:15 · Presentación
- [ ] Escribir `asia`. Se ve el saludo y el prompt `Tú:`.
- [ ] Decir: "Esta es Asia, un asistente que corre entero en esta laptop, con modelos locales. Nada sale de la máquina si yo no lo autorizo."
- [ ] Teclear `hola`. La respuesta llega enseguida: la charla clara no pasa por el IntentEngine.

### 0:15–0:45 · Voz
- [ ] Teclear `/escucha`, que activa también la voz. Sale «Escucha activada: di «Oye Asia»…» y el prompt queda `Tú [esperando «Oye Asia»]:`.
- [ ] Decir: "Oye Asia… ¿qué es un grafo bipartito?"
- [ ] Se ve "Escuchando…", luego la frase transcrita y la respuesta escribiéndose. Asia la lee frase por frase; la primera suena en 3–6 s.
- [ ] Mientras habla, pulsar Enter: la lectura se corta y Asia sigue abierta.
- [ ] Decir: "La primera frase suena en unos segundos y la puedo cortar cuando quiera."

### 0:45–1:10 · Órdenes
- [ ] Decir: "Oye Asia… abre el bloc de notas." Se abre el Bloc de notas («Abriendo bloc de notas.»). Cerrarlo.
- [ ] Decir: "Oye Asia… explica el archivo launcher.py."
  - Con voz, la respuesta es corta (1 a 3 frases) y se lee mientras llega.
  - En pantalla queda `[Para la explicación completa: explica launcher.py a fondo.]`, que no se lee en voz alta.
  - Usar un archivo de la carpeta abierta: una ruta con carpetas dicha en voz alta no se transcribe bien.

### 1:10–1:45 · Biblioteca con citas
- [ ] Teclear `/sin escucha` y luego `/buscar cómo se crea un nodo en ROS 2`.
- [ ] Decir: "Busca en la documentación que yo le di. Primero copia las líneas que responden, el código comprueba que existen, y solo entonces contesta."
- [ ] Se ve la respuesta y, debajo, las líneas verificadas con su archivo y número de línea.
- [ ] Teclear la trampa: `/buscar cómo se configura el firewall de Asia`.
- [ ] Decir: "Si no está en mis fuentes, me lo dice en vez de inventarlo." Se ve «No lo encontré en la documentación.» o una negativa parecida.

### 1:45–2:15 · Privacidad
- [ ] Teclear `explica core/brain.py` y luego `/enviar a gemini` (o "envía esto a Gemini").
- [ ] Decir: "El contenido de mis archivos es local: no sale sin mi permiso explícito, una sola vez."
- [ ] Se ve qué saldría y la petición de `/confirmar envío`. Escribir `/cancelar envío`.
- [ ] Teclear `/modo local` y decir: "En modo local no sale nada, ni lo que tecleo."

### 2:15–2:40 · Cierre
- [ ] Teclear `/tiempos` y repetir una pregunta corta por voz (Enter en una línea vacía y hablar). Sale la línea `[tiempos]` con la voz a texto, la intención, el modelo y el primer audio.
- [ ] Teclear `/salir`.
- [ ] Decir: "Todo esto corre en una laptop con 4 GB de GPU. Gracias."

## Después de grabar

- [ ] Ver el video entero: que no salgan datos personales (`memory/`, nombres de archivos privados, notificaciones).
- [ ] Volver a `/modo normal` si se va a seguir usando Asia.

## Si algo falla durante la grabación

- La palabra de activación no responde: pulsar Enter en una línea vacía (con la voz activa escucha igual) y seguir.
- Una respuesta se alarga: Ctrl+C la corta sin cerrar Asia.
- Ollama tarda en cargar el primer modelo: grabar el "hola" después de una pregunta de calentamiento fuera de cámara.
- Un archivo dicho por voz "no existe": Asia lo busca en la carpeta donde se abrió. Repetir con el nombre de un archivo de esa carpeta.
