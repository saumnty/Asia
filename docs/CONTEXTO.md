# Contexto de Asia · 11-nov-2026

Respóndeme en español.

## Quién soy
Santiago, estudiante de Ingeniería en Computación en la UAM
Cuajimalpa. Proyecto Terminal: Bolitabot (robot diferencial en
co-simulación Gazebo/ROS 2/Simulink, control de punto desplazado,
Hermite), repo github.com/saumnty/Robot_ROS2.

## El proyecto
Asia (A.S.I.A.): asistente de IA local en Python, en Windows.
Repo github.com/saumnty/Asia, en C:\Asia. Comando: asia (alias jarvis).

## Cómo trabajamos
- Claude Code (en VS Code) implementa; Claude (chat) revisa sus
  reportes, decide conmigo y me da el siguiente prompt, con un tiempo
  estimado.
- Reglas fijas en CLAUDE.md: un commit por paso, pytest completo por
  commit, sin push (yo lo hago), no tocar config/apps.json ni
  config/settings.json (lo nuevo va en config/defaults.json),
  preguntar antes de instalar o descargar, medir antes y después, una
  medición con modelo real a la vez, y la sección "Uso eficiente"
  (modelo según la dificultad, preguntas juntas, ahorro de tokens).
- Prefiero respuestas directas y técnicamente precisas, y entender el
  concepto antes de implementar.

## Mi equipo
Laptop HP Victus: Ryzen 7 5800H, RTX 3050 de 4 GB, 16 GB de RAM,
dual boot Windows + Ubuntu. Micrófono de la laptop con las mejoras de
audio de Windows desactivadas y volumen de entrada al 100. iPhone.

## Configuración actual de Asia
- Ollama 0.40.14 con GPU. OLLAMA_KV_CACHE_TYPE=q8_0 y
  LLAMA_ARG_CACHE_RAM=2048 (variables de usuario).
- Estrategia B: qwen3:4b-instruct-2507 (contexto 4096, todo en GPU)
  para intención y charla; qwen2.5-coder:7b (16 capas en GPU, contexto
  16384) para código, /buscar y revisiones; precarga anticipada.
- Modo confidencial (local, normal, abierto) con etiquetas de origen;
  "emocional" nunca sale.
- Voz: Whisper small en CPU, Piper (es_MX), lectura frase por frase,
  acciones por voz breves y con streaming. Palabra de activación:
  "Hey Jarvis" provisional (solo responde pronunciada en inglés).
- Biblioteca offline (fase H): proyectos, docs de ROS 2, Gazebo y
  Python 3.12, Wikipedia completa en español y 6 sitios de Stack
  Exchange, con citas verificadas.
- Afecto v0 (apagado por defecto), /pegar y @imagen con el OCR de
  Windows.
- Documentos: docs/ARQUITECTURA.md, docs/DEMO.md,
  docs/VOZ_PROPIA.md, docs/IDENTIDAD_VISUAL.md; criterios de cierre de
  1.0 en el ROADMAP.

## Estado
- J3, "Oye Asia":
  - v0.1 entrenado en Colab: 7/20 con mi voz; aprendió mal (necesita
    una frase detrás y "hoy hacia" lo activa).
  - v0.2 preparado: sintetico.zip rebalanceado (5000 positivos, la
    mitad "oye Asia" sola; 3000 negativos con más peso en los
    confundibles), cuaderno test/manual/colab/entrenar_oye_asia.ipynb
    (50 000 pasos, dos rondas de aumento) y empaquetar_mi_voz.py.
  - Herramientas listas: comparar_wake.py --audios elige modelo y
    umbral con mis grabaciones; secuencia en docs/J3_V02.md.
  - Falta: entrenar v0.2 y seguir docs/J3_V02.md (check_wake
    --aciertos 20 y --falsas 30, comparar, configurar el umbral).
- Voz propia:
  - 19 audios de una persona que dio permiso (uso privado), 750
    frases transcritas con small y turbo; revisadas a mano: 746
    aceptadas, 52,4 min. Exportado en
    C:\AsiaVoz\dataset\fa\exportado\.
  - dataset_final.py listo (sin correr con mis datos).
  - Decidido: 22 050 Hz; base es_MX/ald/medium, plan B sharvard F.
  - Falta: dataset final (con y sin atenuar silencios), cuaderno de
    entrenamiento, confirmarle a ella que sus audios irán a Colab, y
    entrenar.
- Cierre de 1.0 (docs/CIERRE_1.0.md, 2026-11-10):
  - Primer audio de las acciones: explain_file 4,2 s y
    summarize_file 5,0 s sin micrófono (antes 21,5 y 21,1), con
    qwen3 para la respuesta breve.
  - check_* sin micrófono: todos en verde (Wikipedia 11/12 con las
    palabras clave y la pregunta unidas; check_intents 49/49).
  - Tareas largas con voz: aviso fijo en 0–0,4 s, review_file 22,7 s
    (≤ 25). /buscar 31,2 s, todavía sobre los 30 (antes 41,2).
  - Por voz, "busca en la biblioteca…" va a /buscar y "explica
    timing.py" busca el archivo (pregunta cuál si hay varios).
  - docs/DEMO.md es la lista para grabar.
  - Faltan J3 (17/20 o más y 0,5 o menos falsas por hora) y
    check_voz --timing con el micrófono.

## Hoja de ruta

### Hecho
- Cimientos, modelos por dominio, G (confidencialidad), velocidad,
  comandos con "/", I (asia.exe), R (pendientes y resúmenes), GPU y
  estrategia B, H (biblioteca offline), afecto v0, OCR.
- J1 y J2: voz probada con micrófono (primer audio de la charla 3–6
  s), arreglos de Whisper, open_app con confirmación, streaming en las
  acciones.
- Primer audio de las acciones ≤ 15 s, check_* finales sin
  micrófono, comparar_wake --audios y la demo como lista.
- Segunda vuelta: Wikipedia 11/12, aviso fijo y criterio de tareas
  largas, biblioteca y nombres de archivo por voz.
- Documentos de cierre, identidad visual (orbe amarillo cálido,
  prototipo en test/manual/visual/asia_orbe.html).

### Asia 1.0 · casi lista
1. J3: "Oye Asia" v0.2 ← estás aquí
2. Voz propia (en paralelo; no bloquea 1.0)
3. Criterios de cierre en verde y demo grabada

### Asia 2.0 · 2027
- Motor de permisos y M (agente de varios pasos), delegando la
  programación grande a OpenCode o Claude Code.
- Programación: check_code, arnés (contexto, ediciones pequeñas,
  ruff, tipos, pytest en el ciclo), ruteo a modelos fuertes.
- Proveedores: OpenRouter, control de gastos y créditos con avisos.
- N (MCP), formatos (lectores y escritores; Minecraft → AutoCAD),
  Knowledge Manager, J4 (voz en segundo plano), conversación
  seguida, bots, V (visión), K (avatar bóxer) e identidad visual,
  afecto completo, confidencialidad avanzada, automejora supervisada.
- L: servidor (decidir hardware con check_code; Jetson para el robot).

## Pendientes míos
- git push.
- Entrenar "Oye Asia" v0.2 en Colab y probarlo con docs/J3_V02.md.
- check_voz.py --timing con "explica el archivo launcher.py" dicho.
- Decidir qué hacer con /buscar por voz (31 s): opciones en
  docs/CIERRE_1.0.md, sección 4.
- Grabar la demo (docs/DEMO.md).
- Confirmarle a la persona de la voz que sus audios irán a Colab.
- Revisar el orbe en el navegador y decir qué ajustar.
- Audios del JSON de Facebook (cuando lleguen).
- Elegir el acrónimo de A.S.I.A.
- 10 casos de interacción y registro de ánimo (fase de afecto).
