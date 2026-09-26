# Setlist Admin (USB) — guía de uso

*[Read in English](../../USAGE.md)*

Esta es una **expansión** (`expansions/setlist-admin-usb/`) — ver el
`expansions/README.md` en la raíz del repo para qué significa eso. Es
la app web opcional para administrar el USB de biblioteca (shows,
Sets, pistas) desde el navegador de un teléfono, a la que se accede
conectando el teléfono a la Pi con un cable USB — en vez de SSH +
`nano` + copiar archivos a mano. Diseño y justificación:
[`SPECIFICATION.md`](../../SPECIFICATION.md). No se instala por
defecto — ver "Instalación" abajo.

**Solo antes o después de un show.** No está diseñada ni probada para
editar la biblioteca mientras un show está en curso — la app muestra
una advertencia si detecta que el pedal está reproduciendo algo
activamente, pero no bloquea la acción; trata esa advertencia como
real, no como formalidad.

## Instalación

Opcional, y separada de la instalación base del pedal
(`systemd/README.md`). Requiere desactivar temporalmente el overlay de
solo lectura primero, igual que cualquier otro paso de instalación que
escribe en `/etc/systemd/system` (`systemd/README.md` sección 4):

```
sudo raspi-config nonint do_overlayfs 1
sudo reboot
```

Luego, desde cualquier parte dentro del checkout del repo en la Pi:

```
sh expansions/setlist-admin-usb/scripts/install.sh
```

Si alguna vez vas a conectar un iPhone (no solo Android), instala
también su única dependencia extra:

```
sudo apt install -y usbmuxd
```

Instalar arranca `usb-tether-watchdog.service`, que decide por su
cuenta cuándo debe estar corriendo `setlist-admin.service` (ver "Cómo
funciona la conexión" abajo) — no arrancas el servidor de admin
directamente.

Reactiva el overlay cuando termines:

```
sudo raspi-config nonint do_overlayfs 0
```

Luego edita `/boot/firmware/cmdline.txt` y vuelve a agregar
`:recurse=0` — ver `systemd/README.md` sección 4, el mismo paso
requerido después de cualquier reactivación del overlay.

## Primer uso

1. Conecta tu teléfono a la Pi con un cable USB.
2. **Android**: Ajustes → Red e internet → Punto de acceso y compartir
   red → activa **Compartir conexión por USB**.
   **iPhone**: Ajustes → Compartir Internet → actívalo, luego acepta el
   mensaje "¿Confiar en este ordenador?" que aparece en el teléfono.
3. Visita `http://pedal.local:8080` desde el navegador del teléfono.
   Si no carga (algunos navegadores de Android son inconsistentes
   resolviendo direcciones `.local`): en iPhone, prueba directamente
   `http://172.20.10.2:8080` — Compartir Internet por USB casi siempre
   le asigna a la Pi exactamente esa dirección. En Android, revisa la
   propia pantalla de ajustes de conexión compartida del teléfono para
   ver la dirección del dispositivo conectado, o encuéntrala por SSH
   como lo hace el propio desarrollo de este proyecto (`ip -4 addr
   show` en la Pi, buscando la interfaz que acaba de aparecer).
4. Primera visita: define un PIN (mínimo 4 caracteres). Es
   autenticación compartida de un solo PIN
   (`SPECIFICATION.md` sección 7) — no una cuenta por
   persona.
5. De ahí en adelante, visitar la app pide ese PIN.

**¿Olvidaste el PIN?** No hay flujo de recuperación por correo — es un
aparato local sin sistema de cuentas. Recupéralo por SSH:

```
ssh pedal
sudo umount /media/usb && sudo mount -o rw /media/usb
rm /media/usb/.setlist-admin/pin.hash
sudo umount /media/usb && sudo mount -o ro /media/usb
```

La siguiente visita a la app lo trata como primera vez de nuevo y pide
definir un PIN nuevo.

## Usándola

Elige o crea un show, crea/elimina carpetas `Set`, y para cada casilla
de pista (A/B/C):
- **Upload new** sube un archivo directo a esa letra, reemplazando lo
  que hubiera. También se agrega automáticamente a la **biblioteca de
  canciones** (ver abajo), lista para reutilizarse en un show futuro
  sin volver a subirla.
- **Assign** (junto al selector desplegable de canciones) pone una
  canción existente de la biblioteca en esa letra, sin subir nada — una
  copia instantánea dentro del mismo USB.
- **Renombrar** cambia solo el nombre visible (la letra — su posición
  — y la extensión del archivo se mantienen igual).
- **Eliminar** vacía la casilla. Esto **no** borra la canción de la
  biblioteca — es una copia independiente (ver abajo).
- **Save to library**, visible cuando la casilla ya tiene algo, agrega
  esa copia específica a la biblioteca si todavía no estaba — útil para
  canciones asignadas antes de que existiera esta función, o desde otro
  dispositivo.

No hay un botón separado de "reordenar" — para cambiar qué canción va
en qué posición, sube/renombra hasta que el archivo correcto quede en
la letra correcta, o usa la acción de intercambiar.

A cada subida se le revisa el códec (`ffprobe`) — un video que no sea
H.264 recibe una advertencia, no un bloqueo, que apunta a la guía de
codificación de `LIBRARY.md`. Igual se sube; la reproducción puede no
funcionar hasta que lo recodifiques, igual que si lo hubieras copiado
a mano.

### Biblioteca de canciones: reutilizar canciones entre setlists

La sección **"Song library"** al inicio de la app (toca para
desplegarla) lista todas las canciones disponibles para reutilizar —
es la carpeta `_Songs/` en la raíz del USB (`LIBRARY.md` documenta la
misma convención para editar el USB a mano, sin esta app). Está pensada
para tener **todas las canciones que tiene la banda**, no solo las del
setlist que estás armando ahora, para que empezar el setlist del
próximo show sea cuestión de elegir entre lo que ya existe, en vez de
volver a subir todo.

Desde ahí puedes subir una canción nueva directo a la biblioteca (sin
asignarla a ningún Set todavía), renombrarla, o borrarla. **Borrar una
canción de la biblioteca no se recomienda — si tienes dudas, no la
borres.** `LIBRARY.md` recomienda tratarla como un registro permanente
de todo lo que tiene la banda, incluso canciones que no se usan en
ningún show en este momento, para que la biblioteca sea siempre una
respuesta honesta a "¿cuántas canciones tenemos realmente?". Una vez
borrada, la canción ya no se puede elegir al armar un Set (no aparecerá
en el selector para ningún show futuro) — pero borrarla **no** la quita
de ningún Set donde ya esté asignada; esos siguen sonando normal,
porque asignarla ya hizo una copia independiente. La confirmación de
borrado de la app lo explica así también. Desinstalar cualquiera de las
expansiones de `setlist-admin` tampoco borra `_Songs/` por defecto —
solo lo hace la bandera explícita `--purge-library` (ver "Desinstalar"
abajo). Y en la otra dirección: asignar una canción a un Set nunca la
quita de la biblioteca — cada asignación es una copia, la biblioteca
siempre conserva la suya.

**Los cambios necesitan un reinicio para aplicarse.** El pedal solo lee
la estructura de la biblioteca cuando arranca (igual que siempre —
esta app no cambia eso). Cuando termines de editar, toca **"Reiniciar
ahora para aplicar"** al final de la app en vez de necesitar SSH. Está
bien hacer varios cambios primero y reiniciar una sola vez al final —
no hace falta reiniciar después de cada cambio individual.

## Cómo funciona la conexión

`usb-tether-watchdog.service` revisa cada pocos segundos si hay un
teléfono conectado por USB compartiendo su conexión, identificándolo
por su driver de red (`rndis_host`/`cdc_ether`/`cdc_ncm` de Android, o
`ipheth` de iPhone) en vez de por dirección IP, para que un cable
Ethernet permanentemente conectado nunca arranque el servidor de admin
por accidente. Cuando detecta un teléfono, arranca
`setlist-admin.service`; cuando se desconecta el cable o se apaga la
opción de compartir red, lo detiene unos segundos después.

Desconectar a mitad de una edición es seguro — cada escritura al USB
se completa por entero o no se completa (nunca parcialmente), así que
un cable que se cae no puede corromper la biblioteca. Solo vuelve a
conectarlo y sigue donde ibas.

## Desinstalar / revertir

Si esto alguna vez necesita salir — un bug, o simplemente decidir no
usarlo — `pedal-core.service`, el pedal realmente crítico en vivo,
nunca se toca al instalar o quitar esto:

```
sh expansions/setlist-admin-usb/scripts/rollback.sh
```

Agrega `--purge` para también borrar el PIN guardado del USB; omítelo
para conservarlo y que una futura reinstalación no necesite
configurarse desde cero. Agrega `--purge-library` (aparte) para también
borrar `_Songs/`, la biblioteca compartida de canciones — no incluida
en `--purge` porque borra archivos de canciones reales, un paso más
grande que reiniciar un PIN; ver la recomendación de `LIBRARY.md` de
tratar esa biblioteca como permanente antes de usar esto. Ver
`SPECIFICATION.md` secciones 11 y 13 para exactamente qué toca cada
bandera y qué no.
