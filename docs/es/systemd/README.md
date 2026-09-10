# Configuración de arranque automático

*[Read in English](../../../systemd/README.md)*

Hace que el pedal empiece a reproducir (loop de standby, escuchando al
controlador MIDI) automáticamente al encender la Raspberry Pi, sin
pantalla ni teclado (sección 1 de `MASTER_SPECIFICATION.md`).

Cinco piezas, aplicadas en este orden: flashear el sistema operativo y
configurar su primer arranque, el software del que depende este
proyecto, una entrada en `/etc/fstab` para que el USB de biblioteca se
monte solo, un servicio de `systemd` que corre `src/main.py`, y (como
paso final, deliberadamente el último) un overlay de solo lectura sobre
el propio sistema de archivos raíz de la Pi.

## 0. Flashear Raspberry Pi OS y configurar el primer arranque

Usando [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
(herramienta oficial, Windows/macOS/Linux):

1. **Choose OS** → "Raspberry Pi OS (other)" → **Raspberry Pi OS Lite
   (Legacy, 32-bit)** — el que `MASTER_SPECIFICATION.md` nombra como
   sistema operativo base de este proyecto.
2. **Choose storage** → tu tarjeta SD.
3. Antes de escribir, haz clic en el ícono de engranaje (o `Ctrl+Shift+X`)
   para abrir las opciones avanzadas y configurar, en la misma sesión:
   - **Hostname**: el despliegue de referencia de este proyecto (y cada
     ejemplo `ssh pedal` en la documentación de este repo) usa `pedal`.
     Usa el que quieras, solo sustitúyelo mentalmente donde estos
     documentos digan `pedal`/`pedal.local`.
   - **Enable SSH**, autenticación por contraseña (o pega una llave
     pública si prefieres no usar contraseña).
   - **Username and password**: tu elección, sin requisito fijo — lo que
     pongas acá se vuelve `<YOUR_USER>` en la sección 3
     (`pedal-core.service`) más adelante.
   - **Configure WiFi** (SSID, contraseña, país) si esta Pi no va a estar
     por Ethernet — o sáltatelo y usa Ethernet en su lugar, que es a lo
     que recurrieron las propias pruebas de este proyecto cuando el WiFi
     se puso inestable (ver `TESTING.md`).
   - Idioma/zona horaria/teclado según corresponda.
4. Escribe, mueve la tarjeta a la Pi y enciéndela. El primer arranque
   tarda un minuto o dos más de lo normal (redimensión de partición,
   llaves SSH del host).
5. Desde otra máquina en la misma red, abre una terminal —
   **PowerShell** en Windows 10/11 (ya trae el comando `ssh`; búscalo
   en el menú de inicio como "PowerShell"), **Terminal.app** en macOS,
   o cualquier terminal en Linux — y corre:
   ```
   ssh <tu-usuario>@<hostname>.local
   ```
   La resolución `.local` (mDNS) no es totalmente confiable en la
   práctica (conocida por fallar por WiFi). Si no resuelve, saca la IP
   de la Pi de la lista de clientes DHCP de tu router y usa `ssh
   <tu-usuario>@<esa-ip>`. El resto de esta guía se corre dentro de esta
   misma sesión SSH, salvo que un paso diga lo contrario.

## 1. Prerequisitos de software

Raspberry Pi OS (este proyecto se desarrolló contra Lite) ya trae
`python3`; instala el resto:

```
sudo apt update
sudo apt install -y git mpv ffmpeg ntfs-3g
```

- `git` — para traer el código de este proyecto a la Pi (siguiente
  paso).
- `mpv` — maneja toda la reproducción (`src/core/player.py`, sobre su
  socket IPC en JSON; no hace falta `python-mpv` ni ningún otro paquete
  de Python de terceros).
- `ffmpeg` — solo lo usa `scripts/generate_fallback_standby.sh`, para
  generar el video de standby de respaldo local una vez.
- `ntfs-3g` — solo hace falta si tu USB de biblioteca está formateado en
  NTFS, como en el setup de referencia de este proyecto; usa el driver
  que corresponda al sistema de archivos de tu propio USB (ej.
  `exfat-fuse` para exFAT).

Sin `requirements.txt`: el lado Python de este proyecto (`src/`) es solo
librería estándar, deliberadamente, así que no hay nada que instalar con
`pip`.

Ahora trae el código del proyecto a la Pi — cada paso de acá en
adelante asume que estás dentro de este checkout:

```
git clone https://github.com/hesner/chocolatepi
cd chocolatepi
```

## 2. USB de biblioteca — `/etc/fstab`

Agrega una línea como esta (obtén el UUID real de tu propio USB con
`sudo blkid /dev/sda1`, o el dispositivo que corresponda). Editar
`/etc/fstab` necesita `sudo`; `nano` es el editor más simple que ya
viene en Raspberry Pi OS — `sudo nano /etc/fstab`, agrega la línea al
final, luego `Ctrl+O` (guardar), `Enter` (confirmar el nombre),
`Ctrl+X` (salir):

```
UUID=07C1339846657D95  /media/usb  ntfs-3g  ro,nofail,x-systemd.device-timeout=10  0  0
```

- `ro`: montado de solo lectura por defecto, igual que este proyecto
  opera siempre en el día a día (sección 2 de `MASTER_SPECIFICATION.md`
  — el USB de biblioteca nunca debe formatearse automáticamente ni sus
  archivos borrarse solos). Remonta en lectura-escritura a mano (`sudo
  mount -o remount,rw /media/usb`) solo para gestión deliberada de la
  biblioteca, y vuelve a `ro` después.
- `nofail` + `x-systemd.device-timeout=10`: si el USB no está conectado
  al arrancar, no cuelgues la secuencia de arranque esperándolo — desiste
  después de 10s y continúa. `pedal-core.service` (abajo) maneja que el
  USB siga ausente después de eso cayendo al video de standby local (ver
  `src/core/player.py`).

Prueba la línea **sin reiniciar** antes de confiar en ella:

```
sudo mount -a
mount | grep /media/usb
```

## 3. El servicio — `pedal-core.service`

```
sudo cp systemd/pedal-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pedal-core.service
```

Revísalo:

```
sudo systemctl status pedal-core
journalctl -u pedal-core -f
```

La unidad tal como está en el repo usa placeholders — `<YOUR_USER>` y
`<YOUR_USB_UUID>` — en `User=` y `ExecStart=`. Reemplaza ambos con tus
propios valores antes de copiarla (el despliegue de referencia de este
proyecto usa `User=hesner`, ruta de checkout `/home/hesner/chocolatepi`,
y UUID `07C1339846657D95`, coincidiendo con la entrada de `/etc/fstab`
de la sección 2). Edítalos de nuevo más adelante si la ruta de checkout,
el usuario, o el USB de biblioteca cambian.

`Restart=always` hace que el servicio siga reintentando cada 5s si
termina por cualquier razón (el M-VAVE aún no enumerado, el USB aún no
montado, ...) — no hay teclado/pantalla para reiniciarlo a mano en un
appliance real, así que tiene que recuperarse solo.

Usa `Wants=`/`After=` para el mount del USB deliberadamente, no
`RequiresMountsFor=`: esta última es una dependencia dura, así que
desconectar el USB mientras el servicio corre hace que systemd detenga
todo el servicio (video, audio, todo) en vez de dejar que `Player` caiga
al video de standby local como está diseñado — confirmado de la forma
difícil, desconectando el USB durante una prueba en vivo y sin obtener
ni el standby real ni el de respaldo en pantalla, porque no había nada
corriendo. `Wants=`/`After=` solo afecta el orden de arranque; nunca
tumba este servicio por lo que el USB haga después.

## Comportamiento del USB (decisión final)

Política operativa aprobada: el músico apaga la Pi, cambia el contenido
del USB en otra computadora, vuelve a conectar el USB a la Pi, y la
enciende de nuevo. Editar la biblioteca con el show en curso
explícitamente **no** es un flujo de trabajo soportado.

Se intentó un hot-swap totalmente automático (desconectar, editar,
reconectar, sin reiniciar) vía una regla de `udev` + un servicio de
remount, y por separado vía sondeo en segundo plano; ambos se
abandonaron por poco confiables en esta combinación de hardware/sistema
de archivos — ver `CHANGELOG.md`/el historial de git si te tienta
reconstruir uno.

**Comportamiento final decidido**, implementado en `Player`
(`src/core/player.py`):

- Si el USB de biblioteca está presente se revisa **exactamente una vez,
  al arrancar** — vía `/dev/disk/by-uuid/<usb_uuid>` (el mismo UUID que
  en `/etc/fstab` y `--usb-uuid`). Revisar la ruta de `--standby` o su
  punto de montaje directamente se probó primero y resultó poco
  confiable bajo el overlay del sistema de archivos raíz de abajo (ver
  el docstring de `Player._usb_device_is_present()` para los detalles).
- **USB ausente al arrancar**: se reproduce el standby de respaldo local
  en su lugar ("Please insert the USB into the Raspberry Pi").
- **USB retirado mientras ya está corriendo**: no se detecta — el
  sistema sigue mostrando/reproduciendo lo que ya tenía. Recuperarse (o
  tomar una actualización de biblioteca hecha mientras estaba apagada)
  siempre requiere un reinicio; no hay forma soportada de lograrlo sin
  uno.

## 4. Sistema de archivos raíz de solo lectura (paso final de blindaje)

Requisito: debe ser seguro apagar la Pi en cualquier momento (desconectar
la energía) sin riesgo de corromper su propio sistema de archivos — este
appliance no tiene botón de apagado. El requisito de biblioteca de solo
lectura de `MASTER_SPECIFICATION.md` (sección 2) ya cubre el USB; esto
cubre la propia tarjeta SD de la Pi.

Habilitado vía el sistema de archivos overlay integrado de Raspberry Pi
OS (`raspi-config` → Performance Options → Overlay File System):

```
sudo raspi-config nonint do_overlayfs 0   # habilitar (1 para deshabilitar de nuevo)
```

Luego edita `/boot/firmware/cmdline.txt` (remóntalo `rw` primero: `sudo
mount -o remount,rw /boot/firmware`, luego `sudo nano
/boot/firmware/cmdline.txt`) y agrega `:recurse=0` al parámetro
`overlayroot=tmpfs` que se acaba de agregar, para que la línea quede
`overlayroot=tmpfs:recurse=0`. Este archivo es **una sola línea** — no
agregues un salto de línea, solo agrega texto al final del que ya está,
y guarda (`Ctrl+O`, `Enter`, `Ctrl+X` en `nano`). Vuelve a montar
`/boot/firmware` como `ro` y `sudo reboot`.

Esta es la edición más riesgosa de toda esta guía — un error en un
parámetro de la línea de comandos del kernel puede dejar la Pi sin
poder arrancar. Revisa dos veces la línea antes de reiniciar. Si de
verdad no arranca, nada se pierde de forma irrecuperable: reflashea la
tarjeta SD desde Imager (sección 0) y empieza de nuevo desde ahí.

**`recurse=0` es obligatorio, no opcional**: el valor por defecto
(`recurse=1`) envuelve todos los mounts en su propio overlay, incluido
`/media/usb` — y ese overlay generado automáticamente no tiene
`nofail`, así que arrancar sin el USB de biblioteca caía directo en
systemd emergency mode (sin SSH, irrecuperable en un appliance sin
pantalla) en vez de caer al standby local como pretenden las secciones
2/3. `recurse=0` limita el overlay solo a `/`; `/media/usb` y
`/boot/firmware` ya tienen su propio `ro` en `/etc/fstab` de todas
formas, así que no pierden protección.

Después de reiniciar, `/` es un `overlay` (`mount | grep ' / '` muestra
`lowerdir=/media/root-ro` — la SD real, montada `ro` — con
`upperdir=/media/root-rw` en `tmpfs`, es decir RAM). Toda escritura
durante la operación normal cae en RAM y se descarta en cada reinicio;
la tarjeta SD en sí nunca se toca, así que una pérdida de energía
abrupta no puede corromperla.

**Aplica esto al final, una vez que no se espere más desarrollo del lado
de la Pi**: cualquier cosa escrita a la Pi mientras el overlay está
activo (incluyendo sincronizar una versión nueva de este código) se
pierde en el siguiente reinicio, ya que solo cae en la capa superior
respaldada por RAM. Para hacer más cambios: desactívalo temporalmente
(`do_overlayfs 1`, reiniciar), haz y verifica los cambios normalmente,
luego reactívalo — `do_overlayfs 0` reestablece `overlayroot=tmpfs`
**sin** `:recurse=0`, así que rehaz esa edición a `cmdline.txt` cada vez
antes de reiniciar de vuelta a él.

Compromiso aceptado, confirmado como aceptable: `~/pedal-core.log` y el
journal de systemd también se vuelven efímeros (se borran en cada
reinicio, junto con todo lo demás en `/`) — aceptable porque solo se
usan en vivo, durante una sesión activa de debugging por SSH, no se
leen después.

## Mantenimiento / acceso físico

Correr el servicio significa que `mpv` ocupa permanentemente la salida
HDMI (ver `--force-window=yes` en `src/core/player.py`) — esto es algo a
nivel de software, no un bloqueo a nivel de sistema operativo. Para
recuperar la consola física/login para mantenimiento:

```
sudo systemctl stop pedal-core
```

El acceso SSH no se ve afectado de todas formas, sin importar qué esté
haciendo el servicio. Si el sistema de archivos overlay (sección 4) está
activo, ten en cuenta que los comandos `sudo` siguen funcionando
normalmente — solo las escrituras a `/` y `/boot/firmware` caen en el
overlay respaldado por RAM en vez de la SD real, no fallan.

## ¿Puede una persona hacer esto sola, solo con este sitio y estos documentos?

Una revisión deliberada, hecha siguiendo esta guía exactamente como está
escrita — no asumiendo que funciona, comprobándolo — desde la
perspectiva de un músico con conocimientos básicos de computación
(cómodo instalando software, copiando archivos, siguiendo
instrucciones; no un programador, sin experiencia previa en Linux
asumida).

**Respuesta corta: sí, para el montaje físico y la configuración, con
algunos huecos reales de esta guía ya corregidos (ver abajo, y revisa
el commit que agregó esta sección — deberían estar corregidos para
cuando leas esto, ya que encontrarlos fue el propósito de hacer esta
revisión). No, no de forma independiente para nada que requiera código
nuevo** — ver la salvedad del Adapter al final.

### Recorriéndolo como alguien que lo arma por primera vez

1. **Lee `README.md`.** Entiende qué hace y qué hardware comprar. Claro.
2. **Sigue el link a este archivo** para la instalación real. Sección
   0: flashea la tarjeta SD con Raspberry Pi Imager, configura
   hostname/SSH/usuario en las opciones avanzadas. Es una herramienta
   gráfica real y conocida, con su propia documentación oficial — alguien
   sin experiencia previa puede seguirla.
3. **Abre una terminal en su propia computadora para conectarse por
   SSH.** Esta guía decía `ssh <usuario>@<hostname>.local` pero nunca
   decía *en qué programa escribir eso* — un músico que nunca usó SSH
   no necesariamente sabe que Windows trae un comando `ssh` integrado
   dentro de PowerShell/Terminal, o que Mac tiene Terminal.app. **Hueco
   real, ya corregido**: acá va una nota explícita.
4. **Sección 1, instala `mpv`/`ffmpeg`/`ntfs-3g`.** Copiar y pegar un
   comando, directo. Sin problema.
5. **Necesita el código real del proyecto en la Pi ahora**, para tener
   `pedal-core.service` (sección 3) y todo lo demás referenciado por
   ruta. **Esta guía nunca decía que había que clonar el repositorio en
   la Pi, y nunca listaba `git` como algo que instalar.** Alguien
   siguiendo este documento literalmente, en orden, llega a un callejón
   sin salida acá — `sudo cp systemd/pedal-core.service ...` falla
   porque esa ruta todavía no existe. **Hueco real, ya corregido.**
6. **Sección 2, edita `/etc/fstab`.** La guía decía "agrega una línea"
   pero nunca decía *cómo* — en una instalación fresca de Raspberry Pi
   OS no hay ninguna razón para asumir que alguien sin experiencia
   sepa que `nano` existe, cómo invocarlo, o cómo guardar y salir (una
   primera experiencia famosamente poco obvia incluso para gente con
   algo de trasfondo en computación). **Hueco real, ya corregido.**
7. **Sección 3, instala el servicio.** Una vez corregido el hueco del
   paso 5, esto funciona exactamente como está escrito.
8. **Sección 4, edita `/boot/firmware/cmdline.txt` y agrega
   `:recurse=0`.** Mismo hueco del editor que el paso 6, más el hecho de
   que este paso es genuinamente el más propenso a fallar de toda la
   guía incluso para alguien que *sí* sabe usar `nano` — un solo error
   de tipeo en un parámetro de la línea de comandos del kernel, o
   olvidar remontar `/boot/firmware` en `rw` primero, tiene un modo de
   falla mucho menos perdonador (una Pi que no arranca en absoluto) que
   cualquier otro paso acá. Vale la pena que alguien sin trasfondo
   técnico revise dos veces que la línea quedó exactamente bien antes
   de reiniciar, y sepa que siempre puede reflashear la tarjeta SD desde
   Imager de nuevo si algo sale mal justo en este paso — eso no estaba
   dicho en ningún lado como tranquilidad, y probablemente debería.
9. **Fuente de poder.** Nada en la lista de hardware hasta este punto
   decía que la fuente de poder importa — `TESTING.md`/`TROUBLESHOOTING.md`
   documentan que un cargador subalimentado causa un cuelgue real, pero
   esa información es reactiva (la encuentras *después* de toparte con
   el problema), no está dicha como un requisito de comprar lo correcto
   *antes* de empezar. **Hueco real, ya corregido**: la lista de
   hardware debería decir **mínimo 5V/2.5A** desde el principio.
10. **`LIBRARY.md`, configura el USB.** Claro, sin programación de por
    medio, solo seguir un patrón de nombres y copiar archivos — esto
    está exactamente al nivel correcto para esta persona.
11. **Configurar el controlador MIDI en sí** (ej. poner un M-VAVE PD41
    en modo "Program Change A") requiere la *app y las instrucciones
    propias del fabricante*, que este proyecto deliberadamente no
    redistribuye (`PD41-Software-Instructions.pdf` está en gitignore,
    por una decisión explícita anterior en este proyecto). **Hueco
    real**: nada en este repo enlaza a dónde conseguir eso de M-VAVE.
    Alguien que compra el mismo controlador exacto usualmente puede
    encontrarlo desde el propio empaque/página de soporte del producto,
    pero esta guía no lo dice ni apunta a ningún lado.

### La única cosa que alguien sin programación genuinamente no puede hacer solo

Si el controlador no es un M-VAVE PD41 (u otro controlador para el que
alguien más ya haya escrito y contribuido un `Adapter`), **hacer que uno
nuevo funcione requiere escribir Python** — ver la nota "Si el
controlador no es un M-VAVE PD41" de `REBUILD.md` y `CONTRIBUTING.md`.
"Conocimientos básicos de computación" no cubre esto; es una línea
real y dura entre "reproducir esta construcción exacta" (sí, alguien sin
programación puede) y "adaptarlo a hardware distinto" (no, eso necesita
un desarrollador, o un agente de IA siguiendo la metodología de
`REBUILD.md`/`MAVAVE_ANALYSIS.md` en representación del usuario).

### Veredicto

Con los huecos de arriba corregidos, un músico sin trasfondo en Linux y
sin experiencia de programación puede construir esto de punta a punta
**usando exactamente el hardware validado** (M-VAVE PD41, una interfaz
de audio USB compatible con la clase estándar, una Pi 2). El paso
individual más riesgoso sigue siendo la edición de la línea de comandos
del kernel de la sección 4 — no porque las instrucciones estén mal, sino
porque es el único lugar donde un error pequeño tiene una consecuencia
desproporcionada (una Pi que no arranca), en una guía escrita por lo
demás para gente que nunca ha hecho este tipo de cosa antes.
