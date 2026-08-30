"use strict";

const $ = (selector) => document.querySelector(selector);
const elements = {
  alert: $("#alert"),
  containerStatus: $("#container-status"),
  settingsDialog: $("#settings-dialog"),
  settingsOpen: $("#settings-open"),
  settingsClose: $("#settings-close"),
  donorInput: $("#donor-input"),
  donorName: $("#donor-name"),
  donorMeta: $("#donor-meta"),
  donorAction: $("#donor-action"),
  donorProgress: $("#donor-progress"),
  rafInput: $("#raf-input"),
  dropZone: $("#drop-zone"),
  fileTitle: $("#file-title"),
  fileMeta: $("#file-meta"),
  rafProgress: $("#raf-progress"),
  inverse: $("#inverse-calibration"),
  isoPolicy: $("#iso-policy"),
  mapping: $("#sensor-mapping"),
  donorLensCorrection: $("#donor-lens-correction"),
  convert: $("#convert-button"),
  currentJob: $("#current-job"),
  correctDistortion: $("#correct-distortion"),
  correctVignetting: $("#correct-vignetting"),
  correctCa: $("#correct-ca"),
  distortionStrength: $("#distortion-strength"),
  vignettingStrength: $("#vignetting-strength"),
  caStrength: $("#ca-strength"),
  jobList: $("#job-list"),
  refresh: $("#refresh-button"),
  language: $("#language-toggle"),
};

const copy = {
  zh: {
    home: "RAF / 3FR 首页", openSettings: "打开设置", closeSettings: "关闭设置",
    checkingContainer: "检查容器", convertRaw: "转换 RAW", selectRaf: "选择 RAF",
    dropRaf: "拖放文件，或点按选择", choose: "选择", whiteBalance: "白平衡",
    auto: "自动", asShot: "拍摄值", donor: "供体", lensCorrection: "镜头校正",
    distortion: "畸变", ca: "色差", vignetting: "暗角", convert3fr: "转换为 3FR",
    currentJob: "当前任务", ready: "准备就绪", selectToStart: "选择 RAF 开始转换",
    recent: "最近结果", refresh: "刷新", noHistory: "暂无记录", settings: "设置",
    x2dContainer: "X2D 容器", required: "必需", processing: "处理方式", advanced: "高级",
    sensorMapping: "传感器映射", illuminantAdaptive: "光源自适应", donorLens: "供体镜头数据",
    neutralize: "中和", preserve: "保留", inverseGain: "FFF 增益反向补偿",
    isoPolicy: "ISO 映射", isoNearest: "邻近 X2D 档位", isoHnnrStable: "HNNR 稳定（最高 6400）", isoCapture: "保留富士拍摄值",
    recognizedOnly: "仅对已识别的校准组可用", notConfigured: "未设置",
    selectX2d: "选择 X2D 100C 3FR", replace: "更换", missingContainer: "未设置容器",
    containerReady: "容器就绪", calibrationGroup: "校准组", unknownCalibration: "未知校准组",
    unknown: "未知", selected: "已选择", receiving: "读取文件", queued: "等待",
    converting: "转换", verifying: "核验", lens_profile: "镜头参数", complete: "完成",
    failed: "失败", downloadOutput: "下载 3FR", manifest: "转换记录", verification: "核验报告",
    lensProfile: "镜头配置", record: "记录", readyToConvert: "可以开始转换",
    waitingConvert: "等待转换", chooseRafError: "请选择 GFX 100RF RAF 文件。",
    tooLarge: "这张 RAF 超过 256 MB，未加入转换。", requestFailed: "请求失败",
    cannotConnect: "无法连接转换服务。", uploading: "正在读取 RAW",
    stateFailed: "状态读取失败", chooseDonorError: "请选择真实的 X2D 100C .3FR 供体。",
    donorFailed: "供体配置失败", startFailed: "无法开始转换", fujiAuto: "富士自动 WB",
    captureWB: "拍摄 WB", donorWB: "供体 WB", selectedSize: "可以开始转换",
    distortionStrength: "畸变校正强度", caStrength: "横向色差校正强度", vignettingStrength: "暗角校正强度",
    distortionModel: "畸变模型", nativeMatch: "原生匹配", legacyInBounds: "旧版无空边",
    statusAside: "转换状态与最近结果",
    message_receiving: "正在接收 RAW", message_queued: "已排队", message_converting: "正在转换 Bayer RAW 与元数据",
    message_verifying: "正在核验 3FR 结构与来源", message_lens_profile: "正在提取富士镜头配置",
    message_complete: "转换与核验完成", message_failed: "转换失败",
  },
  en: {
    home: "RAF / 3FR home", openSettings: "Open settings", closeSettings: "Close settings",
    checkingContainer: "Checking container", convertRaw: "Convert RAW", selectRaf: "Select RAF",
    dropRaf: "Drop a file or click to choose", choose: "Choose", whiteBalance: "White balance",
    auto: "Auto", asShot: "As shot", donor: "Donor", lensCorrection: "Lens correction",
    distortion: "Distortion", ca: "Chromatic aberration", vignetting: "Vignetting", convert3fr: "Convert to 3FR",
    currentJob: "Current job", ready: "Ready", selectToStart: "Select a RAF to begin",
    recent: "Recent", refresh: "Refresh", noHistory: "No recent conversions", settings: "Settings",
    x2dContainer: "X2D container", required: "Required", processing: "Processing", advanced: "Advanced",
    sensorMapping: "Sensor mapping", illuminantAdaptive: "Illuminant adaptive", donorLens: "Donor lens data",
    neutralize: "Neutralize", preserve: "Preserve", inverseGain: "Reverse FFF gain",
    isoPolicy: "ISO mapping", isoNearest: "Nearest X2D value", isoHnnrStable: "HNNR stable (max 6400)", isoCapture: "Preserve Fujifilm value",
    recognizedOnly: "Available for recognized calibration groups", notConfigured: "Not configured",
    selectX2d: "Select an X2D 100C 3FR", replace: "Replace", missingContainer: "Container missing",
    containerReady: "Container ready", calibrationGroup: "Calibration group", unknownCalibration: "Unknown calibration group",
    unknown: "Unknown", selected: "Selected", receiving: "Reading file", queued: "Queued",
    converting: "Converting", verifying: "Verifying", lens_profile: "Lens data", complete: "Complete",
    failed: "Failed", downloadOutput: "Download 3FR", manifest: "Conversion record", verification: "Verification report",
    lensProfile: "Lens profile", record: "Record", readyToConvert: "Ready to convert",
    waitingConvert: "Waiting to convert", chooseRafError: "Choose a GFX 100RF RAF file.",
    tooLarge: "This RAF exceeds 256 MB and was not added.", requestFailed: "Request failed",
    cannotConnect: "Unable to connect to the conversion service.", uploading: "Reading RAW",
    stateFailed: "Unable to read status", chooseDonorError: "Choose a genuine X2D 100C .3FR donor.",
    donorFailed: "Donor setup failed", startFailed: "Unable to start conversion", fujiAuto: "Fujifilm Auto WB",
    captureWB: "As-shot WB", donorWB: "Donor WB", selectedSize: "Ready to convert",
    distortionStrength: "Distortion correction strength", caStrength: "Lateral chromatic aberration strength", vignettingStrength: "Vignetting correction strength",
    distortionModel: "Distortion model", nativeMatch: "Native match", legacyInBounds: "Legacy no-blank-edge",
    statusAside: "Conversion status and recent results",
    message_receiving: "Receiving RAW", message_queued: "Queued", message_converting: "Converting Bayer RAW and metadata",
    message_verifying: "Verifying 3FR structure and provenance", message_lens_profile: "Reading Fujifilm lens data",
    message_complete: "Conversion and verification complete", message_failed: "Conversion failed",
  },
};
let language = localStorage.getItem("raf3fr-language") === "zh" ? "zh" : "en";
const t = (key) => copy[language][key] || key;
const stageLabels = new Proxy({}, { get: (_, key) => t(String(key)) });
const processingStages = ["receiving", "queued", "converting", "verifying", "lens_profile", "complete"];
const artifactLabels = new Proxy({}, { get: (_, key) => t({ output: "downloadOutput", manifest: "manifest", verification: "verification", lens_profile: "lensProfile" }[key] || String(key)) });

let appState = null;
let selectedRaf = null;
let polling = null;
let uploading = false;
let uploadingRaf = false;

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function applyLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.i18nAria)); });
  elements.language.setAttribute("aria-label", language === "zh" ? "切换为 English" : "Switch to Chinese");
  if (!selectedRaf) {
    elements.fileTitle.textContent = t("selectRaf");
    elements.fileMeta.textContent = t("dropRaf");
  }
  if (appState) renderState();
}

function showError(message) {
  elements.alert.textContent = message;
  elements.alert.hidden = !message;
}

function setProgress(container, percent) {
  container.hidden = percent === null;
  container.querySelector("span").style.width = `${percent || 0}%`;
}

function validFile(file, extension) {
  return file && file.name.toLowerCase().endsWith(extension) && file.size > 0;
}

function selectRaf(file) {
  showError("");
  if (!validFile(file, ".raf")) {
    selectedRaf = null;
    elements.dropZone.classList.remove("has-file");
    elements.fileTitle.textContent = t("selectRaf");
    elements.fileMeta.textContent = t("dropRaf");
    showError(t("chooseRafError"));
  } else if (file.size > 256 * 1024 * 1024) {
    selectedRaf = null;
    showError(t("tooLarge"));
  } else {
    selectedRaf = file;
    elements.dropZone.classList.add("has-file");
    elements.fileTitle.textContent = file.name;
    elements.fileMeta.textContent = `${formatBytes(file.size)} · ${t("waitingConvert")}`;
    renderSelection(file);
  }
  updateSubmit();
}

function updateSubmit() {
  const donorReady = Boolean(appState?.donor?.configured);
  elements.convert.disabled = !(donorReady && selectedRaf && !uploading);
}

function uploadBinary(url, file, progressContainer) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", url);
    request.responseType = "json";
    request.setRequestHeader("X-RAF2HNCS-Request", "1");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) setProgress(progressContainer, (event.loaded / event.total) * 100);
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) resolve(request.response);
      else reject(new Error(request.response?.error || `${t("requestFailed")} (${request.status})`));
    });
    request.addEventListener("error", () => reject(new Error(t("cannotConnect"))));
    request.send(file);
  });
}

function renderDonor() {
  const donor = appState?.donor;
  if (!donor?.configured) {
    elements.donorName.textContent = t("notConfigured");
    elements.donorMeta.textContent = t("selectX2d");
    elements.donorAction.textContent = t("choose");
    elements.containerStatus.className = "container-status missing";
    elements.containerStatus.querySelector("span").textContent = t("missingContainer");
    elements.inverse.checked = false;
    elements.inverse.disabled = true;
  } else {
    elements.donorName.textContent = donor.name;
    const profile = donor.inverse_calibration_supported
      ? `${t("calibrationGroup")} ${donor.calibration_cohort} · Software ${donor.software}`
      : `${t("unknownCalibration")} · Software ${donor.software || t("unknown")}`;
    elements.donorMeta.textContent = `${formatBytes(donor.size)} · ${profile} · SHA-256 ${donor.sha256.slice(0, 12)}…`;
    elements.donorAction.textContent = t("replace");
    elements.containerStatus.className = "container-status ready";
    elements.containerStatus.querySelector("span").textContent = t("containerReady");
    elements.inverse.disabled = !donor.inverse_calibration_supported;
    if (elements.inverse.disabled) elements.inverse.checked = false;
  }
  updateSubmit();
}

function statusClass(stage) {
  return stage === "complete" ? "complete" : stage === "failed" ? "failed" : "";
}

function jobMessage(job) {
  return copy[language][`message_${job.stage}`] || job.message || stageLabels[job.stage] || job.stage;
}

function artifactLinks(job, compact = false) {
  const wrapper = document.createElement("div");
  wrapper.className = compact ? "row-links" : "artifact-links";
  for (const kind of Object.keys(job.artifacts || {})) {
    if (compact && !["output", "manifest"].includes(kind)) continue;
    const link = document.createElement("a");
    link.href = `/api/jobs/${job.id}/artifacts/${kind}`;
    link.textContent = compact
      ? kind === "output" ? "3FR" : t("record")
      : artifactLabels[kind] || kind;
    link.setAttribute("download", "");
    wrapper.append(link);
  }
  return wrapper;
}

function renderSelection(file) {
  elements.currentJob.className = "job-current";
  elements.currentJob.replaceChildren();
  const header = document.createElement("div");
  header.className = "job-current-header";
  const filename = document.createElement("strong");
  filename.textContent = file.name;
  const pill = document.createElement("span");
  pill.className = "status-pill";
  pill.textContent = stageLabels.selected;
  header.append(filename, pill);
  const message = document.createElement("div");
  message.className = "job-message";
  message.textContent = `${formatBytes(file.size)} · ${t("readyToConvert")}`;
  elements.currentJob.append(header, message);
}

function renderCurrent(job) {
  if (!job) {
    elements.currentJob.className = "empty-state";
    elements.currentJob.replaceChildren();
    const orbit = document.createElement("span");
    orbit.className = "empty-orbit";
    orbit.setAttribute("aria-hidden", "true");
    orbit.append(document.createElement("i"));
    const title = document.createElement("strong");
    title.textContent = t("ready");
    const copy = document.createElement("p");
    copy.textContent = t("selectToStart");
    elements.currentJob.append(orbit, title, copy);
    return;
  }

  elements.currentJob.className = "job-current";
  elements.currentJob.replaceChildren();
  const header = document.createElement("div");
  header.className = "job-current-header";
  const filename = document.createElement("strong");
  filename.textContent = job.filename;
  const pill = document.createElement("span");
  pill.className = `status-pill ${statusClass(job.stage)}`;
  pill.textContent = stageLabels[job.stage] || job.stage;
  header.append(filename, pill);

  const track = document.createElement("ol");
  track.className = "stage-track";
  const currentIndex = processingStages.indexOf(job.stage);
  for (const [index, stage] of processingStages.entries()) {
    const item = document.createElement("li");
    if (job.stage === "complete" || index < currentIndex) item.className = "done";
    if (index === currentIndex && job.stage !== "complete") item.className = "active";
    if (job.stage === "failed" && index === Math.max(0, currentIndex)) item.className = "active";
    item.append(document.createElement("i"), document.createTextNode(stageLabels[stage]));
    track.append(item);
  }
  const message = document.createElement("div");
  message.className = `job-message ${job.stage === "failed" ? "error" : ""}`;
  message.textContent = job.error ? `${jobMessage(job)}: ${job.error}` : jobMessage(job);
  elements.currentJob.append(header, track, message);
  if (job.stage === "complete") elements.currentJob.append(artifactLinks(job));
}

function renderHistory(jobs) {
  elements.jobList.replaceChildren();
  if (!jobs.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = t("noHistory");
    elements.jobList.append(empty);
    return;
  }
  for (const job of jobs.slice(0, 4)) {
    const row = document.createElement("article");
    row.className = "job-row";
    const identity = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = job.filename;
    const time = document.createElement("small");
    time.textContent = formatTime(job.created_at);
    identity.append(name, time);
    const status = document.createElement("span");
    status.className = `status-pill ${statusClass(job.stage)}`;
    status.textContent = stageLabels[job.stage] || job.stage;
    const options = document.createElement("span");
    options.className = "job-options";
    const wb = { auto: t("fujiAuto"), "as-shot": t("captureWB"), donor: t("donorWB") }[job.options.white_balance];
    const lens = `${t("distortion")} ${Math.round((job.options.distortion_strength ?? 1) * 100)}% · ${t("ca")} ${Math.round((job.options.chromatic_aberration_strength ?? 1) * 100)}% · ${t("vignetting")} ${Math.round((job.options.vignetting_strength ?? 0) * 100)}%`;
    options.textContent = `${wb} · ${lens}`;
    row.append(identity, status, options);
    if (job.stage === "complete") row.append(artifactLinks(job, true));
    else row.append(document.createElement("span"));
    elements.jobList.append(row);
  }
}

function renderState() {
  renderDonor();
  const jobs = appState?.jobs || [];
  const conversionJobs = jobs.filter((job) => (job.kind || "conversion") === "conversion");
  if (selectedRaf && uploadingRaf) {
    renderCurrent({
      filename: selectedRaf.name,
      stage: "receiving",
      message: t("uploading"),
      error: null,
      artifacts: {},
    });
  } else if (selectedRaf) {
    renderSelection(selectedRaf);
  } else {
    renderCurrent(conversionJobs[0]);
  }
  renderHistory(conversionJobs);
  const active = jobs.some((job) => !["complete", "failed"].includes(job.stage));
  if (active && !polling) polling = window.setInterval(refreshState, 1200);
  if (!active && polling) {
    window.clearInterval(polling);
    polling = null;
  }
}

function sliderStrength(element, enabled) {
  return enabled ? Number(element.value) / 100 : 0;
}

function updateParameterOutputs() {
  $("#distortion-value").value = elements.correctDistortion.checked ? `${elements.distortionStrength.value}%` : "—";
  $("#vignetting-value").value = elements.correctVignetting.checked ? `${elements.vignettingStrength.value}%` : "—";
  $("#ca-value").value = elements.correctCa.checked ? `${elements.caStrength.value}%` : "—";
}

function syncLensControls() {
  for (const [checkbox, slider] of [
    [elements.correctDistortion, elements.distortionStrength],
    [elements.correctCa, elements.caStrength],
    [elements.correctVignetting, elements.vignettingStrength],
  ]) slider.disabled = !checkbox.checked;
  updateParameterOutputs();
}

async function refreshState() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`${t("stateFailed")} (${response.status})`);
    appState = await response.json();
    renderState();
  } catch (error) {
    showError(error.message);
  }
}

async function configureDonor(file) {
  if (!validFile(file, ".3fr")) {
    showError(t("chooseDonorError"));
    return;
  }
  uploading = true;
  updateSubmit();
  showError("");
  try {
    await uploadBinary("/api/donor", file, elements.donorProgress);
    await refreshState();
  } catch (error) {
    showError(`${t("donorFailed")}: ${error.message}`);
  } finally {
    uploading = false;
    setProgress(elements.donorProgress, null);
    elements.donorInput.value = "";
    updateSubmit();
  }
}

async function submitConversion() {
  if (!selectedRaf || !appState?.donor?.configured) return;
  uploading = true;
  uploadingRaf = true;
  updateSubmit();
  showError("");
  renderState();
  const whiteBalance = document.querySelector('input[name="white-balance"]:checked').value;
  const distortionModel = document.querySelector('input[name="distortion-model"]:checked').value;
  const query = new URLSearchParams({
    white_balance: whiteBalance,
    inverse_x2d_calibration: String(elements.inverse.checked),
    iso_policy: elements.isoPolicy.value,
    sensor_mapping: elements.mapping.value,
    donor_lens_correction: elements.donorLensCorrection.value,
    distortion_model: distortionModel,
    distortion_strength: String(sliderStrength(elements.distortionStrength, elements.correctDistortion.checked)),
    chromatic_aberration_strength: String(sliderStrength(elements.caStrength, elements.correctCa.checked)),
    vignetting_strength: String(sliderStrength(elements.vignettingStrength, elements.correctVignetting.checked)),
  });
  try {
    await uploadBinary(`/api/jobs?${query}`, selectedRaf, elements.rafProgress);
    selectedRaf = null;
    elements.rafInput.value = "";
    elements.dropZone.classList.remove("has-file");
    elements.fileTitle.textContent = t("selectRaf");
    elements.fileMeta.textContent = t("dropRaf");
    await refreshState();
  } catch (error) {
    showError(`${t("startFailed")}: ${error.message}`);
  } finally {
    uploading = false;
    uploadingRaf = false;
    setProgress(elements.rafProgress, null);
    updateSubmit();
    renderState();
  }
}

elements.rafInput.addEventListener("change", () => selectRaf(elements.rafInput.files[0]));
elements.donorInput.addEventListener("change", () => configureDonor(elements.donorInput.files[0]));
elements.convert.addEventListener("click", submitConversion);
elements.refresh.addEventListener("click", refreshState);
elements.language.addEventListener("click", () => {
  language = language === "zh" ? "en" : "zh";
  localStorage.setItem("raf3fr-language", language);
  applyLanguage();
});
elements.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.rafInput.click();
  }
});
for (const eventName of ["dragenter", "dragover"]) {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("dragging");
  });
}
elements.dropZone.addEventListener("drop", (event) => selectRaf(event.dataTransfer.files[0]));

for (const slider of [elements.distortionStrength, elements.vignettingStrength, elements.caStrength]) {
  slider.addEventListener("input", updateParameterOutputs);
}
for (const checkbox of [elements.correctDistortion, elements.correctVignetting, elements.correctCa]) {
  checkbox.addEventListener("change", syncLensControls);
}

function openSettings() {
  if (!elements.settingsDialog.open) elements.settingsDialog.showModal();
}

elements.settingsOpen.addEventListener("click", openSettings);
elements.settingsOpen.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    openSettings();
  }
});
elements.settingsDialog.addEventListener("click", (event) => {
  if (event.target === elements.settingsDialog) elements.settingsDialog.close();
});

applyLanguage();
syncLensControls();
refreshState();
