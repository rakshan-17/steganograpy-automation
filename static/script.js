/**
 * script.js
 * StegoCrypt — Frontend controller
 *
 * Handles:
 *   - Tab switching
 *   - Drag-and-drop / click file uploads
 *   - Live capacity calculation
 *   - Encode text / file  (POST to Flask API)
 *   - Decode text / file  (POST to Flask API)
 *   - Password show/hide toggle
 *   - Toast notifications
 */

"use strict";

/* ════════════════════════════════════════════════════════════
   Utility helpers
════════════════════════════════════════════════════════════ */

/** Format bytes to human-readable string */
function humanBytes(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

/** Show a transient toast message */
let _toastTimer = null;
function toast(msg, duration = 3000) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  // Force reflow to restart transition
  el.offsetHeight;
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.classList.add("hidden"), 300);
  }, duration);
}

/** Build a stat badge HTML fragment */
function badge(label, value) {
  return `<span class="stat-badge">${label}: <strong>${value}</strong></span>`;
}

/** Set a button into loading / ready state */
function setLoading(btn, loading) {
  const text    = btn.querySelector(".btn-text");
  const spinner = btn.querySelector(".spinner");
  btn.disabled  = loading;
  text.classList.toggle("hidden", loading);
  spinner.classList.toggle("hidden", !loading);
}

/** Show a result box */
function showResult(boxId, type, html) {
  const box = document.getElementById(boxId);
  box.className = `result-box ${type}`;
  box.innerHTML = html;
  box.classList.remove("hidden");
}

/** Hide a result box */
function hideResult(boxId) {
  const box = document.getElementById(boxId);
  box.classList.add("hidden");
  box.innerHTML = "";
}

/* ════════════════════════════════════════════════════════════
   Tab switching
════════════════════════════════════════════════════════════ */

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;

    document.querySelectorAll(".tab").forEach(t => {
      t.classList.toggle("active", t === btn);
      t.setAttribute("aria-selected", t === btn ? "true" : "false");
    });

    document.querySelectorAll(".panel").forEach(p => {
      p.classList.toggle("active", p.id === `panel-${target}`);
      p.classList.toggle("hidden", p.id !== `panel-${target}`);
    });
  });
});

/* ════════════════════════════════════════════════════════════
   Password show / hide toggle
════════════════════════════════════════════════════════════ */

document.querySelectorAll(".eye-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.target);
    if (!input) return;
    const isText = input.type === "text";
    input.type    = isText ? "password" : "text";
    btn.textContent = isText ? "👁" : "🙈";
  });
});

/* ════════════════════════════════════════════════════════════
   Dropzone helper factory
   Wires up click-to-browse + drag-and-drop for a dropzone.
════════════════════════════════════════════════════════════ */

function makeDropzone(zoneId, inputId, onFile) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  // Click anywhere on the zone to open file picker
  zone.addEventListener("click", () => input.click());

  // File picker change
  input.addEventListener("change", () => {
    if (input.files.length) onFile(input.files[0]);
  });

  // Drag events
  zone.addEventListener("dragover", e => {
    e.preventDefault();
    zone.classList.add("drag-over");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });
}

/* ════════════════════════════════════════════════════════════
   Capacity display
════════════════════════════════════════════════════════════ */

/** Fetch capacity for a given image File object */
async function fetchCapacity(imageFile) {
  const fd = new FormData();
  fd.append("image", imageFile);

  try {
    const resp = await fetch("/api/capacity", { method: "POST", body: fd });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error);
    return data;
  } catch (err) {
    console.warn("Capacity fetch failed:", err.message);
    return null;
  }
}

/** Update the capacity bar UI */
function updateCapacityBar(cap, usedBytes = 0) {
  const box   = document.getElementById("encode-capacity");
  const total = document.getElementById("cap-total");
  const fill  = document.getElementById("cap-bar-fill");
  const used  = document.getElementById("cap-used");
  const free  = document.getElementById("cap-free");
  const dims  = document.getElementById("cap-dims");

  if (!cap) { box.classList.add("hidden"); return; }

  const pct = Math.min(100, (usedBytes / cap.capacity_bytes) * 100);

  total.textContent = cap.capacity_human;
  fill.style.width  = `${pct.toFixed(1)}%`;
  fill.style.background = pct > 85
    ? "linear-gradient(90deg, #f87171, #fb923c)"
    : "linear-gradient(90deg, #2dd4bf, #a78bfa)";
  used.textContent  = humanBytes(usedBytes);
  free.textContent  = humanBytes(Math.max(0, cap.capacity_bytes - usedBytes));
  dims.textContent  = `${cap.image_width} × ${cap.image_height} px · ${cap.pixels.toLocaleString()} pixels`;

  box.classList.remove("hidden");
}

/* ════════════════════════════════════════════════════════════
   ENCODE — state
════════════════════════════════════════════════════════════ */

let encodeImageFile = null;   // selected carrier image
let encodeHideFile  = null;   // selected file to hide
let encodeMode      = "text"; // "text" | "file"
let encodeCap       = null;   // capacity info from API

/** Re-evaluate whether the Encode button should be enabled */
function refreshEncodeBtn() {
  const btn = document.getElementById("encode-btn");
  const hasImage = !!encodeImageFile;
  const hasPayload = encodeMode === "text"
    ? document.getElementById("encode-message").value.trim().length > 0
    : !!encodeHideFile;
  btn.disabled = !(hasImage && hasPayload);
}

/* ─── Encode image dropzone ─── */
makeDropzone("encode-drop", "encode-image", async file => {
  encodeImageFile = file;

  // Show preview
  const preview = document.getElementById("encode-preview");
  const body    = document.getElementById("encode-drop-body");
  const reader  = new FileReader();
  reader.onload = e => {
    preview.src = e.target.result;
    preview.classList.remove("hidden");
    body.classList.add("hidden");
  };
  reader.readAsDataURL(file);

  // Fetch capacity
  encodeCap = await fetchCapacity(file);
  updateCapacityBar(encodeCap);

  hideResult("encode-result");
  refreshEncodeBtn();
});

/* ─── Mode switch (text / file) ─── */
document.getElementById("mode-text-btn").addEventListener("click", () => {
  encodeMode = "text";
  document.getElementById("mode-text-btn").classList.add("active");
  document.getElementById("mode-file-btn").classList.remove("active");
  document.getElementById("text-mode").classList.remove("hidden");
  document.getElementById("file-mode").classList.add("hidden");
  refreshEncodeBtn();
});

document.getElementById("mode-file-btn").addEventListener("click", () => {
  encodeMode = "file";
  document.getElementById("mode-file-btn").classList.add("active");
  document.getElementById("mode-text-btn").classList.remove("active");
  document.getElementById("file-mode").classList.remove("hidden");
  document.getElementById("text-mode").classList.add("hidden");
  refreshEncodeBtn();
});

/* ─── Live char count & capacity bar update ─── */
document.getElementById("encode-message").addEventListener("input", function () {
  document.getElementById("char-count").textContent =
    this.value.length.toLocaleString();

  if (encodeCap) {
    const bytes = new TextEncoder().encode(this.value).length;
    updateCapacityBar(encodeCap, bytes);
  }

  refreshEncodeBtn();
});

/* ─── Hidden file dropzone ─── */
makeDropzone("file-drop", "encode-file", file => {
  encodeHideFile = file;

  const chip = document.getElementById("file-selected");
  const body = document.getElementById("file-drop-body");
  chip.innerHTML = `📄 <span>${file.name}</span> — <em>${humanBytes(file.size)}</em>`;
  chip.classList.remove("hidden");
  body.classList.add("hidden");

  if (encodeCap) updateCapacityBar(encodeCap, file.size);

  refreshEncodeBtn();
});

/* ─── Encode button click ─── */
document.getElementById("encode-btn").addEventListener("click", async () => {
  if (!encodeImageFile) return toast("Please upload a carrier image first.");

  const btn      = document.getElementById("encode-btn");
  const password = document.getElementById("encode-password").value.trim();

  setLoading(btn, true);
  hideResult("encode-result");

  try {
    const fd = new FormData();
    fd.append("image",    encodeImageFile);
    fd.append("password", password);

    let endpoint;

    if (encodeMode === "text") {
      const message = document.getElementById("encode-message").value.trim();
      if (!message) { toast("Message is empty."); return; }
      fd.append("message", message);
      endpoint = "/api/encode/text";
    } else {
      if (!encodeHideFile) { toast("Please select a file to hide."); return; }
      fd.append("file", encodeHideFile);
      endpoint = "/api/encode/file";
    }

    const resp = await fetch(endpoint, { method: "POST", body: fd });
    const data = await resp.json();

    if (!data.success) throw new Error(data.error);

    // Update capacity bar
    if (encodeCap) updateCapacityBar(encodeCap, data.payload_bytes);

    showResult("encode-result", "success", `
      <div class="result-title">✅ Encoding Successful</div>
      <div class="result-stats">
        ${badge("Payload", data.payload_human)}
        ${badge("Capacity", data.capacity_human)}
        ${badge("Remaining", data.remaining_human)}
        ${data.encrypted ? badge("🔒 Encrypted", "AES-256") : ""}
      </div>
      <a class="download-btn" href="${data.download_url}" download>
        ⬇️ Download Stego Image
      </a>
    `);

    toast("Encoding complete!");

  } catch (err) {
    showResult("encode-result", "error", `
      <div class="result-title">❌ Encoding Failed</div>
      <div>${err.message}</div>
    `);
  } finally {
    setLoading(btn, false);
  }
});

/* ════════════════════════════════════════════════════════════
   DECODE — state
════════════════════════════════════════════════════════════ */

let decodeImageFile = null;

function refreshDecodeBtn() {
  document.getElementById("decode-btn").disabled = !decodeImageFile;
}

/* ─── Decode image dropzone ─── */
makeDropzone("decode-drop", "decode-image", file => {
  decodeImageFile = file;

  const preview = document.getElementById("decode-preview");
  const body    = document.getElementById("decode-drop-body");
  const reader  = new FileReader();
  reader.onload = e => {
    preview.src = e.target.result;
    preview.classList.remove("hidden");
    body.classList.add("hidden");
  };
  reader.readAsDataURL(file);

  hideResult("decode-result");
  refreshDecodeBtn();
});

/* ─── Decode button click ─── */
document.getElementById("decode-btn").addEventListener("click", async () => {
  if (!decodeImageFile) return toast("Please upload a stego image first.");

  const btn      = document.getElementById("decode-btn");
  const password = document.getElementById("decode-password").value.trim();
  const type     = document.querySelector('input[name="decode-type"]:checked').value;

  setLoading(btn, true);
  hideResult("decode-result");

  try {
    const fd = new FormData();
    fd.append("image",    decodeImageFile);
    fd.append("password", password);

    const endpoint = type === "text" ? "/api/decode/text" : "/api/decode/file";
    const resp     = await fetch(endpoint, { method: "POST", body: fd });
    const data     = await resp.json();

    if (!data.success) throw new Error(data.error);

    if (type === "text") {
      showResult("decode-result", "success", `
        <div class="result-title">✅ Message Extracted</div>
        <div class="result-stats">
          ${badge("Length", `${data.message_length.toLocaleString()} chars`)}
          ${data.encrypted ? badge("🔒", "AES-256 decrypted") : ""}
        </div>
        <div class="result-msg">${escapeHtml(data.message)}</div>
      `);
    } else {
      showResult("decode-result", "success", `
        <div class="result-title">✅ File Extracted</div>
        <div class="result-stats">
          ${badge("Filename", data.filename)}
          ${badge("Size", data.file_size_human)}
          ${data.encrypted ? badge("🔒", "AES-256 decrypted") : ""}
        </div>
        <a class="download-btn" href="${data.download_url}" download="${data.filename}">
          ⬇️ Download ${escapeHtml(data.filename)}
        </a>
      `);
    }

    toast("Decoding complete!");

  } catch (err) {
    showResult("decode-result", "error", `
      <div class="result-title">❌ Decoding Failed</div>
      <div>${err.message}</div>
    `);
  } finally {
    setLoading(btn, false);
  }
});

/* ════════════════════════════════════════════════════════════
   Safety: escape HTML before inserting user content
════════════════════════════════════════════════════════════ */

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* ════════════════════════════════════════════════════════════
   Misc init
════════════════════════════════════════════════════════════ */

document.getElementById("year").textContent = new Date().getFullYear();
