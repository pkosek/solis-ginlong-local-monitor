"""
Shared configuration for Solar Monitor.

All settings are read from environment variables with sensible defaults.
For Docker deployments, set variables in the .env file next to docker-compose.yml.
"""
import os
from pathlib import Path

# --- Inverter connection (REQUIRED: INVERTER_IP and LOGGER_SERIAL) ---
INVERTER_IP = os.environ.get("INVERTER_IP", "")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "0"))
MODBUS_PORT = int(os.environ.get("MODBUS_PORT", "8899"))
SLAVE_ID = int(os.environ.get("SLAVE_ID", "1"))

# --- Collection ---
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))

# --- Dashboard ---
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))

# --- Storage ---
# In Docker the /data volume is mounted; outside Docker fall back to project dir
_DATA_DIR = Path("/data") if Path("/data").is_dir() else Path(__file__).parent
DB_PATH = str(_DATA_DIR / os.environ.get("DB_FILENAME", "solar_data.db"))
