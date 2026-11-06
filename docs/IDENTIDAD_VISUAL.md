# Identidad visual de Asia: el orbe

Diseño original de Asia. No toma ninguna interfaz de películas ni nombres o marcas ajenas.

## Concepto

Un núcleo esférico de luz amarilla cálida, con fragmentos cuadrados pequeños que flotan a su alrededor en una órbita inclinada, como un anillo visto de lado. Los fragmentos se separan y se vuelven a juntar según lo que hace Asia. El núcleo respira despacio cuando no pasa nada y late cuando habla. Transmite que Asia está presente sin llamar la atención; nunca alarma.

Prototipo: [`test/manual/visual/asia_orbe.html`](../test/manual/visual/asia_orbe.html). Es un solo archivo con canvas 2D, sin internet ni librerías. Tiene botones (o las teclas 1–6) para cada estado y un deslizador que simula el volumen del micrófono.

## Paleta

Amarillo cálido, **nunca naranja**: todos los tonos van de 44° a 47° de matiz (el naranja empieza por debajo de ~42°).

| Uso | Valor | Matiz | Cambio respecto a la paleta de partida |
|---|---|---|---|
| Núcleo | `#FFD54A` | 46,1° | — |
| Brillo (luz del núcleo, halo, anillo de "esperando") | `#FFE89A` | 46,3° | — |
| Fragmentos | `#F6CA46` | 45,0° | era `#F5C542` (43,9°): un poco de margen sobre 42° |
| Sombras y contorno | `#C29A24` | 44,8° | era `#C9961E` (42,1°): justo en el límite; al dibujarse tenue tiraba a marrón anaranjado |
| Fondo | `#0F0F0F` | gris neutro | era `#0E0E12` (con un tinte azul); ver abajo |
| Apagado (estado de error) | `#8C7E52` | 45,5° | nuevo: dorado gris, el mismo matiz con poca saturación |

**Por qué cambia el fondo.** Medido en el prototipo, sobre los píxeles dibujados: con `#0E0E12`, los bordes del halo, donde el amarillo se mezcla con el fondo, bajaban a **40°**. El tinte azul del fondo desplaza la mezcla hacia el marrón anaranjado. Con un gris neutro (R = G = B), mezclar no cambia el matiz, y el mínimo queda en **42,5–43,3°** en los seis estados. Lo que falta para llegar a 44° es redondeo en los píxeles más oscuros.

## Estados

| Estado | Qué hace el orbe | En Asia |
|---|---|---|
| En reposo | Respira lento (5 s); los fragmentos casi quietos | El prompt espera un mensaje |
| Esperando la palabra | Pulso suave: un anillo de brillo que se abre cada 2,4 s | `/escucha` activa: el `WakeListener` escucha "Oye Asia" |
| Escuchando | Los fragmentos se abren y tiemblan con el volumen del micrófono; el halo sube | `VoiceSession.listen`: grabando la frase |
| Pensando | Los fragmentos giran más rápido y cada 1,8 s se juntan cerca del núcleo y se vuelven a abrir | Entre el mensaje y la primera palabra de la respuesta (IntentEngine, búsqueda, modelo) |
| Hablando | El núcleo late con la voz (la envolvente del audio de Piper) | La lectura frase por frase está sonando |
| Error | Se apaga hacia el dorado gris en un cuarto de segundo y vuelve solo en ~2 s, sin rojo | Un fallo de la acción, del proveedor o del micrófono |

**Menos movimiento.** Se sigue `prefers-reduced-motion`, y también se puede activar con la casilla del prototipo. Los fragmentos se quedan quietos, no hay respiración, latido ni reagrupamiento, y cada estado se distingue solo por el brillo y el color.

## Conexión con Asia

Es el canal de estado local que ya figura en el ROADMAP (Flask-SocketIO):

- Asia emite eventos pequeños, `{"estado": "hablando", "nivel": 0.63}`, desde los puntos de la tabla:
  - el prompt (reposo);
  - `start_wake` y `stop_wake` (esperando);
  - `VoiceSession.listen` (escuchando, con el nivel de cada tramo de 32 ms);
  - `respond`, hasta el primer token (pensando);
  - `Reading` (hablando, con el nivel del audio que suena);
  - los manejadores de error.
- `nivel` va de 0 a 1 y se manda como mucho 20 veces por segundo, solo mientras escucha o habla.
- Solo en `127.0.0.1`, y **nunca con el texto de los mensajes**: el estado no dice qué se habló, así que no toca el modo confidencial.
- La página del orbe cambia de estado con cada evento, igual que con los botones del prototipo. Si no hay conexión, se queda en reposo.
- Alternativa sin dependencias nuevas: Server-Sent Events con `http.server` de la biblioteca estándar, porque el canal va en un solo sentido. El cliente de Socket.IO tendría que ir copiado junto a la página, sin CDN.

## El orbe y el avatar

El ROADMAP prevé además un avatar, un perro bóxer. Pueden convivir: el **orbe es el indicador de estado** (pequeño, en una esquina o en la bandeja, siempre visible) y el **bóxer es el avatar** para cuando hay una ventana dedicada. Ambos leerían el mismo canal de estado.
