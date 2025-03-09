"""
Konfigurationsmodul für Aniworld-Downloader.

Dieses Modul stellt Funktionen und Klassen bereit, um Konfigurationseinstellungen 
zu verwalten. Es lädt Einstellungen aus einer Konfigurationsdatei (falls vorhanden)
und stellt Standardwerte bereit.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple

# Standardpfad für die Konfigurationsdatei
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "aniworld")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Standardwerte für Konfigurationseinstellungen
DEFAULT_CONFIG = {
    # Allgemeine Einstellungen
    "general": {
        "action": "Download",             # Standardaktion (Download, Watch, Syncplay)
        "download_path": "/mnt/Plex",     # Standardpfad für Downloads
        "language": "German Dub",         # Standardsprache (German Dub, English Sub, German Sub)
        "aniskip": False,                 # Aniskip standardmäßig aktivieren?
        "keep_watching": False,           # Nach dem Ansehen weitermachen?
        "terminal_size": [90, 38],        # Standardgröße für das Terminal
        "debug_mode": False,              # Debug-Modus aktivieren?
        "log_file_path": os.path.join(os.path.expanduser('~'), "aniworld.log"),  # Pfad zur Logdatei
    },
    
    # Provider-Einstellungen
    "providers": {
        "default_provider": "VOE",        # Standardprovider für Downloads
        "default_watch_provider": "Doodstream",  # Standardprovider zum Ansehen
        "provider_priority": [            # Priorität der Provider
            "VOE",
            "Vidoza",
            "Streamtape",
            "Doodstream",
            "Vidmoly",
            "SpeedFiles"
        ]
    },
    
    # Tor-Einstellungen
    "tor": {
        "use_tor": False,                 # Tor verwenden?
        "auto_retry": True,               # Automatisch neue IP holen bei Sperre?
        "max_retries": 3                  # Maximale Anzahl an Versuchen mit neuer IP
    },
    
    # Erweiterte Einstellungen
    "advanced": {
        "only_direct_link": False,        # Nur direkte Links ausgeben?
        "only_command": False,            # Nur Befehle ausgeben?
        "use_playwright": False,          # Playwright für das Rendering verwenden?
        "proxy": None                     # Proxy-Einstellungen
    }
}


class Config:
    """
    Konfigurationsklasse für Aniworld-Downloader.
    
    Diese Klasse lädt Konfigurationseinstellungen aus einer Datei und stellt
    Methoden bereit, um auf diese Einstellungen zuzugreifen und sie zu ändern.
    """
    
    def __init__(self, config_file: str = CONFIG_FILE) -> None:
        """
        Initialisiert eine neue Konfigurationsinstanz.
        
        Args:
            config_file: Pfad zur Konfigurationsdatei
        """
        self.config_file = config_file
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
    
    def load_config(self) -> None:
        """
        Lädt die Konfiguration aus der Konfigurationsdatei.
        
        Wenn die Datei nicht existiert, wird die Standardkonfiguration verwendet.
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                
                # Merge user config with default config
                for section in user_config:
                    if section in self.config:
                        self.config[section].update(user_config[section])
                    else:
                        self.config[section] = user_config[section]
                
                logging.debug("Konfiguration aus %s geladen", self.config_file)
            else:
                logging.debug("Keine Konfigurationsdatei gefunden, verwende Standardwerte")
                self.save_config()  # Erstelle die Standardkonfigurationsdatei
        except Exception as e:
            logging.error("Fehler beim Laden der Konfiguration: %s", e)
            # Verwende Standardwerte bei Fehler
    
    def save_config(self) -> None:
        """
        Speichert die aktuelle Konfiguration in der Konfigurationsdatei.
        """
        try:
            # Erstelle Verzeichnis, falls es nicht existiert
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            
            logging.debug("Konfiguration in %s gespeichert", self.config_file)
        except Exception as e:
            logging.error("Fehler beim Speichern der Konfiguration: %s", e)
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Gibt den Wert für einen Schlüssel in einer Sektion zurück.
        
        Args:
            section: Die Sektion der Konfiguration
            key: Der Schlüssel in der Sektion
            default: Der Standardwert, falls der Schlüssel nicht existiert
            
        Returns:
            Der Wert des Schlüssels oder der Standardwert
        """
        try:
            return self.config[section][key]
        except (KeyError, TypeError):
            return default
    
    def set(self, section: str, key: str, value: Any) -> None:
        """
        Setzt den Wert für einen Schlüssel in einer Sektion.
        
        Args:
            section: Die Sektion der Konfiguration
            key: Der Schlüssel in der Sektion
            value: Der zu setzende Wert
        """
        try:
            if section not in self.config:
                self.config[section] = {}
            
            self.config[section][key] = value
            self.save_config()
        except Exception as e:
            logging.error("Fehler beim Setzen der Konfiguration: %s", e)


# Globale Konfigurationsinstanz
config = Config()


# Hilfsfunktionen, um leichter auf häufig verwendete Konfigurationseinstellungen zuzugreifen
def get_download_path() -> str:
    """Gibt den Standardpfad für Downloads zurück."""
    return config.get("general", "download_path")


def get_default_action() -> str:
    """Gibt die Standardaktion zurück."""
    return config.get("general", "action")


def get_default_language() -> str:
    """Gibt die Standardsprache zurück."""
    return config.get("general", "language")


def get_default_provider() -> str:
    """Gibt den Standardprovider zurück."""
    return config.get("providers", "default_provider")


def get_default_watch_provider() -> str:
    """Gibt den Standardprovider zum Ansehen zurück."""
    return config.get("providers", "default_watch_provider")


def get_provider_priority() -> List[str]:
    """Gibt die Priorität der Provider zurück."""
    return config.get("providers", "provider_priority")


def is_tor_enabled() -> bool:
    """Prüft, ob Tor aktiviert ist."""
    # Umgebungsvariable hat Vorrang vor Konfigurationsdatei
    env_tor = os.getenv('USE_TOR', '').lower() in ('true', '1', 't', 'y', 'yes')
    return env_tor or config.get("tor", "use_tor")


def is_debug_mode() -> bool:
    """Prüft, ob der Debug-Modus aktiviert ist."""
    # Umgebungsvariable hat Vorrang vor Konfigurationsdatei
    env_debug = os.getenv('IS_DEBUG_MODE', '').lower() in ('true', '1', 't', 'y', 'yes')
    return env_debug or config.get("general", "debug_mode")


def get_terminal_size() -> Tuple[int, int]:
    """Gibt die Standardgröße für das Terminal zurück."""
    size = config.get("general", "terminal_size")
    return (size[0], size[1]) if isinstance(size, list) and len(size) == 2 else (90, 38)


def get_log_file_path() -> str:
    """Gibt den Pfad zur Logdatei zurück."""
    return config.get("general", "log_file_path") 