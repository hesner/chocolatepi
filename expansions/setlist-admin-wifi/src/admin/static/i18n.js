// Static ES/EN translation table for the UI chrome -- real user request,
// 2026-10-02. Deliberately covers only interface text (labels, buttons,
// confirms, alerts, toasts): song/track/Set/Bank names are DATA, typed in
// by the user, and must NEVER be translated or altered -- every render
// function in app.js keeps those out of t() calls on purpose. Server-sent
// error messages (api.py/server.py) also stay in English for now; that's
// a separate, explicitly deferred piece of work.

const STRINGS = {
  en: {
    pageTitle: "Chocolate Pi — Setlist Admin",
    appTitle: "Setlist Admin",
    setupPinHeading: "Set a PIN",
    setupPinHint: "No PIN has been configured yet. Choose one to protect this app (at least 4 characters).",
    setupPinPlaceholder: "New PIN",
    setupPinSubmit: "Set PIN",
    loginHeading: "Enter PIN",
    loginPinPlaceholder: "PIN",
    loginSubmit: "Unlock",
    tabLibrary: "Library",
    tabWifi: "WiFi",
    playbackWarning: "⚠ The pedal looks like it's actively playing right now. Editing the library while a Set is in progress isn't supported — changes may not be reflected safely until playback stops.",
    songLibrarySummary: "Song library",
    songLibraryCountEmpty: "(empty)",
    songLibraryHint: "Songs here can be reused in any Bank of any Set, without uploading them again. Uploading directly into a Bank slot below also adds it here automatically.",
    uploadToLibraryBtn: "+ Upload song to library",
    uploadingEllipsis: "Uploading…",
    supportedFormatsHint: "Supported formats: audio MP3, WAV — video MP4, MOV, MPEG, MPG (with embedded audio). Video: H.264, 1080p or less, ~8-12 Mbps recommended -- see <code>LIBRARY.md</code> for full encoding guidance.",
    standbySummary: "Standby video",
    standbyHint: "Loops silently on screen whenever nothing is playing. Pick any video already in the song library above -- to use a new file, upload it there first, then choose it here.",
    standbyNoneSet: "No standby video set yet -- the pedal shows its local fallback until one is chosen here.",
    standbyCurrent: "Current: standby.mp4 ({size} MB, last changed {when})",
    standbyChoosePlaceholder: "-- choose a video --",
    standbyNoVideosPlaceholder: "-- no videos in the library yet --",
    setAsStandbyBtn: "Set as standby",
    chooseVideoFirst: "Choose a video from the library first.",
    standbyUpdatedToast: "Standby video updated -- reboot to apply.",
    setLabel: "Set",
    newSetBtn: "+ New Set",
    exportSetBtn: "Export Set",
    newBankBtn: "+ New Bank",
    noSongsYetHint: "No songs yet -- upload one here, or upload directly into a Bank slot below.",
    chooseSongPlaceholder: "-- choose a song --",
    libraryEmptyPlaceholder: "-- library is empty --",
    optimizeBtn: "Optimize",
    optimizeRetryBtn: "Optimize (retry)",
    optimizingBtn: "Optimizing",
    cancelBtn: "Cancel",
    cancelOptimizeConfirm: "Cancel optimizing \"{filename}\"? It will stay as-is, not yet optimized.",
    cancellingToast: "Cancelling -- this can take a few seconds to actually stop.",
    optimizeConfirm: "Optimize \"{filename}\"?\n\nThis can take a long time on this hardware (confirmed up to a few hours for a large 4K video). Do NOT unplug the Raspberry Pi while it's running -- if you need to stop it, use the \"Cancel\" button that appears once it starts, instead.",
    optimizationStartedToast: "Optimization started -- this can take a while on this hardware; check back later.",
    renameBtn: "Rename",
    renamePrompt: "New name:",
    deleteBtn: "Delete",
    deleteSongConfirm: "⚠ Delete \"{filename}\" from the song library?\n\nIf you're not sure, don't delete it. Once deleted, this song can no longer be chosen when building a Bank -- it won't show up in the picker for any future Set.\n\nThis will NOT remove it from any Bank it's already assigned to -- those keep playing normally, since that's an independent copy, made when it was assigned.",
    songAddedToast: "Song added to the library.",
    songReplacedToast: "Song replaced in the library.",
    replaceConfirm: "\"{name}\" already exists in the library. Replace it?",
    createOrSelectSetFirst: "Create or select a Set first.",
    newSetPrompt: "New Set name:",
    newBankPrompt: "New Bank number:",
    invalidBankNumber: "\"{raw}\" isn't a valid Bank number.",
    deleteBankBtn: "Delete Bank",
    deleteBankConfirm: "Delete Bank {number}? This cannot be undone.",
    bankLabel: "Bank {number}",
    emptyTrackName: "(empty)",
    assignBtn: "Assign",
    uploadNewBtn: "Upload new",
    saveToLibraryBtn: "Save to library",
    songSavedToast: "Song saved to the library.",
    deleteTrackConfirm: "Delete track {letter}?",
    exportCloseAriaLabel: "Close",
    exportSetPrefix: "Set:",
    setlistSharePrefix: "Setlist:",
    shareBtn: "Share",
    noTracksAssigned: "No tracks assigned yet in this Set.",
    exportEntryLabel: "{name} — Bank {number} {letter}",
    uploadFailedFallback: "Upload failed",
    requestFailedFallback: "Request failed ({status})",
    activeSetSuffix: "{name} (active)",
    wifiTabHeading: "Home WiFi",
    wifiHint: "Optional. If configured and reachable, the Pi prefers this network; otherwise it falls back to the phone hotspot automatically.",
    wifiStatus: "Home WiFi: {configured} · Currently connected: {connected}",
    wifiConfigured: "configured",
    wifiNotSet: "not set",
    wifiConnectedYes: "yes",
    wifiConnectedNo: "no",
    wifiSsidPlaceholder: "Network name (SSID)",
    wifiPasswordPlaceholder: "Password",
    wifiSaveBtn: "Save home WiFi",
    wifiSavedMessage: "Saved. The Pi will prefer this network when it's reachable.",
  },
  es: {
    pageTitle: "Chocolate Pi — Administrador de Setlist",
    appTitle: "Administrador de Setlist",
    setupPinHeading: "Configurar un PIN",
    setupPinHint: "Todavía no se ha configurado ningún PIN. Elige uno para proteger esta app (mínimo 4 caracteres).",
    setupPinPlaceholder: "PIN nuevo",
    setupPinSubmit: "Configurar PIN",
    loginHeading: "Ingresa el PIN",
    loginPinPlaceholder: "PIN",
    loginSubmit: "Desbloquear",
    tabLibrary: "Biblioteca",
    tabWifi: "WiFi",
    playbackWarning: "⚠ Parece que el pedal está reproduciendo activamente en este momento. Editar la biblioteca mientras un Set está en curso no es seguro — los cambios pueden no reflejarse correctamente hasta que la reproducción se detenga.",
    songLibrarySummary: "Biblioteca de canciones",
    songLibraryCountEmpty: "(vacía)",
    songLibraryHint: "Las canciones aquí se pueden reutilizar en cualquier Bank de cualquier Set, sin volver a subirlas. Subir un archivo directamente en una ranura de un Bank también lo agrega aquí automáticamente.",
    uploadToLibraryBtn: "+ Subir canción a la biblioteca",
    uploadingEllipsis: "Subiendo…",
    supportedFormatsHint: "Formatos soportados: audio MP3, WAV — video MP4, MOV, MPEG, MPG (con audio incluido). Video: H.264, 1080p o menos, ~8-12 Mbps recomendado -- revisa <code>LIBRARY.md</code> para la guía completa de codificación.",
    standbySummary: "Video de espera (standby)",
    standbyHint: "Se repite en pantalla en silencio mientras no haya nada reproduciéndose. Elige cualquier video que ya esté en la biblioteca de canciones arriba -- para usar un archivo nuevo, súbelo primero ahí, y luego elígelo aquí.",
    standbyNoneSet: "Todavía no se ha configurado un video de espera -- el pedal muestra su respaldo local hasta que se elija uno aquí.",
    standbyCurrent: "Actual: standby.mp4 ({size} MB, última modificación {when})",
    standbyChoosePlaceholder: "-- elige un video --",
    standbyNoVideosPlaceholder: "-- todavía no hay videos en la biblioteca --",
    setAsStandbyBtn: "Usar como video de espera",
    chooseVideoFirst: "Primero elige un video de la biblioteca.",
    standbyUpdatedToast: "Video de espera actualizado -- reinicia para aplicar.",
    setLabel: "Set",
    newSetBtn: "+ Nuevo Set",
    exportSetBtn: "Exportar Set",
    newBankBtn: "+ Nuevo Bank",
    noSongsYetHint: "Todavía no hay canciones -- sube una aquí, o sube directamente en una ranura de un Bank.",
    chooseSongPlaceholder: "-- elige una canción --",
    libraryEmptyPlaceholder: "-- la biblioteca está vacía --",
    optimizeBtn: "Optimizar",
    optimizeRetryBtn: "Optimizar (reintentar)",
    optimizingBtn: "Optimizando",
    cancelBtn: "Cancelar",
    cancelOptimizeConfirm: "¿Cancelar la optimización de \"{filename}\"? Quedará como está, sin optimizar.",
    cancellingToast: "Cancelando -- esto puede tardar unos segundos en detenerse de verdad.",
    optimizeConfirm: "¿Optimizar \"{filename}\"?\n\nEsto puede tardar mucho tiempo en este hardware (confirmado hasta varias horas para un video 4K grande). NO desconectes la Raspberry Pi mientras esté en proceso -- si necesitas detenerlo, usa el botón \"Cancelar\" que aparece una vez que inicia.",
    optimizationStartedToast: "Optimización iniciada -- esto puede tardar en este hardware; revisa más tarde.",
    renameBtn: "Renombrar",
    renamePrompt: "Nuevo nombre:",
    deleteBtn: "Eliminar",
    deleteSongConfirm: "⚠ ¿Eliminar \"{filename}\" de la biblioteca de canciones?\n\nSi no estás seguro, no la elimines. Una vez eliminada, esta canción ya no se podrá elegir al armar un Bank -- no aparecerá en el selector de ningún Set futuro.\n\nEsto NO la quitará de ningún Bank donde ya esté asignada -- esos siguen reproduciéndose normalmente, porque es una copia independiente, hecha en el momento en que se asignó.",
    songAddedToast: "Canción agregada a la biblioteca.",
    songReplacedToast: "Canción reemplazada en la biblioteca.",
    replaceConfirm: "\"{name}\" ya existe en la biblioteca. ¿Reemplazarla?",
    createOrSelectSetFirst: "Primero crea o selecciona un Set.",
    newSetPrompt: "Nombre del nuevo Set:",
    newBankPrompt: "Número del nuevo Bank:",
    invalidBankNumber: "\"{raw}\" no es un número de Bank válido.",
    deleteBankBtn: "Eliminar Bank",
    deleteBankConfirm: "¿Eliminar el Bank {number}? Esto no se puede deshacer.",
    bankLabel: "Bank {number}",
    emptyTrackName: "(vacío)",
    assignBtn: "Asignar",
    uploadNewBtn: "Subir nuevo",
    saveToLibraryBtn: "Guardar en la biblioteca",
    songSavedToast: "Canción guardada en la biblioteca.",
    deleteTrackConfirm: "¿Eliminar la pista {letter}?",
    exportCloseAriaLabel: "Cerrar",
    exportSetPrefix: "Set:",
    setlistSharePrefix: "Setlist:",
    shareBtn: "Compartir",
    noTracksAssigned: "Todavía no hay pistas asignadas en este Set.",
    exportEntryLabel: "{name} — Bank {number} {letter}",
    uploadFailedFallback: "Error al subir el archivo",
    requestFailedFallback: "Falló la solicitud ({status})",
    activeSetSuffix: "{name} (activo)",
    wifiTabHeading: "WiFi de casa",
    wifiHint: "Opcional. Si está configurada y disponible, la Pi prefiere esta red; si no, cae automáticamente al hotspot del teléfono.",
    wifiStatus: "WiFi de casa: {configured} · Conectado actualmente: {connected}",
    wifiConfigured: "configurada",
    wifiNotSet: "sin configurar",
    wifiConnectedYes: "sí",
    wifiConnectedNo: "no",
    wifiSsidPlaceholder: "Nombre de la red (SSID)",
    wifiPasswordPlaceholder: "Contraseña",
    wifiSaveBtn: "Guardar WiFi de casa",
    wifiSavedMessage: "Guardado. La Pi preferirá esta red cuando esté disponible.",
  },
};

let currentLang = (function () {
  try {
    return localStorage.getItem("lang") === "es" ? "es" : "en";
  } catch (_) {
    return "en";
  }
})();

function t(key, vars) {
  const dict = STRINGS[currentLang] || STRINGS.en;
  let str = dict[key] !== undefined ? dict[key] : STRINGS.en[key];
  if (str === undefined) return key;
  if (vars) {
    for (const k of Object.keys(vars)) {
      str = str.split(`{${k}}`).join(vars[k]);
    }
  }
  return str;
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLang;
  document.title = t("pageTitle");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  });
}

function initLangSelector() {
  const select = document.getElementById("lang-select");
  if (!select) return;
  select.value = currentLang;
  select.addEventListener("change", () => {
    try {
      localStorage.setItem("lang", select.value);
    } catch (_) { /* private-browsing/blocked storage -- just loses the preference */ }
    // A full reload is simpler and far less error-prone than re-rendering
    // every dynamically-built piece of UI (song rows, bank cards, the
    // export view...) in place -- this is a rare, deliberate action, not
    // something that needs to be instant.
    location.reload();
  });
}

applyStaticTranslations();
initLangSelector();
