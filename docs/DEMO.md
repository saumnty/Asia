# Demo de Asia 1.0 (2–3 min)

Para grabar un video de la pantalla con el audio del sistema y el micrófono. Cada bloque dice qué mostrar, qué decir (o teclear) y qué se ve. Los tiempos son orientativos.

## Antes de grabar

- Cerrar lo que use la GPU o mucha RAM; `ollama ps` vacío; ventana de la terminal grande y con letra legible.
- En `settings.json`, la palabra de activación que se vaya a mostrar ("Oye Asia" si ya pasó sus criterios; si no, "Hey Jarvis") y `stream_output` en true.
- Una carpeta de ejemplo sin datos personales (por ejemplo `C:\Asia` mismo) y una fuente indexada para `/buscar` (la documentación de ROS 2, o el propio repositorio).
- No mostrar `memory/` ni `/revisar memoria`: tienen datos personales. Hacer una pasada de prueba completa antes de grabar.

## Guion

**0:00–0:15. Presentación.** Abrir la terminal en `C:\Asia` y escribir `asia`.
> Decir: "Esta es Asia, un asistente que corre entero en esta laptop, con modelos locales. Nada sale de la máquina si yo no lo autorizo."

Se ve el saludo y el prompt. Teclear `hola`: la respuesta llega al momento, porque la charla clara no pasa por el IntentEngine.

**0:15–0:45. Voz.** Teclear `/escucha`; el prompt dice `[esperando «Oye Asia»]`.
> Decir en voz alta: "Oye Asia… ¿qué es un grafo bipartito?"

Se ve "Escuchando…", la frase transcrita como si se hubiera tecleado y la respuesta escribiéndose mientras Asia la lee frase por frase. Mientras habla, pulsar Enter: la lectura se corta y Asia sigue abierta.
> Decir: "La primera frase suena en unos segundos y la puedo cortar cuando quiera."

**0:45–1:10. Órdenes.** Decir: "Oye Asia… abre el bloc de notas." Se abre el Bloc de notas ("Abriendo bloc de notas."). Cerrarlo.
Decir: "Oye Asia… explica el archivo core/voice/wake.py." Con voz, la respuesta es corta y se lee mientras llega; en pantalla queda "[Para la explicación completa: explica core/voice/wake.py a fondo.]".

**1:10–1:45. Biblioteca con citas.** Teclear `/sin escucha` y luego `/buscar cómo se crea un nodo en ROS 2`.
> Decir: "Busca en la documentación que yo le di. Primero copia las líneas que responden, el código comprueba que existen, y solo entonces contesta."

Se ve la respuesta y, debajo, las líneas verificadas con su archivo y número de línea. Después, una trampa: `/buscar cómo se configura el firewall de Asia`.
> Decir: "Si no está en mis fuentes, me lo dice en vez de inventarlo."

Se ve "No lo encontré en la documentación."

**1:45–2:15. Privacidad.** Teclear `explica core/brain.py` y luego `envía esto a Gemini`.
> Decir: "El contenido de mis archivos es local: no sale sin mi permiso explícito, una sola vez."

Se ve qué saldría y la petición de `/confirmar envío`. Escribir `/cancelar envío`. Teclear `/modo local`: "en modo local no sale nada, ni lo que tecleo".

**2:15–2:40. Cierre.** Teclear `/tiempos` y repetir una pregunta corta para mostrar la línea de tiempos (voz a texto, modelo, primer audio). Teclear `/salir`.
> Decir: "Todo esto corre en una laptop con 4 GB de GPU. Gracias."

## Si algo falla durante la grabación

- La palabra de activación no responde: pulsar Enter en una línea vacía con `/voz` activa (escucha igual) y seguir.
- Una respuesta se alarga: Ctrl+C la corta sin cerrar Asia.
- Ollama tarda en cargar el primer modelo: grabar el "hola" después de una primera pregunta de calentamiento fuera de cámara.
