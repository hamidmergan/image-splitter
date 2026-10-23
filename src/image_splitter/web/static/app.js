"use strict";

// Editor page: shows each page with one frame per found item and lets the user
// move corners, move, draw, delete and rotate frames before downloading the parts.

const SVG_NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

const view = {
  files: [],
  fileId: null,
  page: 1,
  frames: [], // frames of the current page, edited locally and saved to the server
  selected: null, // index into view.frames
  thumbVersion: 0,
  drag: null,
  polling: null,
};

// ---------- helpers ----------

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* not JSON */ }
    throw new Error(message);
  }
  return response;
}

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

const currentFile = () => view.files.find((f) => f.id === view.fileId) || null;
const currentPage = () => {
  const file = currentFile();
  return file && file.state === "done" ? file.pages[view.page - 1] || null : null;
};
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ---------- state from the server ----------

async function refresh() {
  const state = await (await api("/api/state")).json();
  const before = currentFile();
  view.files = state.files;
  if (!currentFile()) {
    const first = view.files.find((f) => f.state === "done" && f.pages.length) || view.files[0];
    view.fileId = first ? first.id : null;
    view.page = 1;
  }
  const file = currentFile();
  // take the server's frames unless the user is in the middle of an edit
  const justFinished = file && file.state === "done" && (!before || before.id !== file.id || before.state !== "done");
  if (!view.drag && (justFinished || !before)) loadFrames();
  renderFiles();
  if (justFinished || !before) renderEditor();
  const busy = view.files.some((f) => f.state !== "done");
  if (busy && !view.polling) view.polling = setInterval(() => refresh().catch((e) => toast(e.message)), 700);
  if (!busy && view.polling) { clearInterval(view.polling); view.polling = null; }
}

function loadFrames() {
  const page = currentPage();
  view.frames = page ? page.frames.map((f) => ({ ...f, corners: f.corners.map((c) => [...c]) })) : [];
  if (view.selected !== null && view.selected >= view.frames.length) view.selected = null;
}

function select(fileId, page) {
  view.fileId = fileId;
  view.page = page;
  view.selected = null;
  loadFrames();
  renderFiles();
  renderEditor();
}

async function save() {
  const file = currentFile();
  if (!file) return;
  try {
    const response = await api(`/api/files/${file.id}/pages/${view.page}/frames`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames: view.frames }),
    });
    const entry = await response.json();
    view.files = view.files.map((f) => (f.id === entry.id ? entry : f));
    loadFrames();
  } catch (e) {
    toast(`Could not save: ${e.message}`);
    loadFrames();
  }
  view.thumbVersion += 1;
  renderFiles();
  renderEditor();
}

// ---------- file list ----------

function statusText(file) {
  if (file.state !== "done") return file.state === "running" ? "Finding items…" : "Waiting…";
  if (file.error) return file.error;
  const parts = file.pages.reduce((n, p) => n + p.frames.length, 0);
  const pages = file.pages.length > 1 ? `${file.pages.length} pages, ` : "";
  return `${pages}${parts} part${parts === 1 ? "" : "s"}`;
}

function renderFiles() {
  const list = $("file-list");
  list.replaceChildren();
  $("files-empty").hidden = view.files.length > 0;
  for (const file of view.files) {
    const li = document.createElement("li");
    li.className = "file" + (file.id === view.fileId ? " active" : "");
    li.tabIndex = 0;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = file.name;
    name.title = file.name;
    const status = document.createElement("span");
    status.className = "status" + (file.error ? " error" : file.state !== "done" ? " pending" : "");
    status.textContent = statusText(file);
    const remove = document.createElement("button");
    remove.className = "remove";
    remove.title = `Remove ${file.name}`;
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await api(`/api/files/${file.id}`, { method: "DELETE" });
        if (view.fileId === file.id) view.fileId = null;
        view.selected = null;
        await refresh();
        loadFrames();
        renderEditor();
      } catch (e) { toast(e.message); }
    });
    li.append(name, remove, status);
    if (file.state === "done" && file.pages.length > 1) {
      const pages = document.createElement("div");
      pages.className = "pages";
      file.pages.forEach((page, i) => {
        const button = document.createElement("button");
        button.textContent = `Page ${i + 1}`;
        if (file.id === view.fileId && view.page === i + 1) button.className = "active";
        button.addEventListener("click", (event) => { event.stopPropagation(); select(file.id, i + 1); });
        pages.append(button);
      });
      li.append(pages);
    }
    li.addEventListener("click", () => select(file.id, 1));
    li.addEventListener("keydown", (event) => { if (event.key === "Enter") select(file.id, 1); });
    list.append(li);
  }
}

// ---------- editor ----------

function renderEditor() {
  const file = currentFile();
  const page = currentPage();
  const svg = $("canvas");
  const ready = Boolean(page);
  svg.toggleAttribute("hidden", !ready); // SVG elements have no .hidden property
  $("placeholder").hidden = ready;
  $("placeholder-text").textContent = !file
    ? "Add images to start, or try the sample images. Each item gets a frame you can correct."
    : file.error ? `This file could not be read: ${file.error}` : "Finding items…";
  $("placeholder-samples").hidden = Boolean(file);
  $("page-title").textContent = file ? file.name + (file.pages.length > 1 ? ` · page ${view.page}` : "") : "No page selected";
  for (const id of ["add-button", "reset-button"]) $(id).disabled = !ready;
  for (const id of ["rotate-button", "delete-button"]) $(id).disabled = !ready || view.selected === null;
  $("download-button").disabled = !view.files.some((f) => f.state === "done" && f.pages.some((p) => p.frames.length));
  if (!ready) { renderParts(); return; }

  const src = `/api/files/${file.id}/pages/${view.page}.jpg`;
  if (svg.dataset.src !== src) {
    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${page.width} ${page.height}`);
    svg.append(svgEl("image", { href: src, x: 0, y: 0, width: page.width, height: page.height, class: "page-image" }));
    svg.append(svgEl("g", { class: "frames" }));
    svg.dataset.src = src;
  }
  drawFrames();
  renderParts();
}

function drawFrames() {
  const page = currentPage();
  const layer = $("canvas").querySelector(".frames");
  if (!page || !layer) return;
  const size = Math.max(page.width, page.height);
  const radius = size / 110;
  layer.replaceChildren();
  view.frames.forEach((frame, i) => {
    const group = svgEl("g", { class: "frame" + (i === view.selected ? " selected" : ""), "data-index": i });
    const points = frame.corners.map((c) => c.join(",")).join(" ");
    group.append(svgEl("polygon", { points, "data-index": i }));
    const cx = frame.corners.reduce((s, c) => s + c[0], 0) / 4;
    const cy = frame.corners.reduce((s, c) => s + c[1], 0) / 4;
    const label = svgEl("text", { x: cx, y: cy, "font-size": size / 26 });
    label.textContent = String(i + 1) + (frame.rotation ? ` ↻${frame.rotation}°` : "");
    group.append(label);
    frame.corners.forEach((c, k) => {
      group.append(svgEl("circle", {
        cx: c[0], cy: c[1], r: radius, class: k === 0 ? "first" : "", "data-index": i, "data-corner": k,
      }));
    });
    layer.append(group);
  });
  if (view.drag && view.drag.kind === "draw") {
    const [x0, y0] = view.drag.start;
    const [x1, y1] = view.drag.now;
    layer.append(svgEl("rect", {
      class: "draft", x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0),
    }));
  }
}

function renderParts() {
  const file = currentFile();
  const list = $("part-list");
  list.replaceChildren();
  const frames = currentPage() ? view.frames : [];
  $("parts-empty").hidden = frames.length > 0;
  $("part-count").textContent = frames.length ? `(${frames.length})` : "";
  frames.forEach((frame, i) => {
    const figure = document.createElement("figure");
    figure.className = "thumb" + (i === view.selected ? " selected" : "");
    figure.tabIndex = 0;
    const img = document.createElement("img");
    img.alt = `Part ${i + 1}`;
    img.loading = "lazy";
    img.src = `/api/files/${file.id}/pages/${view.page}/frames/${i + 1}.jpg?v=${view.thumbVersion}`;
    const caption = document.createElement("figcaption");
    caption.textContent = `${i + 1}` + (frame.rotation ? ` · turned ${frame.rotation}°` : "")
      + (frame.method === "manual" ? " · edited" : "");
    figure.append(img, caption);
    const pick = () => { view.selected = i; drawFrames(); renderEditor(); };
    figure.addEventListener("click", pick);
    figure.addEventListener("keydown", (event) => { if (event.key === "Enter") pick(); });
    list.append(figure);
  });
}

function pagePoint(event) {
  const svg = $("canvas");
  const page = currentPage();
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const p = point.matrixTransform(svg.getScreenCTM().inverse());
  return [clamp(p.x, 0, page.width), clamp(p.y, 0, page.height)];
}

function onPointerDown(event) {
  if (!currentPage() || event.button > 0) return;
  const target = event.target;
  const index = target.dataset.index !== undefined ? Number(target.dataset.index) : null;
  const point = pagePoint(event);
  if (target.dataset.corner !== undefined) {
    view.drag = { kind: "corner", index, corner: Number(target.dataset.corner), moved: false };
  } else if (index !== null) {
    view.drag = { kind: "move", index, last: point, moved: false };
  } else {
    view.drag = { kind: "draw", start: point, now: point, moved: false };
  }
  view.selected = index;
  $("canvas").setPointerCapture(event.pointerId);
  drawFrames();
  renderEditor();
  event.preventDefault();
}

function onPointerMove(event) {
  const drag = view.drag;
  if (!drag) return;
  const point = pagePoint(event);
  if (drag.kind === "corner") {
    view.frames[drag.index].corners[drag.corner] = point;
  } else if (drag.kind === "move") {
    const page = currentPage();
    const frame = view.frames[drag.index];
    let dx = point[0] - drag.last[0];
    let dy = point[1] - drag.last[1];
    // keep the whole frame on the page
    dx = clamp(dx, -Math.min(...frame.corners.map((c) => c[0])), page.width - Math.max(...frame.corners.map((c) => c[0])));
    dy = clamp(dy, -Math.min(...frame.corners.map((c) => c[1])), page.height - Math.max(...frame.corners.map((c) => c[1])));
    frame.corners = frame.corners.map(([x, y]) => [x + dx, y + dy]);
    drag.last = point;
  } else {
    drag.now = point;
  }
  drag.moved = true;
  drawFrames();
}

function onPointerUp() {
  const drag = view.drag;
  view.drag = null;
  if (!drag || !drag.moved) { drawFrames(); renderEditor(); return; }
  if (drag.kind === "draw") {
    const page = currentPage();
    const [x0, y0] = drag.start;
    const [x1, y1] = drag.now;
    const minimum = Math.min(page.width, page.height) / 40;
    if (Math.abs(x1 - x0) < minimum || Math.abs(y1 - y0) < minimum) { drawFrames(); return; }
    const [l, r, t, b] = [Math.min(x0, x1), Math.max(x0, x1), Math.min(y0, y1), Math.max(y0, y1)];
    view.frames.push({ corners: [[l, t], [r, t], [r, b], [l, b]], rotation: 0, method: "manual" });
    view.selected = view.frames.length - 1;
  } else {
    view.frames[drag.index].method = "manual";
  }
  save();
}

// ---------- actions ----------

function addFrame() {
  const page = currentPage();
  if (!page) return;
  const w = page.width * 0.3;
  const h = page.height * 0.3;
  const l = (page.width - w) / 2;
  const t = (page.height - h) / 2;
  view.frames.push({ corners: [[l, t], [l + w, t], [l + w, t + h], [l, t + h]], rotation: 0, method: "manual" });
  view.selected = view.frames.length - 1;
  save();
}

function rotateSelected() {
  if (view.selected === null) return;
  const frame = view.frames[view.selected];
  frame.rotation = (frame.rotation + 90) % 360;
  save();
}

function deleteSelected() {
  if (view.selected === null) return;
  view.frames.splice(view.selected, 1);
  view.selected = null;
  save();
}

async function resetPage() {
  const file = currentFile();
  if (!file) return;
  try {
    const entry = await (await api(`/api/files/${file.id}/pages/${view.page}/reset`, { method: "POST" })).json();
    view.files = view.files.map((f) => (f.id === entry.id ? entry : f));
    view.selected = null;
    view.thumbVersion += 1;
    loadFrames();
    renderFiles();
    renderEditor();
  } catch (e) { toast(e.message); }
}

async function upload(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  try {
    const result = await (await api("/api/files", { method: "POST", body: form })).json();
    if (!view.fileId && result.files.length) { view.fileId = result.files[0].id; view.page = 1; }
    await refresh();
  } catch (e) { toast(`Upload failed: ${e.message}`); }
}

async function loadSamples() {
  try {
    const result = await (await api("/api/samples", { method: "POST" })).json();
    if (result.files.length) { view.fileId = result.files[0].id; view.page = 1; view.selected = null; }
    await refresh();
    loadFrames();
    renderEditor();
  } catch (e) { toast(`Could not load the samples: ${e.message}`); }
}

async function download() {
  try {
    const response = await api(`/api/download?format=${encodeURIComponent($("format").value)}`);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "parts.zip";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (e) { toast(e.message); }
}

async function clearAll() {
  if (!view.files.length || !confirm("Remove all files and frames?")) return;
  try {
    await api("/api/files", { method: "DELETE" });
    view.fileId = null;
    view.selected = null;
    await refresh();
    loadFrames();
    renderEditor();
  } catch (e) { toast(e.message); }
}

// ---------- wiring ----------

function init() {
  const svg = $("canvas");
  svg.addEventListener("pointerdown", onPointerDown);
  svg.addEventListener("pointermove", onPointerMove);
  svg.addEventListener("pointerup", onPointerUp);
  svg.addEventListener("pointercancel", onPointerUp);

  $("file-input").addEventListener("change", (event) => { upload(event.target.files); event.target.value = ""; });
  $("add-button").addEventListener("click", addFrame);
  $("rotate-button").addEventListener("click", rotateSelected);
  $("delete-button").addEventListener("click", deleteSelected);
  $("reset-button").addEventListener("click", resetPage);
  $("download-button").addEventListener("click", download);
  $("samples-button").addEventListener("click", loadSamples);
  $("placeholder-samples").addEventListener("click", loadSamples);
  $("clear-button").addEventListener("click", clearAll);

  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input, select, textarea") || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === "Delete" || event.key === "Backspace") { deleteSelected(); event.preventDefault(); }
    else if (event.key === "r" || event.key === "R") rotateSelected();
    else if (event.key === "Escape") { view.selected = null; drawFrames(); renderEditor(); }
  });

  let depth = 0;
  document.addEventListener("dragenter", (event) => {
    if (![...event.dataTransfer.types].includes("Files")) return;
    depth += 1;
    document.body.classList.add("dragging");
  });
  document.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (!depth) document.body.classList.remove("dragging");
  });
  document.addEventListener("dragover", (event) => event.preventDefault());
  document.addEventListener("drop", (event) => {
    event.preventDefault();
    depth = 0;
    document.body.classList.remove("dragging");
    upload(event.dataTransfer.files);
  });

  refresh().then(renderEditor).catch((e) => toast(e.message));
}

init();
