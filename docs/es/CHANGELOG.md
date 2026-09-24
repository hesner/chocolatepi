# Registro de cambios

*[Read in English](../../CHANGELOG.md)*

El formato sigue libremente [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Este proyecto todavía no usa números de versión — es un aparato dedicado
único, no una librería versionada — así que las entradas se agrupan por
fecha hasta que eso cambie.

## [Sin publicar]

- Se agregó `setlist-admin`: una app web complementaria **opcional**
  para administrar el USB de biblioteca (shows/Sets/pistas, CRUD
  completo) y el WiFi de la Pi (red de casa + respaldo de hotspot del
  celular) desde el navegador de un teléfono o computador. Documento de
  diseño: `SETLIST_ADMIN_SPECIFICATION.md`; guía de uso:
  `SETLIST_ADMIN_APP.md` (en/es). Nunca se instala por defecto y nunca
  modifica `pedal-core.service` ni nada de `src/core/`, `src/adapter/`,
  `src/mapper/` — se instala vía `scripts/install_setlist_admin.sh`, se
  revierte limpiamente vía `scripts/rollback_setlist_admin.sh`.
  Aspectos destacados:
  - Backend de Python solo con librería estándar (`http.server`),
    frontend vanilla responsive — sin dependencia nueva de `pip`/`apt`
    para la app web en sí.
  - Credenciales de WiFi cifradas en reposo en el USB (`openssl enc
    -aes-256-cbc`, no GCM — resultó que `openssl enc` no soporta
    cifrados AEAD, encontrado mientras se construía esto), con una
    llave derivada de esta Pi + este USB específicos.
  - Cada escritura a la biblioteca pasa por una API estructurada que
    hace imposible reproducir por construcción la clase de falla
    silenciosa "doble espacio antes del guion" de LIBRARY.md, no solo
    documentarla.
  - Validación de códec H.264 al subir (advierte, no bloquea).
  - 108 tests nuevos unitarios/de integración (135 en total en todo el
    proyecto) — encontraron y arreglaron dos bugs reales antes de que
    esto toque hardware: un bug de orden en el Set-cookie que rompía en
    silencio cada login, y un límite de longitud de nombre de archivo
    faltante que podía exceder el límite por componente de un sistema
    de archivos.
  - Todavía no validado en hardware real — ver el protocolo de
    seguridad escalonado y respaldado por Ethernet de la sección 8a de
    `SETLIST_ADMIN_SPECIFICATION.md` para cómo debe proceder esa
    validación.
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
