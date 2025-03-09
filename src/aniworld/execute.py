import os
import shutil
import getpass
import platform
import hashlib
import logging
import time
import sys
import traceback
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup

from aniworld.globals import PROVIDER_PRIORITY, DEFAULT_DOWNLOAD_PATH, USE_TOR
from aniworld.common import (
    clean_up_leftovers,
    execute_command,
    setup_aniskip,
    fetch_url_content,
    check_dependencies,
    get_language_string,
    get_season_and_episode_numbers,
    print_progress_info,
    countdown,
    sanitize_path,
    setup_autostart,
    setup_autoexit
)

from aniworld.extractors import (
    doodstream_get_direct_link,
    streamtape_get_direct_link,
    vidoza_get_direct_link,
    voe_get_direct_link,
    vidmoly_get_direct_link,
    speedfiles_get_direct_link
)

from aniworld.aniskip import aniskip


def providers(soup: BeautifulSoup) -> Dict[str, Dict[int, str]]:
    logging.debug("Extracting provider data from soup")
    try:
        provider_options = soup.find(class_='hosterSiteVideo') \
            .find('ul', class_='row') \
            .find_all('li')

        extracted_data = {}
        for provider in provider_options:
            lang_key = int(provider.get('data-lang-key'))
            redirect_link = provider.get('data-link-target')
            provider_name = provider.find('h4').text.strip()
            if provider_name not in extracted_data:
                extracted_data[provider_name] = {}
            extracted_data[provider_name][lang_key] = f"https://aniworld.to{redirect_link}"
        logging.debug("Extracted provider data: %s", extracted_data)
        return extracted_data
    except AttributeError:
        return None


def build_command(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    link: str, mpv_title: str, player: str, aniskip_selected: bool, selected_provider: str,
    aniskip_options: Optional[List[str]] = None
) -> List[str]:
    logging.debug(
        "Building command for mpv with link: %s, title: %s, player: %s, "
        "aniskip_selected: %s, aniskip_options: %s",
        link, mpv_title, player, aniskip_selected, aniskip_options
    )
    command = [
        player,
        link,
        "--fs",
        "--quiet",
        "--really-quiet",
        "--profile=fast",
        "--hwdec=auto-safe",
        "--video-sync=display-resample",
        f"--force-media-title={mpv_title}"
    ]

    doodstream_referer = "https://dood.li/"
    vidmoly_referer = "https://vidmoly.to/"

    if selected_provider == "Doodstream":
        command.append(f"--http-header-fields=Referer: {doodstream_referer}")
    elif selected_provider == "Vidmoly":
        command.append(f"--http-header-fields=Referer: {vidmoly_referer}")

    if aniskip_selected:
        logging.debug("Aniskip selected, setting up aniskip")
        setup_aniskip()
        if aniskip_options:
            logging.debug("Adding aniskip options: %s", aniskip_options)
            command.extend(aniskip_options)

    logging.debug("Built command: %s", command)
    return command


def build_yt_dlp_command(link: str, output_file: str, selected_provider: str) -> List[str]:
    logging.debug("Building yt-dlp command with link: %s, output_file: %s", link, output_file)
    command = [
        "yt-dlp",
        "--fragment-retries", "infinite",
        "--concurrent-fragments", "4",
        "-o", output_file,
        "--quiet",
        "--no-warnings",
        link,
        "--progress"
    ]

    doodstream_referer = "https://dood.li/"
    vidmoly_referer = "https://vidmoly.to/"

    if selected_provider == "Doodstream":
        command.append("--add-header")
        command.append(f"Referer: {doodstream_referer}")
    elif selected_provider == "Vidmoly":
        command.append("--add-header")
        command.append(f"Referer: {vidmoly_referer}")
    
    # Tor-Proxy hinzufügen, wenn USE_TOR aktiviert ist
    if USE_TOR:
        try:
            from aniworld.common.tor_client import get_tor_client
            
            tor_client = get_tor_client(use_tor=True)
            if tor_client and tor_client.is_running:
                proxy_dict = tor_client.get_proxy_dict()
                socks_proxy = proxy_dict.get('http', '').replace('http://', '')
                
                if socks_proxy:
                    logging.info(f"yt-dlp verwendet Tor-Proxy: {socks_proxy}")
                    command.append("--proxy")
                    command.append(f"socks5://{socks_proxy}")
        except ImportError:
            logging.error("Tor-Unterstützung ist nicht verfügbar. Stelle sicher, dass die PySocks und stem Module installiert sind.")
        except Exception as e:
            logging.error(f"Fehler beim Einrichten des Tor-Proxys für yt-dlp: {str(e)}")

    logging.debug("Built yt-dlp command: %s", command)
    return command


def process_aniskip(
    anime_title: str, season_number: int, episode_number: int, anime_slug: str
) -> List[str]:
    logging.debug(
        "Processing aniskip for %s, season %d, episode %d",
        anime_title, season_number, episode_number
    )

    skip_options = aniskip(
        anime_title=anime_title,
        anime_slug=anime_slug,
        episode=episode_number,
        season=season_number
    )
    skip_options_list = skip_options.split(' --')
    processed_options = [
        f"--{opt}" if not opt.startswith('--') else opt
        for opt in skip_options_list
    ]
    logging.debug("Processed aniskip options: %s", processed_options)
    return processed_options


def get_episode_title(soup: BeautifulSoup) -> str:
    logging.debug("Getting episode title from soup")
    german_title_tag = soup.find('span', class_='episodeGermanTitle')
    english_title_tag = soup.find('small', class_='episodeEnglishTitle')

    episode_german_title = german_title_tag.text if german_title_tag else None
    episode_english_title = english_title_tag.text if english_title_tag else None

    episode_title = (
        f"{episode_german_title} / {episode_english_title}"
        if episode_german_title and episode_english_title
        else episode_german_title or episode_english_title
    )

    logging.debug("Episode title: %s", episode_title)
    return episode_title


def get_anime_title(soup: BeautifulSoup) -> str:
    logging.debug("Getting anime title from soup")
    try:
        anime_title = soup.find('div', class_='hostSeriesTitle').text
    except AttributeError:
        logging.warning("Could not use the link provided. Please try using a different one.")
    if 'anime_title' in locals():
        logging.debug("Anime title: %s", anime_title)
        return anime_title
    return None


def get_provider_data(soup: BeautifulSoup) -> Dict[str, Dict[int, str]]:
    logging.debug("Getting provider data from soup")
    data = providers(soup)
    logging.debug("Provider data: %s", data)
    return data


def fetch_direct_link(provider_function, request_url: str) -> str:
    logging.debug("Fetching direct link from URL: %s", request_url)
    html_content = fetch_url_content(request_url)
    soup = BeautifulSoup(html_content, 'html.parser')
    direct_link = provider_function(soup)
    logging.debug("Fetched direct link: %s", direct_link)
    return direct_link


def build_syncplay_command(
    link: str, mpv_title: str, selected_provider: str, aniskip_options: Optional[List[str]] = None
) -> List[str]:
    logging.debug(
        "Building syncplay command with link: %s, title: %s, aniskip_options: %s",
        link, mpv_title, aniskip_options
    )
    syncplay = "SyncplayConsole" if platform.system() == "Windows" else "syncplay"
    anime_title = mpv_title.split(" - ")[0].replace(" ", "_")

    syncplay_password = os.getenv("SYNCPLAY_PASSWORD")
    syncplay_hostname = os.getenv("SYNCPLAY_HOSTNAME")
    syncplay_username = os.getenv("SYNCPLAY_USERNAME")
    syncplay_room = os.getenv("SYNCPLAY_ROOM")

    logging.debug(
        "Syncplay hostname: %s, Syncplay username: %s, Syncplay room: %s",
        syncplay_hostname,
        syncplay_username,
        syncplay_room
    )

    if syncplay_password:
        room_name = (
            f"aniworld-{hashlib.sha256((syncplay_password + anime_title).encode()).hexdigest()}"
        )
    else:
        room_name = f"aniworld-{hashlib.sha256(anime_title.encode()).hexdigest()}"

    if not syncplay_hostname:
        syncplay_hostname = "syncplay.pl:8997"

    if not syncplay_username:
        syncplay_username = getpass.getuser()

    if syncplay_room:
        room_name = syncplay_room

    command = [
        syncplay,
        "--no-gui",
        "--no-store",
        "--host", syncplay_hostname,
        "--name", syncplay_username,
        "--room", room_name,
        "--player-path", shutil.which("mpv"),
    ]
    if syncplay_password:
        password_hash = hashlib.sha256(
            ("aniworld" + syncplay_password + anime_title).encode()
        ).hexdigest()
        command.extend(["--password", password_hash])
    command.extend([
        link,
        "--",
        "--profile=fast",
        "--hwdec=auto-safe",
        "--fs",
        "--video-sync=display-resample",
        f"--force-media-title={mpv_title}"
    ])

    doodstream_referer = "https://dood.li/"
    vidmoly_referer = "https://vidmoly.to/"

    if selected_provider == "Doodstream":
        command.append(f"--http-header-fields=Referer: {doodstream_referer}")
    elif selected_provider == "Vidmoly":
        command.append(f"--http-header-fields=Referer: {vidmoly_referer}")

    if aniskip_options:
        logging.debug("Aniskip options provided, setting up aniskip")
        setup_aniskip()
        command.extend(aniskip_options)

    logging.debug("Built syncplay command: %s", command)
    return command


def perform_action(params: Dict[str, Any]) -> None:
    logging.debug("Performing action with params: %s", params)
    action = params.get("action")
    link = params.get("link")
    mpv_title = params.get("mpv_title")
    anime_title = params.get("anime_title")
    anime_slug = params.get("anime_slug")
    episode_number = params.get("episode_number")
    season_number = params.get("season_number")
    only_command = params.get("only_command", False)
    provider = params.get("provider")
    aniskip_selected = bool(params.get("aniskip_selected", False))

    logging.debug("aniskip_selected: %s", aniskip_selected)

    aniskip_options = process_aniskip_options(
        aniskip_selected=aniskip_selected,
        anime_title=anime_title,
        season_number=season_number,
        episode_number=episode_number,
        anime_slug=anime_slug
    )

    if action == "Watch":
        if not only_command:
            if not platform.system() == "Windows":
                countdown()
        handle_watch_action(
            link, mpv_title, aniskip_selected, aniskip_options, only_command, provider
        )
    elif action == "Download":
        handle_download_action(params)
    elif action == "Syncplay":
        if not only_command:
            if not platform.system() == "Windows":
                countdown()
        setup_autostart()
        setup_autoexit()
        handle_syncplay_action(
            link, mpv_title, aniskip_options, only_command, provider
        )


def process_aniskip_options(
    aniskip_selected: bool,
    anime_title: str,
    season_number: int,
    episode_number: int,
    anime_slug: str
) -> List[str]:
    if aniskip_selected:
        logging.debug("Aniskip is selected, processing aniskip options")
        aniskip_options = process_aniskip(
            anime_title=anime_title,
            season_number=season_number,
            episode_number=episode_number,
            anime_slug=anime_slug
        )
        logging.debug("Aniskip options: %s", aniskip_options)
    else:
        logging.debug("Aniskip is not selected, skipping aniskip options")
        aniskip_options = []
    return aniskip_options


def handle_watch_action(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    link: str,
    mpv_title: str,
    aniskip_selected: bool,
    aniskip_options: List[str],
    only_command: bool,
    selected_provider: str
) -> None:
    logging.debug("Action is Watch")
    mpv_title = mpv_title.replace(" --- ", " - ", 1)
    check_dependencies(["mpv"])
    if not only_command:
        msg = f"Playing '{mpv_title}'"
        if not platform.system() == "Windows":
            print(msg)
        else:
            print_progress_info(msg)
    command = build_command(
        link, mpv_title, "mpv", aniskip_selected, selected_provider, aniskip_options)
    logging.debug("Executing command: %s", command)
    execute_command(command, only_command)
    logging.debug("MPV has finished.\nBye bye!")


def handle_download_action(params: Dict[str, Any]) -> None:
    logging.debug("Action is Download")
    
    # Funktion für die Übersetzung der Sprachkodes
    def get_language_from_key(key: int) -> str:
        key_mapping = {
            1: "German Dub",
            2: "English Sub",
            3: "German Sub"
        }
        
        language = key_mapping.get(key, "Unknown Key")
        
        if language == "Unknown Key":
            raise ValueError("Key not valid.")
            
        return language
    
    # Initialisiere Variablen für Download-Statistiken
    download_speed = 0.0
    file_size = 0
    download_duration = 0.0
    download_status = "completed"  # Standardstatus
    
    # Download-Startzeit
    download_start_time = time.time()
    
    download_path = os.path.expanduser(DEFAULT_DOWNLOAD_PATH)
    direct_link = params['direct_link']
    logging.debug("Direct link: %s", direct_link)

    # Verzeichnis erstellen, falls es nicht existiert
    os.makedirs(download_path, exist_ok=True)

    if not os.path.isdir(download_path):
        logging.critical("Download path %s is not a directory", download_path)
        sys.exit(1)

    anime_title = params['anime_title']
    logging.debug("Anime title: %s", anime_title)

    sanitized_anime_title = sanitize_path(anime_title)
    anime_dir = os.path.join(download_path, sanitized_anime_title)
    os.makedirs(anime_dir, exist_ok=True)

    selected_provider = params['provider']
    language = get_language_string(int(params['language']))
    logging.debug("Selected provider: %s language: %s", selected_provider, language)

    if params['season_title'] and params['episode_title']:
        season_title = params['season_title']
        episode_title = params['episode_title']
    else:
        season_number = int(params['season_number'])
        episode_number = int(params['episode_number'])
        season_title = f"Staffel {season_number}"
        episode_title = f"Folge {episode_number}"

    logging.debug("Season title: %s, Episode title: %s", season_title, episode_title)

    # Formatierte Staffel- und Episodennummern für das Standardformat
    if params.get('season_number'):
        season_num = int(params['season_number'])
        episode_num = int(params['episode_number'])
        
        # Formatiere die Episoden- und Staffelnummern mit führenden Nullen
        if season_num < 10:
            season_str = f"00{season_num}"
        elif season_num < 100:
            season_str = f"0{season_num}"
        else:
            season_str = str(season_num)
            
        if episode_num < 10:
            episode_str = f"00{episode_num}"
        elif episode_num < 100:
            episode_str = f"0{episode_num}"
        else:
            episode_str = str(episode_num)
            
        # Verwende das Standardformat mit S000E000
        file_name = f"{sanitized_anime_title} - S{season_str}E{episode_str} ({language}).mp4"
    else:
        # Falls keine Season/Episode-Nummern vorhanden sind, verwende die Titel-Version
        file_name = f"{sanitized_anime_title} - {season_title} - {episode_title} [{language}].mp4"
    
    file_path = os.path.join(anime_dir, file_name)
    logging.debug("File path: %s", file_path)

    # Überprüfen, ob die Datei bereits existiert
    if os.path.exists(file_path) and not params['force_download']:
        if params['only_direct_link']:
            print(direct_link)
        elif params['only_command']:
            print(" ".join(
                build_yt_dlp_command(direct_link, file_path, selected_provider))
            )
        elif os.path.getsize(file_path) > 0:  # Datei existiert und ist nicht leer
            logging.info("Datei existiert bereits: %s", file_path)
            print_progress_info(f"Datei existiert bereits: '{file_path}'")
            download_status = "skipped"
        else:  # Datei existiert aber ist leer (möglicherweise abgebrochener Download)
            logging.warning("Leere Datei gefunden, starte Download neu: %s", file_path)
            os.remove(file_path)  # Leere Datei entfernen
            command = build_yt_dlp_command(direct_link, file_path, selected_provider)
            try:
                execute_command(command, params['only_command'])
            except KeyboardInterrupt:
                logging.debug("KeyboardInterrupt encountered, cleaning up leftovers")
                clean_up_leftovers(os.path.dirname(file_path))
                download_status = "cancelled"
            except Exception as e:
                logging.error(f"Download-Fehler: {e}")
                download_status = "failed"
    else:
        command = build_yt_dlp_command(direct_link, file_path, selected_provider)
        
        max_download_attempts = 3 if USE_TOR else 1
        download_attempt = 0
        success = False
        
        while download_attempt < max_download_attempts and not success:
            try:
                if download_attempt > 0:
                    logging.info(f"Download-Wiederholungsversuch {download_attempt}/{max_download_attempts-1}")
                    
                    # Bei Tor-Nutzung eine neue IP-Adresse anfordern
                    if USE_TOR:
                        try:
                            from aniworld.common.tor_client import get_tor_client
                            tor_client = get_tor_client(use_tor=True)
                            tor_client.new_identity()
                            logging.info("Neue Tor-IP für Download-Wiederholungsversuch angefordert")
                        except ImportError:
                            logging.error("Tor-Unterstützung ist nicht verfügbar. Stelle sicher, dass die PySocks und stem Module installiert sind.")
                        except Exception as e:
                            logging.error(f"Fehler beim Wechseln der Tor-IP: {e}")
                
                execute_command(command, params['only_command'])
                
                # Download erfolgreich abgeschlossen, Statistiken erfassen
                download_end_time = time.time()
                download_duration = download_end_time - download_start_time
                
                # Dateigröße ermitteln, falls die Datei existiert
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    # Durchschnittsgeschwindigkeit berechnen (Bytes/Sekunde)
                    if download_duration > 0:
                        download_speed = file_size / download_duration
                
                success = True
                download_status = "completed"
                
            except KeyboardInterrupt:
                logging.debug("KeyboardInterrupt encountered, cleaning up leftovers")
                clean_up_leftovers(os.path.dirname(file_path))
                download_status = "cancelled"
                break
                
            except Exception as e:
                logging.error(f"Download-Fehler: {e}")
                download_status = "failed"
                download_attempt += 1
                
                # Wenn weitere Versuche möglich sind, kurz warten
                if download_attempt < max_download_attempts:
                    time.sleep(2)
                else:
                    logging.error(f"Maximale Anzahl an Download-Versuchen ({max_download_attempts}) erreicht.")
    
    # Download-Statistiken in der Datenbank speichern
    try:
        from aniworld.common.db import get_db
        db = get_db()
        
        # Original-Staffel- und Episodennummern für die DB verwenden
        db.save_download_stats(
            anime_title=params['anime_title'],
            season=params['season_number'],
            episode=params['episode_number'],
            language=get_language_from_key(int(params['language'])),
            provider=params['provider'],
            download_speed=download_speed,
            file_size=file_size,
            download_duration=download_duration,
            status=download_status
        )
        logging.debug(f"Download-Statistik erfasst: Status={download_status}, Dauer={download_duration:.2f}s, Größe={file_size or 'unbekannt'}")

        # Aktualisiere die Datenbank-Indizierung für das Anime-Verzeichnis
        if download_status == "completed" and os.path.exists(file_path):
            anime_dir = os.path.dirname(file_path)
            logging.info(f"Aktualisiere Datenbank-Index für neu heruntergeladene Episode in: {anime_dir}")
            db.scan_directory(anime_dir, force_rescan=True)
            logging.info("Datenbank-Index aktualisiert")
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Download-Statistik oder beim Aktualisieren des Index: {e}")
    
    logging.debug("yt-dlp has finished.\nBye bye!")
    if not platform.system() == "Windows":
        print(f"Downloaded to '{file_path}'")
    else:
        print_progress_info(f"Downloaded to '{file_path}'")


def handle_syncplay_action(
    link: str,
    mpv_title: str,
    aniskip_options: List[str],
    only_command: bool,
    selected_provider: str
) -> None:
    logging.debug("Action is Syncplay")
    mpv_title = mpv_title.replace(" --- ", " - ", 1)
    check_dependencies(["mpv", "syncplay"])
    if not only_command:
        msg = f"Playing '{mpv_title}'"
        if not platform.system() == "Windows":
            print(msg)
        else:
            print_progress_info(msg)
    command = build_syncplay_command(link, mpv_title, selected_provider, aniskip_options)
    logging.debug("Executing command: %s", command)
    execute_command(command, only_command)
    logging.debug("Syncplay has finished.\nBye bye!")


def execute(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Führt die Verarbeitung einer Episode mit den angegebenen Parametern aus.
    
    Args:
        params: Die Parameter für die Verarbeitung
        
    Returns:
        Optional[Dict]: Bei Erfolg None, bei Fehler ein Dict mit Fehlermeldungen
    """
    logging.debug("Executing with params: %s", params)

    try:
        if 'episode_url' in params:
            # Neue Methode: Verarbeite eine einzelne Episode direkt
            return process_episode(params)
        elif 'selected_episodes' in params:
            # Alte Methode: Verarbeite mehrere Episoden nacheinander
            errors = []
            for episode_url in params['selected_episodes']:
                # Parameter für die Episode erstellen
                episode_params = params.copy()
                episode_params['episode_url'] = episode_url
                if 'selected_episodes' in episode_params:
                    del episode_params['selected_episodes']
                
                # Episode verarbeiten
                result = process_episode(episode_params)
                if result:  # Fehler aufgetreten
                    errors.append(result)
            
            # Ergebnis zurückgeben
            if errors:
                return errors[0]  # Erstmal nur den ersten Fehler zurückgeben
            return None
        else:
            logging.error("Weder episode_url noch selected_episodes in params angegeben")
            return {
                "error": "Fehlende Parameter",
                "message": "Weder episode_url noch selected_episodes in params angegeben"
            }
    except Exception as e:
        logging.exception(f"Unerwarteter Fehler bei der Ausführung: {e}")
        return {
            "error": "Ausführungsfehler",
            "message": f"Unerwarteter Fehler: {str(e)}",
            "details": traceback.format_exc()
        }


def process_episode(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Verarbeitet eine Episode und führt die ausgewählte Aktion aus.
    
    Args:
        params: Parameter für die Verarbeitung
        
    Returns:
        Optional[Dict]: Bei Erfolg None, bei Fehler ein Dict mit Fehlermeldungen
    """
    logging.debug("Processing episode with params: %s", params)

    try:
        html_content = fetch_url_content(params['episode_url'])

        if not html_content:
            logging.error("Konnte keine HTML-Inhalte für URL abrufen: %s", params['episode_url'])
            return {
                "error": "Verbindungsfehler",
                "message": f"Konnte keine HTML-Inhalte für die Episode abrufen.",
                "details": "Bitte überprüfen Sie Ihre Internetverbindung oder versuchen Sie es später erneut."
            }

        soup = BeautifulSoup(html_content, 'html.parser')
        provider_data = providers(soup)

        # Get anime, season, and episode titles
        anime_title = params.get('anime_title') or get_anime_title(soup)
        episode_name = get_episode_title(soup)

        # Process the anime, season, and episode numbers
        season_number, episode_number = get_season_and_episode_numbers(params['episode_url'])

        # Extract season and episode titles from the URL
        parts = params['episode_url'].split('/')
        if len(parts) >= 7 and 'staffel-' in parts[-2]:
            season_title = parts[-2].replace('-', ' ').title()
        elif len(parts) >= 6 and 'filme' in parts[-2]:
            season_title = "Movie"
            season_number = 0
        else:
            season_title = f"Staffel {season_number}" if season_number else "Movie"

        if len(parts) >= 7 and 'episode-' in parts[-1]:
            episode_title = parts[-1].replace('-', ' ').title()
        elif len(parts) >= 6 and 'film-' in parts[-1]:
            episode_title = parts[-1].replace('-', ' ').title()
        else:
            episode_title = f"Folge {episode_number}" if episode_number else "Movie"

        # Use the provider preference order defined in the module
        provider_tried = False
        for provider in PROVIDER_PRIORITY:
            if provider in provider_data:
                provider_tried = True
                logging.info("Versuche Provider: %s", provider)
                try:
                    process_provider(provider, provider_data, params, anime_title, season_title, episode_title)
                    return None  # Erfolg - kein Fehler
                except ValueError as e:
                    logging.warning("Provider %s fehlgeschlagen: %s", provider, str(e))
                    continue  # Try the next provider
                except Exception as e:
                    logging.error("Unerwarteter Fehler bei Provider %s: %s", provider, str(e))
                    continue  # Try the next provider

        # If we reached here, all providers failed
        if provider_tried:
            # Sammle alle verfügbaren Sprachen
            available_languages = set()
            for provider in provider_data:
                for lang_key in provider_data[provider]:
                    lang = get_language_string(lang_key)
                    available_languages.add(lang)
            
            logging.error("Alle verfügbaren Provider sind fehlgeschlagen für Episode: %s", params['episode_url'])
            return {
                "error": "Keine passenden Provider",
                "message": f"Keine Provider für {get_language_string(int(params['language']))} verfügbar.",
                "available_languages": sorted(list(available_languages)),
                "episode_url": params['episode_url']
            }
        else:
            logging.error("Keine unterstützten Provider für die URL verfügbar: %s", params['episode_url'])
            return {
                "error": "Keine Provider",
                "message": "Keine unterstützten Provider für diese Episode gefunden.",
                "available_languages": [],
                "episode_url": params['episode_url']
            }
    except Exception as e:
        logging.exception("Fehler bei der Verarbeitung der Episode: %s", e)
        return {
            "error": "Verarbeitungsfehler",
            "message": f"Fehler bei der Verarbeitung der Episode: {str(e)}",
            "details": traceback.format_exc(),
            "episode_url": params.get('episode_url', 'Unbekannt')
        }


def process_provider(provider: str, provider_data: dict, params: dict, anime_title: str, season_title: str, episode_title: str) -> None:
    """
    Verarbeitet einen Provider und führt die entsprechende Aktion aus.
    
    Args:
        provider: Der zu verwendende Provider (z.B. 'VOE', 'Vidoza')
        provider_data: Die Provider-Daten für alle verfügbaren Provider
        params: Die Parameter für die Verarbeitung
        anime_title: Der Titel des Animes
        season_title: Der Titel der Staffel
        episode_title: Der Titel der Episode
    """
    logging.debug("Processing provider: %s", provider)
    
    # Prüfe, ob die ausgewählte Sprache für diesen Provider verfügbar ist
    lang_key = int(params['language'])
    if lang_key not in provider_data[provider]:
        # Sammle verfügbare Sprachen für diesen Provider
        available_langs = [get_language_string(key) for key in provider_data[provider].keys()]
        raise ValueError(f"Keine verfügbaren Sprachen für Provider {provider} die der ausgewählten Sprache {get_language_string(lang_key)} entsprechen. \nVerfügbare Sprachen: {available_langs}")
    
    # Extrahiere den direkten Link für diesen Provider und die gewählte Sprache
    request_url = provider_data[provider][lang_key]
    
    # Provider-Funktion auswählen und direkten Link abrufen
    provider_function = None
    if provider == "VOE":
        from aniworld.extractors.provider.voe import voe_get_direct_link
        provider_function = voe_get_direct_link
    elif provider == "Vidoza":
        from aniworld.extractors.provider.vidoza import vidoza_get_direct_link
        provider_function = vidoza_get_direct_link
    elif provider == "Streamtape":
        from aniworld.extractors.provider.streamtape import streamtape_get_direct_link
        provider_function = streamtape_get_direct_link
    elif provider == "Doodstream":
        from aniworld.extractors.provider.doodstream import doodstream_get_direct_link
        provider_function = doodstream_get_direct_link
    elif provider == "Vidmoly":
        from aniworld.extractors.provider.vidmoly import vidmoly_get_direct_link
        provider_function = vidmoly_get_direct_link
    elif provider == "SpeedFiles":
        from aniworld.extractors.provider.speedfiles import speedfiles_get_direct_link
        provider_function = speedfiles_get_direct_link
    else:
        raise ValueError(f"Unbekannter Provider: {provider}")
    
    direct_link = fetch_direct_link(provider_function, request_url)
    
    if direct_link is None:
        raise ValueError(f"Provider {provider} konnte keinen direkten Link liefern")
    
    # Bei nur Direct Link Ausgabe den direkten Link zurückgeben
    if params.get('only_direct_link', False):
        print(direct_link)
        return
    
    # Hole season_number und episode_number aus dem URL-Pfad
    season_number, episode_number = get_season_and_episode_numbers(params['episode_url'])
    
    # Anime-Titel aus dem Slug ableiten wenn nicht angegeben
    if not anime_title:
        anime_title = params.get('anime_title', '')
        if not anime_title and 'anime_slug' in params:
            anime_title = params['anime_slug'].replace('-', ' ').title()
    
    # Baue Parameter für die Aktion
    action_params = {
        'provider': provider,
        'direct_link': direct_link,
        'anime_title': anime_title,
        'anime_slug': params.get('anime_slug', ''),
        'season_title': season_title,
        'episode_title': episode_title,
        'season_number': season_number,
        'episode_number': episode_number,
        'language': lang_key,
        'action': params.get('action', 'Download'),
        'aniskip': params.get('aniskip', False),
        'output': params.get('output', ''),
        'output_directory': params.get('output_directory', ''),
        'only_direct_link': params.get('only_direct_link', False),
        'only_command': params.get('only_command', False),
        'force_download': params.get('force_download', False)
    }
    
    # Führe die Aktion aus
    perform_action(action_params)
