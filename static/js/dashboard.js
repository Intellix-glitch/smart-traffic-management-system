"use strict";

// ── Socket.IO connection ───────────────────────────────
const socket = io();
const DIRS   = ["north", "east", "south", "west"];

// ── Live chart (rolling 30-point window) ──────────────
const liveCtx  = document.getElementById("liveChart").getContext("2d");
const CHART_WINDOW = 30;
const liveData = {
  labels:   Array(CHART_WINDOW).fill(""),
  datasets: DIRS.map((d, i) => ({
    label: d.charAt(0).toUpperCase() + d.slice(1),
    data:  Array(CHART_WINDOW).fill(0),
    borderColor:     ["#3b82f6","#22c55e","#f59e0b","#a855f7"][i],
    backgroundColor: ["#3b82f620","#22c55e20","#f59e0b20","#a855f720"][i],
    tension: 0.35,
    fill: true,
    pointRadius: 0,
  })),
};
const liveChart = new Chart(liveCtx, {
  type: "line",
  data: liveData,
  options: {
    animation: false,
    scales: {
      x: { display: false },
      y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.06)" },
           ticks: { color: "#8b90a0" } },
    },
    plugins: { legend: { labels: { color: "#8b90a0", boxWidth: 12 } } },
  },
});

// ── Hourly chart ───────────────────────────────────────
const hourlyCtx = document.getElementById("hourlyChart").getContext("2d");
let hourlyChart = null;

function renderHourlyChart(summaryData) {
  const hours = [...new Set(summaryData.map(r => r.hour))].sort();
  const datasets = DIRS.map((d, i) => {
    const dKey = d.charAt(0).toUpperCase() + d.slice(1);
    return {
      label: dKey,
      data:  hours.map(h => {
        const row = summaryData.find(r => r.direction === dKey && r.hour === h);
        return row ? row.avg_count : 0;
      }),
      backgroundColor: ["#3b82f670","#22c55e70","#f59e0b70","#a855f770"][i],
      borderColor:     ["#3b82f6","#22c55e","#f59e0b","#a855f7"][i],
      borderWidth: 1,
    };
  });

  if (hourlyChart) hourlyChart.destroy();
  hourlyChart = new Chart(hourlyCtx, {
    type: "bar",
    data: { labels: hours.map(h => h + ":00"), datasets },
    options: {
      scales: {
        x: { ticks: { color: "#8b90a0" }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: "#8b90a0" },
             grid: { color: "rgba(255,255,255,0.06)" } },
      },
      plugins: { legend: { labels: { color: "#8b90a0", boxWidth: 12 } } },
    },
  });
}

// ── Counts per direction (latest) ─────────────────────
const latestCounts = { north: 0, east: 0, south: 0, west: 0 };

// ── Clock ──────────────────────────────────────────────
function updateClock() {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ── Helpers ────────────────────────────────────────────
function updateStatsBar() {
  const total = Object.values(latestCounts).reduce((s, v) => s + v, 0);
  document.getElementById("total-vehicles").textContent = total;

  const busiest = Object.entries(latestCounts)
    .sort((a, b) => b[1] - a[1])[0];
  document.getElementById("busiest-dir").textContent =
    busiest[0].charAt(0).toUpperCase() + busiest[0].slice(1);
}

function pushLiveChart(dir, count) {
  const ds = liveData.datasets.find(d => d.label.toLowerCase() === dir);
  if (!ds) return;
  const now = new Date().toLocaleTimeString();
  liveData.labels.push(now);
  liveData.labels.shift();
  ds.data.push(count);
  ds.data.shift();
  liveChart.update("none");   // no animation for performance
}

function addLogRow(data, direction) {
  const tbody = document.getElementById("logBody");
  const tr    = document.createElement("tr");
  const ts    = new Date().toLocaleTimeString();
  tr.innerHTML = `
    <td>${ts}</td>
    <td>${direction}</td>
    <td>${data.count}</td>
    <td>${data.green_sec}</td>
    <td class="${data.emergency ? 'badge-emergency' : 'badge-normal'}">
      ${data.emergency ? "🚨 YES" : "—"}
    </td>`;
  tbody.prepend(tr);
  // Keep at most 50 rows
  while (tbody.rows.length > 50) tbody.deleteRow(-1);
}

// ── Per-direction frame handler ────────────────────────
DIRS.forEach(dir => {
  socket.on(`frame_${dir}`, data => {
    // Update camera feed
    document.getElementById(`frame-${dir}`).src =
      `data:image/jpeg;base64,${data.image}`;

    // Update overlay labels
    document.getElementById(`count-${dir}`).textContent =
      `Vehicles: ${data.count}`;
    setDensity(document.getElementById(`density-${dir}`), data.density);
    document.getElementById(`timer-${dir}`).textContent =
      `Green: ${data.green_sec}s`;
    const fpsEl = document.getElementById(`fps-${dir}`);
    if (fpsEl) fpsEl.textContent = data.fps ? data.fps + " fps" : "—";

    // Update signal pill
    const pill = document.getElementById(`pill-${dir}`);
    const card = document.getElementById(`card-${dir}`);
    if (data.signal.toUpperCase() === "GREEN") {
      pill.textContent = "GREEN";
      pill.classList.add("green");
      card.classList.add("active-green");
      card.classList.remove("active-red");
    } else {
      pill.textContent = "RED";
      pill.classList.remove("green");
      card.classList.remove("active-green");
      card.classList.add("active-red");
    }

    // Emergency banner
    if (data.emergency) {
      const banner = document.getElementById("emergency-banner");
      banner.style.display = "";
      document.getElementById("emergency-dir").textContent = dir.toUpperCase();
    }

    // Charts
    latestCounts[dir] = data.count;
    updateStatsBar();
    pushLiveChart(dir, data.count);

    // Stats bar — active green direction
    if (data.signal.toUpperCase() === "GREEN") {
      document.getElementById("active-green").textContent =
        dir.charAt(0).toUpperCase() + dir.slice(1);
    }

    // Log table (every ~10 events per direction)
    if (Math.random() < 0.1) addLogRow(data, dir);
  });
});

// ── Signal update (from signal_controller) ────────────
socket.on("signal_update", status => {
  const active = status.active_direction;
  DIRS.forEach(dir => {
    const pill = document.getElementById(`pill-${dir}`);
    const card = document.getElementById(`card-${dir}`);
    const info = status.directions?.[dir.charAt(0).toUpperCase() + dir.slice(1)];
    if (!info) return;

    if (info.signal.toUpperCase() === "GREEN") {
      pill.textContent = "GREEN"; pill.classList.add("green");
      card.classList.add("active-green"); card.classList.remove("active-red");
    } else {
      pill.textContent = "RED"; pill.classList.remove("green");
      card.classList.remove("active-green"); card.classList.add("active-red");
    }
  });
  if (active) {
    document.getElementById("active-green").textContent = active;
  }
});

// ── Density + analytics ────────────────────────────────
const DENSITY_CLASS = { LOW: "d-low", MEDIUM: "d-medium", HIGH: "d-high" };

function setDensity(el, density) {
  if (!el) return;
  const d = (density || "—").toUpperCase();
  el.textContent = d;
  el.className = "density-chip" + (DENSITY_CLASS[d] ? " " + DENSITY_CLASS[d] : "");
}

function renderCongestion(data) {
  const badge = document.getElementById("congestion-badge");
  const fill  = document.getElementById("congestion-fill");
  const idx   = document.getElementById("congestion-index");

  const d = data.overall_density || "—";
  badge.textContent = d;
  badge.className = "congestion-badge" +
    (DENSITY_CLASS[d] ? " " + DENSITY_CLASS[d] : "");

  const ci = data.congestion_index || 0;
  fill.style.width = ci + "%";
  fill.style.background =
    ci >= 67 ? "#ef4444" : ci >= 34 ? "#f59e0b" : "#22c55e";
  idx.textContent = ci + "%";
}

function renderLaneLoad(data) {
  const wrap = document.getElementById("lane-load");
  const dirs = data.directions || [];

  wrap.innerHTML = dirs.map(dir => {
    const cls = DENSITY_CLASS[dir.density] ? " " + DENSITY_CLASS[dir.density] : "";
    return `
      <div class="lane-row">
        <span class="lane-name">${dir.direction}</span>
        <span class="lane-count">${dir.count}</span>
        <div class="lane-share-track">
          <div class="lane-share-fill" style="width:${dir.share_pct}%"></div>
        </div>
        <span class="lane-share-pct">${dir.share_pct}%</span>
      </div>`;
  }).join("") || `<div class="lane-row"><span class="lane-name">—</span></div>`;
}

function renderInsights(data) {
  const list = document.getElementById("insight-list");
  const items = data.insights || [];
  list.innerHTML = items.map(t => `<li>${t}</li>`).join("") ||
    `<li>Start the system to begin live traffic analysis.</li>`;
}

// ── Forecast ────────────────────────────────────────────
function renderForecast(fc) {
  const list = document.getElementById("forecast-list");
  const summary = document.getElementById("forecast-summary");
  if (!list) return;

  if (!fc) { list.innerHTML = ""; summary.textContent = ""; return; }

  const dirs = fc.directions || [];
  list.innerHTML = dirs.map(f => {
    let arrow = "→", cls = "flat";
    if (f.trend === "rising")  { arrow = "▲"; cls = "up"; }
    else if (f.trend === "falling") { arrow = "▼"; cls = "down"; }
    else if (f.trend === "warming up") { arrow = "…"; cls = "flat"; }

    const pred = f.predicted == null
      ? `<span class="fc-to warm">—</span>`
      : `<span class="fc-to">${f.predicted}</span>`;

    return `
      <div class="fc-row">
        <span class="fc-name">${f.direction}</span>
        <span class="fc-from">${f.latest} veh</span>
        <span class="fc-arrow ${cls}">${arrow}</span>
        ${pred}
      </div>`;
  }).join("") || `<div class="fc-row"><span class="fc-name">—</span></div>`;

  summary.textContent = fc.summary || "";
}

// ── Stream settings ────────────────────────────────────
async function loadSettings() {
  let data;
  try {
    const res = await fetch("/api/settings");
    data = await res.json();
  } catch { return; }

  const seg = document.getElementById("res-seg");
  [...seg.querySelectorAll(".seg-btn")].forEach(b =>
    b.classList.toggle("active", Number(b.dataset.width) === data.infer_width));

  const wrap = document.getElementById("lane-settings");
  const lanes = data.lanes || {};
  wrap.innerHTML = DIRS.map(dir => {
    const c = lanes[dir] || { enabled: true, max_fps: 0 };
    const options = [0, 1, 2, 4, 8]
      .map(v => `<option value="${v}" ${Number(c.max_fps) === v ? "selected" : ""}>` +
        (v ? v + " fps" : "Auto") + "</option>")
      .join("");
    return `
      <div class="lane-set-row" data-dir="${dir}">
        <span class="lane-set-name">${dir[0].toUpperCase() + dir.slice(1)}</span>
        <label class="lane-enable-label">
          <input type="checkbox" class="lane-enable" ${c.enabled ? "checked" : ""}> Live
        </label>
        <select class="lane-fps">${options}</select>
      </div>`;
  }).join("");
}

function applySettings(payload) {
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).catch(() => {});
}

function bindSettings() {
  const seg = document.getElementById("res-seg");
  seg.addEventListener("click", e => {
    const btn = e.target.closest(".seg-btn");
    if (!btn) return;
    [...seg.querySelectorAll(".seg-btn")].forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    applySettings({ infer_width: Number(btn.dataset.width) });
  });

  const wrap = document.getElementById("lane-settings");
  wrap.addEventListener("change", e => {
    const row = e.target.closest(".lane-set-row");
    if (!row) return;
    const dir = row.dataset.dir;
    applySettings({
      lanes: {
        [dir]: {
          enabled: row.querySelector(".lane-enable").checked,
          max_fps: Number(row.querySelector(".lane-fps").value)
        }
      }
    });
  });
}

async function loadAnalytics() {
  let data;
  try {
    const res = await fetch("/api/analytics");
    data = await res.json();
  } catch { return; }

  renderCongestion(data);
  renderLaneLoad(data);
  renderForecast(data.forecast);
  renderInsights(data);
}

// ── REST helpers ───────────────────────────────────────
async function startSystem() {

    console.log("START BUTTON CLICKED");

    document.getElementById(
        "btnStart"
    ).disabled = true;

    const response = await fetch("/api/start", {
        method: "POST"
    });

    const data = await response.json();

    console.log(data);
}

async function stopSystem() {

    const response = await fetch("/api/stop", {
        method: "POST"
    });

    const data = await response.json();

    console.log(data);

    // Reset all frames to placeholder
    ["north", "east", "south", "west"]
    .forEach(dir => {

        document.getElementById(
            `frame-${dir}`
        ).src =
            "/static/img/placeholder.svg";

        document.getElementById(
            `count-${dir}`
        ).innerText =
            "Vehicles: 0";

        document.getElementById(
            `timer-${dir}`
        ).innerText =
            "Green: 0s";

        const fpsEl = document.getElementById(
            `fps-${dir}`
        );

        if (fpsEl) fpsEl.innerText = "—";

        const pill = document.getElementById(
            `pill-${dir}`
        );

        pill.innerText = "RED";

        pill.style.background = "#ef4444";
    });

    // Reset stats
    document.getElementById(
        "total-vehicles"
    ).innerText = "0";

    document.getElementById(
        "busiest-dir"
    ).innerText = "—";

    document.getElementById(
        "active-green"
    ).innerText = "—";

    // Enable start button again
    document.getElementById(
        "btnStart"
    ).disabled = false;
}


async function loadHourly() {
  const res  = await fetch("/api/summary");
  const data = await res.json();
  if (data.length) renderHourlyChart(data);
}

// ── Init ───────────────────────────────────────────────
loadHourly();
setInterval(loadHourly, 60_000);   // refresh hourly chart every minute
loadAnalytics();
setInterval(loadAnalytics, 3_000); // live density + insights every 3s
loadSettings();
bindSettings();
window.startSystem = startSystem;
window.stopSystem = stopSystem;