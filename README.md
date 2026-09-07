# 🚦 Smart Traffic AI — Full-Stack System

AI-powered adaptive traffic management using YOLOv8, Flask, Socket.IO,
and a live web dashboard with real-time density and congestion insights.

---

## Project structure

```
smart-traffic-ai/
├── backend/
│   ├── app.py               ← Flask + Socket.IO entry point
│   ├── detector.py          ← YOLOv8 vehicle detection
│   ├── signal_controller.py ← Adaptive signal timing (threaded)
│   ├── emergency.py         ← Emergency-vehicle detection
│   ├── database.py          ← SQLAlchemy models & helpers
│   └── utils.py             ← Shared helpers (frame encoding, paths)
├── frontend/                ← (reserved for React upgrade)
├── models/
│   └── yolov8n.pt           ← Downloaded automatically on first run
├── videos/                  ← Place your MP4 / JPEG traffic files here
├── static/
│   ├── css/style.css
│   └── js/dashboard.js
├── templates/
│   └── index.html
└── requirements.txt
```

---

## Quick start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add traffic videos (optional — system works with static images too)
# Copy north_traffic.mp4 / east_traffic.mp4 … to videos/

# 4. Run
python backend/app.py
# Open http://localhost:5000
```

---

## How it works

1. **Click ▶ Start** in the dashboard.
2. The backend spins up one detection thread per direction (N/E/S/W).
3. Each thread reads frames from the corresponding video file, runs
   YOLOv8 inference, and counts vehicles.
4. `TrafficSignalController` runs a separate cycle thread that grants
   green time proportional to vehicle counts.
5. Results stream to the browser via Socket.IO — live frames, signal
   states, counts and density levels update in real time, and a live
   congestion meter + lane-load/insights panel refreshes every 3 s.
6. All events are persisted to SQLite (`traffic.db`).

---

## Configuration

| Variable            | Default    | Description                              |
|---------------------|------------|------------------------------------------|
| `SECRET_KEY`        | `dev-secret-change-me` | Flask session secret           |
| `DATABASE_URL`      | `sqlite:///traffic.db` | SQLAlchemy DB URI               |
| `MODE`              | `video`    | `video` = stream `media/video/*.mp4` where present, fall back to images for missing directions; `images` = static feeds only |
| `VIDEO_INFER_WIDTH` | `480`      | 4K/1080p sources are downscaled to this width before YOLO inference (lower = faster streaming) |
| `SNAPSHOT_INTERVAL`  | `5`        | Seconds between per-lane count snapshots used by the short-term forecast |

Set via environment variables or a `.env` file in the project root.

---

## Deploy for free

This app needs a **long-running server with WebSockets** (Socket.IO) —
serverless platforms won't work. The easiest $0 option is **Render**:

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New** → **Blueprint**.
3. Connect the repo — Render auto-detects `render.yaml` and deploys.
4. Open the `https://smart-traffic-ai.onrender.com` URL you get.

What the repo already includes:

| File | Purpose |
|------|---------|
| `render.yaml` | Render blueprint (free plan, CPU-only PyTorch) |
| `runtime.txt` | Python version for Render |
| `Dockerfile`  | Alt path: works on any Docker host (Railway, Fly.io, …) |

Free-tier caveats:

- Render spins the service down after **15 min without traffic**; the first
  visit after idle takes ~1 min to wake up (normal for free plans).
- The YOLOv8 model (`models/yolov8n.pt`) is committed, so nothing is
  downloaded at runtime.
- `app.py` reads the `PORT` env var and runs without debug mode on the
  platform — it only needs `python backend/app.py` to start.

### Keep it awake (free tier)

The app ships with a built-in keep-alive: a background thread pings the
lightweight `GET /api/keepalive` route every 10 minutes, so the host never
sees 15 minutes of idle.

| Env var              | Default | Purpose                                      |
|----------------------|---------|----------------------------------------------|
| `KEEPALIVE_ENABLED`  | `1`     | Set to `0` to disable the self-ping          |
| `KEEPALIVE_INTERVAL` | `600`   | Seconds between pings (must be < 900)        |
| `KEEPALIVE_URL`      | *(auto)*| Override the URL to ping (e.g. on a custom domain) |

### Live tuning & forecasting

- **Stream settings card** — change the YOLO inference resolution live
  (360–960 px) and enable/disable or cap the fps of any lane via
  `POST /api/settings`; the dashboard applies it instantly.
- **Traffic forecast card** — every `SNAPSHOT_INTERVAL` seconds each lane's
  count is snapshotted; a linear fit over the last five snapshots is
  extrapolated 60 s ahead (`/api/analytics` → `forecast`).
- `media/video/south.mp4` and `west.mp4` are **generated samples**
  (mirrored/downscaled from the north/east clips) so all four feeds can
  stream; replace them with real footage any time.

The ping target is learned from the first incoming request (`scheme://host`),
so no configuration is needed on Render — it just works. Two honest caveats:

1. **It can't wake a sleeping service.** If the app is spun down (after a
   redeploy or a long idle), the thread isn't running to ping — the first
   visitor still waits ~1 min. For guaranteed wake-up, add a free external
   pinger: [UptimeRobot](https://uptimerobot.com) (free: 50 monitors,
   5-min interval) or [cron-job.org](https://cron-job.org), pointed at
   `https://<your-app>.onrender.com/api/keepalive`.
   ⚠️ **Never point the pinger at `/robots.txt`** — Render answers that
   path itself while the service is down, so the ping never reaches your
   app and it sleeps anyway.
2. **Free instance hours are finite.** Render gives 750 instance
   hours/workspace/month; an always-awake service consumes almost all of
   them (fine for one demo service — just don't add more free services).

## Upgrade path

| Phase | What to add                              |
|-------|------------------------------------------|
| ✅ 1  | YOLOv8 + video feed ← *you are here*    |
| ✅ 2  | Flask dashboard + SQLite DB              |
| ✅ 3  | Emergency priority + analytics           |
| ✅ 4  | Docker + free cloud deploy                |
| ✅ 5  | Video streaming + live density insights   |
| ✅ 6  | Short-term forecast + live stream tuning  |
| 🔜 7  | LSTM prediction                          |

---

## Author
Somesh — Smart AI-based Traffic Management System