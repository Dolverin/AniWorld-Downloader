from .common import (
    check_dependencies,
    clean_up_leftovers,
    clear_screen,
    download_dependencies,
    execute_command,
    fetch_url_content,
    ftoi,
    get_language_code,
    get_language_string,
    get_season_data,
    get_version,
    is_tail_running,
    raise_runtime_error,
    set_terminal_size,
    setup_aniskip,
    get_season_and_episode_numbers,
    setup_anime4k,
    is_version_outdated,
    read_episode_file,
    check_package_installation,
    self_uninstall,
    update_component,
    print_progress_info,
    get_anime_season_title,
    countdown,
    sanitize_path,
    open_terminal_with_command,
    setup_autostart,
    setup_autoexit,
    get_random_anime,
    check_internet_connection,
    show_messagebox,
    get_season_episode_count,
    get_description,
    get_description_with_id,
    fetch_anime_id,
    install_and_import,
    check_if_episode_exists,
    get_tor_version
)

from .ascii_art import display_ascii_art
from .adventure import adventure

# Importiere die neue Datenbankfunktionalität
from aniworld.common.db import get_db

# Import für Tor-Funktionalität
try:
    from aniworld.common.tor_client import get_tor_client, TorClient
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
