"""Constants shared by the Cinema Studio integration."""

from datetime import timedelta

DOMAIN = "cinema_studio"
EVENT_CATALOG_CHANGED = "cinema_studio_catalog_changed"
EVENT_SELECTED = "cinema_studio_selected"
CONF_HOST, CONF_PORT, CONF_TOKEN = "host", "port", "token"
CONF_SEASON_ENTITY, CONF_SCAN_INTERVAL = "season_entity", "scan_interval"
CONF_HISTORY_RESET_MODE, CONF_HISTORY_RESET_TIME = "history_reset_mode", "history_reset_time"
DEFAULT_PORT = 8099
DEFAULT_SCAN_INTERVAL = 30
STORAGE_VERSION = 1
REGULAR = "regular"
CONTRACT_VERSION = 1
MEDIA_SUBDIR = "cinema-studio"
RENDERS_SUBDIR = "cinema-studio/renders"
PIN_TTL = timedelta(hours=6)
LEGACY_DOMAIN = "cinema_collections"
