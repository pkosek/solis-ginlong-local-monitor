"""
Solar Monitor - Web Dashboard

Serves a lightweight web UI with live metrics and historical charts
for solar generation data collected by the companion collector process.

Configuration is read from environment variables -- see config.py.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

import config as cfg

app = Flask(__name__)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.route("/api/live")
def api_live():
    """Most recent reading."""
    conn = get_db()
    row = conn.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/today")
def api_today():
    """All readings for today (UTC)."""
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        """
        SELECT timestamp, active_power_w, pv1_voltage_v, pv1_current_a,
               ac_voltage_v, temperature_c, energy_today_kwh
        FROM readings WHERE date(timestamp) = ? ORDER BY timestamp
        """,
        (today,),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/history")
def api_history():
    """Power readings for a date range.

    Query params:
        start      -- YYYY-MM-DD (default: 7 days ago)
        end        -- YYYY-MM-DD (default: today)
        resolution -- raw | hourly | daily (default: raw)
    """
    start = request.args.get("start") or (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    end = request.args.get("end") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resolution = request.args.get("resolution", "raw")

    conn = get_db()

    if resolution == "hourly":
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m-%dT%H:00:00Z', timestamp) AS timestamp,
                   AVG(active_power_w) AS active_power_w,
                   MAX(active_power_w) AS peak_power_w,
                   AVG(pv1_voltage_v)  AS pv1_voltage_v,
                   AVG(ac_voltage_v)   AS ac_voltage_v,
                   AVG(temperature_c)  AS temperature_c,
                   MAX(energy_today_kwh) AS energy_today_kwh
            FROM readings
            WHERE date(timestamp) >= ? AND date(timestamp) <= ?
            GROUP BY strftime('%Y-%m-%dT%H', timestamp)
            ORDER BY timestamp
            """,
            (start, end),
        ).fetchall()
    elif resolution == "daily":
        rows = conn.execute(
            """
            SELECT date(timestamp) AS timestamp,
                   AVG(active_power_w) AS active_power_w,
                   MAX(active_power_w) AS peak_power_w,
                   AVG(temperature_c)  AS temperature_c,
                   MAX(energy_today_kwh) AS energy_today_kwh
            FROM readings
            WHERE date(timestamp) >= ? AND date(timestamp) <= ?
            GROUP BY date(timestamp)
            ORDER BY timestamp
            """,
            (start, end),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT timestamp, active_power_w, pv1_voltage_v, pv1_current_a,
                   ac_voltage_v, temperature_c, energy_today_kwh
            FROM readings
            WHERE date(timestamp) >= ? AND date(timestamp) <= ?
            ORDER BY timestamp
            """,
            (start, end),
        ).fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/daily_summary")
def api_daily_summary():
    """Daily energy totals.

    Query params:
        days -- number of days to return (default: 30)
    """
    days = int(request.args.get("days", 30))
    conn = get_db()

    rows = conn.execute(
        "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()

    if not rows:
        rows = conn.execute(
            """
            SELECT date(timestamp) AS date,
                   MAX(energy_today_kwh) AS energy_kwh,
                   MAX(active_power_w)   AS peak_power_w,
                   NULL                  AS peak_power_time,
                   AVG(temperature_c)    AS avg_temperature_c,
                   COUNT(*) * 5.0 / 60   AS generation_hours
            FROM readings WHERE active_power_w > 0
            GROUP BY date(timestamp)
            ORDER BY date DESC LIMIT ?
            """,
            (days,),
        ).fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    """Aggregate statistics."""
    conn = get_db()
    stats: dict = {}

    row = conn.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1").fetchone()
    if row:
        stats["current"] = dict(row)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """
        SELECT MAX(energy_today_kwh) AS energy_today,
               MAX(active_power_w)   AS peak_power_today,
               AVG(temperature_c)    AS avg_temp_today,
               COUNT(*)              AS readings_today
        FROM readings WHERE date(timestamp) = ?
        """,
        (today,),
    ).fetchone()
    if row:
        stats["today"] = dict(row)

    row = conn.execute(
        """
        SELECT COUNT(*) AS total_readings,
               MIN(timestamp) AS first_reading,
               MAX(timestamp) AS last_reading,
               MAX(active_power_w) AS all_time_peak_power
        FROM readings
        """
    ).fetchone()
    if row:
        stats["all_time"] = dict(row)

    rows = conn.execute(
        """
        SELECT date(timestamp) AS date, MAX(energy_today_kwh) AS energy_kwh
        FROM readings GROUP BY date(timestamp)
        ORDER BY date DESC LIMIT 7
        """
    ).fetchall()
    stats["last_7_days"] = [dict(r) for r in rows]

    conn.close()
    return jsonify(stats)


# ---------------------------------------------------------------------------
# Dev server entry point (production uses gunicorn via start.sh)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Solar Monitor Dashboard: http://{cfg.WEB_HOST}:{cfg.WEB_PORT}")
    app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT, debug=True)
