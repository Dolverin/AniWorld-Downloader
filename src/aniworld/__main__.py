#!/usr/bin/env python
# encoding: utf-8

import argparse
import os
import sys
import re
import logging
import subprocess
import platform
import threading
import random
import signal
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import colorlog
from queue import Queue
import time
from bs4 import BeautifulSoup
from typing import Dict, Any

import npyscreen

from aniworld.search import search_anime
from aniworld import execute, globals as aniworld_globals
from aniworld.common import (
    clear_screen,
    clean_up_leftovers,
    get_season_data,
    set_terminal_size,
    get_version,
    get_language_code,
    is_tail_running,
    get_season_and_episode_numbers,
    setup_anime4k,
    is_version_outdated,
    read_episode_file,
    check_package_installation,
    self_uninstall,
    update_component,
    get_anime_season_title,
    open_terminal_with_command,
    get_random_anime,
    show_messagebox,
    check_internet_connection,
    adventure,
    get_description,
    get_description_with_id,
    check_if_episode_exists,
    fetch_url_content,
    get_language_string
)
from aniworld.extractors import (
    nhentai,
    streamkiste,
    jav,
    hanime
)

from aniworld.globals import DEFAULT_DOWNLOAD_PATH
from aniworld.execute import providers


def format_anime_title(anime_slug):
    logging.debug("Formatting anime title for slug: %s", anime_slug)
    try:
        formatted_title = anime_slug.replace("-", " ").title()
        logging.debug("Formatted title: %s", formatted_title)
        return formatted_title
    except AttributeError:
        logging.debug("AttributeError encountered in format_anime_title")
        sys.exit()


class CustomTheme(npyscreen.ThemeManager):
    default_colors = {
        'DEFAULT': 'WHITE_BLACK',
        'FORMDEFAULT': 'MAGENTA_BLACK',  # Form border
        'NO_EDIT': 'BLUE_BLACK',
        'STANDOUT': 'CYAN_BLACK',
        'CURSOR': 'WHITE_BLACK',  # Text (focused)
        'CURSOR_INVERSE': 'BLACK_WHITE',
        'LABEL': 'CYAN_BLACK',  # Form labels
        'LABELBOLD': 'CYAN_BLACK',  # Form labels (focused)
        'CONTROL': 'GREEN_BLACK',  # Items in form
        'IMPORTANT': 'GREEN_BLACK',
        'SAFE': 'GREEN_BLACK',
        'WARNING': 'YELLOW_BLACK',
        'DANGER': 'RED_BLACK',
        'CRITICAL': 'BLACK_RED',
        'GOOD': 'GREEN_BLACK',
        'GOODHL': 'GREEN_BLACK',
        'VERYGOOD': 'BLACK_GREEN',
        'CAUTION': 'YELLOW_BLACK',
        'CAUTIONHL': 'BLACK_YELLOW',
    }


# pylint: disable=too-many-ancestors, too-many-instance-attributes
class EpisodeForm(npyscreen.ActionForm):
    def create(self):
        logging.debug("Creating EpisodeForm")

        anime_slug = self.parentApp.anime_slug
        logging.debug("Anime slug: %s", anime_slug)

        anime_title = format_anime_title(anime_slug)
        logging.debug("Anime title: %s", anime_title)

        season_data = get_season_data(anime_slug)
        logging.debug("Season data: %s", season_data)

        self.timer = None
        self.start_timer()
        self.setup_signal_handling()

        anime_season_title = get_anime_season_title(slug=anime_slug, season=1)
        self.anime_title = anime_season_title
        
        # Speichern der Anime-Information für spätere Verwendung
        self.anime_slug = anime_slug

        def process_url(url):
            logging.debug("Processing URL: %s", url)
            season, episode = get_season_and_episode_numbers(url)
            title = (
                f"{anime_season_title} - Season {season} - Episode {episode}"
                if season > 0
                else f"{anime_season_title} - Movie {episode}"
            )
            return (season, episode, title, url)

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_url = {executor.submit(process_url, url): url for url in season_data}

            results = []
            for future in as_completed(future_to_url):
                try:
                    result = future.result(timeout=5)  # Timeout for future result
                    results.append(result)
                    logging.debug("Processed result: %s", result)
                except TimeoutError as e:
                    logging.error("Timeout processing %s: %s", future_to_url[future], e)

        sorted_results = sorted(
            results,
            key=lambda x: (x[0] if x[0] > 0 else 999, x[1])
        )

        # Episoden nach Staffeln gruppieren
        self.seasons_map = {}
        for season, episode, title, url in sorted_results:
            if season not in self.seasons_map:
                self.seasons_map[season] = []
            self.seasons_map[season].append((episode, title))
            
        # Speichern der Original-Infos für jede Episode (Staffel, Episode)
        self.episode_info = {}
        for season, episode, title, url in sorted_results:
            self.episode_info[title] = (season, episode)

        season_episode_map = {title: url for _, _, title, url in sorted_results}
        self.episode_map = season_episode_map

        episode_list = list(self.episode_map.keys())
        logging.debug("Episode list: %s", episode_list)

        self.action_selector = self.add(
            npyscreen.TitleSelectOne,
            name="Action",
            values=["Watch", "Download", "Syncplay"],
            max_height=4,
            value=[["Watch", "Download", "Syncplay"].index(aniworld_globals.DEFAULT_ACTION)],
            scroll_exit=True
        )
        logging.debug("Action selector created")

        self.aniskip_selector = self.add(
            npyscreen.TitleSelectOne,
            name="Aniskip",
            values=["Enable", "Disable"],
            max_height=3,
            value=[0 if aniworld_globals.DEFAULT_ANISKIP else 1],
            scroll_exit=True
        )
        logging.debug("Aniskip selector created")

        self.directory_field = self.add(
            npyscreen.TitleFilenameCombo,
            name="Directory:",
            value=aniworld_globals.DEFAULT_DOWNLOAD_PATH
        )
        logging.debug("Directory field created")

        self.language_selector = self.add(
            npyscreen.TitleSelectOne,
            name="Language",
            values=["German Dub", "English Sub", "German Sub"],
            max_height=4,
            value=[
                ["German Dub", "English Sub", "German Sub"].index(
                    aniworld_globals.DEFAULT_LANGUAGE
                )
            ],
            scroll_exit=True
        )
        logging.debug("Language selector created")

        # Event-Handler für Sprachänderung hinzufügen
        self.language_selector.when_value_edited = self.filter_episodes_by_language

        self.provider_selector = self.add(
            npyscreen.TitleSelectOne,
            name="Provider",
            values=[
                "VOE",
                "Vidmoly",
                "Doodstream",
                "SpeedFiles",
                "Vidoza"
            ],
            max_height=6,
            value=[
                [
                    "VOE",
                    "Vidmoly",
                    "Doodstream",
                    "SpeedFiles",
                    "Vidoza"
                ].index(aniworld_globals.DEFAULT_PROVIDER)
            ],
            scroll_exit=True
        )

        logging.debug("Provider selector created")
        
        # Status-Text für Benachrichtigungen hinzufügen
        self.status_text = self.add(
            npyscreen.TitleFixedText,
            name="Status:",
            value="",
            editable=False
        )

        self.episode_selector = self.add(
            npyscreen.TitleMultiSelect,
            name="Episode Selection",
            values=episode_list,
            max_height=6,
            scroll_exit=True
        )
        logging.debug("Episode selector created")
        
        # Dropdown für Staffelauswahl
        self.season_selector = self.add(
            npyscreen.TitleSelectOne, 
            name="Staffel auswählen:",
            values=["Staffel " + str(season) if season > 0 else "Filme" for season in sorted(self.seasons_map.keys())],
            max_height=4,
            scroll_exit=True
        )
        
        # Button zum Markieren vorhandener Episoden
        self.mark_existing_button = self.add(
            npyscreen.ButtonPress,
            name="Vorhandene Episoden markieren",
            max_height=1,
            when_pressed_function=self.mark_existing_episodes,
            scroll_exit=True
        )
        
        # Button zum Filtern und Anzeigen nur fehlender Episoden
        self.filter_missing_button = self.add(
            npyscreen.ButtonPress,
            name="Nur fehlende Episoden anzeigen",
            max_height=1,
            when_pressed_function=self.show_only_missing_episodes,
            scroll_exit=True
        )
        
        # Button zum Auswählen aller fehlenden Episoden
        self.select_missing_button = self.add(
            npyscreen.ButtonPress,
            name="Alle fehlenden Episoden auswählen",
            max_height=1,
            when_pressed_function=self.select_all_missing_episodes,
            scroll_exit=True
        )
        
        # Button zum Auswählen aller Episoden einer Staffel
        self.select_season_button = self.add(
            npyscreen.ButtonPress,
            name="Alle Episoden dieser Staffel auswählen",
            max_height=1,
            when_pressed_function=self.select_season_episodes,
            scroll_exit=True
        )

        # Button zum Auswählen aller Episoden hinzufügen
        self.select_all_button = self.add(
            npyscreen.ButtonPress,
            name="Alle Episoden auswählen",
            max_height=1,
            when_pressed_function=self.select_all_episodes,
            scroll_exit=True
        )

        self.display_text = False
        
        # Automatisch nach vorhandenen Episoden suchen
        threading.Timer(0.5, self.mark_existing_episodes).start()

        self.toggle_button = self.add(
            npyscreen.ButtonPress,
            name="Description",
            max_height=1,
            when_pressed_function=self.go_to_second_form,
            scroll_exit=True
        )

        self.action_selector.when_value_edited = self.update_directory_visibility
        logging.debug("Set update_directory_visibility as callback for action_selector")

    def setup_signal_handling(self):
        def signal_handler(_signal_number, _frame):
            try:
                self.parentApp.switchForm(None)
            except AttributeError:
                pass
            self.cancel_timer()
            sys.exit()

        signal.signal(signal.SIGINT, signal_handler)
        logging.debug("Signal handler for SIGINT registered")

    def start_timer(self):
        self.timer = threading.Timer(  # pylint: disable=attribute-defined-outside-init
            random.randint(600, 900),
            self.delayed_message_box
        )
        self.timer.start()

    def cancel_timer(self):
        if self.timer and self.timer.is_alive():
            self.timer.cancel()
            logging.debug("Timer canceled")

    def delayed_message_box(self):
        show_messagebox("Are you still there?", "Uhm...", "info")

    def update_directory_visibility(self):
        logging.debug("Updating directory visibility")
        selected_action = self.action_selector.get_selected_objects()
        logging.debug("Selected action: %s", selected_action)
        if selected_action and selected_action[0] == "Watch" or selected_action[0] == "Syncplay":
            self.directory_field.hidden = True
            self.aniskip_selector.hidden = False
            logging.debug("Directory field hidden, Aniskip selector shown")
        else:
            self.directory_field.hidden = False
            self.aniskip_selector.hidden = True
            logging.debug("Directory field shown, Aniskip selector hidden")
        self.display()

    def on_ok(self):
        logging.debug("OK button pressed")
        self.cancel_timer()
        npyscreen.blank_terminal()
        output_directory = self.directory_field.value if not self.directory_field.hidden else None
        logging.debug("Output directory: %s", output_directory)
        if not output_directory and not self.directory_field.hidden:
            logging.debug("No output directory provided")
            self.status_text.value = "Bitte geben Sie ein Verzeichnis an."
            self.display()
            return

        # Stellen sicher, dass die Episoden auf Vorhandensein überprüft wurden
        if not hasattr(self, 'existing_episodes'):
            logging.debug("Checking for existing episodes before processing")
            self.mark_existing_episodes()

        selected_episodes = self.episode_selector.get_selected_objects()
        action_selected = self.action_selector.get_selected_objects()
        language_selected = self.language_selector.get_selected_objects()
        provider_selected = self.provider_selector.get_selected_objects()
        aniskip_selected = self.aniskip_selector.get_selected_objects()[0] == "Enable"

        logging.debug("Selected episodes: %s", selected_episodes)
        logging.debug("Action selected: %s", action_selected)
        logging.debug("Language selected: %s", language_selected)
        logging.debug("Provider selected: %s", provider_selected)
        logging.debug("Aniskip selected: %s", aniskip_selected)

        if not (selected_episodes and action_selected and language_selected):
            logging.debug("No episodes or action or language selected")
            self.status_text.value = "Keine Episoden ausgewählt."
            self.display()
            return
            
        # Die markierten Episoden entfernen und Original-Titel wiederherstellen
        cleaned_selected_episodes = []
        for episode in selected_episodes:
            if episode.startswith("[✓] ") or episode.startswith("[✗] "):
                # Titel ohne Markierung
                cleaned_episode = episode[4:]
                cleaned_selected_episodes.append(cleaned_episode)
            else:
                cleaned_selected_episodes.append(episode)
        
        # Überprüfen, ob der Benutzer bereits heruntergeladene Episoden erneut herunterladen möchte
        existing_episodes_selected = []
        for episode in selected_episodes:
            if episode.startswith("[✓] "):
                existing_episodes_selected.append(episode)
        
        if existing_episodes_selected and action_selected[0] == "Download":
            # Bestätigung vom Benutzer einholen
            confirm = npyscreen.notify_yes_no(
                f"Sie haben {len(existing_episodes_selected)} bereits heruntergeladene Episoden ausgewählt. "
                "Möchten Sie diese erneut herunterladen?",
                title="Bestätigung erforderlich"
            )
            
            if not confirm:
                # Wenn der Benutzer 'Nein' wählt, die bereits heruntergeladenen Episoden aus der Auswahl entfernen
                cleaned_selected_episodes = [
                    episode for episode in cleaned_selected_episodes 
                    if episode not in [e[4:] for e in existing_episodes_selected]
                ]
                
                if not cleaned_selected_episodes:
                    self.status_text.value = "Keine neuen Episoden zum Herunterladen ausgewählt."
                    self.display()
                    return

        lang = self.get_language_code(language_selected[0])
        logging.debug("Language code: %s", lang)
        provider_selected = self.validate_provider(provider_selected)
        logging.debug("Validated provider: %s", provider_selected)

        # Den bereinigten Titel verwenden, um die URLs zu finden
        selected_urls = []
        for episode in cleaned_selected_episodes:
            if episode in self.episode_map:
                selected_urls.append(self.episode_map[episode])
            
        selected_str = "\n".join(cleaned_selected_episodes)
        logging.debug("Selected URLs: %s", selected_urls)
        
        # Status-Nachricht: Ausgewählte Episoden
        if len(cleaned_selected_episodes) <= 3:
            self.status_text.value = f"Ausgewählte Episoden: {', '.join(cleaned_selected_episodes)}"
        else:
            self.status_text.value = f"{len(cleaned_selected_episodes)} Episoden ausgewählt"
        self.display()

        if not self.directory_field.hidden:
            output_directory = os.path.join(output_directory)
            os.makedirs(output_directory, exist_ok=True)
            logging.debug("Output directory created: %s", output_directory)

        # Für jede Episode ein eigenes Parameter-Objekt erstellen
        for episode_url in selected_urls:
            params = {
                'episode_url': episode_url,
                'provider_selected': provider_selected,
                'action_selected': action_selected[0],
                'aniskip_selected': aniskip_selected,
                'lang': lang,
                'output_directory': output_directory,
                'anime_title': format_anime_title(self.parentApp.anime_slug),
                'anime_slug': self.parentApp.anime_slug,
                'only_direct_link': False,
                'only_command': False,
                'force_download': False
            }

            # Führe die Verarbeitung in einem separaten Thread aus, um das UI nicht zu blockieren
            threading.Thread(target=self.__execute_and_exit, args=(params,), daemon=True).start()
            return  # Nach dem Start des Threads sofort zurückkehren

    def __execute_and_exit(self, params):
        try:
            execute_with_params(params)
        except Exception as e:
            logging.exception(f"Fehler beim Ausführen der Episode: {e}")
            # Zeige Fehler im TUI an
            npyscreen.notify_confirm(
                f"Fehler beim Ausführen der Episode: {str(e)}",
                title="Fehler",
                form_color="DANGER",
                wrap=True
            )
        finally:
            # Schließe das Formular nach der Ausführung (egal ob erfolgreicher oder fehlerhafter Ausführung)
            self.parentApp.switchForm(None)

    def get_language_code(self, language):
        logging.debug("Getting language code for: %s", language)
        return {
            'German Dub': "1",
            'English Sub': "2",
            'German Sub': "3"
        }.get(language, "")

    def validate_provider(self, provider_selected):
        logging.debug("Validating provider: %s", provider_selected)
        valid_providers = ["Vidoza", "Streamtape", "VOE", "Vidmoly", "SpeedFiles"]
        while provider_selected[0] not in valid_providers:
            logging.debug("Invalid provider selected, falling back to Vidoza")
            npyscreen.notify_confirm(
                "Doodstream is currently broken.\nFalling back to Vidoza.",
                title="Provider Error"
            )
            self.provider_selector.value = 0
            provider_selected = ["Vidoza"]
        return provider_selected[0]

    def check_available_languages(self, episode_url):
        """
        Prüft, welche Sprachen für eine bestimmte Episode verfügbar sind.
        
        Args:
            episode_url: Die URL der Episode
            
        Returns:
            Ein Set mit den verfügbaren Sprachen ("German Dub", "English Sub", "German Sub")
        """
        logging.debug(f"Prüfe verfügbare Sprachen für: {episode_url}")
        available_languages = set()
        
        try:
            # HTML-Content der Episode laden
            html_content = fetch_url_content(episode_url)
            if not html_content:
                logging.error(f"Konnte keine HTML-Inhalte für URL abrufen: {episode_url}")
                return available_languages
                
            # Provider-Daten extrahieren
            soup = BeautifulSoup(html_content, 'html.parser')
            provider_data = providers(soup)
            
            # Verfügbare Sprachen sammeln
            for provider in provider_data:
                for lang_key in provider_data[provider]:
                    lang = get_language_string(int(lang_key))
                    available_languages.add(lang)
                    
            logging.debug(f"Verfügbare Sprachen für {episode_url}: {available_languages}")
            return available_languages
            
        except Exception as e:
            logging.error(f"Fehler bei der Prüfung der verfügbaren Sprachen: {e}")
            return available_languages
            
    def filter_episodes_by_language(self, *args):
        """
        Filtert die Episodenliste basierend auf der ausgewählten Sprache.
        Wird als Event-Handler für den Language-Selector verwendet.
        """
        if not hasattr(self, 'original_episode_list'):
            # Beim ersten Aufruf die ursprüngliche Liste speichern
            self.original_episode_list = self.episode_selector.values.copy()
            self.original_episode_map = self.episode_map.copy()
        
        # Ausgewählte Sprache
        selected_language = ["German Dub", "English Sub", "German Sub"][self.language_selector.value[0]]
        
        # Status-Nachricht aktualisieren
        self.status_text.value = f"Prüfe verfügbare Episoden für {selected_language}..."
        self.display()
        
        # Episoden-URLs und ihre Verfügbarkeit in einem Dictionary speichern
        filtered_episodes = []
        filtered_map = {}
        
        # Thread-Funktion für die Prüfung
        def check_language_availability():
            results = {}
            count = 0
            total = len(self.original_episode_map)
            
            for title, url in self.original_episode_map.items():
                count += 1
                if count % 5 == 0:
                    self.status_text.value = f"Prüfe Sprachen... ({count}/{total})"
                    self.display()
                
                # Verfügbare Sprachen prüfen
                available_langs = self.check_available_languages(url)
                results[title] = selected_language in available_langs
            
            return results
            
        # Thread starten
        availability_thread = threading.Thread(target=lambda: self.update_episode_list(check_language_availability))
        availability_thread.daemon = True
        availability_thread.start()
        
    def update_episode_list(self, check_function):
        """
        Aktualisiert die Episodenliste basierend auf den Ergebnissen der Sprachverfügbarkeitsprüfung.
        
        Args:
            check_function: Eine Funktion, die ein Dictionary mit Episodenname -> Verfügbarkeit zurückgibt
        """
        # Ausgewählte Sprache
        selected_language = ["German Dub", "English Sub", "German Sub"][self.language_selector.value[0]]
        
        try:
            # Verfügbarkeit prüfen
            availability_results = check_function()
            
            # Gefilterte Listen erstellen
            filtered_episodes = []
            filtered_map = {}
            
            for title, is_available in availability_results.items():
                if is_available:
                    filtered_episodes.append(title)
                    filtered_map[title] = self.original_episode_map[title]
            
            # Episodenliste aktualisieren
            self.episode_selector.values = filtered_episodes
            self.episode_map = filtered_map
            
            # Season-Maps aktualisieren
            self.update_season_maps()
            
            # Anzeige aktualisieren
            self.episode_selector.display()
            
            # Status-Nachricht aktualisieren
            if len(filtered_episodes) == 0:
                # Keine Episoden in dieser Sprache verfügbar
                message = f"Keine Episoden in {selected_language} verfügbar."
                self.status_text.value = message
                
                # Kurz verzögern, dann Fehlermeldung anzeigen
                threading.Timer(0.5, lambda: npyscreen.notify_confirm(
                    f"Für diesen Anime sind keine Episoden in {selected_language} verfügbar.\n"
                    f"Bitte wählen Sie eine andere Sprache.",
                    title="Keine Episoden verfügbar"
                )).start()
                
                # Sprache auf die erste verfügbare zurücksetzen
                all_available_langs = set()
                for _, avail in availability_results.items():
                    if avail:
                        all_available_langs.add(title)
                
                if all_available_langs:
                    self.episode_selector.values = list(self.original_episode_list)
                    self.episode_map = dict(self.original_episode_map)
                
            elif len(filtered_episodes) < len(self.original_episode_list):
                # Nur teilweise verfügbar
                self.status_text.value = f"{len(filtered_episodes)} von {len(self.original_episode_list)} Episoden sind in {selected_language} verfügbar."
            else:
                # Alle verfügbar
                self.status_text.value = f"Alle {len(filtered_episodes)} Episoden sind in {selected_language} verfügbar."
                
            self.display()
            
        except Exception as e:
            logging.error(f"Fehler beim Aktualisieren der Episodenliste: {e}")
            self.status_text.value = f"Fehler beim Filtern: {str(e)}"
            self.display()
            
            # Fehlermeldung anzeigen
            npyscreen.notify_confirm(
                f"Fehler bei der Prüfung der verfügbaren Sprachen:\n{str(e)}",
                title="Fehler"
            )
            
    def update_season_maps(self):
        """Aktualisiert die seasons_map basierend auf den gefilterten Episoden"""
        # Zurücksetzen der seasons_map
        self.seasons_map = {}
        
        # Neu aufbauen basierend auf den gefilterten Episoden
        for title in self.episode_selector.values:
            if title in self.episode_info:
                season, episode = self.episode_info[title]
                if season not in self.seasons_map:
                    self.seasons_map[season] = []
                self.seasons_map[season].append((episode, title))
        
        # Staffel-Dropdown aktualisieren
        self.season_selector.values = ["Staffel " + str(season) if season > 0 else "Filme" 
                                   for season in sorted(self.seasons_map.keys())]
        self.season_selector.display()

    def on_cancel(self):
        logging.debug("Cancel button pressed")
        self.cancel_timer()
        self.parentApp.setNextForm(None)

    def go_to_second_form(self):
        self.parentApp.switchForm("SECOND")

    def select_all_episodes(self):
        """Wählt alle Episoden in der MultiSelect-Liste aus."""
        logging.debug("Selecting all episodes")
        all_indices = list(range(len(self.episode_selector.values)))
        self.episode_selector.value = all_indices
        self.episode_selector.display()
        
        # Status-Nachricht aktualisieren
        self.status_text.value = f"Alle {len(all_indices)} Episoden wurden ausgewählt."
        self.display()
    
    def select_season_episodes(self):
        """Wählt alle Episoden der ausgewählten Staffel aus."""
        if not self.season_selector.value:
            return
        
        selected_season_idx = self.season_selector.value[0]
        seasons = sorted(self.seasons_map.keys())
        selected_season = seasons[selected_season_idx]
        
        logging.debug("Selecting all episodes for season {}".format(selected_season))
        
        # Episodentitel für diese Staffel finden
        season_episodes = []
        for _, title in self.seasons_map[selected_season]:
            season_episodes.append(title)
        
        # Indizes dieser Episoden in der episode_selector-Liste finden
        indices_to_select = []
        for i, title in enumerate(self.episode_selector.values):
            # Titel bereinigen, falls er markiert ist
            cleaned_title = title
            if title.startswith("[✓] ") or title.startswith("[✗] "):
                cleaned_title = title[4:]
            
            # Basistitel in der episode_info suchen
            for original_title in season_episodes:
                if original_title == cleaned_title or original_title + " ([✓])" == cleaned_title or original_title + " ([✗])" == cleaned_title:
                    indices_to_select.append(i)
                    break
        
        # Diese Episoden in der MultiSelect-Liste auswählen
        if self.episode_selector.value:
            # Bestehende Auswahl behalten und neue hinzufügen
            current_selection = set(self.episode_selector.value)
            current_selection.update(indices_to_select)
            self.episode_selector.value = list(current_selection)
        else:
            self.episode_selector.value = indices_to_select
        
        self.episode_selector.display()
        
        # Status-Nachricht aktualisieren
        season_name = "Staffel " + str(selected_season) if selected_season > 0 else "Filme"
        self.status_text.value = f"{len(indices_to_select)} Episoden von {season_name} wurden ausgewählt."
        self.display()

    def mark_existing_episodes(self):
        """Markiert bereits existierende Episoden in der Liste"""
        download_path = self.directory_field.value or aniworld_globals.DEFAULT_DOWNLOAD_PATH
        language = ["German Dub", "English Sub", "German Sub"][self.language_selector.value[0]]
        
        logging.info(f"DEBUG-UI: Starte Suche nach vorhandenen Episoden, Pfad: {download_path}, Sprache: {language}")
        logging.info(f"DEBUG-UI: Anime-Titel: {self.anime_title}, {len(self.episode_selector.values)} Episoden zu prüfen")
        
        self.existing_episodes = []
        new_values = []
        
        # Status-Nachricht aktualisieren
        self.status_text.value = "Suche nach vorhandenen Episoden..."
        self.display()
        
        # Verwende ein Queue für die Ergebnisse des Hintergrund-Scans
        result_queue = Queue()
        
        # Erstelle einen Thread für die Überprüfung der Episoden
        def check_episodes_thread():
            try:
                for i, title in enumerate(self.episode_selector.values):
                    # Bei jedem 5. Element UI aktualisieren
                    if i % 5 == 0:
                        self.status_text.value = f"Suche nach vorhandenen Episoden... ({i+1}/{len(self.episode_selector.values)})"
                        self.display()
                    
                    # Überprüfen, ob die Episode bereits existiert
                    if title.startswith("[✓] ") or title.startswith("[✗] "):
                        # Bereits markiert, Original-Titel extrahieren
                        original_title = title[4:]
                        logging.debug(f"DEBUG-UI: Prüfe bereits markierte Episode: {original_title}")
                        try:
                            season, episode = self.episode_info[original_title]
                        except KeyError:
                            logging.error(f"DEBUG-UI: Keine Info für {original_title} gefunden, überspringe")
                            result_queue.put((i, title, False, False))  # Keine Info, überspringen
                            continue
                    else:
                        # Nicht markiert, Staffel- und Episodennummer aus dem Titel extrahieren
                        logging.debug(f"DEBUG-UI: Prüfe unmarkierte Episode: {title}")
                        try:
                            season, episode = self.episode_info[title]
                        except KeyError:
                            logging.error(f"DEBUG-UI: Keine Info für {title} gefunden, überspringe")
                            result_queue.put((i, title, False, False))  # Keine Info, überspringen
                            continue
                    
                    # Logge die Episode, die wir überprüfen
                    logging.info(f"DEBUG-UI: Prüfe Episode {i+1}/{len(self.episode_selector.values)}: S{season}E{episode}, Titel: {title}")
                    
                    try:
                        # Episode im Dateisystem suchen
                        exists = check_if_episode_exists(
                            self.anime_title, 
                            season, 
                            episode, 
                            language, 
                            download_path
                        )
                        logging.debug(f"DEBUG-UI: Ergebnis für S{season}E{episode}: {'Gefunden' if exists else 'Nicht gefunden'}")
                        # Ergebnis in die Queue schreiben
                        result_queue.put((i, title, exists, True))  # Valides Ergebnis
                    except Exception as e:
                        # Bei Fehler Eintrag überspringen
                        logging.error(f"DEBUG-UI: Fehler bei Prüfung von S{season}E{episode}: {str(e)}")
                        result_queue.put((i, title, False, False))  # Fehler, als nicht gefunden markieren
                
                # Signal für Ende
                result_queue.put(None)
            except Exception as e:
                # Bei Fehler Signal senden
                logging.error(f"DEBUG-UI: Kritischer Fehler beim Überprüfen von Episoden: {e}")
                result_queue.put(f"ERROR: {str(e)}")
        
        # Thread starten
        scan_thread = threading.Thread(target=check_episodes_thread, daemon=True)
        scan_thread.start()
        
        # Auf Ergebnisse warten mit Timeout
        episodes_found = 0
        episodes_checked = 0
        start_time = time.time()
        timeout = 300  # Maximale Wartezeit auf 5 Minuten erhöht
        
        while True:
            # Prüfen, ob der Scan zu lange dauert
            if time.time() - start_time > timeout:
                logging.error(f"DEBUG-UI: Zeitüberschreitung nach {timeout} Sekunden. {episodes_checked} von {len(self.episode_selector.values)} geprüft.")
                self.status_text.value = f"Zeitüberschreitung bei der Suche. {episodes_checked} von {len(self.episode_selector.values)} Episoden geprüft."
                self.display()
                # Thread beenden lassen und mit den bisherigen Ergebnissen fortfahren
                break
                
            # Auf Ergebnis mit kurzem Timeout warten, damit die UI nicht blockiert
            try:
                result = result_queue.get(timeout=0.1)
            except:
                # Timeout bei Queue.get, aber weiter warten
                continue
                
            # Prüfen, ob Ende oder Fehler
            if result is None:
                logging.info(f"DEBUG-UI: Alle {episodes_checked} Episoden wurden geprüft.")
                break
            if isinstance(result, str) and result.startswith("ERROR"):
                logging.error(f"DEBUG-UI: Thread-Fehler: {result[6:]}")
                self.status_text.value = f"Fehler: {result[6:]}"
                self.display()
                break
                
            # Ergebnis verarbeiten
            i, title, exists, is_valid = result
            episodes_checked += 1
            
            if not is_valid:
                # Ungültiges Ergebnis, Episode als nicht vorhanden markieren
                if not title.startswith("[✗] "):
                    original_title = title[4:] if title.startswith("[✓] ") else title
                    new_values.append(f"[✗] {original_title}")
                else:
                    new_values.append(title)
                continue
            
            # Je nach Vorhandensein markieren
            if exists:
                self.existing_episodes.append(i)
                episodes_found += 1
                if not title.startswith("[✓] "):
                    original_title = title[4:] if title.startswith("[✗] ") else title
                    new_values.append(f"[✓] {original_title}")
                else:
                    new_values.append(title)
            else:
                if not title.startswith("[✗] "):
                    original_title = title[4:] if title.startswith("[✓] ") else title
                    new_values.append(f"[✗] {original_title}")
                else:
                    new_values.append(title)
                    
            # UI aktualisieren für Fortschrittsanzeige
            if len(new_values) % 5 == 0 or len(new_values) == len(self.episode_selector.values):
                self.status_text.value = f"Suche nach vorhandenen Episoden... ({len(new_values)}/{len(self.episode_selector.values)})"
                self.display()
        
        # Warte auf Thread-Ende
        scan_thread.join(timeout=1.0)
        
        # Stelle sicher, dass alle Episoden markiert wurden
        while len(new_values) < len(self.episode_selector.values):
            title = self.episode_selector.values[len(new_values)]
            if not title.startswith("[✗] "):
                original_title = title[4:] if title.startswith("[✓] ") else title
                new_values.append(f"[✗] {original_title}")
            else:
                new_values.append(title)
        
        # Aktualisiere die Anzeige
        logging.info(f"DEBUG-UI: Aktualisiere UI mit {len(new_values)} Episoden, davon {episodes_found} gefunden")
        self.episode_selector.values = new_values
        self.episode_selector.display()
        
        # Status-Nachricht aktualisieren
        self.status_text.value = f"{episodes_found} von {len(new_values)} Episoden wurden bereits heruntergeladen."
        self.display()

    def show_only_missing_episodes(self):
        """Filtert die Liste, um nur fehlende Episoden anzuzeigen"""
        if not hasattr(self, 'existing_episodes'):
            self.mark_existing_episodes()
            
        # Alle Indizes, die nicht in existing_episodes sind
        missing_indices = [i for i in range(len(self.episode_selector.values)) 
                         if i not in self.existing_episodes]
        
        # Nur fehlende Episoden auswählen
        self.episode_selector.value = missing_indices
        self.episode_selector.display()
        
        # Status-Nachricht aktualisieren
        self.status_text.value = f"{len(missing_indices)} fehlende Episoden werden angezeigt."
        self.display()
    
    def select_all_missing_episodes(self):
        """Wählt alle fehlenden Episoden aus"""
        if not hasattr(self, 'existing_episodes'):
            self.mark_existing_episodes()
            
        # Alle Indizes, die nicht in existing_episodes sind
        missing_indices = [i for i in range(len(self.episode_selector.values)) 
                         if i not in self.existing_episodes]
        
        # Alle fehlenden Episoden auswählen
        self.episode_selector.value = missing_indices
        self.episode_selector.display()
        
        # Status-Nachricht aktualisieren
        self.status_text.value = f"{len(missing_indices)} fehlende Episoden wurden ausgewählt."
        self.display()


# pylint: disable=R0901
class SecondForm(npyscreen.ActionFormV2):
    def create(self):
        anime_slug = self.parentApp.anime_slug
        anime_title = format_anime_title(anime_slug)

        text_content1 = get_description(anime_slug)
        text_content2 = get_description_with_id(anime_title, 1)

        wrapped_text1 = "\n".join(textwrap.wrap(text_content1, width=100))
        wrapped_text2 = "\n".join(textwrap.wrap(text_content2, width=100))

        text_content = f"{wrapped_text1}\n\n{wrapped_text2}"

        self.expandable_text = self.add(
            npyscreen.MultiLineEdit,
            value=text_content,
            max_height=None,
            editable=False
        )

    def on_ok(self):
        self.parentApp.switchForm("MAIN")

    def on_cancel(self):
        self.parentApp.switchForm("MAIN")


class AnimeApp(npyscreen.NPSAppManaged):
    def __init__(self, anime_slug):
        logging.debug("Initializing AnimeApp with slug: %s", anime_slug)
        super().__init__()
        self.anime_slug = anime_slug

    def onStart(self):
        logging.debug("Starting AnimeApp")
        npyscreen.setTheme(CustomTheme)
        version = get_version()
        update_notice = " (Update Available)" if is_version_outdated() else ""
        name = f"AniWorld-Downloader{version}{update_notice}"
        self.addForm(
            "MAIN", EpisodeForm,
            name=name
        )
        self.addForm("SECOND", SecondForm, name="Description")


# pylint: disable=R0912, R0915
def parse_arguments():
    logging.debug("Parsing command line arguments")

    parser = argparse.ArgumentParser(
        description="Parse optional command line arguments."
    )

    # General options
    general_group = parser.add_argument_group('General Options')
    general_group.add_argument(
        '-v', '--version',
        action='store_true',
        help='Print version info'
    )
    general_group.add_argument(
        '-d', '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    general_group.add_argument(
        '-u', '--uninstall',
        action='store_true',
        help='Self uninstall'
    )
    general_group.add_argument(
        '-U', '--update',
        type=str,
        choices=['mpv', 'yt-dlp', 'syncplay', 'all'],
        help='Update mpv, yt-dlp, syncplay, or all.'
    )

    # Search options
    search_group = parser.add_argument_group('Search Options')
    search_group.add_argument(
        '-s', '--slug',
        type=str,
        help='Search query - E.g. demon-slayer-kimetsu-no-yaiba'
    )
    search_group.add_argument(
        '-l', '--link',
        type=str,
        help='Search query - E.g. https://aniworld.to/anime/stream/demon-slayer-kimetsu-no-yaiba'
    )
    search_group.add_argument(
        '-q', '--query',
        type=str,
        help='Search query input - E.g. demon'
    )

    # Episode options
    episode_group = parser.add_argument_group('Episode Options')
    episode_group.add_argument(
        '-e', '--episode',
        type=str,
        nargs='+',
        help='List of episode URLs'
    )
    episode_group.add_argument(
        '-f', '--episode-file',
        type=str,
        help='File path containing a list of episode URLs'
    )
    episode_group.add_argument(
        '-lf', '--episode-local',
        action='store_true',
        help='NOT IMPLEMENTED YET - Use local episode files instead of URLs'
    )

    # Action options
    action_group = parser.add_argument_group('Action Options')
    action_group.add_argument(
        '-a', '--action',
        type=str,
        choices=['Watch', 'Download', 'Syncplay'],
        default=aniworld_globals.DEFAULT_ACTION,
        help='Action to perform'
    )
    action_group.add_argument(
        '-o', '--output',
        type=str,
        help='Download directory E.g. /Users/phoenixthrush/Downloads',
        default=DEFAULT_DOWNLOAD_PATH
    )
    action_group.add_argument(
        '-O', '--output-directory',
        type=str,
        help=(
            'Final download directory, e.g., ExampleDirectory. '
            'Defaults to anime name if not specified.'
        )
    )
    action_group.add_argument(
        '-L', '--language',
        type=str,
        choices=['German Dub', 'English Sub', 'German Sub'],
        default=aniworld_globals.DEFAULT_LANGUAGE,
        help='Language choice'
    )
    action_group.add_argument(
        '-p', '--provider',
        type=str,
        choices=['Vidoza', 'Streamtape', 'VOE',
                 'Doodstream', 'Vidmoly', 'Doodstream', "SpeedFiles"],
        help='Provider choice'
    )

    # Anime4K options
    anime4k_group = parser.add_argument_group('Anime4K Options')
    anime4k_group.add_argument(
        '-A', '--anime4k',
        type=str,
        choices=['High', 'Low', 'Remove'],
        help=(
            'Set Anime4K optimised mode (High, e.g., GTX 1080, RTX 2070, RTX 3060, '
            'RX 590, Vega 56, 5700XT, 6600XT; Low, e.g., GTX 980, GTX 1060, RX 570, '
            'or Remove).'
        )
    )

    # Syncplay options
    syncplay_group = parser.add_argument_group('Syncplay Options')
    syncplay_group.add_argument(
        '-sH', '--syncplay-hostname',
        type=str,
        help='Set syncplay hostname'
    )
    syncplay_group.add_argument(
        '-sU', '--syncplay-username',
        type=str,
        help='Set syncplay username'
    )
    syncplay_group.add_argument(
        '-sR', '--syncplay-room',
        type=str,
        help='Set syncplay room'
    )
    syncplay_group.add_argument(
        '-sP', '--syncplay-password',
        type=str,
        nargs='+',
        help='Set a syncplay room password'
    )

    # Miscellaneous options
    misc_group = parser.add_argument_group('Miscellaneous Options')
    misc_group.add_argument(
        '-k', '--aniskip',
        action='store_true',
        help='Skip intro and outro'
    )
    misc_group.add_argument(
        '-K', '--keep-watching',
        action='store_true',
        help='Continue watching'
    )
    misc_group.add_argument(
        '-r', '--random-anime',
        type=str,
        nargs='?',
        const="all",
        help='Select random anime (default genre is "all", Eg.: Drama)'
    )
    misc_group.add_argument(
        '-D', '--only-direct-link',
        action='store_true',
        help='Output direct link'
    )
    misc_group.add_argument(
        '-C', '--only-command',
        action='store_true',
        help='Output command'
    )
    misc_group.add_argument(
        '-x', '--proxy',
        type=str,
        help='Set HTTP Proxy - E.g. http://0.0.0.0:8080'
    )
    misc_group.add_argument(
        '-w', '--use-playwright',
        action='store_true',
        help='Bypass fetching with a headless browser using Playwright instead (EXPERIMENTAL!!!)'
    )
    misc_group.add_argument(
        '-t', '--use-tor',
        action='store_true',
        help='Verwende Tor-Netzwerk für Anonymität und zum Umgehen von IP-Blockierungen'
    )

    args = parser.parse_args()

    if not args.provider:
        if args.action == "Download":
            args.provider = aniworld_globals.DEFAULT_PROVIDER
        else:
            args.provider = aniworld_globals.DEFAULT_PROVIDER_WATCH

    if args.version:
        update_status = " (Update Available)" if is_version_outdated() else ""
        divider = "-------------------" if is_version_outdated() else ""
        banner = fR"""
     ____________________________________{divider}
    < Installed aniworld {get_version()} via {check_package_installation()}{update_status}. >
     ------------------------------------{divider}
            \\   ^__^
             \\  (oo)\\_______
                (__)\\       )\\/\\
                    ||----w |
                    ||     ||
        """

        print(banner)
        sys.exit()

    if args.episode and args.episode_file:
        msg = "Cannot specify both --episode and --episode-file."
        logging.critical(msg)
        print(msg)
        sys.exit()

    if args.debug:
        os.environ['IS_DEBUG_MODE'] = '1'
        aniworld_globals.IS_DEBUG_MODE = True
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("============================================")
        logging.debug("Welcome to Aniworld!")
        logging.debug("============================================\n")
        logging.debug("Debug mode enabled")

        if platform.system() == "Darwin":
            if not is_tail_running():
                try:
                    subprocess.run(
                        [
                            "osascript",
                            "-e",
                            'tell application "Terminal" to do script "'
                            'trap exit SIGINT; '
                            'tail -f -n +1 $TMPDIR/aniworld.log" '
                            'activate'
                        ],
                        check=True
                    )
                    logging.debug("Started tailing the log file in a new Terminal window.")
                except subprocess.CalledProcessError as e:
                    logging.error("Failed to start tailing the log file: %s", e)
        elif platform.system() == "Windows":
            try:
                command = ('start cmd /c "powershell -NoExit -c Get-Content '
                           '-Wait \\"$env:TEMP\\aniworld.log\\""')
                subprocess.Popen(command, shell=True)  # pylint: disable=consider-using-with
                logging.debug("Started tailing the log file in a new Terminal window.")
            except subprocess.CalledProcessError as e:
                logging.error("Failed to start tailing the log file: %s", e)
        elif platform.system() == "Linux":
            open_terminal_with_command('tail -f -n +1 /tmp/aniworld.log')

    if args.uninstall:
        self_uninstall()

    if args.update:
        update_component(args.update)
        sys.exit()

    if args.proxy:
        os.environ['HTTP_PROXY'] = args.proxy
        os.environ['HTTPS_PROXY'] = args.proxy
        aniworld_globals.DEFAULT_PROXY = args.proxy
        logging.debug("Proxy set to: %s", args.proxy)
        
    if args.use_tor:
        os.environ['USE_TOR'] = 'True'
        aniworld_globals.USE_TOR = True
        logging.info("Tor-Netzwerk wird verwendet für anonyme Verbindungen")

    if args.anime4k:
        setup_anime4k(args.anime4k)

    if args.syncplay_password:
        os.environ['SYNCPLAY_PASSWORD'] = args.syncplay_password[0]
        logging.debug("Syncplay password set.")

    if args.syncplay_hostname:
        os.environ['SYNCPLAY_HOSTNAME'] = args.syncplay_hostname
        logging.debug("Syncplay hostname set.")

    if args.syncplay_username:
        os.environ['SYNCPLAY_USERNAME'] = args.syncplay_username
        logging.debug("Syncplay username set.")

    if args.syncplay_room:
        os.environ['SYNCPLAY_ROOM'] = args.syncplay_room
        logging.debug("Syncplay room set.")

    if args.output_directory:
        os.environ['OUTPUT_DIRECTORY'] = args.output_directory
        logging.debug("Output directory set.")

    if args.use_playwright:
        os.environ['USE_PLAYWRIGHT'] = str(args.use_playwright)
        logging.debug("Playwright set.")

    if not args.slug and args.random_anime:
        args.slug = get_random_anime(args.random_anime)

    return args


def handle_query(args):
    logging.debug("Handling query with args: %s", args)
    if args.query and not args.episode:
        slug = search_anime(query=args.query)
        logging.debug("Found slug: %s", slug)
        season_data = get_season_data(anime_slug=slug)
        logging.debug("Season data: %s", season_data)
        episode_list = list(season_data)
        logging.debug("Episode list: %s", episode_list)

        user_input = input("Please enter the episode (e.g., S1E2): ")
        logging.debug("User input: %s", user_input)
        match = re.match(r"S(\d+)E(\d+)", user_input)
        if match:
            s = int(match.group(1))
            e = int(match.group(2))
            logging.debug("Parsed season: %d, episode: %d", s, e)

        args.episode = [f"https://aniworld.to/anime/stream/{slug}/staffel-{s}/episode-{e}"]
        logging.debug("Set episode URL: %s", args.episode)


def get_anime_title(args):
    logging.debug("Getting anime title from args: %s", args)
    if args.link:
        title = args.link.split('/')[-1]
        logging.debug("Anime title from link: %s", title)
        return title
    if args.slug:
        logging.debug("Anime title from slug: %s", args.slug)
        return args.slug
    if args.episode:
        title = args.episode[0].split('/')[5]
        logging.debug("Anime title from episode URL: %s", title)
        return title
    return None


def main():
    # Globale Variablen
    global DEFAULT_PROVIDER
    global DEFAULT_LANGUAGE
    global DEFAULT_DOWNLOAD_PATH
    global DEFAULT_PROVIDER_WATCH

    # Setze Zeitlimit für Anfragen
    socket.setdefaulttimeout(30)

    # Logging-Setup: Alle Logs in Datei umleiten, nur kritische Fehler auf Konsole
    # Stelle sicher, dass der Log-Handler existiert
    file_handler = aniworld_globals.setup_file_handler()
    
    # Konsolen-Handler nur für kritische Fehler
    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s%(levelname)s:%(message)s',
        log_colors=aniworld_globals.log_colors))
    console_handler.setLevel(logging.CRITICAL)  # Nur kritische Fehler auf der Konsole

    # Konfiguriere das Root-Logger
    logger = logging.getLogger()
    
    if aniworld_globals.IS_DEBUG_MODE:
        logger.setLevel(logging.DEBUG)
        # Warnung über Debug-Modus anzeigen (einmalig auf Konsole)
        print(f"DEBUG-Modus ist aktiviert! Logs werden in {aniworld_globals.LOG_FILE_PATH} gespeichert.")
    else:
        logger.setLevel(logging.INFO)
    
    # Entferne alle bestehenden Handler
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Füge die neuen Handler hinzu
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Reduziere das Logging-Level für externe Bibliotheken
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    # Initialisiere die Episoden-Datenbank und starte eine Hintergrund-Indizierung
    try:
        from aniworld.common.db import get_db
        db = get_db()
        
        # Überprüfe, ob ein Download-Pfad konfiguriert ist
        download_path = aniworld_globals.DEFAULT_DOWNLOAD_PATH
        if download_path and os.path.exists(download_path):
            # Starte einen Thread für die Hintergrund-Indizierung mit einer neuen Funktion,
            # damit die Hauptanwendung nicht blockiert wird
            def run_background_indexing():
                try:
                    import time
                    # Warte kurz, damit die Hauptanwendung starten kann
                    time.sleep(1)
                    # Logging in Datei statt Konsolenausgabe
                    logging.info(f"Starte Hintergrund-Indexierung des Download-Ordners: {download_path}")
                    from aniworld.common.db import get_db
                    background_db = get_db()  # Eine eigene Instanz für diesen Thread
                    background_db.scan_directory(download_path)
                    logging.info("Hintergrund-Indexierung abgeschlossen")
                except Exception as e:
                    logging.error(f"Fehler bei der Hintergrund-Indexierung: {e}")
            
            # Starte den Thread
            threading.Thread(
                target=run_background_indexing, 
                daemon=True,
                name="DB-Indexer"
            ).start()
            logging.info(f"Hintergrund-Indexierung des Download-Ordners gestartet: {download_path}")
        else:
            logging.info("Kein gültiger Download-Pfad konfiguriert, Indexierung wird übersprungen")
    except Exception as e:
        logging.warning(f"Episoden-Datenbank konnte nicht initialisiert werden: {e}")
        
    logging.debug("============================================")
    logging.debug("Welcome to Aniworld!")
    logging.debug("============================================\n")
    if not check_internet_connection():
        clear_screen()

        logging.disable(logging.CRITICAL)
        adventure()

        sys.exit()

    # Argumente parsen
    try:
        args = parse_arguments()
        logging.debug("Parsed arguments: %s", args)

        validate_link(args)
        handle_query(args)

        language = get_language_code(args.language)
        logging.debug("Language code: %s", language)

        if args.episode_file:
            animes = read_episode_file(args.episode_file)
            for slug, seasons in animes.items():
                if args.output == aniworld_globals.DEFAULT_DOWNLOAD_PATH:
                    args.output = os.path.join(args.output, slug.replace("-", " ").title())
                execute_with_params(args, seasons, slug, language, anime_slug=slug)
            sys.exit()

        anime_title = get_anime_title(args)
        logging.debug("Anime title: %s", anime_title)

        selected_episodes = get_selected_episodes(args, anime_title)

        logging.debug("Selected episodes: %s", selected_episodes)

        if args.episode:
            for episode_url in args.episode:
                slug = episode_url.split('/')[-1]
                execute_with_params(args, selected_episodes, anime_title, language, anime_slug=slug)
            logging.debug("Execution complete. Exiting.")
            sys.exit()
    except KeyboardInterrupt:
        logging.debug("KeyboardInterrupt encountered. Exiting.")
        sys.exit()

    run_app_with_query(args)


def validate_link(args):
    if args.link:
        if args.link.count('/') == 5:
            logging.debug("Provided link format valid.")
        elif args.link.count('/') == 6 and args.link.endswith('/'):
            logging.debug("Provided link format valid.")
            args.link = args.link.rstrip('/')
        else:
            logging.debug("Provided link invalid.")
            args.link = None


def get_selected_episodes(args, anime_title):
    updated_list = None
    if args.keep_watching and args.episode:
        season_data = get_season_data(anime_slug=anime_title)
        logging.debug("Season data: %s", season_data)
        episode_list = list(season_data)
        logging.debug("Episode list: %s", episode_list)

        index = episode_list.index(args.episode[0])
        updated_list = episode_list[index:]
        logging.debug("Updated episode list: %s", updated_list)

    return updated_list if updated_list else args.episode


def check_other_extractors(episode_urls: list):
    logging.debug("Those are all urls: %s", episode_urls)

    jav_urls = []
    nhentai_urls = []
    streamkiste_urls = []
    hanime_urls = []
    remaining_urls = []

    for episode in episode_urls:
        if episode.startswith("https://jav.guru/"):
            jav_urls.append(episode)
        elif episode.startswith("https://nhentai.net/g/"):
            nhentai_urls.append(episode)
        elif episode.startswith("https://streamkiste.tv/movie/"):
            streamkiste_urls.append(episode)
        elif episode.startswith("https://hanime.tv/videos/hentai/"):
            hanime_urls.append(episode)
        else:
            remaining_urls.append(episode)

    logging.debug("Jav URLs: %s", jav_urls)
    logging.debug("Nhentai URLs: %s", nhentai_urls)
    logging.debug("Hanime URLs: %s", hanime_urls)
    logging.debug("Streamkiste URLs: %s", streamkiste_urls)

    for jav_url in jav_urls:
        logging.info("Processing JAV URL: %s", jav_url)
        jav(jav_url)

    for nhentai_url in nhentai_urls:
        logging.info("Processing Nhentai URL: %s", nhentai_url)
        nhentai(nhentai_url)

    for hanime_url in hanime_urls:
        logging.info("Processing hanime URL: %s", hanime_url)
        hanime(hanime_url)

    for streamkiste_url in streamkiste_urls:
        logging.info("Processing Streamkiste URL: %s", streamkiste_url)
        streamkiste(streamkiste_url)

    return remaining_urls


def execute_with_params(params: Dict[str, Any]) -> None:
    """
    Führt die Verarbeitung mit den angegebenen Parametern aus und zeigt Fehlermeldungen im TUI an
    """
    from aniworld.execute import execute
    
    try:
        only_direct_link = params.get('only_direct_link', False)
        only_command = params.get('only_command', False)
        force_download = params.get('force_download', False)
        
        result = execute(params)
        
        if result:  # Fehler aufgetreten
            error_msg = result.get("message", "Unbekannter Fehler")
            available_langs = result.get("available_languages", [])
            
            if "keine Streams verfügbar" in error_msg.lower() and available_langs:
                langs_str = ", ".join(available_langs)
                error_msg = f"Keine Streams für die gewählte Sprache verfügbar.\nVerfügbare Sprachen: {langs_str}"
            
            # Fehlermeldung im TUI anzeigen
            npyscreen.notify_confirm(
                error_msg,
                title="Fehler bei der Ausführung",
                form_color="DANGER",
                wrap=True,
                wide=True
            )
        elif not (only_direct_link or only_command):
            npyscreen.notify_confirm(
                "Ausführung erfolgreich abgeschlossen!",
                title="Erfolg",
                form_color="GOOD",
                wrap=True
            )
            
    except Exception as e:
        npyscreen.notify_confirm(
            f"Unerwarteter Fehler: {str(e)}",
            title="Fehler",
            form_color="DANGER",
            wrap=True,
            wide=True
        )
        logging.exception("Unerwarteter Fehler in execute_with_params:")


def run_app_with_query(args):
    """Run the application with a query, slug, or link."""
    # Prüfe, ob wir in einer SSH-Sitzung sind
    is_ssh = os.environ.get('SSH_CLIENT') or os.environ.get('SSH_TTY')
    
    if is_ssh and args.slug:
        logging.info("SSH-Sitzung erkannt, verwende direkte Parameterverarbeitung ohne TUI")
        direct_execute_with_params(args)
    else:
        try:
            try:
                logging.debug("Trying to resize Terminal.")
                set_terminal_size()
                run_app(search_anime(slug=args.slug, link=args.link))
            except npyscreen.wgwidget.NotEnoughSpaceForWidget:
                logging.debug("Not enough space for widget. Asking user to resize terminal.")
                clear_screen()
                print("Please increase your current terminal size.")
                logging.debug("Exiting due to terminal size.")
                sys.exit()
        except KeyboardInterrupt:
            logging.debug("KeyboardInterrupt encountered. Exiting.")
            sys.exit()


def run_app(query):
    logging.debug("Running app with query: %s", query)
    clear_screen()
    app = AnimeApp(query)
    app.run()


def direct_execute_with_params(args):
    """Führt die Aktion direkt aus, ohne das TUI zu verwenden."""
    try:
        anime_slug = search_anime(slug=args.slug, link=args.link)
        if not anime_slug:
            print(f"Konnte keine Anime-Informationen für den Slug '{args.slug}' finden.")
            return
            
        # Anime-Titel aus dem Slug ableiten (vereinfachte Version)
        anime_title = anime_slug.replace('-', ' ').title()
        
        language = get_language_code(args.language) if args.language else 1  # Default: German Dub
        
        # Wenn args.episode numerische Werte enthält, konvertieren wir sie in URLs
        if args.episode:
            try:
                # Prüfen, ob die Episoden numerisch sind
                episode_numbers = []
                for ep in args.episode:
                    try:
                        # Versuche, die Episode als Zahl zu interpretieren
                        episode_numbers.append(int(ep))
                    except ValueError:
                        # Wenn es keine Zahl ist, behandle es als URL
                        episode_numbers.append(ep)
                
                # Wenn wir numerische Episoden haben, konvertieren wir sie in URLs
                if all(isinstance(ep, int) for ep in episode_numbers):
                    logging.debug("Konvertiere Episodennummern in URLs")
                    # Erstelle URLs für die Episoden
                    base_url = f"https://aniworld.to/anime/stream/{anime_slug}/staffel-1/episode-"
                    selected_episodes = [f"{base_url}{ep}" for ep in episode_numbers]
                else:
                    # Wenn es bereits URLs sind, verwende sie direkt
                    selected_episodes = args.episode
            except Exception as e:
                logging.error("Fehler beim Konvertieren der Episodennummern: %s", str(e))
                selected_episodes = args.episode
        else:
            print("Keine Episode angegeben. Verwende Episode 1.")
            base_url = f"https://aniworld.to/anime/stream/{anime_slug}/staffel-1/episode-"
            selected_episodes = [f"{base_url}1"]
            
        execute_with_params(args, selected_episodes, anime_title, language, anime_slug)
    except Exception as e:
        logging.error("Fehler bei der direkten Ausführung: %s", str(e))
        print(f"Ein Fehler ist aufgetreten: {str(e)}")


if __name__ == "__main__":
    main()
