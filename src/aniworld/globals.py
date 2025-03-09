import logging
import os
import random
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import colorlog

# Import der neuen Konfiguration
from aniworld.config import (config, get_default_action, get_default_language,
                             get_default_provider, get_default_watch_provider,
                             get_download_path, get_log_file_path,
                             get_provider_priority, get_terminal_size,
                             is_debug_mode, is_tor_enabled)

# Abwärtskompatibilität: Alte Konstanten auf neue Konfigurationswerte verweisen
IS_DEBUG_MODE = is_debug_mode()
LOG_FILE_PATH = get_log_file_path()

DEFAULT_ACTION = get_default_action()
DEFAULT_DOWNLOAD_PATH = get_download_path()
DEFAULT_LANGUAGE = get_default_language()
DEFAULT_PROVIDER = get_default_provider()
DEFAULT_PROVIDER_WATCH = get_default_watch_provider()
DEFAULT_ANISKIP = config.get("general", "aniskip")
DEFAULT_KEEP_WATCHING = config.get("general", "keep_watching")
DEFAULT_ONLY_DIRECT_LINK = config.get("advanced", "only_direct_link")
DEFAULT_ONLY_COMMAND = config.get("advanced", "only_command")
DEFAULT_PROXY = config.get("advanced", "proxy")
DEFAULT_USE_PLAYWRIGHT = config.get("advanced", "use_playwright")
DEFAULT_TERMINAL_SIZE = get_terminal_size()

# Tor-Konfiguration
USE_TOR = is_tor_enabled()
TOR_AUTO_RETRY = config.get("tor", "auto_retry")
TOR_MAX_RETRIES = config.get("tor", "max_retries")

# Provider-Priorität
PROVIDER_PRIORITY = get_provider_priority()

log_colors = {
    'DEBUG': 'bold_blue',
    'INFO': 'bold_green',
    'WARNING': 'bold_yellow',
    'ERROR': 'bold_red',
    'CRITICAL': 'bold_purple'
}


def setup_file_handler():
    try:
        # Verwende RotatingFileHandler anstelle von FileHandler
        # für automatische Rotation bei Größenüberschreitung
        from logging.handlers import RotatingFileHandler

        # Erstelle das Verzeichnis für die Logdatei, falls es nicht existiert
        log_dir = os.path.dirname(LOG_FILE_PATH)
        os.makedirs(log_dir, exist_ok=True)

        # Erstelle einen RotatingFileHandler mit maximal 5MB pro Datei
        # und maximal 3 Backup-Dateien
        handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding='utf-8'
        )

        # Setze ein klares Format für die Logeinträge
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        return handler
    except Exception as e:
        print(f"Fehler beim Einrichten des Datei-Log-Handlers: {e}")
        return None


file_handler = setup_file_handler()
console_handler = colorlog.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors=log_colors
))

handlers = [console_handler]
if file_handler:
    handlers.append(file_handler)

logging.basicConfig(
    level=logging.DEBUG if IS_DEBUG_MODE else logging.INFO,
    handlers=handlers
)

logging.getLogger('urllib3').setLevel(logging.WARNING)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) "
    "Gecko/20100101 Firefox/130.",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.3",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; rv:109.0) Gecko/20100101 Firefox/115.",
    "Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Geck",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Config/91.2.1916.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 OPR/112.0.0.",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128."]

DEFAULT_USER_AGENT = random.choice(USER_AGENTS)


class ExitOnError(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            sys.exit(1)


exit_on_error_handler = ExitOnError()
logging.getLogger().addHandler(exit_on_error_handler)
