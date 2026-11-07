const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  file: null,
  originalUrl: null,
  result: null,
  originalBlob: null,
  watermarkedBlob: null,
  selectedBlock: { x: 0, y: 0 },
  telemetry: null,
  resultMode: "checkerboard",
  showResidual: false,
  animationTimer: null,
  step: 0,
  resultUrls: [],
};

const coords = [[2, 3], [3, 2], [4, 1], [1, 4]];
const grid = $("#transform-matrix");
const pixelGrid = $("#pixel-grid");

function setStatus(element, message, kind = "") {
  element.textContent = message;
  element.className = `form-status ${kind}`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2300);
}

function selectedMode() {
  return $('input[name="mode"]:checked').value;
}

function imageDataFrom(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      resolve({ url, imageData: context.getImageData(0, 0, canvas.width, canvas.height) });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read this image."));
    };
    image.src = url;
  });
}

function setCover(file) {
  if (!file || !/^image\/(png|jpeg)$/.test(file.type)) {
    showToast("Choose a PNG or JPEG image.");
    return;
  }
  state.file = file;
  state.result = null;
  clearResultUrls();
  $("#results").classList.add("hidden");
  if (state.originalUrl) URL.revokeObjectURL(state.originalUrl);
  imageDataFrom(file).then(({ url, imageData }) => {
    state.originalUrl = url;
    const { width, height, data } = imageData;
    const blockCols = Math.floor(width / 8);
    const blockRows = Math.floor(height / 8);
    let eligible = blockCols * blockRows;
    if (file.type === "image/png") {
      eligible = 0;
      for (let by = 0; by < blockRows; by++) {
        for (let bx = 0; bx < blockCols; bx++) {
          let opaque = true;
          for (let y = by * 8; y < by * 8 + 8 && opaque; y++) {
            for (let x = bx * 8; x < bx * 8 + 8; x++) {
              if (data[(y * width + x) * 4 + 3] !== 255) {
                opaque = false;
                break;
              }
            }
          }
          if (opaque) eligible++;
        }
      }
    }
    $("#cover-preview").src = url;
    $("#cover-name").textContent = file.name;
    $("#cover-size").textContent = `${width} × ${height} PX`;
    $("#cover-blocks").textContent = `${eligible.toLocaleString()} · ${blockRows} × ${blockCols}`;
    $("#cover-capacity").textContent = `${(eligible * 4).toLocaleString()} BITS`;
    $("#dropzone").classList.add("hidden");
    $("#cover-info").classList.remove("hidden");
  }).catch((error) => showToast(error.message));
}

function b64Blob(encoded, type = "image/png") {
  const raw = atob(encoded);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return new Blob([bytes], { type });
}

function b64Url(encoded) {
  const url = URL.createObjectURL(b64Blob(encoded));
  state.resultUrls.push(url);
  return url;
}

function clearResultUrls() {
  state.resultUrls.forEach((url) => URL.revokeObjectURL(url));
  state.resultUrls = [];
}

async function apiError(response) {
  let detail = `Request failed (${response.status}).`;
  try {
    const body = await response.json();
    if (body.detail) detail = body.detail;
  } catch { /* use the status fallback */ }
  throw new Error(detail);
}

$("#image-file").addEventListener("change", (event) => setCover(event.target.files[0]));
$("#remove-image").addEventListener("click", () => {
  state.file = null;
  if (state.originalUrl) URL.revokeObjectURL(state.originalUrl);
  clearResultUrls();
  clearResultUrls();
  state.originalUrl = null;
  $("#image-file").value = "";
  $("#cover-info").classList.add("hidden");
  $("#dropzone").classList.remove("hidden");
  $("#results").classList.add("hidden");
  state.result = null;
});

const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.add("drag-over");
}));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.remove("drag-over");
}));
dropzone.addEventListener("drop", (event) => setCover(event.dataTransfer.files[0]));

$("#alpha").addEventListener("input", (event) => {
  $("#alpha-value").value = event.target.value;
  $("#alpha-value").textContent = event.target.value;
});
$("#toggle-password").addEventListener("click", () => {
  const input = $("#password");
  input.type = input.type === "password" ? "text" : "password";
  $("#toggle-password").textContent = input.type === "password" ? "SHOW" : "HIDE";
});

$("#embed-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.file) {
    setStatus($("#embed-status"), "Choose a cover image first.", "error");
    return;
  }
  const button = $("#embed-button");
  button.disabled = true;
  button.querySelector("span").textContent = "Encrypting & embedding…";
  setStatus($("#embed-status"), "AES-GCM encryption and block transforms are running locally.");
  const form = new FormData();
  state.resultMode = selectedMode();
  form.append("image", state.file);
  form.append("owner", $("#owner").value);
  form.append("password", $("#password").value);
  form.append("mode", state.resultMode);
  form.append("alpha", $("#alpha").value);
  try {
    const response = await fetch("/api/embed", { method: "POST", body: form });
    if (!response.ok) await apiError(response);
    state.result = await response.json();
    state.originalBlob = b64Blob(state.result.original_png);
    state.watermarkedBlob = b64Blob(state.result.watermarked_png);
    displayResult();
    setStatus($("#embed-status"), "Watermark embedded. PNG verification is ready.", "success");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
    const sample = state.result.telemetry;
    state.selectedBlock = { x: sample.block_x, y: sample.block_y };
    state.telemetry = sample;
    renderTelemetry(sample);
  } catch (error) {
    setStatus($("#embed-status"), error.message, "error");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Encrypt & Embed Watermark";
  }
});

function displayResult() {
  clearResultUrls();
  const result = state.result;
  $("#results").classList.remove("hidden");
  $("#original-result").src = b64Url(result.original_png);
  $("#watermarked-result").src = b64Url(result.watermarked_png);
  $("#spectrum-result").src = b64Url(result.spectrum_png);
  $("#metric-psnr").textContent = Number(result.psnr).toFixed(2);
  $("#metric-ssim").textContent = Number(result.ssim).toFixed(5);
  $("#metric-payload").textContent = Number(result.used_bits).toLocaleString();
  $("#salt-value").textContent = result.crypto.salt_hex;
  $("#nonce-value").textContent = result.crypto.nonce_hex;
  $("#result-file").textContent = `${state.file.name} · AES-GCM AUTHENTICATED`;
  const dimensions = $("#cover-size").textContent;
  $("#original-dimensions").textContent = dimensions;
  const download = $("#download-link");
  if (download.dataset.url) URL.revokeObjectURL(download.dataset.url);
  download.dataset.url = URL.createObjectURL(state.watermarkedBlob);
  download.href = download.dataset.url;
}

$("#toggle-diff").addEventListener("click", () => {
  if (!state.result) return;
  state.showResidual = !state.showResidual;
  $("#watermarked-result").src = state.showResidual
    ? b64Url(state.result.residual_diff_map)
    : b64Url(state.result.watermarked_png);
  $("#second-image-label").textContent = state.showResidual ? "02 / RESIDUAL × 20" : "02 / WATERMARKED";
  $("#toggle-diff").textContent = state.showResidual ? "VIEW WATERMARK" : "VIEW RESIDUAL";
});

function gridMatrix(matrix, { qim = false, coefficients = false, spatial = false, wave = false } = {}) {
  grid.innerHTML = "";
  const flat = matrix.flat();
  const max = Math.max(1, ...flat.map((value) => Math.abs(value)));
  matrix.forEach((row, y) => row.forEach((value, x) => {
    const cell = document.createElement("div");
    const isQim = coords.some(([qy, qx]) => qy === y && qx === x);
    cell.className = "matrix-cell";
    if (wave) {
      cell.classList.add("wave-cell");
      cell.style.animationDelay = `${(y * 8 + x) * 7}ms`;
    }
    if (qim && isQim) cell.classList.add("qim-cell");
    if (spatial && y === 0 && x === 0) cell.classList.add("dc-cell");
    if (coefficients || qim) {
      const intensity = Math.min(1, Math.abs(value) / max);
      const isDst = state.resultMode === "hybrid"
        || (state.selectedBlock.x + state.selectedBlock.y) % 2 === 1;
      const rgb = isDst ? [5, 150, 105] : [37, 99, 235];
      cell.style.background = `rgba(${rgb.join(",")},${0.06 + intensity * 0.72})`;
      if (intensity > 0.42) cell.style.color = "#fff";
      if (qim && isQim) cell.style.outline = "1px solid #059669";
    } else {
      const level = Math.max(0, Math.min(255, Math.round(value)));
      cell.style.background = `rgb(${level},${level},${level})`;
      if (level < 105) cell.style.color = "#fff";
    }
    cell.textContent = Number(value).toFixed(coefficients || qim ? 0 : 0);
    cell.title = `row ${y}, col ${x}: ${Number(value).toFixed(3)}${isQim ? " · QIM coordinate" : ""}`;
    if (y === 0 && x === 0 && spatial) cell.classList.add("dc-cell");
    if (y >= 6 && x >= 6) cell.classList.add("high-cell");
    grid.appendChild(cell);
  }));
}

function renderTelemetry(data) {
  state.telemetry = data;
  $("#transform-name").textContent = data.transform.toUpperCase();
  $("#block-position").textContent = `${data.block_x}, ${data.block_y} / 8 × 8`;
  updateBasisWaves(data);
  renderStep(state.step);
  renderPixels(data);
}

function updateBasisWaves(data) {
  const hybrid = state.resultMode === "hybrid";
  const checkerboardDst = !hybrid && (data.block_x + data.block_y) % 2 === 1;
  const checkerboardType = checkerboardDst ? "DST-II" : "DCT-II";
  const rowType = hybrid ? "DCT-II" : checkerboardType;
  const columnType = hybrid ? "DST-II" : checkerboardType;
  $("#row-basis-label").textContent = `ROW BASIS · ${rowType}${hybrid ? " · COSINE ROWS" : ""}`;
  $("#column-basis-label").textContent = `COLUMN BASIS · ${columnType}${hybrid ? " · SINE COLUMNS" : ""}`;
  const pathFor = (type) => {
    const points = Array.from({ length: 8 }, (_, sample) => {
      const angle = Math.PI * (sample + 0.5) / 8;
      const amplitude = type === "DCT-II" ? Math.cos(angle) : Math.sin(angle);
      return `${sample === 0 ? "M" : "L"}${sample * (144 / 7)},${22 - amplitude * 17}`;
    });
    return points.join(" ");
  };
  $("#row-basis-wave").setAttribute("d", pathFor(rowType));
  $("#column-basis-wave").setAttribute("d", pathFor(columnType));
}

function renderStep(step) {
  state.step = step;
  $$(".process-step").forEach((button) => button.classList.toggle("active", Number(button.dataset.step) === step));
  if (!state.telemetry) {
    $("#matrix-caption").textContent = "SPATIAL LUMINANCE · 8 × 8";
    return;
  }
  const telemetry = state.telemetry;
  const modeName = telemetry.transform;
  const frames = [
    ["SPATIAL LUMINANCE · 8 × 8", telemetry.spatial_y, { spatial: true }],
    [`${modeName.toUpperCase()} COEFFICIENT RESPONSE`, telemetry.coefficients, { coefficients: true, wave: true }],
    ["QIM MID-BAND PROJECTION · GREEN CELLS", telemetry.modified_qim, { coefficients: true, qim: true, wave: true }],
    ["INVERSE TRANSFORM · RECONSTRUCTED Y", telemetry.reconstructed_y, { spatial: true, wave: true }],
  ];
  $("#matrix-caption").textContent = frames[step][0];
  $("#basis-strip").classList.toggle("is-animating", step === 1 || step === 3);
  gridMatrix(frames[step][1], frames[step][2]);
}

$$(".process-step").forEach((button) => button.addEventListener("click", () => {
  if (state.animationTimer) {
    clearInterval(state.animationTimer);
    state.animationTimer = null;
    $("#play-animation").textContent = "▶";
  }
  renderStep(Number(button.dataset.step));
}));

$("#play-animation").addEventListener("click", () => {
  if (!state.telemetry) {
    showToast("Embed an image to animate its transform.");
    return;
  }
  if (state.animationTimer) {
    clearInterval(state.animationTimer);
    state.animationTimer = null;
    $("#play-animation").textContent = "▶";
    return;
  }
  $("#play-animation").textContent = "Ⅱ";
  renderStep(0);
  state.animationTimer = setInterval(() => {
    const next = (state.step + 1) % 4;
    renderStep(next);
    if (next === 0) {
      clearInterval(state.animationTimer);
      state.animationTimer = null;
      $("#play-animation").textContent = "▶";
    }
  }, 850);
});

function renderPixels(data) {
  pixelGrid.innerHTML = "";
  data.original_ycrcb.forEach((row, y) => row.forEach((ycrcb, x) => {
    const originalRgb = data.original_rgb[y][x];
    const changedRgb = data.watermarked_rgb[y][x];
    const changedYcrcb = data.watermarked_ycrcb[y][x];
    const beforeY = ycrcb[0];
    const afterY = changedYcrcb[0];
    const cell = document.createElement("div");
    cell.className = "matrix-cell";
    cell.style.background = `linear-gradient(90deg,${`rgb(${originalRgb.join(",")})`} 0 48%,${`rgb(${changedRgb.join(",")})`} 52% 100%)`;
    cell.innerHTML = `<span>${Math.round(beforeY)}<br>${Math.round(afterY)}</span>`;
    cell.title = `pixel ${data.block_x * 8 + x}, ${data.block_y * 8 + y}\nRGB before: ${originalRgb.join(", ")}\nRGB after: ${changedRgb.join(", ")}\nYCrCb before: ${ycrcb.map((v) => v.toFixed(2)).join(", ")}\nYCrCb after: ${changedYcrcb.map((v) => v.toFixed(2)).join(", ")}`;
    pixelGrid.appendChild(cell);
  }));
}

function selectBlockFromClick(event) {
  if (!state.result) return;
  const button = event.currentTarget;
  const image = button.querySelector("img");
  const rect = image.getBoundingClientRect();
  const scaleX = image.naturalWidth / rect.width;
  const scaleY = image.naturalHeight / rect.height;
  const x = Math.max(0, Math.min(image.naturalWidth - 1, Math.floor((event.clientX - rect.left) * scaleX)));
  const y = Math.max(0, Math.min(image.naturalHeight - 1, Math.floor((event.clientY - rect.top) * scaleY)));
  inspectBlock(Math.floor(x / 8), Math.floor(y / 8));
}

async function inspectBlock(blockX, blockY) {
  if (!state.result) return;
  const form = new FormData();
  form.append("original", state.originalBlob, "original.png");
  form.append("watermarked", state.watermarkedBlob, "watermarked.png");
  form.append("block_x", blockX);
  form.append("block_y", blockY);
  form.append("mode", state.resultMode);
  try {
    const response = await fetch("/api/inspect", { method: "POST", body: form });
    if (!response.ok) await apiError(response);
    state.selectedBlock = { x: blockX, y: blockY };
    renderTelemetry(await response.json());
    $("#viz-subtitle").textContent = "Selected 8 × 8 transform block · click another image region";
  } catch (error) {
    showToast(error.message);
  }
}

$$(".image-view").forEach((button) => button.addEventListener("click", selectBlockFromClick));

$("#verify-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#verify-image").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("image", file);
  form.append("password", $("#verify-password").value);
  form.append("mode", selectedMode());
  form.append("alpha", $("#alpha").value);
  setStatus($("#verify-status"), "Checking authenticated payload…");
  try {
    const response = await fetch("/api/verify", { method: "POST", body: form });
    if (!response.ok) await apiError(response);
    const data = await response.json();
    setStatus($("#verify-status"), `Authenticated owner: ${data.owner}`, "success");
  } catch (error) {
    setStatus($("#verify-status"), error.message, "error");
  }
});

function initialMatrix() {
  grid.innerHTML = "";
  for (let i = 0; i < 64; i++) {
    const cell = document.createElement("div");
    cell.className = "matrix-cell";
    cell.textContent = "·";
    grid.appendChild(cell);
  }
  pixelGrid.innerHTML = '<div class="empty-matrix">Embed an image, then click any block.</div>';
}

initialMatrix();
