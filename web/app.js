const COLORS = ["red", "blue", "green", "yellow", "white", "black", "brown", "unknown"];
const PALETTE = {
  red: "#ff5555", blue: "#3d7bff", green: "#38ce77", yellow: "#ffd23f",
  white: "#f4f7f8", black: "#30383d", brown: "#a96f42", unknown: "#87959b",
};
const DEFAULTS = {
  linePosition: 55, motionThreshold: 32, minArea: 1800, maxDistance: 105,
  direction: "any", roiPreset: "full", saveSnapshots: true,
  ranges: {
    red: { hMin: 170, hMax: 10, sMin: 80, sMax: 255, vMin: 45, vMax: 255 },
    blue: { hMin: 95, hMax: 135, sMin: 70, sMax: 255, vMin: 40, vMax: 255 },
    green: { hMin: 35, hMax: 90, sMin: 55, sMax: 255, vMin: 35, vMax: 255 },
    yellow: { hMin: 18, hMax: 35, sMin: 80, sMax: 255, vMin: 80, vMax: 255 },
    white: { hMin: 0, hMax: 179, sMin: 0, sMax: 65, vMin: 170, vMax: 255 },
    black: { hMin: 0, hMax: 179, sMin: 0, sMax: 255, vMin: 0, vMax: 55 },
    brown: { hMin: 5, hMax: 22, sMin: 60, sMax: 255, vMin: 25, vMax: 190 },
  },
};
const ROI_PRESETS = {
  full: { x: 0.03, y: 0.04, w: 0.94, h: 0.92 },
  center: { x: 0.10, y: 0.10, w: 0.80, h: 0.80 },
  conveyor: { x: 0.03, y: 0.22, w: 0.94, h: 0.62 },
};
const $ = (selector) => document.querySelector(selector);
const video = $("#sourceVideo");
const canvas = $("#visionCanvas");
const context = canvas.getContext("2d", { willReadFrequently: true });
const colorGrid = $("#colorGrid");
const statusElement = $("#systemStatus");

let settings = loadSettings();
let stream = null;
let sourceUrl = null;
let running = false;
let animationId = 0;
let videoFrameHandle = 0;
let lastProcessTime = 0;
let lastMediaTime = -1;
let lastImageData = null;
let background = null;
let warmupFrames = 0;
let gridWidth = 0;
let gridHeight = 0;
let tracks = new Map();
let nextTrackId = 1;
let sessionId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
let latestFps = 0;
let lastFpsTick = performance.now();
let sourceName = "No source";
let toastTimer = 0;
let databasePromise;
const diagnostics = { frames: 0, maxDetections: 0, maxVisibleTracks: 0, crossings: 0, lastDetections: 0 };
window.boxCounterDiagnostics = diagnostics;

for (const color of COLORS) {
  colorGrid.insertAdjacentHTML("beforeend", `<div class="color-row"><span><i style="background:${PALETTE[color]}"></i>${color}</span><strong id="count-${color}">0</strong></div>`);
}

function loadSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem("smart-box-counter-settings-v1") || "null");
    return stored ? { ...structuredClone(DEFAULTS), ...stored, ranges: { ...structuredClone(DEFAULTS.ranges), ...(stored.ranges || {}) } } : structuredClone(DEFAULTS);
  } catch { return structuredClone(DEFAULTS); }
}

function saveSettings() { localStorage.setItem("smart-box-counter-settings-v1", JSON.stringify(settings)); }
function setStatus(text, state = "idle") { statusElement.dataset.state = state; statusElement.querySelector("span").textContent = text; }
function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message; toast.classList.add("show"); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function openDatabase() {
  if (databasePromise) return databasePromise;
  databasePromise = new Promise((resolve, reject) => {
    const request = indexedDB.open("smart-box-counter", 1);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore("events", { keyPath: "id", autoIncrement: true });
      store.createIndex("timestamp", "timestamp");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return databasePromise;
}

async function getEvents() {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = database.transaction("events", "readonly").objectStore("events").getAll();
    request.onsuccess = () => resolve(request.result.sort((a, b) => b.timestamp.localeCompare(a.timestamp)));
    request.onerror = () => reject(request.error);
  });
}

async function addEvent(event) {
  const database = await openDatabase();
  await new Promise((resolve, reject) => {
    const request = database.transaction("events", "readwrite").objectStore("events").add(event);
    request.onsuccess = resolve; request.onerror = () => reject(request.error);
  });
}

async function deleteEvents() {
  const database = await openDatabase();
  await new Promise((resolve, reject) => {
    const request = database.transaction("events", "readwrite").objectStore("events").clear();
    request.onsuccess = resolve; request.onerror = () => reject(request.error);
  });
}

async function refreshEvents() {
  const events = await getEvents();
  const counts = Object.fromEntries(COLORS.map((color) => [color, 0]));
  for (const event of events) counts[event.color] = (counts[event.color] || 0) + 1;
  $("#totalCount").textContent = String(events.length);
  for (const color of COLORS) $(`#count-${color}`).textContent = String(counts[color] || 0);
  const rows = $("#eventRows");
  if (!events.length) { rows.innerHTML = '<tr class="empty-row"><td colspan="6">No crossings recorded yet.</td></tr>'; return; }
  rows.innerHTML = events.slice(0, 150).map((event) => {
    const time = new Date(event.timestamp).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
    const snapshot = event.snapshot ? `<a class="snapshot-link" href="${event.snapshot}" download="track-${event.trackId}-${event.color}.jpg">Download</a>` : "—";
    return `<tr><td>${escapeHtml(time)}</td><td>#${event.trackId}</td><td><span class="color-chip"><i style="background:${PALETTE[event.color] || PALETTE.unknown}"></i>${escapeHtml(event.color)}</span></td><td>${Math.round(event.confidence * 100)}%</td><td>${escapeHtml(event.source)}</td><td>${snapshot}</td></tr>`;
  }).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function configureCanvas() {
  const sourceWidth = video.videoWidth || 960;
  const sourceHeight = video.videoHeight || 540;
  const width = Math.min(960, sourceWidth);
  canvas.width = width; canvas.height = Math.max(240, Math.round(width * sourceHeight / sourceWidth));
  relearnBackground();
}

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) { showToast("This browser does not support webcam access. Try current Chrome, Edge, or Safari."); return; }
  stopSource();
  try {
    setStatus("Requesting camera", "idle");
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" }, audio: false });
    video.srcObject = stream; sourceName = stream.getVideoTracks()[0]?.label || "Webcam";
    await video.play(); configureCanvas(); beginProcessing();
  } catch (error) {
    console.error(error); setStatus("Camera unavailable", "error");
    showToast(error.name === "NotAllowedError" ? "Camera permission was denied. Allow it in browser settings and try again." : "The camera could not be opened. Close other camera apps and try again.");
  }
}

async function openVideo(file) {
  if (!file) return;
  stopSource(); sourceUrl = URL.createObjectURL(file); video.srcObject = null; video.src = sourceUrl; sourceName = file.name;
  try {
    await waitForVideoReady();
    configureCanvas();
    await analyzeUploadedVideo();
  }
  catch (error) { console.error(error); setStatus("Video error", "error"); showToast("This video could not be opened by the browser."); }
}

function waitForVideoReady() {
  if (video.readyState >= 2 && Number.isFinite(video.duration)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const ready = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(video.error || new Error("Video load failed")); };
    const cleanup = () => { video.removeEventListener("loadeddata", ready); video.removeEventListener("error", failed); };
    video.addEventListener("loadeddata", ready, { once: true });
    video.addEventListener("error", failed, { once: true });
    video.load();
  });
}

function seekVideo(time) {
  if (Math.abs(video.currentTime - time) < 0.001 && video.readyState >= 2) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const done = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(video.error || new Error("Video seek failed")); };
    const cleanup = () => { video.removeEventListener("seeked", done); video.removeEventListener("error", failed); };
    video.addEventListener("seeked", done, { once: true });
    video.addEventListener("error", failed, { once: true });
    video.currentTime = Math.min(time, Math.max(0, video.duration - 0.001));
  });
}

async function analyzeUploadedVideo() {
  Object.assign(diagnostics, { frames: 0, maxDetections: 0, maxVisibleTracks: 0, crossings: 0, lastDetections: 0 });
  running = true; $("#emptyCamera").hidden = true; $("#stopSource").disabled = false; $("#startCamera").disabled = true;
  $("#sourceLabel").textContent = sourceName; setStatus("Analyzing 0%", "live");
  lastFpsTick = performance.now();
  const sampleRate = 15;
  const frameTotal = Math.max(1, Math.ceil(video.duration * sampleRate));
  for (let frameIndex = 0; frameIndex < frameTotal && running; frameIndex += 1) {
    await seekVideo(frameIndex / sampleRate);
    processFrame(performance.now());
    if (frameIndex % 4 === 0) {
      setStatus(`Analyzing ${Math.round((frameIndex + 1) / frameTotal * 100)}%`, "live");
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }
  if (running) finishUploadedVideo();
}

function finishUploadedVideo() {
  running = false; $("#warmup").hidden = true; $("#stopSource").disabled = true; $("#startCamera").disabled = false;
  setStatus("Analysis complete", "idle"); $("#fpsLabel").textContent = "Complete";
  video.pause(); video.removeAttribute("src"); video.load();
  if (sourceUrl) URL.revokeObjectURL(sourceUrl); sourceUrl = null;
  showToast(`Video complete · ${diagnostics.crossings} crossing${diagnostics.crossings === 1 ? "" : "s"} detected.`);
}

function beginProcessing() {
  Object.assign(diagnostics, { frames: 0, maxDetections: 0, maxVisibleTracks: 0, crossings: 0, lastDetections: 0 });
  running = true; $("#emptyCamera").hidden = true; $("#stopSource").disabled = false; $("#startCamera").disabled = true;
  $("#sourceLabel").textContent = sourceName; setStatus("Running", "live"); lastProcessTime = 0; lastFpsTick = performance.now();
  lastMediaTime = -1;
  if (video.requestVideoFrameCallback) videoFrameHandle = video.requestVideoFrameCallback(processVideoFrame);
  else animationId = requestAnimationFrame(processLoop);
}

function stopSource(showMessage = false) {
  running = false; cancelAnimationFrame(animationId);
  if (video.cancelVideoFrameCallback && videoFrameHandle) video.cancelVideoFrameCallback(videoFrameHandle);
  if (stream) { for (const track of stream.getTracks()) track.stop(); stream = null; }
  video.pause(); video.srcObject = null; video.removeAttribute("src"); video.load();
  if (sourceUrl) URL.revokeObjectURL(sourceUrl); sourceUrl = null;
  $("#emptyCamera").hidden = false; $("#warmup").hidden = true; $("#stopSource").disabled = true; $("#startCamera").disabled = false;
  $("#sourceLabel").textContent = "No source"; $("#fpsLabel").textContent = "0.0 FPS"; setStatus("Ready", "idle");
  if (showMessage) showToast("Source stopped. Saved counts remain available below.");
}

function relearnBackground() {
  background = null; warmupFrames = 0; tracks = new Map(); nextTrackId = 1; $("#warmup").hidden = !running;
  if (running) showToast("Background reset. Keep the scene empty for one second.");
}

function processLoop(timestamp) {
  if (!running) return;
  animationId = requestAnimationFrame(processLoop);
  if (video.readyState < 2 || timestamp - lastProcessTime < 66) return;
  lastProcessTime = timestamp; processFrame(timestamp);
}

function processVideoFrame(timestamp, metadata) {
  if (!running) return;
  videoFrameHandle = video.requestVideoFrameCallback(processVideoFrame);
  if (lastMediaTime >= 0 && metadata.mediaTime - lastMediaTime < 1 / 15) return;
  lastMediaTime = metadata.mediaTime;
  processFrame(timestamp);
}

function processFrame(timestamp) {
  const width = canvas.width, height = canvas.height;
  context.drawImage(video, 0, 0, width, height); lastImageData = context.getImageData(0, 0, width, height);
  const detections = detectMotion(lastImageData); const visibleTracks = updateTracks(detections); const roi = getRoi(width, height);
  diagnostics.frames += 1; diagnostics.lastDetections = detections.length;
  diagnostics.maxDetections = Math.max(diagnostics.maxDetections, detections.length);
  diagnostics.maxVisibleTracks = Math.max(diagnostics.maxVisibleTracks, visibleTracks.length);
  $("#sourceLabel").dataset.diagnostics = JSON.stringify(diagnostics);
  const lineY = Math.round(roi.y + roi.h * settings.linePosition / 100);
  for (const track of visibleTracks) {
    track.colorVotes.push(classifyColor(lastImageData, track.bbox));
    if (track.colorVotes.length > 12) track.colorVotes.shift();
    updateCrossing(track, lineY);
  }
  drawOverlay(visibleTracks, roi, lineY);
  const elapsed = Math.max(1, timestamp - lastFpsTick), instantFps = 1000 / elapsed;
  latestFps = latestFps ? latestFps * 0.88 + instantFps * 0.12 : instantFps; lastFpsTick = timestamp;
  $("#fpsLabel").textContent = `${latestFps.toFixed(1)} FPS`;
}

function getRoi(width, height) {
  const preset = ROI_PRESETS[settings.roiPreset] || ROI_PRESETS.full;
  return { x: Math.round(width * preset.x), y: Math.round(height * preset.y), w: Math.round(width * preset.w), h: Math.round(height * preset.h) };
}

function detectMotion(imageData) {
  const { width, height, data } = imageData;
  const sampleStep = width > 720 ? 5 : 4;
  const nextGridWidth = Math.ceil(width / sampleStep), nextGridHeight = Math.ceil(height / sampleStep), total = nextGridWidth * nextGridHeight;
  if (!background || gridWidth !== nextGridWidth || gridHeight !== nextGridHeight) {
    gridWidth = nextGridWidth; gridHeight = nextGridHeight; background = new Float32Array(total); warmupFrames = 0;
  }
  const mask = new Uint8Array(total), roi = getRoi(width, height), threshold = settings.motionThreshold;
  for (let gy = 0; gy < gridHeight; gy += 1) {
    const y = Math.min(height - 1, gy * sampleStep + Math.floor(sampleStep / 2));
    for (let gx = 0; gx < gridWidth; gx += 1) {
      const x = Math.min(width - 1, gx * sampleStep + Math.floor(sampleStep / 2));
      const index = gy * gridWidth + gx, pixelIndex = (y * width + x) * 4;
      const gray = data[pixelIndex] * 0.114 + data[pixelIndex + 1] * 0.587 + data[pixelIndex + 2] * 0.299;
      if (warmupFrames === 0) background[index] = gray;
      const inside = x >= roi.x && x <= roi.x + roi.w && y >= roi.y && y <= roi.y + roi.h;
      const difference = Math.abs(gray - background[index]);
      const foreground = warmupFrames >= 12 && inside && difference >= threshold;
      mask[index] = foreground ? 1 : 0;
      const alpha = warmupFrames < 12 ? 0.22 : foreground ? 0.001 : 0.025;
      background[index] += (gray - background[index]) * alpha;
    }
  }
  warmupFrames += 1; $("#warmup").hidden = warmupFrames >= 12;
  if (warmupFrames < 12) return [];
  const closed = erode(dilate(mask, gridWidth, gridHeight), gridWidth, gridHeight);
  return connectedComponents(dilate(closed, gridWidth, gridHeight), gridWidth, gridHeight, sampleStep, width, height);
}

function dilate(mask, width, height) {
  const result = new Uint8Array(mask.length);
  for (let y = 1; y < height - 1; y += 1) for (let x = 1; x < width - 1; x += 1) {
    let value = 0;
    for (let dy = -1; dy <= 1 && !value; dy += 1) for (let dx = -1; dx <= 1; dx += 1) if (mask[(y + dy) * width + x + dx]) { value = 1; break; }
    result[y * width + x] = value;
  }
  return result;
}

function erode(mask, width, height) {
  const result = new Uint8Array(mask.length);
  for (let y = 1; y < height - 1; y += 1) for (let x = 1; x < width - 1; x += 1) {
    let value = 1;
    for (let dy = -1; dy <= 1 && value; dy += 1) for (let dx = -1; dx <= 1; dx += 1) if (!mask[(y + dy) * width + x + dx]) { value = 0; break; }
    result[y * width + x] = value;
  }
  return result;
}

function connectedComponents(mask, width, height, step, frameWidth, frameHeight) {
  const visited = new Uint8Array(mask.length), detections = [], minimumCells = settings.minArea / (step * step), queue = new Int32Array(mask.length);
  for (let index = 0; index < mask.length; index += 1) {
    if (!mask[index] || visited[index]) continue;
    let head = 0, tail = 0, count = 0, minX = width, maxX = 0, minY = height, maxY = 0;
    queue[tail++] = index; visited[index] = 1;
    while (head < tail) {
      const current = queue[head++], x = current % width, y = Math.floor(current / width);
      count += 1; minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      for (const neighbor of [current - 1, current + 1, current - width, current + width]) {
        if (neighbor < 0 || neighbor >= mask.length || visited[neighbor] || !mask[neighbor]) continue;
        if (Math.abs(neighbor % width - x) > 1) continue;
        visited[neighbor] = 1; queue[tail++] = neighbor;
      }
    }
    if (count < minimumCells) continue;
    const boxWidth = (maxX - minX + 1) * step, boxHeight = (maxY - minY + 1) * step, area = count * step * step;
    const rectangularity = area / Math.max(1, boxWidth * boxHeight), aspect = boxWidth / Math.max(1, boxHeight);
    if (boxWidth < 28 || boxHeight < 28 || rectangularity < 0.28 || aspect < 0.2 || aspect > 5) continue;
    detections.push({
      bbox: { x: minX * step, y: minY * step, w: Math.min(boxWidth, frameWidth - minX * step), h: Math.min(boxHeight, frameHeight - minY * step) },
      confidence: Math.min(1, 0.45 + rectangularity * 0.4 + Math.min(0.15, area / Math.max(settings.minArea, 1) * 0.05)),
    });
  }
  return detections;
}

function centroid(bbox) { return { x: bbox.x + bbox.w / 2, y: bbox.y + bbox.h / 2 }; }
function distance(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

function updateTracks(detections) {
  for (const track of tracks.values()) track.missed += 1;
  const candidates = [];
  for (const track of tracks.values()) detections.forEach((detection, detectionIndex) => {
    const gap = distance(track.center, centroid(detection.bbox));
    if (gap <= settings.maxDistance) candidates.push({ gap, track, detectionIndex });
  });
  candidates.sort((a, b) => a.gap - b.gap);
  const assignedTracks = new Set(), assignedDetections = new Set(), visible = [];
  for (const candidate of candidates) {
    if (assignedTracks.has(candidate.track.id) || assignedDetections.has(candidate.detectionIndex)) continue;
    applyDetection(candidate.track, detections[candidate.detectionIndex]); assignedTracks.add(candidate.track.id); assignedDetections.add(candidate.detectionIndex); visible.push(candidate.track);
  }
  detections.forEach((detection, index) => {
    if (assignedDetections.has(index)) return;
    const center = centroid(detection.bbox);
    const track = { id: nextTrackId++, bbox: detection.bbox, center, previousCenter: null, age: 1, missed: 0, totalMovement: 0, counted: false, stableSide: 0, colorVotes: [], confidence: detection.confidence };
    tracks.set(track.id, track); visible.push(track);
  });
  for (const [id, track] of tracks) if (track.missed > 12) tracks.delete(id);
  return visible;
}

function applyDetection(track, detection) {
  const newCenter = centroid(detection.bbox);
  track.previousCenter = track.center; track.totalMovement += distance(track.center, newCenter); track.center = newCenter;
  track.bbox = detection.bbox; track.confidence = detection.confidence; track.age += 1; track.missed = 0;
}

function rgbToHsv(red, green, blue) {
  const r = red / 255, g = green / 255, b = blue / 255, maximum = Math.max(r, g, b), minimum = Math.min(r, g, b), delta = maximum - minimum;
  let hue = 0;
  if (delta) {
    if (maximum === r) hue = ((g - b) / delta) % 6; else if (maximum === g) hue = (b - r) / delta + 2; else hue = (r - g) / delta + 4;
    hue = ((hue * 30) + 180) % 180;
  }
  return { h: Math.round(hue), s: Math.round(maximum ? delta / maximum * 255 : 0), v: Math.round(maximum * 255) };
}

function hsvMatches(hsv, range) {
  const hueMatches = range.hMin <= range.hMax ? hsv.h >= range.hMin && hsv.h <= range.hMax : hsv.h >= range.hMin || hsv.h <= range.hMax;
  return hueMatches && hsv.s >= range.sMin && hsv.s <= range.sMax && hsv.v >= range.vMin && hsv.v <= range.vMax;
}

function classifyColor(imageData, bbox) {
  const { width, height, data } = imageData, insetX = Math.round(bbox.w * 0.16), insetY = Math.round(bbox.h * 0.16);
  const startX = Math.max(0, Math.round(bbox.x + insetX)), endX = Math.min(width, Math.round(bbox.x + bbox.w - insetX));
  const startY = Math.max(0, Math.round(bbox.y + insetY)), endY = Math.min(height, Math.round(bbox.y + bbox.h - insetY));
  if (endX <= startX || endY <= startY) return { color: "unknown", confidence: 0 };
  const scores = Object.fromEntries(COLORS.slice(0, -1).map((color) => [color, 0]));
  let samples = 0;
  const sampleStep = Math.max(2, Math.floor(Math.min(bbox.w, bbox.h) / 28));
  for (let y = startY; y < endY; y += sampleStep) for (let x = startX; x < endX; x += sampleStep) {
    const index = (y * width + x) * 4, hsv = rgbToHsv(data[index], data[index + 1], data[index + 2]);
    for (const color of COLORS.slice(0, -1)) if (hsvMatches(hsv, settings.ranges[color])) scores[color] += 1;
    samples += 1;
  }
  const [color, count] = Object.entries(scores).sort((a, b) => b[1] - a[1])[0], confidence = count / Math.max(1, samples);
  return confidence >= 0.08 ? { color, confidence } : { color: "unknown", confidence };
}

function bestColor(track) {
  if (!track.colorVotes.length) return { color: "unknown", confidence: 0 };
  const grouped = {};
  for (const vote of track.colorVotes) { grouped[vote.color] ||= []; grouped[vote.color].push(vote.confidence); }
  const color = Object.keys(grouped).sort((a, b) => grouped[b].length - grouped[a].length || grouped[b].reduce((x, y) => x + y, 0) - grouped[a].reduce((x, y) => x + y, 0))[0];
  return { color, confidence: grouped[color].reduce((a, b) => a + b, 0) / grouped[color].length };
}

function updateCrossing(track, lineY) {
  const hysteresis = Math.max(4, canvas.height * 0.008), offset = track.center.y - lineY;
  const side = offset < -hysteresis ? -1 : offset > hysteresis ? 1 : 0;
  if (side && track.stableSide && side !== track.stableSide && !track.counted) {
    const movingDown = track.stableSide === -1 && side === 1;
    const directionAllowed = settings.direction === "any" || (settings.direction === "down" && movingDown) || (settings.direction === "up" && !movingDown);
    const frameMovement = track.previousCenter ? Math.abs(track.center.y - track.previousCenter.y) : 0;
    if (directionAllowed && track.age >= 3 && track.totalMovement >= 15 && frameMovement >= 2) { track.counted = true; diagnostics.crossings += 1; void recordCrossing(track); }
  }
  if (side) track.stableSide = side;
}

async function recordCrossing(track) {
  const result = bestColor(track);
  const event = { sessionId, timestamp: new Date().toISOString(), trackId: track.id, color: result.color, confidence: Math.max(0, Math.min(1, result.confidence * track.confidence)), source: sourceName, snapshot: settings.saveSnapshots ? makeSnapshot(track.bbox) : null };
  try { await addEvent(event); await refreshEvents(); showToast(`Counted track #${track.id} · ${result.color}`); }
  catch (error) { console.error(error); track.counted = false; showToast("The count could not be saved. Browser storage may be unavailable."); }
}

function makeSnapshot(bbox) {
  const x = Math.max(0, Math.floor(bbox.x)), y = Math.max(0, Math.floor(bbox.y));
  const width = Math.min(canvas.width - x, Math.ceil(bbox.w)), height = Math.min(canvas.height - y, Math.ceil(bbox.h));
  if (width <= 0 || height <= 0 || !lastImageData) return null;
  const snapshotCanvas = document.createElement("canvas"); snapshotCanvas.width = width; snapshotCanvas.height = height;
  snapshotCanvas.getContext("2d").putImageData(context.getImageData(x, y, width, height), 0, 0);
  return snapshotCanvas.toDataURL("image/jpeg", 0.82);
}

function drawOverlay(visibleTracks, roi, lineY) {
  context.save(); context.lineWidth = Math.max(1, canvas.width / 600); context.strokeStyle = "rgba(160, 190, 198, .62)"; context.setLineDash([8, 7]);
  context.strokeRect(roi.x, roi.y, roi.w, roi.h); context.setLineDash([]); context.strokeStyle = "#ffb224"; context.lineWidth = Math.max(3, canvas.width / 260);
  context.beginPath(); context.moveTo(roi.x, lineY); context.lineTo(roi.x + roi.w, lineY); context.stroke();
  context.font = `700 ${Math.max(12, canvas.width / 60)}px ui-monospace, monospace`; context.fillStyle = "#ffca5a"; context.fillText("COUNT LINE", roi.x + 10, Math.max(20, lineY - 9));
  for (const track of visibleTracks) {
    const result = bestColor(track), { x, y, w, h } = track.bbox;
    context.strokeStyle = PALETTE[result.color] || PALETTE.unknown; context.lineWidth = Math.max(2, canvas.width / 400); context.strokeRect(x, y, w, h);
    const label = `ID ${track.id} · ${result.color.toUpperCase()} ${Math.round(result.confidence * 100)}%`;
    context.font = `700 ${Math.max(12, canvas.width / 60)}px ui-monospace, monospace`;
    const labelWidth = context.measureText(label).width + 14; context.fillStyle = "rgba(3, 10, 14, .82)"; context.fillRect(x, Math.max(0, y - 25), labelWidth, 24);
    context.fillStyle = PALETTE[result.color] || PALETTE.unknown; context.fillText(label, x + 7, Math.max(17, y - 8));
  }
  context.restore();
}

function bindSettings() {
  const controls = {
    linePosition: ["#linePosition", "#lineValue", (value) => `${value}%`],
    motionThreshold: ["#motionThreshold", "#thresholdValue", (value) => value],
    minArea: ["#minArea", "#areaValue", (value) => `${value} px²`],
  };
  for (const [key, [inputSelector, outputSelector, format]] of Object.entries(controls)) {
    const input = $(inputSelector), output = $(outputSelector); input.value = settings[key]; output.textContent = format(settings[key]);
    input.addEventListener("input", () => { settings[key] = Number(input.value); output.textContent = format(input.value); saveSettings(); });
  }
  bindSettingsFromState();
  $("#direction").addEventListener("change", (event) => { settings.direction = event.target.value; saveSettings(); });
  $("#roiPreset").addEventListener("change", (event) => { settings.roiPreset = event.target.value; saveSettings(); relearnBackground(); });
  $("#saveSnapshots").addEventListener("change", (event) => { settings.saveSnapshots = event.target.checked; saveSettings(); });
  $("#colorSelect").addEventListener("change", renderHsvFields); renderHsvFields();
}

function renderHsvFields() {
  const color = $("#colorSelect").value, range = settings.ranges[color];
  const fields = [["hMin", "H min", 0, 179], ["hMax", "H max", 0, 179], ["sMin", "S min", 0, 255], ["sMax", "S max", 0, 255], ["vMin", "V min", 0, 255], ["vMax", "V max", 0, 255]];
  $("#hsvFields").innerHTML = fields.map(([key, label, min, max]) => `<label class="hsv-field">${label}<input type="number" data-hsv-key="${key}" min="${min}" max="${max}" value="${range[key]}" /></label>`).join("");
  for (const input of document.querySelectorAll("[data-hsv-key]")) input.addEventListener("change", () => {
    const key = input.dataset.hsvKey, maximum = key.startsWith("h") ? 179 : 255;
    settings.ranges[color][key] = Math.max(0, Math.min(maximum, Number(input.value))); input.value = settings.ranges[color][key]; saveSettings();
  });
}

function exportCsv(events) {
  const escapeCsv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [["timestamp", "session_id", "track_id", "color", "confidence", "source"]];
  for (const event of [...events].reverse()) rows.push([event.timestamp, event.sessionId, event.trackId, event.color, event.confidence.toFixed(4), event.source]);
  const url = URL.createObjectURL(new Blob([rows.map((row) => row.map(escapeCsv).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `box-counts-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function registerWebMcpTools() {
  const modelContext = document.modelContext;
  if (!modelContext?.registerTool) return;
  const controller = new AbortController();
  const register = (tool) => Promise.resolve(modelContext.registerTool(tool, { signal: controller.signal })).catch(console.error);
  void register({
    name: "read_counter_status", title: "Read counter status", description: "Read the current Smart Box Counter totals, source status, and per-color counts without changing the app.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true, untrustedContentHint: false },
    async execute() { const events = await getEvents(); return { running, source: sourceName, total: events.length, counts: Object.fromEntries(COLORS.map((color) => [color, events.filter((event) => event.color === color).length])) }; },
  });
  void register({
    name: "configure_counter", title: "Configure counter", description: "Set the line position, motion threshold, minimum box area, or crossing direction and update the visible controls.",
    inputSchema: { type: "object", properties: { linePosition: { type: "number", minimum: 15, maximum: 85 }, motionThreshold: { type: "number", minimum: 10, maximum: 90 }, minArea: { type: "number", minimum: 300, maximum: 12000 }, direction: { type: "string", enum: ["any", "down", "up"] } }, additionalProperties: false },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    async execute(input) {
      if (!input || typeof input !== "object" || !Object.keys(input).length) throw new Error("Provide at least one setting.");
      for (const [key, value] of Object.entries(input)) { if (!(key in settings)) throw new Error(`Unsupported setting: ${key}`); settings[key] = value; }
      saveSettings(); bindSettingsFromState();
      return { linePosition: settings.linePosition, motionThreshold: settings.motionThreshold, minArea: settings.minArea, direction: settings.direction };
    },
  });
}

function bindSettingsFromState() {
  $("#linePosition").value = settings.linePosition; $("#lineValue").textContent = `${settings.linePosition}%`;
  $("#motionThreshold").value = settings.motionThreshold; $("#thresholdValue").textContent = settings.motionThreshold;
  $("#minArea").value = settings.minArea; $("#areaValue").textContent = `${settings.minArea} px²`;
  $("#direction").value = settings.direction; $("#roiPreset").value = settings.roiPreset; $("#saveSnapshots").checked = settings.saveSnapshots;
}

$("#startCamera").addEventListener("click", startCamera);
$("#videoFile").addEventListener("change", (event) => { void openVideo(event.target.files?.[0]); event.target.value = ""; });
$("#stopSource").addEventListener("click", () => stopSource(true));
video.addEventListener("ended", () => { if (stream) stopSource(false); });
$("#settingsToggle").addEventListener("click", (event) => {
  const button = event.currentTarget, expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded)); $("#settingsBody").hidden = expanded;
});
$("#resetBackground").addEventListener("click", relearnBackground);
$("#resetSettings").addEventListener("click", () => { settings = structuredClone(DEFAULTS); saveSettings(); bindSettingsFromState(); renderHsvFields(); relearnBackground(); showToast("Default settings restored."); });
$("#exportCsv").addEventListener("click", async () => { const events = await getEvents(); exportCsv(events); showToast(`Exported ${events.length} event${events.length === 1 ? "" : "s"}.`); });
$("#clearEvents").addEventListener("click", async () => { if (!confirm("Clear every locally stored count and snapshot?")) return; await deleteEvents(); await refreshEvents(); showToast("Local event log cleared."); });
canvas.addEventListener("click", (event) => {
  if (!lastImageData) return;
  const rect = canvas.getBoundingClientRect(), x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width))), y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  const index = (y * canvas.width + x) * 4, hsv = rgbToHsv(lastImageData.data[index], lastImageData.data[index + 1], lastImageData.data[index + 2]);
  $("#pixelHsv").textContent = `H ${hsv.h} · S ${hsv.s} · V ${hsv.v}`;
});
window.addEventListener("beforeunload", () => stopSource(false));

bindSettings();
void refreshEvents().catch((error) => { console.error(error); showToast("Local storage is unavailable in this browser mode."); });
registerWebMcpTools();
