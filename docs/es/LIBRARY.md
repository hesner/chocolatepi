# USB de biblioteca — nombres de carpetas y archivos

*[Read in English](../../LIBRARY.md)*

Cómo organizar el USB de biblioteca para que `Library.resolve()`
(`src/core/library.py`) realmente encuentre lo que le pongas. Esto no lo
valida ninguna herramienta — si te equivocas en un nombre, la pista se
trata en silencio como un espacio vacío (sin error, no pasa nada al
presionar el pedal). Lee esto antes de editar la biblioteca, no después
de que un show salga mal.

## Estructura

```
<raíz del USB>/
├── active_show.txt          -- texto plano, una línea: el nombre de la carpeta del show activo
├── standby.mp4               -- en loop cuando no hay nada reproduciéndose
├── _Songs/                    -- recomendado: la biblioteca maestra de canciones de la banda (ver abajo)
│   ├── nombre de canción.mp3
│   └── otra canción.mp4
└── <Nombre del Show>/         -- ej. "Live", una carpeta por show/colección de setlists
    ├── Set 1/
    │   ├── A - nombre de canción.mp3
    │   ├── B - otra canción.mp4
    │   └── C - una tercera.wav
    ├── Set 2/
    │   └── ...
    └── Set N/
```

- **`active_show.txt`**: su contenido (sin espacios extra) debe coincidir
  exactamente con el nombre de una carpeta directamente bajo la raíz del
  USB. Si apunta a una carpeta que no existe, o está vacío/no se puede
  leer, se reproduce el standby de respaldo en vez de cualquier contenido
  real.
- **`Set N/`**: `N` es el número de setlist, coincide con el grupo del
  controlador (ver `MAVAVE_ANALYSIS.md` para cómo un número de grupo se
  mapea a `N` específicamente para el M-VAVE PD41). Los nombres de
  carpeta se comparan exactamente como `Set ` seguido de dígitos —
  `Set 1`, `Set 12`, no `set 1`, `Set1`, ni `Set 01`.
- **Archivos de pista**: exactamente un archivo por letra, `A`/`B`/`C`
  (el footswitch `D` siempre es STOP — nunca necesita archivo). Un
  espacio vacío (sin archivo para una letra) es normal y esperado, no un
  error.
- **`_Songs/`** y cualquier otra carpeta que empiece con `_`: reservadas,
  nunca se tratan como un Show. `Library.resolve()` (`src/core/library.py`)
  ni siquiera lista el contenido de la raíz del USB — solo lee
  `active_show.txt` y entra directo a esa carpeta específica — así que
  `_Songs/` es completamente invisible para la reproducción sin importar
  qué tenga adentro. Ver la siguiente sección para qué sirve.

## Recomendado: mantén una biblioteca maestra de canciones en `_Songs/`

Pon **todas las canciones que tiene la banda** — no solo las del setlist
actual — como archivos planos directamente bajo `_Songs/` en la raíz del
USB, nombrados `<nombre de la canción>.<extensión>` (sin el prefijo
`<Letra> - ` aquí; ese prefijo solo significa algo dentro de una carpeta
`Set`, donde marca *qué posición del pedal* reproduce el archivo). Esta
es la biblioteca completa y permanente de canciones de la banda,
independiente de cualquier show en particular.

Para armar o editar un setlist real: **copia** (no muevas) las
canciones específicas que necesite ese show desde `_Songs/` hacia las
carpetas `Set N/` de ese show, agregando el prefijo `<Letra> - ` en el
proceso. `_Songs/` conserva su copia intacta, así que la misma canción
queda a una copia de distancia de poder reutilizarse en el siguiente
setlist también, sin tener que re-codificarla ni volver a transferirla.

**Nunca borres una canción de `_Songs/` a menos que estés seguro.**
Trátala como un registro permanente, de solo agregar, de todo lo que la
banda alguna vez tuvo listo para tocar — incluso una canción que hoy no
se use en ningún show activo vale la pena conservarla ahí, tanto para
no tener que re-conseguirla/re-codificarla desde cero después, como
para que el número de archivos en `_Songs/` sea siempre una respuesta
honesta a "¿cuántas canciones tiene realmente la banda?".

Qué afecta y qué no afecta borrar de `_Songs/`:
- **Sí** significa que esa canción ya no se puede elegir al armar un
  `Set` futuro — simplemente ya no estará ahí para seleccionarla.
- **No** toca ningún `Set` que ya tenga una copia de esa canción
  asignada a una letra — esa copia es un archivo completamente
  separado, hecho en el momento en que se asignó, así que sigue
  sonando normal sin importar qué pase después en `_Songs/`.
- Borrar un show o un `Set` tampoco toca `_Songs/`, en la otra
  dirección (mismo razonamiento: copias independientes, no el mismo
  archivo).

Esto es una disciplina que hay que mantener por cuenta propia — nada en
el USB la obliga. Si usas las expansiones opcionales de
`setlist-admin`, la propia confirmación de borrado de la app repite
esta advertencia antes de dejarte borrar una canción de la biblioteca.

Si usas las expansiones opcionales de `setlist-admin`
(`expansions/setlist-admin-usb/` o `expansions/setlist-admin-wifi/`),
todo este flujo queda automatizado: subir una canción en cualquier
lugar la agrega a `_Songs/` automáticamente, y asignar una casilla de
un `Set` desde la biblioteca es una copia de un toque en vez de un `cp`
manual. Es la misma convención de cualquier forma — esta sección
describe lo que la app realmente hace por debajo, y qué hacer a mano si
no la estás usando.

## La única regla que realmente importa: el patrón del nombre de archivo

```
<Letra> - <lo que sea>.<extensión>
```

**Exactamente un espacio antes del guion, uno después.** La letra debe
ir seguida inmediatamente por ` - ` (espacio, guion, espacio), luego
cualquier nombre, luego una extensión soportada:

- Solo audio (el standby sigue en loop debajo, el audio suena encima):
  `.mp3`, `.wav`
- Video con audio embebido: `.mp4`, `.mov`, `.mpeg`, `.mpg`

Mayúsculas/minúsculas no importan ni en la letra ni en la extensión
(`a - x.MOV` calza perfecto). Lo único que tiene que ser exacto es ese
único espacio a cada lado del guion.

**Este es el error más fácil de cometer**, y falla completamente en
silencio — ningún error en ningún lado, el footswitch simplemente no
hace nada, porque un nombre de archivo que no calza se ve idéntico a un
espacio vacío intencional.

```
A - mi canción.mp3        <- correcto
A  - mi canción.mp3       <- MAL (dos espacios antes del guion) -- ignorado en silencio
A- mi canción.mp3         <- MAL (sin espacio antes del guion) -- ignorado en silencio
A -mi canción.mp3         <- MAL (sin espacio después del guion) -- ignorado en silencio
```

**La forma más segura de evitarlo**: no escribas un nombre de archivo
nuevo desde cero. Duplica un archivo de pista que ya funcione (en el
mismo `Set` o en otro) y renombra solo la parte después de ` - `, así el
` - ` en sí nunca se vuelve a teclear.

Si una pista no suena y todo lo demás se ve bien (el archivo sí está
ahí, en el `Set` correcto, con el show correcto activo), renombra el
archivo para descartar un problema de espacios antes de asumir que es un
problema de códec o de hardware.

## Codificación recomendada para video grabado con el celular

Los videos de las carpetas `Set` se decodifican por hardware (`mpv
--hwdec=v4l2m2m-copy` en la Raspberry Pi 2), que solo soporta **H.264**.
Las apps de cámara —especialmente la del iPhone— vienen configuradas por
defecto con ajustes que este hardware no puede tocar en absoluto. Antes
de copiar metraje del celular a la biblioteca, re-codifícalo a:

| Ajuste | Recomendado | Por qué |
|---|---|---|
| Códec de video | H.264 (`libx264`) | El único códec que este hardware decodifica; fila "Video" de `MASTER_SPECIFICATION.md` |
| Formato de píxel | `yuv420p` (8-bit) | El metraje HEVC/HDR de celular suele ser 10-bit; el decodificador de hardware espera 4:2:0 de 8-bit plano |
| Resolución | 1080p máximo (`scale=-2:1080`) | La resolución objetivo de este proyecto; 4K solo agrega trabajo de decodificación sin ganancia visible en un TV alimentado a 1080p |
| Bitrate de video | ~8-12 Mbps para 1080p | Buena calidad de sobra para un clip corto. Esta **no** es la situación del video de standby (la salida de `scripts/generate_fallback_standby.sh` y el `standby.mp4` real están codificados mucho más ligero, alrededor de 1.8 Mbps) — el standby está en loop durante todo el show y su tamaño de archivo sí importa; una canción/video individual en el USB de biblioteca no tiene esa restricción, así que no hay razón para escatimarle bitrate también |
| Códec de audio | AAC, 44.1 u 48kHz, estéreo | `Player` fuerza 48kHz/estéreo en la salida sin importar el origen, así que la fuente solo necesita ser un stream AAC normal, no una tasa de muestreo específica |
| Contenedor | `.mp4` | Sin importar la extensión original del archivo — un origen `.mov` se codifica bien a salida `.mp4` |

```
ffmpeg -i entrada.mov -c:v libx264 -pix_fmt yuv420p -vf scale=-2:1080 \
       -b:v 10M -c:a aac -b:a 192k -movflags +faststart "A - nombre de canción.mp4"
```

Si un video se ve bien en un teléfono/computador pero no a través del
pedal, revisa su códec (`ffmpeg -i <archivo>` lo muestra en la línea
`Video:`) antes de sospechar del nombre del archivo, y re-codifica con
el comando de arriba — un nombre mal puesto y un códec incompatible
pueden ser ambos ciertos en el mismo archivo a la vez, así que arreglar
uno no garantiza que el otro no siga siendo un problema.
