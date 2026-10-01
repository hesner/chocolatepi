// setlist-admin frontend. Vanilla JS, no build step, no framework --
// SPECIFICATION.md section 3. Talks to the JSON API in
// server.py/api.py; the session cookie is HttpOnly, so this code never
// touches the token directly, just relies on the browser sending it.

const state = {
  sets: [],
  activeSet: null,
  selectedSet: null,
  songs: [], // the shared library (_Songs/) -- reusable across every Set/Bank
  standby: null, // { exists, size_bytes, modified_at } -- current standby.mp4
};

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body = {};
  try { body = await res.json(); } catch (_) { /* empty body is fine */ }
  if (!res.ok) {
    const err = new Error(body.error || `Request failed (${res.status})`);
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
  try {
    await apiFetch("/api/pin", { method: "POST", body: JSON.stringify({ pin }) });
    hide("view-setup-pin");
    show("view-login");
  } catch (e) {
    const errEl = document.getElementById("setup-pin-error");
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

// -- Login --------------------------------------------------------------------

document.getElementById("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const pin = document.getElementById("login-pin-input").value;
  try {
    await apiFetch("/api/login", { method: "POST", body: JSON.stringify({ pin }) });
    hide("view-login");
    await loadSongs();
    await loadStandby();
    await loadSets();
    show("view-main");
    await refreshPlaybackWarning();
  } catch (e) {
    const errEl = document.getElementById("login-error");
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

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
  countEl.textContent = state.songs.length ? `(${state.songs.length})` : "(empty)";

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
    p.textContent = "No songs yet -- upload one here, or upload directly into a Bank slot below.";
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
}

// -- Standby video (the looped idle screen) -----------------------------------

async function loadStandby() {
  const data = await apiFetch("/api/standby");
  state.standby = data;
  const el = document.getElementById("standby-current");
  if (data.exists) {
    const sizeMb = (data.size_bytes / (1024 * 1024)).toFixed(1);
    const when = new Date(data.modified_at * 1000).toLocaleString();
    setText(el, `Current: standby.mp4 (${sizeMb} MB, last changed ${when})`);
  } else {
    setText(el, "No standby video set yet -- the pedal shows its local fallback until one is chosen here.");
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
  placeholder.textContent = videos.length ? "-- choose a video --" : "-- no videos in the library yet --";
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
    setText(errEl, "Choose a video from the library first.");
    errEl.hidden = false;
    return;
  }
  flashSuccess(btn);
  try {
    await apiFetch("/api/standby", { method: "POST", body: JSON.stringify({ song_filename: select.value }) });
    await loadStandby();
    showToast("Standby video updated -- reboot to apply.");
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
  placeholder.textContent = state.songs.length ? "-- choose a song --" : "-- library is empty --";
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

  const renameSongBtn = node.querySelector(".btn-rename-song");
  renameSongBtn.addEventListener("click", async () => {
    const newName = prompt("New name:", song.display_name);
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
  deleteSongBtn.addEventListener("click", async () => {
    if (!confirm(
      `⚠ Delete "${song.filename}" from the song library?\n\n` +
      `If you're not sure, don't delete it. Once deleted, this song can ` +
      `no longer be chosen when building a Bank -- it won't show up in ` +
      `the picker for any future Set.\n\n` +
      `This will NOT remove it from any Bank it's already assigned to -- ` +
      `those keep playing normally, since that's an independent copy, ` +
      `made when it was assigned.`
    )) return;
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
  const res = await fetch("/api/songs", { method: "POST", headers, body: file });
  const result = await res.json();
  if (!res.ok) {
    const err = new Error(result.error || "Upload failed");
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
  // Real bug found on real hardware: a file upload over the phone's USB
  // tether can take several real seconds (not the ~200ms a plain API
  // call takes), and this button gave zero feedback for that whole
  // window -- flashSuccess()/showToast() only ever fired once the
  // request had already finished, so tapping it looked like nothing had
  // happened until the result showed up unexplained moments later.
  const originalText = btn.textContent;
  btn.textContent = "Uploading…";
  btn.disabled = true;
  flashSuccess(btn);
  try {
    try {
      await uploadSongToLibrary(displayName, extension, file, false);
      await loadSongs();
      showToast("Song added to the library.");
    } catch (e) {
      if (!e.conflict) throw e;
      // Real user request, 2026-10-01: offer to replace instead of just
      // failing -- a name collision is a normal thing to want to resolve
      // in the moment, not necessarily a mistake to go fix separately
      // via rename_song()/delete_song() first.
      if (!confirm(`"${displayName}.${extension}" already exists in the library. Replace it?`)) {
        clearFlash(btn);
        return;
      }
      flashSuccess(btn);
      await uploadSongToLibrary(displayName, extension, file, true);
      await loadSongs();
      showToast("Song replaced in the library.");
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
    opt.textContent = name === data.active ? `${name} (active)` : name;
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
  const name = prompt("New Set name:");
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

const SUPPORTED_FORMATS_DISCLAIMER =
  "Supported formats for uploading: audio MP3, WAV — video MP4, MOV, MPEG, MPG (with embedded audio).";

let exportSetName = null;
let exportEntries = [];

document.getElementById("btn-export-set").addEventListener("click", async () => {
  if (!state.selectedSet) {
    alert("Create or select a Set first.");
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
    li.textContent = `${entry.name} — Bank ${entry.bankNumber} ${entry.letter}`;
    listEl.appendChild(li);
  }
  if (entries.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No tracks assigned yet in this Set.";
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
      await navigator.share({ files: [file], title: `Setlist: ${exportSetName}` });
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
  const disclaimerLineHeight = 34;
  const footerPadding = 40;

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  // Measuring the wrapped disclaimer needs a sized context first.
  canvas.width = width;
  const disclaimerLines = wrapTextLines(ctx, SUPPORTED_FORMATS_DISCLAIMER, width - paddingX * 2, "24px -apple-system, sans-serif");
  const bodyHeight = Math.max(entries.length, 1) * lineHeight;
  const footerHeight = footerPadding + disclaimerLines.length * disclaimerLineHeight + footerPadding;
  canvas.height = headerHeight + bodyHeight + footerHeight;

  // Background
  ctx.fillStyle = "#0f1115";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Title
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#e8e9ec";
  ctx.font = "bold 52px -apple-system, sans-serif";
  ctx.fillText(`Set: ${setName}`, paddingX, 76);

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
    ctx.fillText("No tracks assigned yet in this Set.", paddingX, headerHeight + 48);
  } else {
    entries.forEach((entry, index) => {
      const baseline = headerHeight + (index + 1) * lineHeight - 24;
      ctx.fillStyle = "#4f8cff";
      ctx.font = "bold 38px -apple-system, sans-serif";
      ctx.fillText(`${index + 1}.`, paddingX, baseline);
      ctx.fillStyle = "#e8e9ec";
      ctx.font = "38px -apple-system, sans-serif";
      ctx.fillText(`${entry.name} — Bank ${entry.bankNumber} ${entry.letter}`, paddingX + 64, baseline);
    });
  }

  // Footer disclaimer
  ctx.fillStyle = "#9aa0ab";
  ctx.font = "24px -apple-system, sans-serif";
  let disclaimerY = headerHeight + bodyHeight + footerPadding + 20;
  for (const line of disclaimerLines) {
    ctx.fillText(line, paddingX, disclaimerY);
    disclaimerY += disclaimerLineHeight;
  }

  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

function wrapTextLines(ctx, text, maxWidth, font) {
  ctx.font = font;
  const words = text.split(" ");
  const lines = [];
  let line = "";
  for (const word of words) {
    const testLine = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(testLine).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = testLine;
    }
  }
  if (line) lines.push(line);
  return lines;
}

document.getElementById("btn-new-bank").addEventListener("click", async () => {
  if (!state.selectedSet) {
    // Real, pre-existing bug: this used to return here silently, with
    // no feedback at all -- looked exactly like a broken button. Only
    // reachable if no Set exists/is selected yet.
    alert("Create or select a Set first.");
    return;
  }
  const raw = prompt("New Bank number:");
  if (!raw) return;
  // Strip anything that isn't a digit before parsing -- real,
  // pre-existing bug found on real hardware: a stray non-digit
  // character from a mobile keyboard's autocomplete (e.g. an invisible
  // directional mark iOS sometimes inserts) makes parseInt() return
  // NaN, which JSON.stringify() then silently turns into `null`,
  // crashing the server with an unhandled 500 instead of a clear error.
  const number = parseInt(raw.replace(/[^0-9]/g, ""), 10);
  if (!Number.isInteger(number) || number < 1) {
    alert(`"${raw}" isn't a valid Bank number.`);
    return;
  }
  const newBankBtn = document.getElementById("btn-new-bank");
  flashSuccess(newBankBtn);
  try {
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
  node.querySelector(".bank-number-label").textContent = `Bank ${bankNumber}`;

  const deleteBankBtn = node.querySelector(".btn-delete-bank");
  deleteBankBtn.addEventListener("click", async () => {
    if (!confirm(`Delete Bank ${bankNumber}? This cannot be undone.`)) return;
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
    : "(empty)";

  const fileInput = node.querySelector(".track-file-input");
  const uploadBtn = node.querySelector(".btn-upload");
  const renameBtn = node.querySelector(".btn-rename");
  const deleteBtn = node.querySelector(".btn-delete");
  const songSelect = node.querySelector(".track-song-select");
  const assignBtn = node.querySelector(".btn-assign-from-library");
  const saveToLibraryBtn = node.querySelector(".btn-save-to-library");

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
    uploadBtn.textContent = "Uploading…";
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
      if (!res.ok) throw new Error(result.error || "Upload failed");
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
      alert(e.message);
    } finally {
      uploadBtn.textContent = "Upload new";
      uploadBtn.disabled = false;
    }
  });

  if (track) {
    renameBtn.hidden = false;
    deleteBtn.hidden = false;
    saveToLibraryBtn.hidden = false;

    renameBtn.addEventListener("click", async () => {
      const newName = prompt("New name:", track.display_name);
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
      if (!confirm(`Delete track ${letter}?`)) return;
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
        showToast("Song saved to the library.");
      } catch (e) {
        clearFlash(saveToLibraryBtn);
        alert(e.message);
      }
    });
  }

  return node;
}

// -- Reboot to apply (section 8: the pedal only reads the library at boot) --

document.getElementById("btn-reboot").addEventListener("click", async () => {
  if (!confirm("Reboot the Pi now to apply your changes? Playback will stop briefly.")) return;
  const errEl = document.getElementById("reboot-error");
  const okEl = document.getElementById("reboot-success");
  errEl.hidden = true;
  okEl.hidden = true;
  try {
    // Real bug found on real hardware: selecting a Set in the dropdown
    // only changed what this app was showing/editing -- it never told
    // the pedal which Set to actually play. Only *creating* a new Set
    // called /api/sets/active; switching between existing ones had no
    // way to become "the" active one at all. Applying changes is the
    // one moment this app already asks the user to confirm intent, so
    // that's also the right moment to commit to whichever Set is
    // currently selected as the one to boot into.
    if (state.selectedSet) {
      await apiFetch("/api/sets/active", { method: "POST", body: JSON.stringify({ name: state.selectedSet }) });
    }
    await apiFetch("/api/reboot", { method: "POST" });
    setText(okEl, "Rebooting now — this page will stop responding shortly.");
    okEl.hidden = false;
  } catch (e) {
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

boot();
