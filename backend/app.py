from itertools import count
import os
import cv2
import time
import base64
import threading
import urllib.request

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from detector import VehicleDetector, classify_density
from signal_controller import calculate_green_time


# =====================================================
# FLASK SETUP
# =====================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

app = Flask(

    __name__,

    template_folder=os.path.join(
        BASE_DIR,
        "templates"
    ),

    static_folder=os.path.join(
        BASE_DIR,
        "static"
    )
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)


# =====================================================
# MODE
# =====================================================

# OPTIONS:
# "video"  — stream media/video/*.mp4 where present
# "images" — analyze the static media/images/*.jpg feeds

MODE = os.getenv(
    "MODE",
    "video"
).lower()

# 4K/1080p sources are downscaled to this width before YOLO
# inference — a large CPU speedup that keeps streams smooth.
VIDEO_INFER_WIDTH = int(
    os.getenv(
        "VIDEO_INFER_WIDTH",
        "480"
    )
)


# =====================================================
# MEDIA SOURCES
# =====================================================

MEDIA_SOURCES = {}

for _direction in ["north", "east", "south", "west"]:

    _video = os.path.join(
        BASE_DIR,
        "media",
        "video",
        f"{_direction}.mp4"
    )

    _image = os.path.join(
        BASE_DIR,
        "media",
        "images",
        f"{_direction}.jpg"
    )

    if MODE == "video" and os.path.exists(_video):

        MEDIA_SOURCES[_direction] = {
            "video": _video
        }

    else:

        MEDIA_SOURCES[_direction] = {
            "image": _image
        }


# =====================================================
# GLOBALS
# =====================================================

system_running = False

detector = VehicleDetector()

latest_data = {

    "north": {},
    "east": {},
    "south": {},
    "west": {}
}

event_logs = []
traffic_history = []

# Rolling per-direction counts for live trend charts
analytics_history = {
    "north": [],
    "east": [],
    "south": [],
    "west": []
}

DENSITY_WEIGHT = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3
}

# =====================================================
# SNAPSHOT + FORECAST STATE
# =====================================================

# How often each lane's count is snapshotted for forecasting
SNAPSHOT_INTERVAL = int(
    os.getenv(
        "SNAPSHOT_INTERVAL",
        "5"
    )
)

# Per-lane periodic snapshots (oldest first), capped to 120 (~10 min)
snapshot_history = {
    "north": [],
    "east": [],
    "south": [],
    "west": []
}

last_snapshot_ts = 0.0


# =====================================================
# LIVE STREAM SETTINGS
# =====================================================

# Tuned live from the dashboard (see /api/settings)
stream_settings = {
    "infer_width": VIDEO_INFER_WIDTH,
    "mode": MODE
}

# Per-lane controls: enabled + optional fps cap (0 = no cap)
lane_controls = {
    direction: {
        "enabled": True,
        "max_fps": 0
    }
    for direction in ["north", "east", "south", "west"]
}


# =====================================================
# ENCODE FRAME
# =====================================================

def encode_frame(frame):

    _, buffer = cv2.imencode(
        ".jpg",
        frame
    )

    return base64.b64encode(
        buffer
    ).decode("utf-8")


# =====================================================
# PROCESS IMAGE
# =====================================================

def process_image(direction, image_path):

    frame = cv2.imread(image_path)

    if frame is None:

        print(f"[ERROR] Cannot read image: {image_path}")

        return

    annotated, count, detections = detector.detect(frame)

    green_time = calculate_green_time(count)

    frame_base64 = encode_frame(annotated)

    signal_state = "GREEN"

    socketio.emit(

        f"frame_{direction}",

        {
            "image": frame_base64,

            "count": count,

            "signal": signal_state,

            "green_sec": green_time,

            "emergency": False,

            "density": classify_density(count)
        }
    )

    # Store latest data
    latest_data[direction] = {

        "count": count,

        "green_time": green_time,

        "signal": signal_state
    }

    # Add log
    event_logs.append({

        "timestamp": time.strftime("%H:%M:%S"),

        "direction": direction.upper(),

        "vehicle_count": count,

        "green_time": green_time,

        "emergency": False
    })


# =====================================================
# PROCESS VIDEO
# =====================================================

def process_video(direction, video_path):

    global system_running

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():

        print(f"[ERROR] Cannot open video: {video_path}")

        return

    while system_running:

        ret, frame = cap.read()

        # Restart video if ended
        if not ret:

            cap.set(
                cv2.CAP_PROP_POS_FRAMES,
                0
            )

            continue

        # YOLO DETECTION
        annotated, count, detections = detector.detect(frame)

        green_time = calculate_green_time(count)

        # Determine busiest direction
        busiest_direction = max(

            latest_data,

            key=lambda d:
            latest_data[d].get("count", 0)
        )

        signal_state = (

            "GREEN"

            if direction == busiest_direction

            else "RED"
        )

        # Encode image
        frame_base64 = encode_frame(annotated)

        # Store latest data
        latest_data[direction] = {

            "count": count,

            "green_time": green_time,

            "signal": signal_state
        }

        # Emergency detection placeholder
        emergency = False

        # SOCKET EMIT
        socketio.emit(

            f"frame_{direction}",

            {
                "image": frame_base64,

                "count": count,

                "signal": signal_state,

                "green_sec": green_time,

                "emergency": emergency,

                "density": classify_density(count)
            }
        )

        # Event log
        event_logs.append({

            "timestamp": time.strftime("%H:%M:%S"),

            "direction": direction.upper(),

            "vehicle_count": count,

            "green_time": green_time,

            "emergency": emergency
        })    # Limit logs
    if len(event_logs) > 50:

        event_logs.pop(0)

    socketio.sleep(0.03)

    cap.release()


# =====================================================
# START PROCESSING
# =====================================================

def publish_result(
    direction,
    frame,
    count,
    green_time,
    signal_state,
    fps=0
):

    """Store + emit one direction's latest detection result."""

    density = classify_density(count)

    # Store latest data
    latest_data[direction] = {
        "count": count,
        "green_time": green_time,
        "signal": signal_state,
        "density": density,
        "fps": fps
    }

    # Rolling history for trend charts
    analytics_history[direction].append(count)

    if len(analytics_history[direction]) > 30:

        analytics_history[direction].pop(0)

    # Hourly aggregation
    traffic_history.append({
        "direction": direction.capitalize(),
        "count": count,
        "hour": time.strftime("%H")
    })

    if len(traffic_history) > 5000:

        traffic_history.pop(0)

    # Event log
    event_logs.append({
        "timestamp": time.strftime("%H:%M:%S"),
        "direction": direction.upper(),
        "vehicle_count": count,
        "green_time": green_time,
        "emergency": False
    })

    if len(event_logs) > 50:

        event_logs.pop(0)

    print(
        f"[DETECT] {direction}: {count} vehicles, "
        f"{density} density, signal {signal_state}"
        + (f", {fps} fps" if fps else "")
    )

    # SOCKET EMIT
    socketio.emit(

        f"frame_{direction}",

        {
            "image": encode_frame(frame),
            "count": count,
            "signal": signal_state,
            "green_sec": green_time,
            "emergency": False,
            "density": density,
            "fps": fps
        }
    )


def run_image_loop():

    """Round-robin static-image loop (re-detects every few seconds)."""

    print("[INFO] IMAGE MODE STARTED")

    while system_running:

        results = {}

        # Detect all directions first so signal states are coherent
        for direction, source in MEDIA_SOURCES.items():

            image_path = source["image"]

            frame = cv2.imread(image_path)

            if frame is None:

                print(f"[ERROR] Cannot load image: {image_path}")

                continue

            annotated, count, detections = detector.detect(frame)

            results[direction] = {
                "frame": annotated,
                "count": count,
                "green_time": calculate_green_time(count)
            }

        if not results:
            break

        busiest = max(
            results,
            key=lambda d: results[d]["count"]
        )

        for direction, r in results.items():

            signal_state = (
                "GREEN"
                if direction == busiest
                else "RED"
            )

            publish_result(
                direction,
                r["frame"],
                r["count"],
                r["green_time"],
                signal_state
            )

        # Periodic per-lane snapshot for the forecast
        maybe_snapshot()

        socketio.sleep(3)


def run_video_loop():

    """
    Round-robin video loop. Streams every camera feed smoothly by running
    one inference at a time and downscaling large sources before detection.
    Videos loop when they end; directions without a video fall back to
    their (pre-detected) static image.
    """

    caps = {}
    statics = {}
    fps_ema = {}

    # Open video captures; pre-detect static (image) feeds once
    for direction, source in MEDIA_SOURCES.items():

        if "video" in source:

            cap = cv2.VideoCapture(source["video"])

            if not cap.isOpened():

                print(f"[ERROR] Cannot open video: {source['video']}")

                continue

            caps[direction] = cap

            fps_ema[direction] = 0.0

        else:

            frame = cv2.imread(source["image"])

            if frame is None:

                print(f"[ERROR] Cannot load image: {source['image']}")

                continue

            annotated, count, detections = detector.detect(frame)

            statics[direction] = {
                "frame": annotated,
                "count": count,
                "green_time": calculate_green_time(count)
            }

    if not caps:

        print("[ERROR] No video feeds available — aborting")

        return

    print(
        f"[INFO] Video streams: {', '.join(caps)} "
        f"| static: {', '.join(statics) or 'none'}"
    )

    last_ts = {
        d: time.time()
        for d in caps
    }

    while system_running:

        now = time.time()

        results = {}

        # Read + detect one frame per enabled video direction
        for direction, cap in caps.items():

            control = lane_controls[direction]

            if not control["enabled"]:
                continue

            max_fps = control["max_fps"]

            if max_fps > 0 and (
                now - last_ts[direction]
            ) < (1.0 / max_fps):

                # fps cap hit — skip this lane this round
                continue

            ret, frame = cap.read()

            if not ret:

                # Loop the video
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

                ret, frame = cap.read()

                if not ret:

                    print(f"[ERROR] Cannot rewind video: {direction}")

                    continue

            # Downscale before inference for smooth CPU streaming
            # (width is tunable live from the dashboard)
            infer_width = stream_settings["infer_width"]

            h, w = frame.shape[:2]

            if w > infer_width:

                scale = infer_width / w

                frame = cv2.resize(
                    frame,
                    (infer_width, int(h * scale))
                )

            annotated, count, detections = detector.detect(frame)

            # Real inference takes 100ms+ per frame here, so clamp the
            # interval floor to 50ms (max 20 fps) — this keeps the rolling
            # average sane on the very first samples after Start.
            dt = max(
                now - last_ts[direction],
                0.05
            )

            last_ts[direction] = now

            fps_ema[direction] = (
                0.9 * fps_ema[direction] + 0.1 * (1.0 / dt)
            )

            results[direction] = {
                "frame": annotated,
                "count": count,
                "green_time": calculate_green_time(count),
                "fps": round(fps_ema[direction], 1)
            }

        if not results:
            break

        # Static feeds join with their cached detection
        for direction, s in statics.items():

            if not lane_controls[direction]["enabled"]:
                continue

            results[direction] = {
                "frame": s["frame"],
                "count": s["count"],
                "green_time": s["green_time"],
                "fps": 0
            }

        busiest = max(
            results,
            key=lambda d: results[d]["count"]
        )

        for direction, r in results.items():

            signal_state = (
                "GREEN"
                if direction == busiest
                else "RED"
            )

            publish_result(
                direction,
                r["frame"],
                r["count"],
                r["green_time"],
                signal_state,
                r["fps"]
            )

        # Periodic per-lane snapshot for the forecast
        maybe_snapshot()

        socketio.sleep(0.02)


def start_processing():

    """
    Dispatcher: picks the detection loop for the current MODE.
    Runs as a background task after /api/start until /api/stop.
    """

    if any("video" in s for s in MEDIA_SOURCES.values()):

        run_video_loop()

    else:

        run_image_loop()

# =====================================================
# STOP PROCESSING
# =====================================================

def stop_processing():

    global system_running

    system_running = False

    print("[INFO] System stopped")


# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def index():

    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():

    global system_running

    if system_running:

        return jsonify({
            "status": "already running"
        })

    system_running = True

    socketio.start_background_task(
        start_processing
    )

    return jsonify({
        "status": "started"
    })


@app.route("/api/stop", methods=["POST"])
def api_stop():

    stop_processing()

    return jsonify({

        "status": "stopped"
    })


@app.route("/api/logs")
def api_logs():

    return jsonify(event_logs)


@app.route("/api/status")
def api_status():

    return jsonify({

        "running": system_running,

        "latest": latest_data
    })
@app.route("/api/keepalive")
def api_keepalive():

    """Lightweight health/keep-alive target (no DB, tiny body)."""

    return jsonify({
        "status": "ok"
    })


# =====================================================
# ANALYTICS
# =====================================================

def build_insights(dirs, busiest, total):

    """Rule-based insights derived from the live per-lane data."""

    insights = []

    if not total:

        insights.append(
            "Start the system to begin live traffic analysis."
        )

        return insights

    # Busiest lane
    insights.append(
        f"{busiest['direction']} is the busiest lane "
        f"({busiest['count']} vehicles, "
        f"{busiest['share_pct']}% of current traffic)."
    )

    # Heavy lanes
    heavy = [
        d for d in dirs
        if d["density"] == "HIGH"
    ]

    if heavy:

        names = ", ".join(
            d["direction"] for d in heavy
        )

        insights.append(
            f"High density on {names} — extend the green phase there."
        )

    # Free-flowing lanes
    light = [
        d for d in dirs
        if d["density"] == "LOW" and d["count"] > 0
    ]

    if light:

        names = ", ".join(
            d["direction"] for d in light
        )

        verb = "is" if len(light) == 1 else "are"

        insights.append(
            f"{names} {verb} flowing freely (low density)."
        )

    # Imbalance vs. balance
    counts = sorted(
        (d["count"] for d in dirs),
        reverse=True
    )

    if counts and counts[0] > 0 and counts[-1] > 0:

        ratio = counts[0] / counts[-1]

        if ratio >= 2:

            insights.append(
                f"The busiest lane carries {ratio:.1f}× the lightest "
                f"({counts[0]} vs {counts[-1]} vehicles)."
            )

        elif len(counts) == 4 and counts[0] <= counts[-1] * 1.5 + 1:

            insights.append(
                "Traffic is fairly balanced across all four lanes."
            )

    return insights


# =====================================================
# SNAPSHOTS + FORECAST
# =====================================================

def maybe_snapshot():

    """Append current per-lane counts to the forecast series on a timer."""

    global last_snapshot_ts

    now = time.time()

    if now - last_snapshot_ts < SNAPSHOT_INTERVAL:
        return

    last_snapshot_ts = now

    for direction in ["north", "east", "south", "west"]:

        count = latest_data.get(
            direction,
            {}
        ).get("count", 0)

        snapshot_history[direction].append(count)

        if len(snapshot_history[direction]) > 120:

            snapshot_history[direction].pop(0)


def build_forecast():

    """
    Short-term forecast: linear fit over the last few per-lane snapshots,
    extrapolated one minute ahead.
    """

    horizon_sec = 60

    if not system_running:

        return {
            "horizon_sec": horizon_sec,
            "sampled_every_sec": SNAPSHOT_INTERVAL,
            "directions": [],
            "summary": "System stopped — forecasts resume on Start."
        }

    MIN_FIT = 5

    steps = max(
        1,
        round(horizon_sec / SNAPSHOT_INTERVAL)
    )

    directions = []

    for direction, series in snapshot_history.items():

        label = direction.capitalize()

        latest = latest_data.get(
            direction,
            {}
        ).get("count", 0)

        if len(series) < MIN_FIT:

            directions.append({
                "direction": label,
                "latest": latest,
                "predicted": None,
                "trend": "warming up"
            })

            continue

        fit = series[-MIN_FIT:]

        n = len(fit)

        x_mean = (n - 1) / 2.0

        y_mean = sum(fit) / n

        num = sum(
            (i - x_mean) * (fit[i] - y_mean)
            for i in range(n)
        )

        den = sum(
            (i - x_mean) ** 2
            for i in range(n)
        )

        slope_per_sample = num / den if den else 0.0

        predicted = max(
            0,
            round(latest + slope_per_sample * steps)
        )

        slope_per_min = slope_per_sample * (
            60 / SNAPSHOT_INTERVAL
        )

        if slope_per_min >= 3:
            trend = "rising"

        elif slope_per_min <= -3:
            trend = "falling"

        else:
            trend = "steady"

        directions.append({
            "direction": label,
            "latest": latest,
            "predicted": predicted,
            "delta": predicted - latest,
            "trend": trend,
            "slope_per_min": round(slope_per_min, 1)
        })

    rising = [
        d["direction"] for d in directions
        if d.get("trend") == "rising"
    ]

    falling = [
        d["direction"] for d in directions
        if d.get("trend") == "falling"
    ]

    if rising and falling:

        summary = (
            f"Building on {', '.join(rising)}, "
            f"easing on {', '.join(falling)}."
        )

    elif rising:

        summary = (
            f"Traffic expected to build on "
            f"{', '.join(rising)} over the next minute."
        )

    elif falling:

        summary = (
            f"Congestion easing on {', '.join(falling)} — "
            f"expect lighter traffic shortly."
        )

    elif directions:

        summary = "Traffic levels expected to hold steady across all lanes."

    else:

        summary = "Collecting samples — forecasts appear shortly."

    return {
        "horizon_sec": horizon_sec,
        "sampled_every_sec": SNAPSHOT_INTERVAL,
        "directions": directions,
        "summary": summary
    }


@app.route("/api/analytics")
def api_analytics():

    """Live analytics: congestion index, per-lane load and insights."""

    if not system_running:

        return jsonify({
            "generated_at": time.strftime("%H:%M:%S"),
            "running": False,
            "total_vehicles": 0,
            "busiest_direction": None,
            "overall_density": "—",
            "congestion_index": 0,
            "directions": [
                {
                    "direction": d.capitalize(),
                    "count": 0,
                    "density": "—",
                    "signal": "RED",
                    "green_time": 0,
                    "share_pct": 0,
                    "fps": 0
                }
                for d in latest_data
            ],
            "trend": analytics_history,
            "forecast": build_forecast(),
            "insights": [
                "System stopped — press Start to resume live analysis."
            ]
        })

    total = sum(
        latest_data[d].get("count", 0)
        for d in latest_data
    )

    dirs = []

    for direction, data in latest_data.items():

        count = data.get("count", 0)

        share_pct = round(
            100 * count / total,
            1
        ) if total else 0

        dirs.append({
            "direction": direction.capitalize(),
            "count": count,
            "density": data.get("density", "—"),
            "signal": data.get("signal", "RED"),
            "green_time": data.get("green_time", 0),
            "share_pct": share_pct,
            "fps": data.get("fps", 0)
        })

    busiest = max(
        dirs,
        key=lambda d: d["count"]
    ) if total else None

    # Congestion index: average density level scaled to 0-100
    weights = [
        DENSITY_WEIGHT.get(d["density"], 0)
        for d in dirs
    ]

    congestion_index = round(
        100 * sum(weights) / (3 * len(weights))
    ) if weights else 0

    if congestion_index >= 67:
        overall_density = "HIGH"

    elif congestion_index >= 34:
        overall_density = "MEDIUM"

    else:
        overall_density = "LOW"

    return jsonify({
        "generated_at": time.strftime("%H:%M:%S"),
        "running": True,
        "total_vehicles": total,
        "busiest_direction": (
            busiest["direction"]
            if busiest
            else None
        ),
        "overall_density": overall_density,
        "congestion_index": congestion_index,
        "directions": dirs,
        "trend": analytics_history,
        "forecast": build_forecast(),
        "insights": build_insights(dirs, busiest, total)
    })


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():

    """Read/tune live stream settings from the dashboard."""

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        infer_width = payload.get("infer_width")

        if infer_width:

            stream_settings["infer_width"] = max(
                160,
                min(1280, int(infer_width))
            )

        controls = payload.get("lanes")

        if isinstance(controls, dict):

            for direction, cfg in controls.items():

                if direction not in lane_controls:
                    continue

                if "enabled" in cfg:

                    lane_controls[direction]["enabled"] = bool(
                        cfg["enabled"]
                    )

                if "max_fps" in cfg:

                    lane_controls[direction]["max_fps"] = max(
                        0,
                        min(30, int(cfg["max_fps"]))
                    )

        print(
            f"[SETTINGS] infer_width={stream_settings['infer_width']}, "
            f"lanes={lane_controls}"
        )

    return jsonify({
        "mode": MODE,
        "infer_width": stream_settings["infer_width"],
        "lanes": lane_controls
    })


@app.route("/api/summary")
def api_summary():

    summary = {}

    # Aggregate counts
    for item in traffic_history:

        key = (
            item["direction"],
            item["hour"]
        )

        if key not in summary:

            summary[key] = {
                "total": 0,
                "samples": 0
            }

        summary[key]["total"] += item["count"]

        summary[key]["samples"] += 1

    # Convert to frontend format
    result = []

    for (direction, hour), values in summary.items():

        avg = (
            values["total"] /
            values["samples"]
        )

        result.append({

            "direction": direction,

            "hour": hour,

            "avg_count": round(avg, 2)
        })

    return jsonify(result)

# =====================================================
# KEEP-ALIVE (free hosts spin down after ~15 min idle)
# =====================================================

KEEPALIVE_ENABLED = os.getenv(
    "KEEPALIVE_ENABLED",
    "1"
).lower() in ("1", "true", "yes")

KEEPALIVE_INTERVAL = int(
    os.getenv(
        "KEEPALIVE_INTERVAL",
        "600"
    )
)

# Optional override, e.g. https://smart-traffic-ai.onrender.com
KEEPALIVE_URL = os.getenv(
    "KEEPALIVE_URL",
    ""
)

# Learned from the first incoming request (scheme://host)
public_base_url = ""


@app.before_request
def record_public_url():

    global public_base_url

    if not public_base_url:

        public_base_url = request.scheme + "://" + request.host


def keepalive_loop():

    """Ping our own public URL so the host never sees 15 min of idle."""

    while True:

        time.sleep(KEEPALIVE_INTERVAL)

        target = KEEPALIVE_URL or public_base_url

        if not target:
            continue

        try:

            urllib.request.urlopen(
                target.rstrip("/") + "/api/keepalive",
                timeout=10
            )

            print(f"[KEEPALIVE] pinged {target}/api/keepalive")

        except Exception as exc:

            print(f"[KEEPALIVE] ping failed: {exc}")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":

    if KEEPALIVE_ENABLED:

        threading.Thread(
            target=keepalive_loop,
            daemon=True
        ).start()

        print(
            f"[INFO] Keep-alive on: pings /api/keepalive every "
            f"{KEEPALIVE_INTERVAL}s"
        )

    socketio.run(

        app,

        host="0.0.0.0",

        port=int(os.getenv("PORT", "5000")),

        debug=os.getenv("FLASK_DEBUG", "0") == "1",

        allow_unsafe_werkzeug=True
    )