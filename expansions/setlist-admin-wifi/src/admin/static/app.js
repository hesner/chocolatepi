// setlist-admin frontend. Vanilla JS, no build step, no framework --
// SPECIFICATION.md section 2. Talks to the JSON API in
// server.py/api.py; the session cookie is HttpOnly, so this code never
// touches the token directly, just relies on the browser sending it.

const state = {
  sets: [],
  activeSet: null,
  selectedSet: null,
  songs: [], // the shared library (_Songs/) -- reusable across every Set/Bank
  standby: null, // { exists, size_bytes, modified_at } -- current standby.mp4
};

// Real incident (2026-10-02, in the sibling setlist-admin-usb
// expansion -- ported here unchanged): a slow/overloaded Pi (e.g. a
// background "Optimize" job's scratch-copy holding the USB busy for
// minutes -- see usb_mount.exclusive_read()) can make a request sit
// long enough for the phone's own browser/OS to abort it at the
// network level, which surfaces as a raw, untranslated `TypeError:
// Failed to fetch` (or similar) -- confirmed live, reported as a
// confusing "Type error" popup. Anything thrown by fetch() itself
// (never an HTTP error -- those are handled separately, below) gets
// rewritten into a plain, translated message instead.
function friendlyNetworkError(e) {
  if (e instanceof TypeError) {
    return new Error(t("networkErrorFallback"));
  }
  return e;
}

async function apiFetch(path, options = {}) {
  let res;
  try {
    res = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (e) {
    throw friendlyNetworkError(e);
  }
  let body = {};
  try { body = await res.json(); } catch (_) { /* empty body is fine */ }
  if (!res.ok) {
    const err = new Error(body.error || t("requestFailedFallback", { status: res.status }));
    err.status = res.status;
    throw err;
  }
  return body;
}

function show(id) {
  document.getElementById(id).hidden = false;
}
function hide(id) {
  document.getElementById(id).hidden = true;
}
function setText(el, text) {
  el.textContent = text;
}

// A small bottom banner for "this succeeded" confirmations that don't
// warrant a blocking alert() -- e.g. a song landing in the library.
// Reused across calls: one persistent element, re-triggered by resetting
// its hide timer, rather than stacking multiple banners.
function showToast(message) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("visible");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.remove("visible"), 2200);
}

// Highlights a button green the instant it's tapped -- before the
// request even goes out -- so the tap itself is acknowledged right away,
// not only once a slow request (a real file upload over the phone's USB
// tether can take several real seconds) eventually finishes. Left green
// through the request; the button is then either torn down by the
// reload that follows a success, or explicitly reverted via
// clearFlash() if the request fails.
function flashSuccess(btn) {
  if (btn) btn.classList.add("btn-flash-success");
}

function clearFlash(btn) {
  if (btn) btn.classList.remove("btn-flash-success");
}

// Real bug found on real hardware: rebuilding a container this size
// (innerHTML = "" in loadSongs()/loadBanks()) doesn't just shrink/regrow
// the page -- when the button the user just tapped had focus and gets
// destroyed as part of the rebuild, several mobile browsers auto-scroll
// to wherever focus lands next (often the top of the page) *after* the
// DOM update, later than a single scrollTo()/requestAnimationFrame()
// restore call could catch (confirmed still jumping on rename/delete
// song even with that single restore in place). Blur first so nothing
// forces that, then restore on three separate ticks (sync, next frame,
// +60ms) to cover whichever one the browser's own correction lands on.
function beginScrollPreservation() {
  const scrollY = window.scrollY;
  if (document.activeElement && document.activeElement !== document.body) {
    document.activeElement.blur();
  }
  return () => {
    window.scrollTo(0, scrollY);
    requestAnimationFrame(() => window.scrollTo(0, scrollY));
    setTimeout(() => window.scrollTo(0, scrollY), 60);
  };
}

// -- Boot: figure out which screen to show ----------------------------------

async function boot() {
  try {
    const status = await apiFetch("/api/status");
    if (status.first_run) {
      show("view-setup-pin");
      return;
    }
  } catch (e) {
    console.error(e);
  }

  // Try loading sets -- if the session cookie is missing/expired this
  // 401s, which means "show the login screen", not an error to surface.
  try {
    await loadSongs();
    await loadStandby();
    await loadSets();
    show("view-main");
    initTabs();
    await refreshWifiStatus();
    await refreshPlaybackWarning();
  } catch (e) {
    if (e.status === 401) {
      show("view-login");
    } else {
      console.error(e);
      show("view-login");
    }
  }
}

// -- First-run PIN setup -----------------------------------------------------

document.getElementById("form-setup-pin").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const pin = document.getElementById("setup-pin-input").value;
  // Real user request (2026-10-02): tapping submit gave zero feedback
  // until the request finished -- same flashSuccess()/clearFlash()
  // pattern already used for every other button in this app.
  const btn = ev.target.querySelector('button[type="submit"]');
  flashSuccess(btn);
  try {
    await apiFetch("/api/pin", { method: "POST", body: JSON.stringify({ pin }) });
    hide("view-setup-pin");
    show("view-login");
  } catch (e) {
    clearFlash(btn);
    const errEl = document.getElementById("setup-pin-error");
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

// -- Login --------------------------------------------------------------------

document.getElementById("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const pin = document.getElementById("login-pin-input").value;
  // Real user request (2026-10-02): tapping "Unlock" gave zero
  // feedback until the request finished (loading the whole library can
  // take a few seconds) -- same flashSuccess()/clearFlash() pattern
  // already used for every other button in this app.
  const btn = ev.target.querySelector('button[type="submit"]');
  flashSuccess(btn);
  try {
    await apiFetch("/api/login", { method: "POST", body: JSON.stringify({ pin }) });
    hide("view-login");
    await loadSongs();
    await loadStandby();
    await loadSets();
    show("view-main");
    initTabs();
    await refreshWifiStatus();
    await refreshPlaybackWarning();
  } catch (e) {
    clearFlash(btn);
    const errEl = document.getElementById("login-error");
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

// -- Tabs -----------------------------------------------------------------

let tabsInitialized = false;
function initTabs() {
  if (tabsInitialized) return;
  tabsInitialized = true;
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = true));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).hidden = false;
    });
  });
}

// -- Playback warning (section 6: advisory, never blocks) -------------------

async function refreshPlaybackWarning() {
  try {
    const status = await apiFetch("/api/status");
    document.getElementById("playback-warning").hidden = !status.playback_active;
  } catch (_) { /* non-fatal -- just don't show the warning */ }
}

// -- Song library (reusable across every Set/Bank) ---------------------------

async function loadSongs() {
  const data = await apiFetch("/api/songs");
  state.songs = data.songs;

  const countEl = document.getElementById("song-library-count");
  countEl.textContent = state.songs.length ? `(${state.songs.length})` : t("songLibraryCountEmpty");

  // Real bug found on real hardware: capturing/restoring scroll around
  // this *whole* function (including the page-wide track-song-select
  // rebuild below) left a visible ~1s window where the page was
  // genuinely shorter than the old scroll position -- the browser has
  // to clamp scroll to fit, which is real clamping, not an animation,
  // and it's visible for exactly as long as the container stays empty.
  // Narrowing this to just the synchronous empty->rebuilt swap (nothing
  // slower in between) makes that window imperceptible.
  const restoreScroll = beginScrollPreservation();
  const container = document.getElementById("songs-container");
  container.innerHTML = "";
  if (state.songs.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = t("noSongsYetHint");
    container.appendChild(p);
  }
  for (const song of state.songs) {
    container.appendChild(renderSongRow(song));
  }
  restoreScroll();

  // Every track row's "choose from library" dropdown needs to reflect
  // the current song list too -- done after the swap/restore above so
  // this page-wide sweep is never what's keeping songs-container empty.
  document.querySelectorAll(".track-song-select").forEach(populateSongSelect);
  populateStandbySelect();
  ensureSongPolling();
}

// Real user request, 2026-10-02: cancelling (or starting) an optimize job
// resolves on the backend in seconds, but this app only ever re-fetches
// song state on an explicit action -- without this, the button stayed
// stuck showing "Cancel"/"Optimize" until a manual page refresh. Polls
// only while something is actually queued/running, and stops itself the
// moment nothing is -- never ticks in the common case where nothing's
// being optimized.
const SONG_POLL_INTERVAL_MS = 5000;
let songPollTimer = null;

function ensureSongPolling() {
  const active = state.songs.some(
    (s) => s.optimization_status === "queued" || s.optimization_status === "running"
  );
  if (active && !songPollTimer) {
    songPollTimer = setInterval(async () => {
      try {
        await loadSongs();
      } catch (_) { /* transient fetch failure -- just retry next tick */ }
    }, SONG_POLL_INTERVAL_MS);
  } else if (!active && songPollTimer) {
    clearInterval(songPollTimer);
    songPollTimer = null;
  }
}

// -- Standby video (the looped idle screen) -----------------------------------

async function loadStandby() {
  const data = await apiFetch("/api/standby");
  state.standby = data;
  const el = document.getElementById("standby-current");
  if (data.exists) {
    const sizeMb = (data.size_bytes / (1024 * 1024)).toFixed(1);
    const when = new Date(data.modified_at * 1000).toLocaleString();
    setText(el, t("standbyCurrent", { size: sizeMb, when }));
  } else {
    setText(el, t("standbyNoneSet"));
  }
  populateStandbySelect();
}

function populateStandbySelect() {
  const select = document.getElementById("standby-song-select");
  if (!select) return;
  const previousValue = select.value;
  select.innerHTML = "";
  const videos = state.songs.filter((s) => !s.is_audio_only);
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = videos.length ? t("standbyChoosePlaceholder") : t("standbyNoVideosPlaceholder");
  select.appendChild(placeholder);
  for (const song of videos) {
    const opt = document.createElement("option");
    opt.value = song.filename;
    opt.textContent = `${song.display_name}.${song.extension}`;
    select.appendChild(opt);
  }
  select.value = previousValue || "";
}

document.getElementById("btn-set-standby").addEventListener("click", async () => {
  const select = document.getElementById("standby-song-select");
  const btn = document.getElementById("btn-set-standby");
  const errEl = document.getElementById("standby-error");
  errEl.hidden = true;
  if (!select.value) {
    setText(errEl, t("chooseVideoFirst"));
    errEl.hidden = false;
    return;
  }
  flashSuccess(btn);
  try {
    await apiFetch("/api/standby", { method: "POST", body: JSON.stringify({ song_filename: select.value }) });
    // Real user request (2026-10-02): the dropdown used to keep
    // whatever was selected, so right after a successful change the
    // button still read "Set as standby" with that same video still
    // picked -- looked like nothing had happened, or like it needed
    // tapping again. Resetting to the placeholder makes the just-
    // completed action visually final; "Current: ..." above (updated
    // by loadStandby() next) is the actual confirmation of what's
    // playing now.
    select.value = "";
    await loadStandby();
    showToast(t("standbyUpdatedToast"));
  } catch (e) {
    clearFlash(btn);
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

function populateSongSelect(select) {
  const previousValue = select.value;
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.songs.length ? t("chooseSongPlaceholder") : t("libraryEmptyPlaceholder");
  select.appendChild(placeholder);
  for (const song of state.songs) {
    const opt = document.createElement("option");
    opt.value = song.filename;
    opt.textContent = `${song.display_name}.${song.extension}`;
    select.appendChild(opt);
  }
  select.value = previousValue || "";
}

function renderSongRow(song) {
  const tpl = document.getElementById("tpl-song");
  const node = tpl.content.cloneNode(true);
  node.querySelector(".song-name").textContent = song.filename;

  // "Optimize" (real user request, 2026-10-01): offered whenever
  // codec_check.is_optimized() says a video's codec isn't H.264 -- see
  // library_optimizer.py for the always-on background daemon that
  // actually does the re-encode, independent of whether the phone
  // that tapped this button is still connected by the time it finishes
  // (it can take a very long time on this hardware -- confirmed live,
  // roughly 90 minutes for one problematic video).
  const optimizeBtn = node.querySelector(".btn-optimize-song");
  const cancelOptimizeBtn = node.querySelector(".btn-cancel-optimize-song");
  if (song.needs_optimization) {
    const inProgress = song.optimization_status === "queued" || song.optimization_status === "running";
    if (inProgress) {
      // Real user request (2026-10-02): shown as a standing indicator,
      // not hidden -- needs to read as "something is happening" right
      // next to "Cancel", not disappear in favor of it.
      //
      // Real incident, same day: "queued" and "running" used to render
      // identically (both green "Optimizing") -- with two songs
      // in-flight at once (one actually encoding, one just waiting its
      // turn), there was no way to tell which was which. Confirmed
      // live: this led to cancelling the wrong one by mistake, since
      // both rows looked the same. Now visually distinct: green only
      // for the one actually running; a plain, secondary "Queued" for
      // one still waiting its turn.
      const actuallyRunning = song.optimization_status === "running";
      optimizeBtn.hidden = false;
      optimizeBtn.classList.toggle("success", actuallyRunning);
      optimizeBtn.classList.toggle("secondary", !actuallyRunning);
      optimizeBtn.textContent = actuallyRunning ? t("optimizingBtn") : t("queuedBtn");
      optimizeBtn.disabled = true;
      // Real user request (2026-10-02), after a real incident: a long
      // optimize job (hours, on this hardware) running in the
      // background isn't visible from the outside -- someone could
      // reasonably think nothing's happening and unplug the Pi. Give
      // an explicit way to stop it cleanly instead.
      cancelOptimizeBtn.hidden = false;
      cancelOptimizeBtn.textContent = t("cancelBtn");
      cancelOptimizeBtn.addEventListener("click", async () => {
        if (!confirm(t("cancelOptimizeConfirm", { filename: song.filename }))) return;
        flashSuccess(cancelOptimizeBtn);
        try {
          await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}/optimize/cancel`, { method: "POST" });
          await loadSongs();
          showToast(t("cancellingToast"));
        } catch (e) {
          clearFlash(cancelOptimizeBtn);
          alert(e.message);
        }
      });
    } else {
      optimizeBtn.hidden = false;
      optimizeBtn.textContent = song.optimization_status === "error" ? t("optimizeRetryBtn") : t("optimizeBtn");
      if (song.optimization_error) optimizeBtn.title = song.optimization_error;
      optimizeBtn.addEventListener("click", async () => {
        // Real user request (2026-10-02), after a real incident: an
        // optimize job can run for hours, writing to the Pi's own
        // local storage the whole time -- unplugging the Pi mid-job
        // loses all that progress (safe to retry, but wasted time) and,
        // if this Pi's protective overlay ever isn't active for some
        // other reason, is a genuine power-loss risk for the Pi itself,
        // not just the library USB.
        if (!confirm(t("optimizeConfirm", { filename: song.filename }))) return;
        flashSuccess(optimizeBtn);
        try {
          await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}/optimize`, { method: "POST" });
          await loadSongs();
          showToast(t("optimizationStartedToast"));
        } catch (e) {
          clearFlash(optimizeBtn);
          alert(e.message);
        }
      });
    }
  }

  const renameSongBtn = node.querySelector(".btn-rename-song");
  renameSongBtn.textContent = t("renameBtn");
  renameSongBtn.addEventListener("click", async () => {
    const newName = prompt(t("renamePrompt"), song.display_name);
    if (!newName) return;
    flashSuccess(renameSongBtn);
    try {
      await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}`, {
        method: "PUT", body: JSON.stringify({ display_name: newName }),
      });
      await loadSongs();
    } catch (e) {
      clearFlash(renameSongBtn);
      alert(e.message);
    }
  });

  const deleteSongBtn = node.querySelector(".btn-delete-song");
  deleteSongBtn.textContent = t("deleteBtn");
  deleteSongBtn.addEventListener("click", async () => {
    if (!confirm(t("deleteSongConfirm", { filename: song.filename }))) return;
    flashSuccess(deleteSongBtn);
    try {
      await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}`, { method: "DELETE" });
      await loadSongs();
    } catch (e) {
      clearFlash(deleteSongBtn);
      alert(e.message);
    }
  });

  return node;
}

document.getElementById("btn-upload-to-library").addEventListener("click", () => {
  document.getElementById("library-upload-input").click();
});

// Posts a file to the song library. Throws on failure; the error carries
// a `.conflict` flag (set from the 409 ApiError api.py raises
// specifically for an overwrite-able name collision, see api.py's
// upload_song() docstring) so callers can offer "replace it?" instead of
// just failing, without string-matching the error text themselves.
async function uploadSongToLibrary(displayName, extension, file, overwrite) {
  const headers = { "X-Track-Name": displayName, "X-Track-Extension": extension };
  if (overwrite) headers["X-Track-Overwrite"] = "true";
  let res;
  try {
    res = await fetch("/api/songs", { method: "POST", headers, body: file });
  } catch (e) {
    throw friendlyNetworkError(e);
  }
  const result = await res.json();
  if (!res.ok) {
    const err = new Error(result.error || t("uploadFailedFallback"));
    err.conflict = res.status === 409;
    throw err;
  }
  if (result.warning) alert(result.warning);
}

document.getElementById("library-upload-input").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const dotIndex = file.name.lastIndexOf(".");
  const displayName = dotIndex > 0 ? file.name.slice(0, dotIndex) : file.name;
  const extension = dotIndex > 0 ? file.name.slice(dotIndex + 1) : "";
  const btn = document.getElementById("btn-upload-to-library");

  // Real incident (2026-10-02): the only way to learn about a name
  // collision used to be uploading the *whole file* first and reading
  // the server's 409 -- normally fast, but if the USB happens to be
  // busy with something else (e.g. an "Optimize" job's scratch-copy --
  // see usb_mount.exclusive_read()), that upload can legitimately wait
  // minutes before the collision even gets reported. state.songs is
  // already loaded client-side, so checking there first catches the
  // common case instantly, before sending any file data at all. The
  // server's own check (in uploadSongToLibrary()'s .conflict branch
  // below) still runs for the real upload either way -- this is a
  // fast-path, not a replacement for it.
  const targetFilename = `${displayName}.${extension}`;
  const knownDuplicate = state.songs.some((s) => s.filename === targetFilename);
  if (knownDuplicate && !confirm(t("replaceConfirm", { name: targetFilename }))) {
    ev.target.value = "";
    return;
  }

  // Real bug found on real hardware: a file upload over the phone's USB
  // tether can take several real seconds (not the ~200ms a plain API
  // call takes), and this button gave zero feedback for that whole
  // window -- flashSuccess()/showToast() only ever fired once the
  // request had already finished, so tapping it looked like nothing had
  // happened until the result showed up unexplained moments later.
  const originalText = btn.textContent;
  btn.textContent = t("uploadingEllipsis");
  btn.disabled = true;
  flashSuccess(btn);
  try {
    try {
      await uploadSongToLibrary(displayName, extension, file, knownDuplicate);
      await loadSongs();
      showToast(knownDuplicate ? t("songReplacedToast") : t("songAddedToast"));
    } catch (e) {
      if (!e.conflict) throw e;
      // Real user request, 2026-10-01: offer to replace instead of just
      // failing -- a name collision is a normal thing to want to resolve
      // in the moment, not necessarily a mistake to go fix separately
      // via rename_song()/delete_song() first. Only reachable now if
      // state.songs was stale (e.g. uploaded from another device
      // moments ago) -- the common case is already handled above,
      // before any file data was even sent.
      if (!confirm(t("replaceConfirm", { name: targetFilename }))) {
        clearFlash(btn);
        return;
      }
      flashSuccess(btn);
      await uploadSongToLibrary(displayName, extension, file, true);
      await loadSongs();
      showToast(t("songReplacedToast"));
    }
  } catch (e) {
    clearFlash(btn);
    alert(e.message);
  } finally {
    ev.target.value = "";
    btn.textContent = originalText;
    btn.disabled = false;
  }
});

// -- Sets / Banks / Tracks ---------------------------------------------------

async function loadSets() {
  const data = await apiFetch("/api/sets");
  state.sets = data.sets;
  state.activeSet = data.active;
  state.selectedSet = state.selectedSet || data.active || data.sets[0] || null;

  const select = document.getElementById("set-select");
  select.innerHTML = "";
  for (const name of data.sets) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name === data.active ? t("activeSetSuffix", { name }) : name;
    select.appendChild(opt);
  }
  if (state.selectedSet) select.value = state.selectedSet;

  if (state.selectedSet) await loadBanks(state.selectedSet);
}

document.getElementById("set-select").addEventListener("change", async (ev) => {
  state.selectedSet = ev.target.value;
  try {
    await loadBanks(state.selectedSet);
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("btn-new-set").addEventListener("click", async () => {
  const name = prompt(t("newSetPrompt"));
  if (!name) return;
  const btn = document.getElementById("btn-new-set");
  flashSuccess(btn);
  try {
    await apiFetch("/api/sets", { method: "POST", body: JSON.stringify({ name }) });
    await apiFetch("/api/sets/active", { method: "POST", body: JSON.stringify({ name }) });
    state.selectedSet = name;
    await loadSets();
  } catch (e) {
    clearFlash(btn);
    alert(e.message);
  }
});

// -- Export Set: full-screen "cheat sheet" view + share-as-image ------------

let exportSetName = null;
let exportEntries = [];

document.getElementById("btn-export-set").addEventListener("click", async () => {
  if (!state.selectedSet) {
    alert(t("createOrSelectSetFirst"));
    return;
  }
  try {
    exportSetName = state.selectedSet;
    exportEntries = await buildSetlistEntries(exportSetName);
    renderExportView(exportSetName, exportEntries);
    showExportView();
  } catch (e) {
    alert(e.message);
  }
});

async function buildSetlistEntries(setName) {
  const banksData = await apiFetch(`/api/sets/${encodeURIComponent(setName)}/banks`);
  const entries = [];
  for (const bankNumber of banksData.banks) {
    const tracks = await apiFetch(`/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks`);
    for (const letter of ["A", "B", "C"]) {
      const track = tracks[letter];
      if (track) {
        entries.push({
          bankNumber,
          letter,
          // Exact stored name + extension, deliberately -- consistent
          // with whatever's really on the USB, per an explicit request
          // that this view never show a "prettied up" name that could
          // drift from what a person editing the USB by hand would see.
          name: `${track.display_name}.${track.extension}`,
        });
      }
    }
  }
  return entries;
}

function renderExportView(setName, entries) {
  document.getElementById("export-set-name").textContent = setName;
  const listEl = document.getElementById("export-list");
  listEl.innerHTML = "";
  for (const entry of entries) {
    const li = document.createElement("li");
    li.textContent = t("exportEntryLabel", { name: entry.name, number: entry.bankNumber, letter: entry.letter });
    listEl.appendChild(li);
  }
  if (entries.length === 0) {
    const li = document.createElement("li");
    li.textContent = t("noTracksAssigned");
    listEl.appendChild(li);
  }
}

function showExportView() {
  document.getElementById("export-view").hidden = false;
  // Pushing a history entry lets the phone's own back button/gesture
  // close this view instead of navigating away from the app entirely.
  history.pushState({ exportView: true }, "");
}

function closeExportView() {
  const view = document.getElementById("export-view");
  if (view.hidden) return;
  view.hidden = true;
  if (history.state && history.state.exportView) {
    history.back();
  }
}

window.addEventListener("popstate", () => {
  document.getElementById("export-view").hidden = true;
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeExportView();
});

document.getElementById("btn-export-close").addEventListener("click", closeExportView);

document.getElementById("btn-export-share").addEventListener("click", async () => {
  const shareBtn = document.getElementById("btn-export-share");
  flashSuccess(shareBtn);
  try {
    const blob = await renderSetlistToPngBlob(exportSetName, exportEntries);
    const fileName = `${exportSetName.replace(/[^a-z0-9]+/gi, "_")}-setlist.png`;
    const file = new File([blob], fileName, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: `${t("setlistSharePrefix")} ${exportSetName}` });
    } else {
      // Desktop/unsupported-browser fallback -- to be certified from a
      // PC separately later; a plain download always works meanwhile.
      downloadBlob(blob, fileName);
    }
  } catch (e) {
    clearFlash(shareBtn);
    if (e.name !== "AbortError") alert(e.message); // AbortError = user cancelled the share sheet, not a failure
  }
});

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function renderSetlistToPngBlob(setName, entries) {
  const width = 1080;
  const paddingX = 64;
  const headerHeight = 160;
  const lineHeight = 76;
  const footerHeight = 48;

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = width;
  const bodyHeight = Math.max(entries.length, 1) * lineHeight;
  canvas.height = headerHeight + bodyHeight + footerHeight;

  // Background
  ctx.fillStyle = "#0f1115";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Title
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#e8e9ec";
  ctx.font = "bold 52px -apple-system, sans-serif";
  ctx.fillText(`${t("exportSetPrefix")} ${setName}`, paddingX, 76);

  ctx.strokeStyle = "#2e333d";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(paddingX, headerHeight - 20);
  ctx.lineTo(width - paddingX, headerHeight - 20);
  ctx.stroke();

  // Entries
  if (entries.length === 0) {
    ctx.fillStyle = "#9aa0ab";
    ctx.font = "36px -apple-system, sans-serif";
    ctx.fillText(t("noTracksAssigned"), paddingX, headerHeight + 48);
  } else {
    entries.forEach((entry, index) => {
      const baseline = headerHeight + (index + 1) * lineHeight - 24;
      ctx.fillStyle = "#4f8cff";
      ctx.font = "bold 38px -apple-system, sans-serif";
      ctx.fillText(`${index + 1}.`, paddingX, baseline);
      ctx.fillStyle = "#e8e9ec";
      ctx.font = "38px -apple-system, sans-serif";
      ctx.fillText(t("exportEntryLabel", { name: entry.name, number: entry.bankNumber, letter: entry.letter }), paddingX + 64, baseline);
    });
  }

  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

document.getElementById("btn-new-bank").addEventListener("click", async () => {
  if (!state.selectedSet) {
    // Real, pre-existing bug: this used to return here silently, with
    // no feedback at all -- looked exactly like a broken button. Only
    // reachable if no Set exists/is selected yet.
    alert(t("createOrSelectSetFirst"));
    return;
  }
  const newBankBtn = document.getElementById("btn-new-bank");
  flashSuccess(newBankBtn);
  try {
    // Real user request (2026-10-02): Banks are sequential slots a
    // physical MIDI controller steps through one at a time -- asking
    // the user to type a number by hand only ever risked a typo or an
    // accidental gap, with no real reason to ever pick anything but
    // the next one. Auto-assigns the next number after whatever
    // already exists (1 if the Set has none yet), same as counting up
    // by hand. Not capped at this band's own M-VAVE's 8 physical
    // banks -- this app supports any MIDI controller, so a Bank
    // 9/10/etc. is always allowed even though a specific controller
    // might never reach it.
    const existing = (await apiFetch(`/api/sets/${encodeURIComponent(state.selectedSet)}/banks`)).banks;
    const number = existing.length ? Math.max(...existing) + 1 : 1;
    await apiFetch(`/api/sets/${encodeURIComponent(state.selectedSet)}/banks`, {
      method: "POST", body: JSON.stringify({ number }),
    });
    await loadBanks(state.selectedSet);
  } catch (e) {
    // Real, pre-existing bug found on real hardware: this had no catch
    // at all, so any server error (including a transient USB
    // remount-busy failure -- admin.usb_mount's retry now covers the
    // common case, but not every possible failure) surfaced as an
    // unhandled promise rejection: no alert, no visible change, looking
    // exactly like a completely unresponsive button.
    clearFlash(newBankBtn);
    alert(e.message);
  }
});

async function loadBanks(setName) {
  const data = await apiFetch(`/api/sets/${encodeURIComponent(setName)}/banks`);

  // Real bug found on real hardware: renderBankCard() below does its own
  // network round-trip per Bank (fetching that Bank's tracks), awaited
  // one at a time -- with the container already emptied first, the page
  // sat genuinely shorter than the old scroll position for the combined
  // duration of every one of those round-trips (easily ~1s with several
  // Banks on real Pi-2-speed hardware), forcing a real scroll clamp, not
  // just a brief animation. Build every card first, while the *old*
  // content is still fully in place on screen, then swap all at once --
  // the empty window shrinks to one synchronous DOM swap.
  const cards = [];
  for (const bankNumber of data.banks) {
    cards.push(await renderBankCard(setName, bankNumber));
  }

  const restoreScroll = beginScrollPreservation();
  const container = document.getElementById("banks-container");
  container.innerHTML = "";
  for (const card of cards) {
    container.appendChild(card);
  }
  restoreScroll();
}

async function renderBankCard(setName, bankNumber) {
  const tpl = document.getElementById("tpl-bank");
  const node = tpl.content.cloneNode(true);
  const card = node.querySelector(".bank-card");
  node.querySelector(".bank-number-label").textContent = t("bankLabel", { number: bankNumber });

  const deleteBankBtn = node.querySelector(".btn-delete-bank");
  deleteBankBtn.textContent = t("deleteBankBtn");
  deleteBankBtn.addEventListener("click", async () => {
    if (!confirm(t("deleteBankConfirm", { number: bankNumber }))) return;
    flashSuccess(deleteBankBtn);
    try {
      await apiFetch(`/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}`, { method: "DELETE" });
      await loadBanks(setName);
    } catch (e) {
      clearFlash(deleteBankBtn);
      alert(e.message);
    }
  });

  const tracksData = await apiFetch(`/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks`);
  const tracksEl = node.querySelector(".tracks");
  for (const letter of Object.keys(tracksData).sort()) {
    tracksEl.appendChild(renderTrackRow(setName, bankNumber, letter, tracksData[letter]));
  }

  return card;
}

function renderTrackRow(setName, bankNumber, letter, track) {
  const tpl = document.getElementById("tpl-track");
  const node = tpl.content.cloneNode(true);
  node.querySelector(".track-letter").textContent = letter;
  node.querySelector(".track-name").textContent = track
    ? `${track.display_name}.${track.extension}`
    : t("emptyTrackName");

  const fileInput = node.querySelector(".track-file-input");
  const uploadBtn = node.querySelector(".btn-upload");
  const renameBtn = node.querySelector(".btn-rename");
  const deleteBtn = node.querySelector(".btn-delete");
  const songSelect = node.querySelector(".track-song-select");
  const assignBtn = node.querySelector(".btn-assign-from-library");
  const saveToLibraryBtn = node.querySelector(".btn-save-to-library");

  assignBtn.textContent = t("assignBtn");
  uploadBtn.textContent = t("uploadNewBtn");
  populateSongSelect(songSelect);

  assignBtn.addEventListener("click", async () => {
    const songFilename = songSelect.value;
    if (!songFilename) return;
    flashSuccess(assignBtn);
    try {
      await apiFetch(
        `/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks/${letter}/assign-from-library`,
        { method: "POST", body: JSON.stringify({ song_filename: songFilename }) },
      );
      await loadBanks(setName);
    } catch (e) {
      clearFlash(assignBtn);
      alert(e.message);
    }
  });

  uploadBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    const dotIndex = file.name.lastIndexOf(".");
    const displayName = dotIndex > 0 ? file.name.slice(0, dotIndex) : file.name;
    const extension = dotIndex > 0 ? file.name.slice(dotIndex + 1) : "";
    uploadBtn.textContent = t("uploadingEllipsis");
    uploadBtn.disabled = true;
    flashSuccess(uploadBtn);
    try {
      const res = await fetch(
        `/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks/${letter}`,
        {
          method: "POST",
          headers: { "X-Track-Name": displayName, "X-Track-Extension": extension },
          body: file,
        },
      );
      const result = await res.json();
      // Real, pre-existing bug: this never checked res.ok, so a server
      // error here (a 400/500) was silently treated as success -- no
      // alert, no thrown error, just quietly reloading stale state as if
      // nothing had gone wrong.
      if (!res.ok) throw new Error(result.error || t("uploadFailedFallback"));
      if (result.warning) {
        // Codec warning (section 9): the upload still succeeded, this
        // is advisory, not blocking -- alert() is blunt but this is a
        // rare path and doesn't warrant its own UI component.
        alert(result.warning);
      }
      await loadSongs(); // the upload also added it to the library
      await loadBanks(setName);
    } catch (e) {
      clearFlash(uploadBtn);
      alert(friendlyNetworkError(e).message);
    } finally {
      uploadBtn.textContent = t("uploadNewBtn");
      uploadBtn.disabled = false;
    }
  });

  if (track) {
    renameBtn.hidden = false;
    deleteBtn.hidden = false;
    saveToLibraryBtn.hidden = false;
    renameBtn.textContent = t("renameBtn");
    deleteBtn.textContent = t("deleteBtn");
    saveToLibraryBtn.textContent = t("saveToLibraryBtn");

    renameBtn.addEventListener("click", async () => {
      const newName = prompt(t("renamePrompt"), track.display_name);
      if (!newName) return;
      flashSuccess(renameBtn);
      try {
        await apiFetch(
          `/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks/${letter}`,
          { method: "PUT", body: JSON.stringify({ display_name: newName }) },
        );
        await loadBanks(setName);
      } catch (e) {
        clearFlash(renameBtn);
        alert(e.message);
      }
    });

    deleteBtn.addEventListener("click", async () => {
      if (!confirm(t("deleteTrackConfirm", { letter }))) return;
      flashSuccess(deleteBtn);
      try {
        await apiFetch(
          `/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks/${letter}`,
          { method: "DELETE" },
        );
        await loadBanks(setName);
      } catch (e) {
        clearFlash(deleteBtn);
        alert(e.message);
      }
    });

    saveToLibraryBtn.addEventListener("click", async () => {
      flashSuccess(saveToLibraryBtn);
      try {
        await apiFetch(
          `/api/sets/${encodeURIComponent(setName)}/banks/${bankNumber}/tracks/${letter}/save-to-library`,
          { method: "POST" },
        );
        await loadSongs();
        showToast(t("songSavedToast"));
      } catch (e) {
        clearFlash(saveToLibraryBtn);
        alert(e.message);
      }
    });
  }

  return node;
}

// -- WiFi ---------------------------------------------------------------------

async function refreshWifiStatus() {
  try {
    const data = await apiFetch("/api/wifi");
    const el = document.getElementById("wifi-status");
    const configured = data.home_configured ? t("wifiConfigured") : t("wifiNotSet");
    // data.active_connection is the real network name the Pi is joined
    // to -- DATA, kept verbatim regardless of language, same rule as
    // song/Set/Bank names.
    const connected = data.connected ? (data.active_connection || t("wifiConnectedYes")) : t("wifiConnectedNo");
    el.textContent = t("wifiStatus", { configured, connected });
  } catch (e) {
    console.error(e);
  }
}

document.getElementById("form-home-wifi").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const ssid = document.getElementById("wifi-ssid").value;
  const password = document.getElementById("wifi-password").value;
  const errEl = document.getElementById("wifi-error");
  const okEl = document.getElementById("wifi-success");
  errEl.hidden = true;
  okEl.hidden = true;
  try {
    await apiFetch("/api/wifi/home", { method: "POST", body: JSON.stringify({ ssid, password }) });
    setText(okEl, t("wifiSavedMessage"));
    okEl.hidden = false;
    await refreshWifiStatus();
  } catch (e) {
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

boot();
