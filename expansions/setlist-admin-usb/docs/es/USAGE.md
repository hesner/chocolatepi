# Setlist Admin (USB) — guía de uso

*[Read in English](../../USAGE.md)*

Esta es una **expansión** (`expansions/setlist-admin-usb/`) — ver el
`expansions/README.md` en la raíz del repo para qué significa eso. Es
la app web opcional para administrar el USB de biblioteca (Sets,
Banks, pistas) desde el navegador de un teléfono, a la que se accede
conectando el teléfono a la Pi con un cable USB — en vez de SSH +
`nano` + copiar archivos a mano. Diseño y justificación:
[`SPECIFICATION.md`](../../SPECIFICATION.md). No se instala por
defecto — ver "Instalación" abajo.

**Solo antes o después de un Set.** No está diseñada ni probada para
editar la biblioteca mientras un Set está en curso — la app muestra
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

**Idioma**: el menú desplegable **EN/ES** en la barra superior cambia
cada etiqueta, botón, confirmación y notificación entre inglés y
español, guardado solo en este teléfono/navegador (cada dispositivo
recuerda su propia elección). Los nombres de canciones, pistas, Sets y
Banks nunca se traducen ni se alteran, en ningún idioma — son tus
datos, se muestran exactamente como los escribiste.

Elige o crea un Set, crea/elimina carpetas `Bank`, y para cada casilla
de pista (A/B/C):
- **Upload new** sube un archivo directo a esa letra, reemplazando lo
  que hubiera. También se agrega automáticamente a la **biblioteca de
  canciones** (ver abajo), lista para reutilizarse en un Set futuro
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

### Exportar Set: el repertorio en letra grande para leer en el escenario

El botón **"Export Set"** (junto al selector de Set) abre una vista a
pantalla completa, en letra grande, con todas las pistas asignadas en
ese Set, en orden (Bank 1 A, B, C, luego Bank 2, y así sucesivamente) —
cada línea muestra el nombre de archivo exacto y su extensión tal como
están guardados, para que lo que veas acá siempre coincida con lo que
realmente hay en el USB. Pensada para verse de un vistazo mientras
tocas, no para leerse de cerca.

Se cierra con la **✕** en la esquina, la tecla Escape, o el gesto/botón
de atrás de tu teléfono.

**Share** convierte la lista en una imagen PNG y la entrega al menú
nativo de compartir de tu teléfono (WhatsApp, Mensajes, correo, guardar
en Fotos — lo que tengas instalado); en un navegador de escritorio sin
ese soporte, en cambio descarga el PNG directamente (el soporte desde
un PC todavía se está verificando por separado).

### Biblioteca de canciones: reutilizar canciones entre Sets

La sección **"Song library"** al inicio de la app (toca para
desplegarla) lista todas las canciones disponibles para reutilizar —
es la carpeta `_Songs/` en la raíz del USB (`LIBRARY.md` documenta la
misma convención para editar el USB a mano, sin esta app). Está pensada
para tener **todas las canciones que tiene la banda**, no solo las del
Set que estás armando ahora, para que empezar el Set de la próxima
presentación sea cuestión de elegir entre lo que ya existe, en vez de
volver a subir todo.

Desde ahí puedes subir una canción nueva directo a la biblioteca (sin
asignarla a ningún Bank todavía), renombrarla, o borrarla. Si subes un
nombre que ya está ahí, la app pregunta **"... already exists in the
library. Replace it?"** — confirma para reemplazarla en el mismo lugar,
o cancela para dejar la existente sin tocar.

Si el video de una canción no está en el formato recomendado (H.264 —
ver el aviso junto a la subida, o `LIBRARY.md`), igual se sube, pero
aparece un botón **"Optimize"** junto a ella. Tócalo para re-codificar
el archivo en el mismo lugar al formato recomendado, sin tener que
hacerlo a mano. Primero verás una advertencia: **no desconectes la
Raspberry Pi mientras esté corriendo** — la recodificación escribe al
almacenamiento local de la propia Pi durante todo el proceso, y esto
puede tardar un rato en este hardware (confirmado hasta unos 90
minutos, o varias horas para un video 4K grande) — mientras corre, el
botón muestra un verde permanente que dice **"Optimizando"**, que se
mantiene (junto a un botón **"Cancel"**) aunque desconectes el celular
y vuelvas más tarde, así que puedes revisarlo cuando te quede cómodo.
La app se refresca sola cada pocos segundos mientras un trabajo esté
activo, así que no necesitas refrescar a mano para ver cuándo termina
o se cancela. Si falla (un archivo dañado o ilegible), el botón pasa a
**"Optimize (retry)"** con el motivo al mantener presionado.

**¿Cambiaste de opinión, o necesitas la Pi para otra cosa ahora
mismo?** Toca **"Cancel"** — detiene la recodificación en pocos
segundos y deja el archivo exactamente como estaba, sin optimizar.
Es seguro tocar "Optimize" de nuevo más tarde para reintentar.

La optimización corre de forma independiente a esta app y a cualquier Set
que esté sonando — una canción en la biblioteca no se carga a ningún
Set en vivo ni al standby hasta que la asignes por separado, así que
una optimización en curso nunca afecta lo que realmente se puede
reproducir en este momento. **Borrar una
canción de la biblioteca no se recomienda — si tienes dudas, no la
borres.** `LIBRARY.md` recomienda tratarla como un registro permanente
de todo lo que tiene la banda, incluso canciones que no se usan en
ningún Set en este momento, para que la biblioteca sea siempre una
respuesta honesta a "¿cuántas canciones tenemos realmente?". Una vez
borrada, la canción ya no se puede elegir al armar un Bank (no
aparecerá en el selector para ningún Set futuro) — pero borrarla **no**
la quita de ningún Bank donde ya esté asignada; esos siguen sonando
normal, porque asignarla ya hizo una copia independiente. La
confirmación de borrado de la app lo explica así también. Desinstalar
cualquiera de las expansiones de `setlist-admin` tampoco borra
`_Songs/` por defecto — solo lo hace la bandera explícita
`--purge-library` (ver "Desinstalar" abajo). Y en la otra dirección:
asignar una canción a un Bank nunca la quita de la biblioteca — cada
asignación es una copia, la biblioteca siempre conserva la suya.

**Los cambios necesitan un reinicio para aplicarse.** El pedal solo lee
la estructura de la biblioteca cuando arranca (igual que siempre —
esta app no cambia eso). Cuando termines de editar, toca **"Reiniciar
ahora para aplicar"** al final de la app en vez de necesitar SSH. Está
bien hacer varios cambios primero y reiniciar una sola vez al final —
no hace falta reiniciar después de cada cambio individual.

### Video de standby: qué se repite cuando no hay nada sonando

La sección **"Standby video"** muestra qué está en loop ahora mismo
(tamaño del archivo y cuándo se cambió por última vez) y te permite
reemplazarlo: elige cualquier video de la **biblioteca de canciones** de
arriba y toca **"Set as standby"**. Para usar un video que todavía no
está en la biblioteca, súbelo primero ahí (el mismo botón "+ Upload song
to library" que se usa para canciones normales) y luego elígelo acá.

Solo se pueden usar videos como standby (los archivos de solo audio no
aparecen en el selector) — el standby no tiene ningún pedal apuntándole,
así que no habría nada que ver ni escuchar de un archivo de solo audio
repitiéndose en silencio. Renombrarlo o borrarlo después funciona
exactamente igual que cualquier otra canción de la biblioteca (ver
arriba). Misma regla que todo lo demás acá: **necesita un reinicio para
aplicarse.**

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

### Llegar a la app por WiFi

Desde el 2026-10-03, el mismo watchdog también arranca la app admin
automáticamente cuando un dongle USB de WiFi en la Pi está conectado a
la propia red de WiFi de casa de la banda — la misma que ya se guardó
durante la primera configuración de esta Pi (`systemd/README.md`
sección 0). No necesita instalación ni configuración adicional:
conecta el dongle, espera a que se una a esa red (igual que siempre),
y luego visita `http://pedal.local:8080` (o la IP de WiFi de la Pi
directamente) desde cualquier teléfono o computador en esa misma red.

Esto es independiente de la conexión por cable USB de arriba, y
totalmente compatible con ella:
- Teléfono conectado por cable, sin WiFi: funciona exactamente como
  se describió arriba.
- WiFi conectado, sin ningún teléfono por cable: la app admin se
  levanta sola, alcanzable desde cualquier dispositivo en esa red —
  útil para administrar la biblioteca desde un computador en vez de un
  teléfono.
- Ambos a la vez: no hay conflicto, la app simplemente se queda arriba
  de cualquiera de las dos formas.
- Desconectar el dongle de WiFi (o perder esa red) mientras el
  teléfono sigue conectado por cable: sin cambios, el cable la
  mantiene arriba. Desconectar el teléfono mientras el WiFi sigue
  conectado: sin cambios tampoco, el WiFi la mantiene arriba. Solo
  perder **ambas** detiene el servicio, unos segundos después, igual
  que siempre.

**Nota de seguridad**: esto solo confía en ese perfil de WiFi
específico y nombrado (`preconfigured` por defecto) — conectar el
dongle a una red distinta (el WiFi de invitados de un lugar donde
tocan, por ejemplo) nunca arranca la app admin por esa red, aunque esa
red tenga su propio acceso a internet. Ver la sección "Cambiar a qué
red WiFi se conecta la Pi" de `systemd/README.md` si la red de casa de
la banda cambia alguna vez y esto necesita apuntar a una nueva.

**Llegar a la app por WiFi en una red en la que el watchdog no
confía** (solo uso de desarrollo/SSH — confirmado en vivo, 2026-10-02):
el watchdog hace cumplir activamente las reglas de arriba, volviendo a
detener el servidor admin a los pocos segundos de cualquier
`systemctl start setlist-admin.service` manual que no las cumpla. Para
anularlo temporalmente:

```
sudo systemctl stop usb-tether-watchdog.service
sudo systemctl start setlist-admin.service
```

Recuerda hacer `sudo systemctl start usb-tether-watchdog.service` de
nuevo cuando termines, o el servidor admin se queda alcanzable
indefinidamente en vez de seguir la convención normal de
cable/WiFi.

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
