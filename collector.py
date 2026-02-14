"""
Solar Monitor - Data Collector

Polls a Solis inverter via the SolarMAN V5 protocol and stores readings
in a local SQLite database. Designed to run continuously (every POLL_INTERVAL
seconds) as a background process alongside the dashboard.

Configuration is read from environment variables -- see config.py.
"""
import sqlite3
import sys
import time
import logging
from datetime import datetime, timezone

from pysolarmanv5 import PySolarmanV5

import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collector")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    """Create the database and tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            active_power_w REAL,
            reactive_power_var REAL,
            pv1_voltage_v REAL,
            pv1_current_a REAL,
            pv2_voltage_v REAL,
            pv2_current_a REAL,
            ac_voltage_v REAL,
            ac_current_a REAL,
            grid_frequency_hz REAL,
            temperature_c REAL,
            energy_today_kwh REAL,
            energy_total_kwh REAL,
            status INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            energy_kwh REAL,
            peak_power_w REAL,
            peak_power_time TEXT,
            avg_temperature_c REAL,
            generation_hours REAL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_readings_timestamp
        ON readings (timestamp)
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Inverter communication
# ---------------------------------------------------------------------------

def read_inverter() -> dict:
    """Read all relevant Modbus registers from the inverter.

    Register map is based on the Solis single-phase inverter documentation.
    Tested on a Solis-mini-2000-4G with SolarMAN V5 data-logger stick.
    """
    modbus = PySolarmanV5(
        address=cfg.INVERTER_IP,
        serial=cfg.LOGGER_SERIAL,
        port=cfg.MODBUS_PORT,
        mb_slave_id=cfg.SLAVE_ID,
        verbose=False,
        socket_timeout=10,
    )

    data: dict = {}
    try:
        # Active Power (reg 3004, uint32 across 2 registers)
        r = modbus.read_input_registers(register_addr=3004, quantity=2)
        data["active_power_w"] = (r[0] << 16) + r[1]
        time.sleep(0.3)

        # Reactive Power (reg 3006, int32)
        r = modbus.read_input_registers(register_addr=3006, quantity=2)
        val = (r[0] << 16) + r[1]
        data["reactive_power_var"] = val - 4294967296 if val > 2147483647 else val
        time.sleep(0.3)

        # PV1 Voltage & Current (reg 3021-3022)
        r = modbus.read_input_registers(register_addr=3021, quantity=2)
        data["pv1_voltage_v"] = r[0] * 0.1
        data["pv1_current_a"] = r[1] * 0.1
        time.sleep(0.3)

        # PV2 Voltage & Current (reg 3023-3024)
        r = modbus.read_input_registers(register_addr=3023, quantity=2)
        data["pv2_voltage_v"] = r[0] * 0.1
        data["pv2_current_a"] = r[1] * 0.1
        time.sleep(0.3)

        # AC Voltage (reg 3035 -- "Phase B" on single-phase Solis)
        r = modbus.read_input_registers(register_addr=3035, quantity=1)
        data["ac_voltage_v"] = r[0] * 0.1
        time.sleep(0.3)

        # AC Current (reg 3038 -- "Phase C" on single-phase Solis)
        r = modbus.read_input_registers(register_addr=3038, quantity=1)
        data["ac_current_a"] = r[0] * 0.1
        time.sleep(0.3)

        # Temperature (reg 3041, int16, x0.1)
        r = modbus.read_input_registers(register_addr=3041, quantity=1)
        val = r[0]
        data["temperature_c"] = (val - 65536 if val > 32767 else val) * 0.1
        time.sleep(0.3)

        # Grid Frequency (reg 3042, x0.01)
        r = modbus.read_input_registers(register_addr=3042, quantity=1)
        data["grid_frequency_hz"] = r[0] * 0.01
        time.sleep(0.3)

        # Energy Today (reg 3014, x0.1)
        r = modbus.read_input_registers(register_addr=3014, quantity=1)
        data["energy_today_kwh"] = r[0] * 0.1
        time.sleep(0.3)

        # Total Energy (reg 3008, uint32)
        r = modbus.read_input_registers(register_addr=3008, quantity=2)
        data["energy_total_kwh"] = (r[0] << 16) + r[1]
        time.sleep(0.3)

        # Operating Status (reg 3043)
        r = modbus.read_input_registers(register_addr=3043, quantity=1)
        data["status"] = r[0]

    except Exception as exc:
        log.error("Error reading inverter: %s", exc)
        raise
    finally:
        modbus.disconnect()

    return data


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def store_reading(conn: sqlite3.Connection, data: dict) -> None:
    """Insert a single reading row."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO readings (
            timestamp, active_power_w, reactive_power_var,
            pv1_voltage_v, pv1_current_a, pv2_voltage_v, pv2_current_a,
            ac_voltage_v, ac_current_a, grid_frequency_hz,
            temperature_c, energy_today_kwh, energy_total_kwh, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            data.get("active_power_w"),
            data.get("reactive_power_var"),
            data.get("pv1_voltage_v"),
            data.get("pv1_current_a"),
            data.get("pv2_voltage_v"),
            data.get("pv2_current_a"),
            data.get("ac_voltage_v"),
            data.get("ac_current_a"),
            data.get("grid_frequency_hz"),
            data.get("temperature_c"),
            data.get("energy_today_kwh"),
            data.get("energy_total_kwh"),
            data.get("status"),
        ),
    )
    conn.commit()
    log.info(
        "Stored: %sW | PV1: %.1fV/%.1fA | Today: %.1fkWh | Total: %skWh",
        data.get("active_power_w", 0),
        data.get("pv1_voltage_v", 0),
        data.get("pv1_current_a", 0),
        data.get("energy_today_kwh", 0),
        data.get("energy_total_kwh", 0),
    )


def update_daily_summary(conn: sqlite3.Connection) -> None:
    """Upsert the daily summary row for today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """
        SELECT
            MAX(energy_today_kwh),
            MAX(active_power_w),
            AVG(temperature_c),
            COUNT(*) * ? / 60.0
        FROM readings
        WHERE date(timestamp) = ? AND active_power_w > 0
        """,
        (cfg.POLL_INTERVAL, today),
    ).fetchone()

    if row and row[0] is not None:
        peak_row = conn.execute(
            "SELECT timestamp FROM readings WHERE date(timestamp) = ? ORDER BY active_power_w DESC LIMIT 1",
            (today,),
        ).fetchone()
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_summary
                (date, energy_kwh, peak_power_w, peak_power_time, avg_temperature_c, generation_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (today, row[0], row[1], peak_row[0] if peak_row else None, row[2], row[3]),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    if not cfg.INVERTER_IP or not cfg.LOGGER_SERIAL:
        log.error("INVERTER_IP and LOGGER_SERIAL must be set. See .env.example.")
        sys.exit(1)

    conn = init_db(cfg.DB_PATH)

    log.info("Solar Monitor Collector started")
    log.info("  Inverter : %s:%s", cfg.INVERTER_IP, cfg.MODBUS_PORT)
    log.info("  Logger SN: %s", cfg.LOGGER_SERIAL)
    log.info("  Interval : %ss", cfg.POLL_INTERVAL)
    log.info("  Database : %s", cfg.DB_PATH)

    while True:
        try:
            data = read_inverter()
            store_reading(conn, data)
            update_daily_summary(conn)
        except Exception as exc:
            log.error("Collection cycle failed: %s", exc)

        time.sleep(cfg.POLL_INTERVAL)


if __name__ == "__main__":
    main()
