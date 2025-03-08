import os
import shutil
import getpass
import platform
import hashlib
import logging
import time
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup

from aniworld.globals import PROVIDER_PRIORITY
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
    check_dependencies(["yt-dlp"])
    sanitize_anime_title = sanitize_path(params['anime_title'])

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

    output_directory = os.getenv("OUTPUT_DIRECTORY") or params['output_directory']
    seasons = params['season_number']
    episodes = params['episode_number']
    if seasons:
        if seasons < 10:
            seasons = "00" + str(seasons)
        elif 10 <= seasons < 100:
            seasons = "0" + str(seasons)
    if episodes < 10:
        episodes = "00" + str(episodes)
    elif 10 <= episodes < 100:
        episodes = "0" + str(episodes)

    file_name = (
        f"{sanitize_anime_title} - S{seasons}E{episodes}"
        if params['season_number']
        else f"{sanitize_anime_title} - Movie {episodes}"
    )

    file_path = os.path.join(
        output_directory,
        sanitize_anime_title,
        f"{file_name} ({get_language_from_key(int(params['language']))}).mp4"
    )

    if not params['only_command']:
        msg = f"Downloading to '{file_path}'"
        if not platform.system() == "Windows":
            print(msg)
        else:
            print_progress_info(msg)
    command = build_yt_dlp_command(params['link'], file_path, params['provider'])
    logging.debug("Executing command: %s", command)
    
    # Variablen für Download-Statistiken
    download_start_time = time.time()
    download_status = "completed"
    download_speed = None
    file_size = None
    download_duration = None
    
    try:
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
        
    except KeyboardInterrupt:
        logging.debug("KeyboardInterrupt encountered, cleaning up leftovers")
        clean_up_leftovers(os.path.dirname(file_path))
        download_status = "cancelled"
    except Exception as e:
        logging.error(f"Download-Fehler: {e}")
        download_status = "failed"
    finally:
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
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Download-Statistik: {e}")
    
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


def execute(params: Dict[str, Any]) -> None:
    logging.debug("Executing with params: %s", params)
    provider_mapping = {
        "Vidoza": vidoza_get_direct_link,
        "VOE": voe_get_direct_link,
        "Doodstream": doodstream_get_direct_link,
        "Streamtape": streamtape_get_direct_link,
        "Vidmoly": vidmoly_get_direct_link,
        "SpeedFiles": speedfiles_get_direct_link
    }

    selected_episodes = params['selected_episodes']
    action_selected = params['action_selected']
    aniskip_selected = bool(params.get("aniskip_selected", False))
    lang = params['lang']
    output_directory = params['output_directory']
    anime_title = params['anime_title']
    anime_slug = params['anime_slug']
    only_direct_link = params.get('only_direct_link', False)
    only_command = params.get('only_command', False)
    provider_selected = params['provider_selected']

    logging.debug("aniskip_selected: %s", aniskip_selected)

    for episode_url in selected_episodes:
        process_episode({
            'episode_url': episode_url,
            'provider_mapping': provider_mapping,
            'provider_selected': provider_selected,
            'lang': lang,
            'action_selected': action_selected,
            'aniskip_selected': aniskip_selected,
            'output_directory': output_directory,
            'anime_title': anime_title,
            "anime_slug": anime_slug,
            'only_direct_link': only_direct_link,
            'only_command': only_command
        })


def process_episode(params: Dict[str, Any]) -> None:
    logging.debug("Processing episode: %s", params['episode_url'])
    try:
        episode_html = fetch_url_content(params['episode_url'])
        soup = BeautifulSoup(episode_html, 'html.parser')
        episode_title = get_episode_title(soup)
        anime_title = get_anime_title(soup)
        data = get_provider_data(soup)

        logging.debug("Language Code: %s", params['lang'])
        logging.debug("Available Providers: %s", data.keys())

        # Priorisierte Provider-Liste verwenden
        available_providers = set(data.keys())
        
        # Initialisiere eine leere Liste für die zu versuchenden Provider
        providers_to_try = []
        
        # Zuerst den ausgewählten Provider hinzufügen, falls er verfügbar ist
        if params['provider_selected'] in available_providers:
            providers_to_try.append(params['provider_selected'])
            
        # Dann die restlichen Provider gemäß der Prioritätsliste hinzufügen
        for provider in PROVIDER_PRIORITY:
            if provider in available_providers and provider != params['provider_selected']:
                providers_to_try.append(provider)
        
        # Prüfen, ob irgendwelche Provider verfügbar sind
        if not providers_to_try:
            logging.error("Keine Provider verfügbar für diese Episode: %s", params['episode_url'])
            return
            
        # Durch die Provider iterieren und versuchen, die Episode herunterzuladen
        for provider in providers_to_try:
            try:
                logging.info("Versuche Provider: %s", provider)
                process_provider({
                    'provider': provider,
                    'data': data,
                    'lang': params['lang'],
                    'provider_mapping': params['provider_mapping'],
                    'episode_url': params['episode_url'],
                    'action_selected': params['action_selected'],
                    'aniskip_selected': params['aniskip_selected'],
                    'output_directory': params['output_directory'],
                    'anime_title': anime_title,
                    "anime_slug": params['anime_slug'],
                    'episode_title': episode_title,
                    'only_direct_link': params['only_direct_link'],
                    'only_command': params['only_command']
                })
                # Wenn erfolgreich, breche die Schleife ab
                logging.debug("Provider %s erfolgreich verwendet", provider)
                break
            except Exception as e:
                logging.warning("Provider %s fehlgeschlagen: %s", provider, str(e))
                continue
        else:
            # Wenn alle Provider fehlschlagen
            logging.error("Alle verfügbaren Provider sind fehlgeschlagen für Episode: %s", params['episode_url'])
            
    except AttributeError:
        logging.warning("Episode broken.")


def process_provider(params: Dict[str, Any]) -> None:
    logging.debug("Trying provider: %s", params['provider'])
    available_languages = params['data'].get(params['provider'], {}).keys()
    logging.debug("Available Languages for %s: %s", params['provider'], available_languages)

    for language in params['data'][params['provider']]:
        if language == int(params['lang']):
            season_number, episode_number = get_season_and_episode_numbers(params['episode_url'])
            action = params['action_selected']

            provider_function = params['provider_mapping'][params['provider']]
            request_url = params['data'][params['provider']][language]
            link = fetch_direct_link(provider_function, request_url)

            if link is None:
                logging.warning("Provider %s konnte keinen direkten Link liefern", params['provider'])
                raise Exception(f"Provider {params['provider']} konnte keinen direkten Link liefern")

            if params['only_direct_link']:
                logging.debug("Only direct link requested: %s", link)
                print(link)
                break

            mpv_title = (
                f"{params['anime_title']} --- S{season_number}E{episode_number} - "
                f"{params['episode_title']}"
                if season_number and episode_number
                else f"{params['anime_title']} --- Movie {episode_number} - "
                f"{params['episode_title']}"
            )

            episode_params = {
                "action": action,
                "link": link,
                "mpv_title": mpv_title,
                "anime_title": params['anime_title'],
                "anime_slug": params['anime_slug'],
                "episode_number": episode_number,
                "season_number": season_number,
                "output_directory": params['output_directory'],
                "only_command": params['only_command'],
                "aniskip_selected": params['aniskip_selected'],
                "provider": params['provider'],
                "language": params['lang']
            }

            logging.debug("Performing action with params: %s", episode_params)
            perform_action(episode_params)
            return  # Erfolgreich verarbeitet
    
    # Wenn wir hierher kommen, wurde keine passende Sprache gefunden
    available_languages = [
        get_language_string(lang_code)
        for lang_code in params['data'][params['provider']].keys()
    ]

    message = (
        f"Keine verfügbaren Sprachen für Provider {params['provider']} "
        f"die der ausgewählten Sprache {get_language_string(int(params['lang']))} entsprechen. "
        f"\nVerfügbare Sprachen: {available_languages}"
    )

    logging.warning(message)
    print(message)
    raise Exception(message)  # Ausnahme werfen, damit der nächste Provider versucht wird
