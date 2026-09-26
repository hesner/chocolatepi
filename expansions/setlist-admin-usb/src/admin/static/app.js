// setlist-admin frontend. Vanilla JS, no build step, no framework --
// SETLIST_ADMIN_USB_SPECIFICATION.md section 3. Talks to the JSON API in
// server.py/api.py; the session cookie is HttpOnly, so this code never
// touches the token directly, just relies on the browser sending it.

const state = {
  shows: [],
  activeShow: null,
  selectedShow: null,
  songs: [], // the shared library (_Songs/) -- reusable across every Show/Set
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

  // Try loading shows -- if the session cookie is missing/expired this
  // 401s, which means "show the login screen", not an error to surface.
  try {
    await loadSongs();
    await loadShows();
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
    await loadShows();
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

// -- Song library (reusable across every Show/Set) ---------------------------

async function loadSongs() {
  const data = await apiFetch("/api/songs");
  state.songs = data.songs;

  const countEl = document.getElementById("song-library-count");
  countEl.textContent = state.songs.length ? `(${state.songs.length})` : "(empty)";

  const container = document.getElementById("songs-container");
  container.innerHTML = "";
  if (state.songs.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No songs yet -- upload one here, or upload directly into a Set slot below.";
    container.appendChild(p);
  }
  for (const song of state.songs) {
    container.appendChild(renderSongRow(song));
  }

  // Every track row's "choose from library" dropdown needs to reflect
  // the current song list too.
  document.querySelectorAll(".track-song-select").forEach(populateSongSelect);
}

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

  node.querySelector(".btn-rename-song").addEventListener("click", async () => {
    const newName = prompt("New name:", song.display_name);
    if (!newName) return;
    await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}`, {
      method: "PUT", body: JSON.stringify({ display_name: newName }),
    });
    await loadSongs();
  });

  node.querySelector(".btn-delete-song").addEventListener("click", async () => {
    if (!confirm(
      `⚠ Delete "${song.filename}" from the song library?\n\n` +
      `If you're not sure, don't delete it. Once deleted, this song can ` +
      `no longer be chosen when building a Set -- it won't show up in ` +
      `the picker for any future show.\n\n` +
      `This will NOT remove it from any Set it's already assigned to -- ` +
      `those keep playing normally, since that's an independent copy, ` +
      `made when it was assigned.`
    )) return;
    await apiFetch(`/api/songs/${encodeURIComponent(song.filename)}`, { method: "DELETE" });
    await loadSongs();
  });

  return node;
}

document.getElementById("btn-upload-to-library").addEventListener("click", () => {
  document.getElementById("library-upload-input").click();
});

document.getElementById("library-upload-input").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const dotIndex = file.name.lastIndexOf(".");
  const displayName = dotIndex > 0 ? file.name.slice(0, dotIndex) : file.name;
  const extension = dotIndex > 0 ? file.name.slice(dotIndex + 1) : "";
  try {
    const res = await fetch("/api/songs", {
      method: "POST",
      headers: { "X-Track-Name": displayName, "X-Track-Extension": extension },
      body: file,
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || "Upload failed");
    if (result.warning) alert(result.warning);
    await loadSongs();
  } catch (e) {
    alert(e.message);
  } finally {
    ev.target.value = "";
  }
});

// -- Shows / Sets / Tracks ---------------------------------------------------

async function loadShows() {
  const data = await apiFetch("/api/shows");
  state.shows = data.shows;
  state.activeShow = data.active;
  state.selectedShow = state.selectedShow || data.active || data.shows[0] || null;

  const select = document.getElementById("show-select");
  select.innerHTML = "";
  for (const name of data.shows) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name === data.active ? `${name} (active)` : name;
    select.appendChild(opt);
  }
  if (state.selectedShow) select.value = state.selectedShow;

  if (state.selectedShow) await loadSets(state.selectedShow);
}

document.getElementById("show-select").addEventListener("change", async (ev) => {
  state.selectedShow = ev.target.value;
  await loadSets(state.selectedShow);
});

document.getElementById("btn-new-show").addEventListener("click", async () => {
  const name = prompt("New show name:");
  if (!name) return;
  await apiFetch("/api/shows", { method: "POST", body: JSON.stringify({ name }) });
  await apiFetch("/api/shows/active", { method: "POST", body: JSON.stringify({ name }) });
  state.selectedShow = name;
  await loadShows();
});

document.getElementById("btn-new-set").addEventListener("click", async () => {
  if (!state.selectedShow) {
    // Real, pre-existing bug: this used to return here silently, with
    // no feedback at all -- looked exactly like a broken button. Only
    // reachable if no show exists/is selected yet.
    alert("Create or select a show first.");
    return;
  }
  const raw = prompt("New Set number:");
  if (!raw) return;
  // Strip anything that isn't a digit before parsing -- real,
  // pre-existing bug found on real hardware: a stray non-digit
  // character from a mobile keyboard's autocomplete (e.g. an invisible
  // directional mark iOS sometimes inserts) makes parseInt() return
  // NaN, which JSON.stringify() then silently turns into `null`,
  // crashing the server with an unhandled 500 instead of a clear error.
  const number = parseInt(raw.replace(/[^0-9]/g, ""), 10);
  if (!Number.isInteger(number) || number < 1) {
    alert(`"${raw}" isn't a valid Set number.`);
    return;
  }
  await apiFetch(`/api/shows/${encodeURIComponent(state.selectedShow)}/sets`, {
    method: "POST", body: JSON.stringify({ number }),
  });
  await loadSets(state.selectedShow);
});

async function loadSets(showName) {
  const data = await apiFetch(`/api/shows/${encodeURIComponent(showName)}/sets`);
  const container = document.getElementById("sets-container");
  container.innerHTML = "";
  for (const setNumber of data.sets) {
    container.appendChild(await renderSetCard(showName, setNumber));
  }
}

async function renderSetCard(showName, setNumber) {
  const tpl = document.getElementById("tpl-set");
  const node = tpl.content.cloneNode(true);
  const card = node.querySelector(".set-card");
  node.querySelector(".set-number-label").textContent = `Set ${setNumber}`;

  node.querySelector(".btn-delete-set").addEventListener("click", async () => {
    if (!confirm(`Delete Set ${setNumber}? This cannot be undone.`)) return;
    await apiFetch(`/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}`, { method: "DELETE" });
    await loadSets(showName);
  });

  const tracksData = await apiFetch(`/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks`);
  const tracksEl = node.querySelector(".tracks");
  for (const letter of Object.keys(tracksData).sort()) {
    tracksEl.appendChild(renderTrackRow(showName, setNumber, letter, tracksData[letter]));
  }

  return card;
}

function renderTrackRow(showName, setNumber, letter, track) {
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
    await apiFetch(
      `/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks/${letter}/assign-from-library`,
      { method: "POST", body: JSON.stringify({ song_filename: songFilename }) },
    );
    await loadSets(showName);
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
    try {
      const res = await fetch(
        `/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks/${letter}`,
        {
          method: "POST",
          headers: { "X-Track-Name": displayName, "X-Track-Extension": extension },
          body: file,
        },
      );
      const result = await res.json();
      if (result.warning) {
        // Codec warning (section 9): the upload still succeeded, this
        // is advisory, not blocking -- alert() is blunt but this is a
        // rare path and doesn't warrant its own UI component.
        alert(result.warning);
      }
      await loadSongs(); // the upload also added it to the library
      await loadSets(showName);
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
      await apiFetch(
        `/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks/${letter}`,
        { method: "PUT", body: JSON.stringify({ display_name: newName }) },
      );
      await loadSets(showName);
    });

    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`Delete track ${letter}?`)) return;
      await apiFetch(
        `/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks/${letter}`,
        { method: "DELETE" },
      );
      await loadSets(showName);
    });

    saveToLibraryBtn.addEventListener("click", async () => {
      try {
        await apiFetch(
          `/api/shows/${encodeURIComponent(showName)}/sets/${setNumber}/tracks/${letter}/save-to-library`,
          { method: "POST" },
        );
        await loadSongs();
      } catch (e) {
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
    await apiFetch("/api/reboot", { method: "POST" });
    setText(okEl, "Rebooting now — this page will stop responding shortly.");
    okEl.hidden = false;
  } catch (e) {
    setText(errEl, e.message);
    errEl.hidden = false;
  }
});

boot();
