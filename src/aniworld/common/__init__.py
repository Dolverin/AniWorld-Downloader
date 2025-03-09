# Importiere die neue Datenbankfunktionalität
from aniworld.common.db import get_db

from .adventure import adventure
from .ascii_art import display_ascii_art
from .common import (check_dependencies, check_if_episode_exists,
                     check_internet_connection, check_package_installation,
                     clean_up_leftovers, clear_screen, countdown,
                     create_advanced_episode_pattern, create_episode_pattern,
                     download_dependencies, execute_command, fetch_anime_id,
                     fetch_url_content, format_anime_title, ftoi,
                     get_anime_season_title, get_description,
                     get_description_with_id, get_language_code,
                     get_language_string, get_random_anime,
                     get_season_and_episode_numbers, get_season_data,
                     get_season_episode_count, get_version, install_and_import,
                     is_tail_running, is_version_outdated,
                     open_terminal_with_command, parse_anime_url,
                     parse_episodes_from_url, print_progress_info,
                     raise_runtime_error, read_episode_file, sanitize_path,
                     search_anime_by_name, self_uninstall, set_terminal_size,
                     setup_anime4k, setup_aniskip, setup_autoexit,
                     setup_autostart, show_messagebox, update_component)

# Import für Tor-Funktionalität
try:
    from aniworld.common.tor_client import TorClient, get_tor_client
except ImportError:
    # Fehlende Tor-Bibliotheken werden bei Bedarf zur Laufzeit gemeldet
    pass


def get_tor_version() -> str:
    """Gibt die Tor-Version zurück, wenn Tor verfügbar ist."""
    try:
        import subprocess
        result = subprocess.run(
            ["tor", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # Format: "Tor version X.Y.Z."
            version_line = result.stdout.strip().split('\n')[0]
            if "version" in version_line:
                return version_line.split("version")[1].strip().rstrip(".")
        return "nicht verfügbar"
    except (FileNotFoundError, subprocess.SubprocessError):
        return "nicht installiert"


def is_tor_running() -> bool:
    """Prüft, ob der Tor-Dienst auf dem System läuft."""
    try:
        import platform
        import subprocess

        if platform.system() == "Windows":
            cmd = ["tasklist", "/FI", "IMAGENAME eq tor.exe", "/NH"]
        else:  # Linux/Mac
            cmd = ["pgrep", "-x", "tor"]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        # Wenn der Prozess gefunden wurde, ist Tor aktiv
        if result.returncode == 0 and result.stdout.strip():
            return True

        return False
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
