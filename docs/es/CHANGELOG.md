# Registro de cambios

*[Read in English](../../CHANGELOG.md)*

El formato sigue libremente [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Este proyecto todavía no usa números de versión — es un aparato dedicado
único, no una librería versionada — así que las entradas se agrupan por
fecha hasta que eso cambie.

## [Sin publicar]

- Se agregó `setlist-admin` (diseño por USB): un segundo intento de la
  app web complementaria para administrar el USB de biblioteca
  (shows/Sets/pistas, CRUD completo) desde el navegador de un teléfono,
  esta vez conectando el teléfono a la Pi con un cable USB (compartir
  conexión por USB en Android, o Compartir Internet por cable en
  iPhone) en vez de que la Pi necesite su propio radio WiFi — ver
  `SETLIST_ADMIN_USB_SPECIFICATION.md` para el diseño y el porqué (el
  intento anterior por WiFi quedó en pausa por un dongle USB de WiFi
  muerto, preservado en la rama `explore/setlist-admin`, no por culpa
  de ese diseño). Reutiliza sin cambios el backend de CRUD y la
  experiencia del frontend de ese diseño (`library_ops.py`,
  `usb_mount.py` incluyendo su arreglo de `ntfs-3g`, `auth.py`, las
  pantallas de CRUD) para que los dos queden convergibles más adelante.
  Un teléfono se identifica por el nombre de su driver de red USB
  (`rndis_host`/`cdc_ether`/`cdc_ncm` para Android, `ipheth` para
  iPhone), no por rango de IP, así que un cable Ethernet permanente
  nunca arranca el servidor de admin por accidente. Sin
  almacenamiento de credenciales de WiFi, sin manejo de perfiles de
  NetworkManager — toda esa capa desapareció. Aplicar un cambio de
  setlist sigue requiriendo un reinicio (este proyecto ya intentó y
  abandonó un mecanismo de recarga en vivo una vez, ver más abajo en
  este mismo archivo); la app agrega un botón "Reiniciar ahora para
  aplicar" para que eso no necesite SSH. Todavía no validado en
  hardware real.
- Se diseñó e implementó `setlist-admin` (una app web complementaria
  para administrar el USB de biblioteca y el WiFi de la Pi desde el
  navegador de un teléfono/computador), y luego se revirtió de `main`:
  la validación en hardware real (`SETLIST_ADMIN_SPECIFICATION.md`
  sección 8a) avanzó limpio por la instalación y las etapas de dry-run
  y arranque en vivo del watchdog, pero el dongle USB de WiFi (Realtek
  rtl8192cu) resultó ser hardware defectuoso — confirmado al probarlo
  en un computador aparte, donde no apareció como ningún dispositivo
  USB en absoluto. Como toda la funcionalidad depende de un adaptador
  de WiFi funcional, seguir probando queda bloqueado hasta contar con
  uno en buen estado. El diseño completo, la implementación, los tests,
  y un bug real encontrado en el camino (`ntfs-3g` no soporta `mount -o
  remount,rw` — se arregló a un ciclo real de umount+mount) quedan
  preservados en la rama `explore/setlist-admin` para un intento futuro
  con un diseño alternativo.
- Se agregó `REBUILD.md` (en/es): guía ordenada por ejecución para
  reproducir este proyecto en un PC nuevo + una Raspberry Pi nueva,
  escrita para un agente de IA trabajando en frío, sin historial de
  conversación.
- Se agregó `TROUBLESHOOTING.md` (en/es): referencia organizada por
  síntoma de cada falla real que este proyecto tuvo durante su
  desarrollo/pruebas.
- `systemd/README.md` (en/es): se agregó un capítulo de revisión
  "¿puede una persona hacer esto sola?" (se recorrió la guía como lo
  haría un músico sin programación), que encontró y corrigió varios
  huecos reales — nunca se mencionaba `git`/clonar el repo en la Pi,
  sin guía de cliente SSH, sin instrucciones de editor de texto
  (`nano`) para los dos archivos que necesitan edición manual, y el
  requisito de fuente de poder solo estaba documentado de forma
  reactiva (después del hecho, en `TESTING.md`) en vez de como
  requisito previo (ahora también en la lista de hardware de
  `README.md`).
- Se arregló un hueco de contenido real entre EN/ES en `TESTING.md`: a
  la versión en español le faltaba la sección que cierra la prueba 4.0
  (el seguimiento de la prueba en TV real), dejando a un lector solo en
  español pensando que seguía abierta cuando ya se había resuelto.
- **Arreglado**: arrancar sin el USB de biblioteca caía en systemd
  emergency mode (sin SSH, irrecuperable en un appliance sin pantalla)
  en vez del standby de respaldo local. Causa: el `recurse=1` por
  defecto del overlay envuelve todos los mounts (incluido `/media/usb`)
  en su propio overlay sin `nofail`, así que un USB ausente hacía
  fallar un mount crítico para el arranque. Arreglado con `recurse=0`
  (solo raíz) en `cmdline.txt` — ver `systemd/README.md` sección 4.
- Se agregó `LIBRARY.md` (en/es): cómo nombrar carpetas/archivos del USB
  de biblioteca, y el error exacto de espaciado en el nombre de archivo
  (`A  - x.mov` vs `A - x.mov`) que falla completamente en silencio —
  encontrado en vivo probando un video del Set 5 que no se reproducía.
- Proyecto renombrado de "Sequence Pedal" / "Pedal de Secuencias" a
  **Chocolate Pi** -- un nombre de producto propio (juego de palabras
  con el pedal M-VAVE Chocolate + la Raspberry Pi que realmente se usan)
  en vez de una descripción literal. Repo, badges y documentación
  actualizados; GitHub redirige automáticamente la URL vieja del repo.

## 2026-09-05 -- Primera publicación open source

Primer release open source. En uso activo y validado contra hardware
real (Raspberry Pi 2, interfaz de audio USB Behringer U-PHORIA UM2,
controlador MIDI M-VAVE PD41, USB de biblioteca).

- Arquitectura por capas (Adapter → Mapper → Core) para que el código
  específico de un controlador nunca se filtre a la lógica de
  reproducción.
- `Adapter` validado contra un M-VAVE PD41 en modo Program Change A (ver
  `MAVAVE_ANALYSIS.md` para el mapeo empírico y su corrección: 8 grupos,
  no 32).
- `Core`: resolución de biblioteca desde un USB, video manejado por
  `mpv` con loop de standby, un carril de audio dedicado para pistas de
  solo audio, y audio siempre priorizado sobre video.
- Video de standby de respaldo local para cuando el USB de biblioteca no
  está presente al arrancar.
- Servicio de `systemd` para arranque automático; la presencia del USB
  se revisa una sola vez al arrancar (sin hot-swap en vivo — hace falta
  reiniciar para tomar cambios de biblioteca).
- Sistema de archivos raíz de solo lectura (overlay de Raspberry Pi OS)
  para poder apagar la Pi en cualquier momento sin riesgo de corrupción
  del sistema de archivos.
- Licencia MIT, documentación bilingüe (inglés primero, español en
  `docs/es/`), GitHub Sponsors.
