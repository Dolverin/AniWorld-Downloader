#!/usr/bin/env python
# encoding: utf-8

import logging
import os
import platform
import re
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

from aniworld.common.common import sanitize_path


def get_database_path():
    """
    Gibt den Pfad zur SQLite-Datenbank zurück.
    Speichert die Datenbank im Anwendungsdatenverzeichnis.
    """
    if platform.system() == "Windows":
        base_dir = os.path.join(os.getenv('APPDATA'), 'aniworld')
    else:
        base_dir = os.path.join(os.getenv('HOME'), '.aniworld')

    # Stelle sicher, dass der Ordner existiert
    os.makedirs(base_dir, exist_ok=True)

    return os.path.join(base_dir, 'episode_index.db')


class ThreadSafeSQLite:
    """Eine Thread-sichere Wrapper-Klasse für SQLite."""

    def __init__(self, db_path: str):
        """
        Initialisiert den Thread-sicheren SQLite-Wrapper.

        Args:
            db_path: Pfad zur SQLite-Datenbank
        """
        self.db_path = db_path
        self.local = threading.local()
        self.lock = threading.RLock()

    def get_connection(self):
        """
        Gibt eine Thread-lokale Verbindung zurück.
        Jeder Thread erhält seine eigene Verbindung.

        Returns:
            Eine SQLite-Connection für den aktuellen Thread
        """
        if not hasattr(self.local, 'conn') or self.local.conn is None:
            self.local.conn = sqlite3.connect(self.db_path)
            self.local.conn.row_factory = sqlite3.Row
        return self.local.conn

    def execute(self, query: str, params: Tuple = ()):
        """
        Führt eine SQL-Abfrage thread-sicher aus.

        Args:
            query: SQL-Abfrage
            params: Parameter für die Abfrage

        Returns:
            Cursor-Objekt mit dem Ergebnis
        """
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor

    def executemany(self, query: str, params_list: List[Tuple]):
        """
        Führt eine SQL-Abfrage mit mehreren Parametersätzen thread-sicher aus.

        Args:
            query: SQL-Abfrage
            params_list: Liste von Parametern für die Abfrage

        Returns:
            Cursor-Objekt mit dem Ergebnis
        """
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            return cursor

    def commit(self):
        """Commit der Transaktion im aktuellen Thread."""
        if hasattr(self.local, 'conn') and self.local.conn is not None:
            with self.lock:
                self.local.conn.commit()

    def close(self):
        """Schließt die Verbindung im aktuellen Thread."""
        if hasattr(self.local, 'conn') and self.local.conn is not None:
            with self.lock:
                self.local.conn.close()
                self.local.conn = None


class EpisodeDatabase:
    """
    SQLite-Datenbank zur Indexierung von Episodendateien im Dateisystem.
    Speichert Informationen über Anime, Staffeln, Episoden und Dateinamen.
    """

    def __init__(self):
        """Initialisiert die Datenbankverbindung und erstellt die Tabellen, falls nötig."""
        self.db_path = get_database_path()
        self.db = ThreadSafeSQLite(self.db_path)
        self.is_indexing = False
        self.create_tables()
        logging.debug(
            f"Thread-sichere Datenbank initialisiert: {self.db_path}")

    def create_tables(self):
        """Erstellt die erforderlichen Tabellen in der Datenbank, falls sie nicht existieren."""
        try:
            # Tabelle für Episodendateien
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS episode_files (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    season INTEGER,
                    episode INTEGER NOT NULL,
                    language TEXT,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    last_modified INTEGER NOT NULL,
                    indexed_at INTEGER NOT NULL
                )
            ''')

            # Indizes für schnellere Suche
            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_episode_search ON episode_files
                (title, season, episode, language)
            ''')

            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_file_path ON episode_files
                (file_path)
            ''')

            # Tabelle für Scan-Verlauf
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY,
                    directory TEXT NOT NULL,
                    last_scan INTEGER NOT NULL
                )
            ''')

            # Neue Tabelle für Download-Statistiken
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS download_stats (
                    id INTEGER PRIMARY KEY,
                    episode_id INTEGER,
                    download_date INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    download_speed REAL,
                    file_size INTEGER,
                    download_duration INTEGER,
                    status TEXT NOT NULL,
                    FOREIGN KEY (episode_id) REFERENCES episode_files (id)
                )
            ''')

            # Index für schnellere Abfragen der Download-Statistiken
            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_download_stats_episode ON download_stats
                (episode_id)
            ''')

            # --- NEUE TABELLEN FÜR CACHE-SYSTEM ---

            # Tabelle für grundlegende Anime-Metadaten
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS anime_metadata (
                    id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT,
                    thumbnail_url TEXT,
                    last_updated INTEGER NOT NULL,
                    ttl INTEGER NOT NULL,
                    UNIQUE(slug)
                )
            ''')

            # Tabelle für Staffel-Metadaten
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS season_metadata (
                    id INTEGER PRIMARY KEY,
                    anime_id INTEGER NOT NULL,
                    season_number INTEGER NOT NULL,
                    season_title TEXT NOT NULL,
                    episode_count INTEGER,
                    last_updated INTEGER NOT NULL,
                    FOREIGN KEY (anime_id) REFERENCES anime_metadata (id) ON DELETE CASCADE,
                    UNIQUE(anime_id, season_number)
                )
            ''')

            # Tabelle für Episoden-Metadaten
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS episode_metadata (
                    id INTEGER PRIMARY KEY,
                    season_id INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    episode_title TEXT,
                    url TEXT,
                    last_updated INTEGER NOT NULL,
                    FOREIGN KEY (season_id) REFERENCES season_metadata (id) ON DELETE CASCADE,
                    UNIQUE(season_id, episode_number)
                )
            ''')

            # Tabelle für Sprachverfügbarkeit
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS language_availability (
                    id INTEGER PRIMARY KEY,
                    episode_id INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    is_available BOOLEAN NOT NULL,
                    last_checked INTEGER NOT NULL,
                    FOREIGN KEY (episode_id) REFERENCES episode_metadata (id) ON DELETE CASCADE,
                    UNIQUE(episode_id, language)
                )
            ''')

            # Indizes für schnellere Suche nach Metadaten
            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_anime_slug ON anime_metadata (slug)
            ''')

            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_season_anime ON season_metadata (anime_id)
            ''')

            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_episode_season ON episode_metadata (season_id)
            ''')

            self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_language_episode ON language_availability (episode_id, language)
            ''')

            self.db.commit()
            logging.debug("Alle Tabellen wurden erfolgreich erstellt oder existieren bereits")
        except Exception as e:
            logging.error(f"Fehler beim Erstellen der Tabellen: {e}")

    def scan_directory(
            self,
            directory: str,
            force_rescan: bool = False) -> int:
        """
        Durchsucht ein Verzeichnis nach Episodendateien und aktualisiert den Index.

        Args:
            directory: Pfad zum Verzeichnis, das durchsucht werden soll
            force_rescan: Erzwingt vollständigen Rescan unabhängig vom letzten Scan-Zeitpunkt

        Returns:
            Anzahl der neu indizierten Dateien
        """
        if not os.path.exists(directory):
            logging.warning(
                f"Verzeichnis {directory} existiert nicht und kann nicht gescannt werden")
            return 0

        # Setze den Indexierungsstatus
        thread_id = threading.get_ident()
        logging.debug(
            f"DEBUG-SCAN: Thread {thread_id} startet Indizierung von {directory}")

        # Verwende einen lokalen Indexierungs-Flag für diesen Thread
        local_indexing = True

        try:
            # Prüfe, wann das Verzeichnis zuletzt gescannt wurde
            if not force_rescan:
                cursor = self.db.execute(
                    "SELECT last_scan FROM scan_history WHERE directory = ?",
                    (directory,)
                )
                result = cursor.fetchone()

                if result:
                    last_scan = result[0]
                    # Wenn innerhalb der letzten Stunde gescannt und kein
                    # force_rescan, überspringe
                    if time.time() - last_scan < 3600:  # 1 Stunde
                        logging.debug(
                            f"DEBUG-SCAN: Verzeichnis {directory} wurde vor weniger als 1 Stunde gescannt, Scan wird übersprungen")
                        return 0

            logging.info(f"DEBUG-SCAN: Starte Indexierung von {directory}")

            # Aktuelle Dateien in der Datenbank für dieses Verzeichnis
            try:
                cursor = self.db.execute(
                    "SELECT id, file_path, last_modified FROM episode_files WHERE file_path LIKE ?",
                    (f"{directory}%",)
                )
                existing_files = {
                    row['file_path']: (
                        row['id'],
                        row['last_modified']) for row in cursor.fetchall()}
                logging.debug(
                    f"DEBUG-SCAN: {len(existing_files)} bereits indizierte Dateien gefunden")
            except Exception as e:
                logging.error(
                    f"DEBUG-SCAN: Fehler beim Abfragen vorhandener Dateien: {e}")
                existing_files = {}

            new_files_count = 0
            current_time = int(time.time())

            # Rekursiv alle Dateien im Verzeichnis durchsuchen
            try:
                all_files = []
                for root, dirs, files in os.walk(directory):
                    logging.debug(
                        f"DEBUG-SCAN: Durchsuche Verzeichnis: {root} mit {len(files)} Dateien")
                    for file in files:
                        all_files.append((root, file))

                logging.debug(
                    f"DEBUG-SCAN: Insgesamt {len(all_files)} Dateien gefunden")

                # Verarbeite Dateien
                for i, (root, file) in enumerate(all_files):
                    if i % 100 == 0:
                        logging.debug(
                            f"DEBUG-SCAN: Verarbeite Datei {i}/{len(all_files)}")

                    file_path = os.path.join(root, file)

                    try:
                        # Letzte Änderung der Datei auslesen
                        file_mtime = int(os.path.getmtime(file_path))

                        # Prüfen ob Datei neu oder geändert wurde
                        if file_path in existing_files:
                            file_id, db_mtime = existing_files[file_path]
                            if file_mtime <= db_mtime:
                                # Datei ist nicht neu und wurde nicht geändert
                                continue

                            # Datei wurde geändert, also vorhandenen Eintrag
                            # löschen
                            self.db.execute(
                                "DELETE FROM episode_files WHERE id = ?", (file_id,))

                        # Versuche, Anime-Informationen aus dem Dateinamen zu
                        # extrahieren
                        logging.debug(
                            f"DEBUG-SCAN: Analysiere Dateiname: {file}")
                        extracted_info = self._parse_filename(file, file_path)
                        if extracted_info:
                            title, season, episode, language = extracted_info
                            logging.debug(
                                f"DEBUG-SCAN: Extrahierte Info: {title}, S{season}E{episode}, {language}")

                            # Neuen Eintrag erstellen
                            try:
                                self.db.execute(
                                    '''
                                    INSERT INTO episode_files
                                    (title, season, episode, language, file_path, file_name, last_modified, indexed_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (title, season, episode, language, file_path, file, file_mtime, current_time))

                                new_files_count += 1
                                if new_files_count % 100 == 0:
                                    logging.debug(
                                        f"DEBUG-SCAN: Bereits {new_files_count} neue Dateien indexiert")
                                    self.db.commit()  # Zwischenspeichern für große Verzeichnisse
                            except sqlite3.Error as e:
                                logging.error(
                                    f"DEBUG-SCAN: Datenbankfehler beim Einfügen von {file_path}: {e}")
                        else:
                            logging.debug(
                                f"DEBUG-SCAN: Keine Anime-Info gefunden in: {file}")

                    except (OSError, sqlite3.Error) as e:
                        logging.error(
                            f"DEBUG-SCAN: Fehler beim Verarbeiten von {file_path}: {e}")
            except Exception as e:
                logging.error(
                    f"DEBUG-SCAN: Unerwarteter Fehler beim Verarbeiten des Verzeichnisses: {e}")

            # Lösche Einträge für Dateien, die nicht mehr existieren
            try:
                deleted_count = 0
                for file_path in existing_files:
                    if not os.path.exists(file_path):
                        self.db.execute(
                            "DELETE FROM episode_files WHERE file_path = ?", (file_path,))
                        deleted_count += 1

                logging.debug(
                    f"DEBUG-SCAN: {deleted_count} nicht mehr existierende Dateien aus dem Index entfernt")
            except Exception as e:
                logging.error(
                    f"DEBUG-SCAN: Fehler beim Löschen nicht mehr existierender Dateien: {e}")

            # Aktualisiere den Scan-Verlauf
            try:
                self.db.execute(
                    "INSERT OR REPLACE INTO scan_history (directory, last_scan) VALUES (?, ?)",
                    (directory, current_time)
                )

                self.db.commit()
                logging.info(
                    f"DEBUG-SCAN: Indexierung abgeschlossen. {new_files_count} neue Dateien indexiert.")
            except Exception as e:
                logging.error(
                    f"DEBUG-SCAN: Fehler beim Aktualisieren des Scan-Verlaufs: {e}")

            return new_files_count

        except Exception as e:
            logging.error(
                f"DEBUG-SCAN: Kritischer Fehler bei der Indizierung von {directory}: {str(e)}")
            return 0

        finally:
            # Setze den lokalen Indexierungsstatus zurück
            local_indexing = False
            logging.debug(
                f"DEBUG-SCAN: Thread {thread_id} hat Indizierung abgeschlossen")

    def is_currently_indexing(self) -> bool:
        """
        Prüft, ob gerade eine Indizierung läuft.

        Returns:
            True wenn eine Indizierung läuft, sonst False
        """
        return self.is_indexing

    def _parse_filename(self, filename: str,
                        file_path: str) -> Optional[Tuple[str, int, int, str]]:
        """
        Extrahiert Anime-Titel, Staffel, Episode und Sprache aus einem Dateinamen.

        Args:
            filename: Der Dateiname
            file_path: Vollständiger Pfad zur Datei

        Returns:
            Tuple aus (Titel, Staffel, Episode, Sprache) oder None wenn keine Infos gefunden
        """
        # Verschiedene Muster für Episoden-Dateinamen
        patterns = [
            # Standard-Muster: "Anime Titel - S01E01 (German Dub).mp4"
            r"(.*?) - S(\d+)E(\d+) \((.*?)\)",

            # Ohne führende Nullen: "Anime Titel - S1E1 (German Dub).mp4"
            r"(.*?) - S(\d+)E(\d+) \((.*?)\)",

            # Andere Formate: "Anime Titel S01E01 German Dub.mp4"
            r"(.*?) S(\d+)E(\d+) (.*)",

            # Film-Format: "Anime Titel - Movie 01 (German Dub).mp4"
            r"(.*?) - Movie (\d+) \((.*?)\)",

            # Ausgeschriebene Staffel/Episode: "Anime Titel Staffel 1 Episode 1
            # German.mp4"
            r"(.*?) (?:Staffel|Season) (\d+) (?:Episode|Folge) (\d+) (.*)",

            # Mit Unterstrichen/Punkten: "Anime_Titel.S01E01.German.mp4"
            r"(.+?)[\._]S(\d+)E(\d+)[\._](.*)"
        ]

        # Sonderfall für Filme (ohne Staffel)
        movie_patterns = [
            # Film-Format: "Anime Titel - Movie 01 (German Dub).mp4"
            r"(.*?) - Movie (\d+) \((.*?)\)",

            # Andere Film-Formate
            r"(.*?) Movie (\d+) (.*)"
        ]

        try:
            # Versuche Staffel+Episode-Muster
            for pattern in patterns:
                match = re.match(pattern, filename, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    # Spezifische Muster können 3 oder 4 Gruppen haben
                    if len(groups) == 4:
                        title, season, episode, language = groups
                        return title.strip(), int(season), int(episode), language.strip()
                    elif len(groups) == 3:
                        # Falls keine Sprachinformation vorhanden, versuche aus
                        # dem Dateipfad zu extrahieren
                        title, season, episode = groups
                        language = self._extract_language_from_path(file_path)
                        return title.strip(), int(season), int(episode), language

            # Versuche Film-Muster (ohne Staffel)
            for pattern in movie_patterns:
                match = re.match(pattern, filename, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        title, episode, language = groups
                        return title.strip(), 0, int(episode), language.strip()
                    elif len(groups) == 2:
                        title, episode = groups
                        language = self._extract_language_from_path(file_path)
                        return title.strip(), 0, int(episode), language
        except Exception as e:
            logging.error(
                f"DEBUG-SCAN: Fehler beim Parsen des Dateinamens {filename}: {e}")

        return None

    def _extract_language_from_path(self, file_path: str) -> str:
        """
        Versucht, Sprachinfos aus dem Dateipfad zu extrahieren.

        Args:
            file_path: Vollständiger Pfad zur Datei

        Returns:
            Extrahierte Sprache oder "Unknown"
        """
        languages = ["German Dub", "German Sub", "English Sub", "English Dub"]

        # Überprüfe, ob einer der Sprachbegriffe im Pfad vorkommt
        for language in languages:
            if language.lower() in file_path.lower():
                return language

            # Auch nach alternativen Schreibweisen suchen
            alt_forms = [
                language.replace(" ", "."),
                language.replace(" ", "_"),
                language.replace(" ", "-"),
                language.split()[0]  # Nur die Sprache (German/English)
            ]

            for alt in alt_forms:
                if alt.lower() in file_path.lower():
                    return language

        return "Unknown"

    def episode_exists(
            self,
            anime_title: str,
            season: int,
            episode: int,
            language: str) -> bool:
        """
        Prüft, ob eine bestimmte Episode in der Datenbank vorhanden ist.

        Args:
            anime_title: Der Titel des Animes
            season: Staffelnummer
            episode: Episodennummer
            language: Sprachversion (z.B. "German Dub", "English Sub")

        Returns:
            True wenn die Episode existiert, sonst False
        """
        sanitized_title = sanitize_path(anime_title)

        # Normalisiere die Sprache, da sie in verschiedenen Formen gespeichert
        # sein könnte
        language_variants = [
            language,
            language.replace(" ", "."),
            language.replace(" ", "_"),
            language.replace(" ", "-"),
            language.split()[0]  # Nur die Sprache (German/English)
        ]

        # Suche nach exaktem Titel
        query = """
            SELECT 1 FROM episode_files
            WHERE (
                title = ? OR title LIKE ? OR title LIKE ?
            )
            AND season = ?
            AND episode = ?
            AND (
        """

        # Füge WHERE-Klauseln für jede Sprachvariante hinzu
        language_conditions = []
        for _ in language_variants:
            language_conditions.append("language LIKE ?")

        query += " OR ".join(language_conditions) + ")"

        # Bereite die Query-Parameter vor
        params = [
            sanitized_title,
            f"{sanitized_title}%",  # Titel-Präfix
            f"%{sanitized_title}%",  # Titel-Substring
            season,
            episode
        ]

        # Füge die Sprachvarianten zu den Parametern hinzu
        for lang in language_variants:
            params.append(f"%{lang}%")

        # Führe die Abfrage aus
        try:
            cursor = self.db.execute(query, params)
            result = cursor.fetchone()
            return result is not None
        except Exception as e:
            logging.error(f"DEBUG-DB: Fehler bei episode_exists Abfrage: {e}")
            return False

    def get_episode_file(
            self,
            anime_title: str,
            season: int,
            episode: int,
            language: str) -> Optional[Dict]:
        """
        Gibt den Dateipfad einer bestimmten Episode zurück, falls vorhanden.

        Args:
            anime_title: Der Titel des Animes
            season: Staffelnummer
            episode: Episodennummer
            language: Sprachversion (z.B. "German Dub", "English Sub")

        Returns:
            Dict mit Dateiinformationen oder None wenn nicht gefunden
        """
        sanitized_title = sanitize_path(anime_title)

        # Normalisiere die Sprache
        language_variants = [
            language,
            language.replace(" ", "."),
            language.replace(" ", "_"),
            language.replace(" ", "-"),
            language.split()[0]  # Nur die Sprache (German/English)
        ]

        # Suche nach exaktem Titel
        query = """
            SELECT id, title, season, episode, language, file_path, file_name, last_modified
            FROM episode_files
            WHERE (
                title = ? OR title LIKE ? OR title LIKE ?
            )
            AND season = ?
            AND episode = ?
            AND (
        """

        # Füge WHERE-Klauseln für jede Sprachvariante hinzu
        language_conditions = []
        for _ in language_variants:
            language_conditions.append("language LIKE ?")

        query += " OR ".join(language_conditions) + ")"

        # Bereite die Query-Parameter vor
        params = [
            sanitized_title,
            f"{sanitized_title}%",
            f"%{sanitized_title}%",
            season,
            episode
        ]

        # Füge die Sprachvarianten zu den Parametern hinzu
        for lang in language_variants:
            params.append(f"%{lang}%")

        # Führe die Abfrage aus
        try:
            cursor = self.db.execute(query, params)
            result = cursor.fetchone()

            if result:
                return dict(result)
            return None
        except Exception as e:
            logging.error(
                f"DEBUG-DB: Fehler bei get_episode_file Abfrage: {e}")
            return None

    def get_statistics(self) -> Dict:
        """
        Gibt Statistiken über die indexierten Episoden zurück.

        Returns:
            Dict mit Statistiken (Anzahl Animes, Episoden, etc.)
        """
        stats = {}

        try:
            # Gesamtzahl der indexierten Dateien
            cursor = self.db.execute("SELECT COUNT(*) FROM episode_files")
            stats['total_files'] = cursor.fetchone()[0]

            # Anzahl der Animes
            cursor = self.db.execute(
                "SELECT COUNT(DISTINCT title) FROM episode_files")
            stats['total_anime'] = cursor.fetchone()[0]

            # Größe der Datenbank
            if os.path.exists(self.db_path):
                stats['database_size_mb'] = round(
                    os.path.getsize(self.db_path) / (1024 * 1024), 2)
            else:
                stats['database_size_mb'] = 0

            # Letzte Indizierung
            cursor = self.db.execute("SELECT MAX(last_scan) FROM scan_history")
            last_scan = cursor.fetchone()[0]
            stats['last_indexed'] = last_scan if last_scan else 0

            return stats
        except Exception as e:
            logging.error(
                f"DEBUG-DB: Fehler beim Abrufen der Statistiken: {e}")
            return {'error': str(e)}

    def maintenance(self):
        """Führt Wartungsarbeiten an der Datenbank durch (Vacuum, Reindex, etc.)."""
        try:
            logging.info("Führe Datenbankwartung durch...")
            self.db.execute("VACUUM")
            self.db.execute("ANALYZE")
            logging.info("Datenbankwartung abgeschlossen")
        except sqlite3.Error as e:
            logging.error(f"Fehler bei der Datenbankwartung: {e}")

    def save_download_stats(self,
                            episode_id=None,
                            anime_title=None,
                            season=None,
                            episode=None,
                            language=None,
                            provider=None,
                            download_speed=None,
                            file_size=None,
                            download_duration=None,
                            status="completed"):
        """
        Speichert Informationen über einen Download in der Datenbank.

        Args:
            episode_id: ID der Episode in der Datenbank (wenn bekannt)
            anime_title: Titel des Animes (falls episode_id nicht bekannt)
            season: Staffelnummer (falls episode_id nicht bekannt)
            episode: Episodennummer (falls episode_id nicht bekannt)
            language: Sprache der Episode (falls episode_id nicht bekannt)
            provider: Name des Providers, von dem heruntergeladen wurde
            download_speed: Durchschnittliche Download-Geschwindigkeit in Bytes/Sekunde
            file_size: Größe der Datei in Bytes
            download_duration: Dauer des Downloads in Sekunden
            status: Status des Downloads (completed, failed, cancelled)

        Returns:
            ID des erstellten Datensatzes oder None bei Fehler
        """
        try:
            # Aktuelle Zeit als UNIX-Timestamp
            current_time = int(time.time())

            # Falls keine episode_id angegeben, versuche die Episode zu finden
            if not episode_id and anime_title and season is not None and episode is not None:
                episode_data = self.get_episode_file(
                    anime_title, season, episode, language)
                if episode_data:
                    episode_id = episode_data['id']

            # Speichere die Download-Statistik
            cursor = self.db.execute('''
                INSERT INTO download_stats
                (episode_id, download_date, provider, download_speed, file_size, download_duration, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                episode_id,
                current_time,
                provider or "unknown",
                download_speed,
                file_size,
                download_duration,
                status
            ))

            self.db.commit()
            logging.debug(
                f"Download-Statistik gespeichert: Provider={provider}, Status={status}")
            return cursor.lastrowid
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Download-Statistik: {e}")
            return None

    def get_download_stats(self, anime_title=None, provider=None, days=None):
        """
        Gibt Download-Statistiken zurück, gefiltert nach verschiedenen Kriterien.
        
        Args:
            anime_title: Filtert nach Anime-Titel
            provider: Filtert nach Provider
            days: Gibt nur Statistiken der letzten X Tage zurück
            
        Returns:
            Liste mit Download-Statistiken
        """
        try:
            query = """
                SELECT ds.*, ef.title, ef.season, ef.episode, ef.language, ef.file_path 
                FROM download_stats ds
                LEFT JOIN episode_files ef ON ds.episode_id = ef.id
                WHERE 1=1
            """
            params = []
            
            if anime_title:
                query += " AND ef.title LIKE ? "
                params.append(f"%{anime_title}%")
                
            if provider:
                query += " AND ds.provider = ? "
                params.append(provider)
                
            if days:
                min_time = int(time.time()) - (days * 86400)
                query += " AND ds.download_date >= ? "
                params.append(min_time)
                
            query += " ORDER BY ds.download_date DESC"
            
            cursor = self.db.execute(query, params)
            results = []
            for row in cursor.fetchall():
                # Konvertiere das Row-Objekt in ein Dictionary
                result = {}
                for key in row.keys():
                    result[key] = row[key]
                results.append(result)
            return results
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Download-Statistiken: {e}")
            return []

    # ----- NEUE METHODEN FÜR ANIME METADATA CACHE -----

    def save_anime_metadata(self, slug, title, description=None, thumbnail_url=None, ttl=86400):
        """
        Speichert oder aktualisiert Metadaten für einen Anime.
        
        Args:
            slug: Der eindeutige Slug des Animes (z.B. 'demon-slayer')
            title: Der Titel des Animes
            description: Die Beschreibung des Animes (optional)
            thumbnail_url: URL zum Thumbnail-Bild (optional)
            ttl: Time-to-Live in Sekunden (Standard: 24 Stunden)
            
        Returns:
            Die ID des Anime-Eintrags
        """
        try:
            current_time = int(time.time())
            
            # Prüfen, ob der Anime bereits existiert
            cursor = self.db.execute(
                "SELECT id FROM anime_metadata WHERE slug = ?", 
                (slug,)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Aktualisiere den bestehenden Eintrag
                self.db.execute("""
                    UPDATE anime_metadata 
                    SET title = ?, description = ?, thumbnail_url = ?, 
                        last_updated = ?, ttl = ?
                    WHERE id = ?
                """, (title, description, thumbnail_url, current_time, ttl, existing[0]))
                anime_id = existing[0]
            else:
                # Füge einen neuen Eintrag hinzu
                cursor = self.db.execute("""
                    INSERT INTO anime_metadata 
                    (slug, title, description, thumbnail_url, last_updated, ttl)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (slug, title, description, thumbnail_url, current_time, ttl))
                anime_id = cursor.lastrowid
            
            self.db.commit()
            logging.debug(f"Anime-Metadaten gespeichert/aktualisiert für {slug} (ID: {anime_id})")
            return anime_id
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Anime-Metadaten für {slug}: {e}")
            return None

    def get_anime_metadata(self, slug):
        """
        Ruft die Metadaten für einen Anime anhand seines Slugs ab.
        
        Args:
            slug: Der eindeutige Slug des Animes
            
        Returns:
            Dictionary mit Anime-Metadaten oder None, wenn nicht gefunden oder veraltet
        """
        try:
            cursor = self.db.execute("""
                SELECT id, slug, title, description, thumbnail_url, last_updated, ttl
                FROM anime_metadata 
                WHERE slug = ?
            """, (slug,))
            
            row = cursor.fetchone()
            if not row:
                return None
                
            current_time = int(time.time())
            anime_data = {
                'id': row[0],
                'slug': row[1],
                'title': row[2],
                'description': row[3],
                'thumbnail_url': row[4],
                'last_updated': row[5],
                'ttl': row[6]
            }
            
            # Prüfen, ob der Cache-Eintrag noch gültig ist
            if current_time - anime_data['last_updated'] > anime_data['ttl']:
                logging.debug(f"Cache-Eintrag für Anime {slug} ist veraltet")
                return None
                
            return anime_data
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Anime-Metadaten für {slug}: {e}")
            return None

    def save_season_metadata(self, anime_id, season_number, season_title, episode_count=None):
        """
        Speichert oder aktualisiert Metadaten für eine Staffel.
        
        Args:
            anime_id: Die ID des zugehörigen Animes
            season_number: Die Staffelnummer
            season_title: Der Titel der Staffel
            episode_count: Die Anzahl der Episoden (optional)
            
        Returns:
            Die ID des Staffel-Eintrags
        """
        try:
            current_time = int(time.time())
            
            # Prüfen, ob die Staffel bereits existiert
            cursor = self.db.execute(
                "SELECT id FROM season_metadata WHERE anime_id = ? AND season_number = ?", 
                (anime_id, season_number)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Aktualisiere den bestehenden Eintrag
                self.db.execute("""
                    UPDATE season_metadata 
                    SET season_title = ?, episode_count = ?, last_updated = ?
                    WHERE id = ?
                """, (season_title, episode_count, current_time, existing[0]))
                season_id = existing[0]
            else:
                # Füge einen neuen Eintrag hinzu
                cursor = self.db.execute("""
                    INSERT INTO season_metadata 
                    (anime_id, season_number, season_title, episode_count, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                """, (anime_id, season_number, season_title, episode_count, current_time))
                season_id = cursor.lastrowid
            
            self.db.commit()
            logging.debug(f"Staffel-Metadaten gespeichert für Anime ID {anime_id}, Staffel {season_number} (ID: {season_id})")
            return season_id
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Staffel-Metadaten für Anime ID {anime_id}, Staffel {season_number}: {e}")
            return None

    def get_seasons_for_anime(self, anime_id):
        """
        Ruft alle Staffeln für einen Anime ab.
        
        Args:
            anime_id: Die ID des Animes
            
        Returns:
            Liste von Dictionaries mit Staffel-Metadaten
        """
        try:
            cursor = self.db.execute("""
                SELECT id, anime_id, season_number, season_title, episode_count, last_updated
                FROM season_metadata 
                WHERE anime_id = ?
                ORDER BY season_number
            """, (anime_id,))
            
            seasons = []
            for row in cursor.fetchall():
                seasons.append({
                    'id': row[0],
                    'anime_id': row[1],
                    'season_number': row[2],
                    'season_title': row[3],
                    'episode_count': row[4],
                    'last_updated': row[5]
                })
                
            return seasons
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Staffeln für Anime ID {anime_id}: {e}")
            return []

    def save_episode_metadata(self, season_id, episode_number, episode_title=None, url=None):
        """
        Speichert oder aktualisiert Metadaten für eine Episode.
        
        Args:
            season_id: Die ID der zugehörigen Staffel
            episode_number: Die Episodennummer
            episode_title: Der Titel der Episode (optional)
            url: Die URL zur Episode (optional)
            
        Returns:
            Die ID des Episoden-Eintrags
        """
        try:
            current_time = int(time.time())
            
            # Prüfen, ob die Episode bereits existiert
            cursor = self.db.execute(
                "SELECT id FROM episode_metadata WHERE season_id = ? AND episode_number = ?", 
                (season_id, episode_number)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Aktualisiere den bestehenden Eintrag
                self.db.execute("""
                    UPDATE episode_metadata 
                    SET episode_title = ?, url = ?, last_updated = ?
                    WHERE id = ?
                """, (episode_title, url, current_time, existing[0]))
                episode_id = existing[0]
            else:
                # Füge einen neuen Eintrag hinzu
                cursor = self.db.execute("""
                    INSERT INTO episode_metadata 
                    (season_id, episode_number, episode_title, url, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                """, (season_id, episode_number, episode_title, url, current_time))
                episode_id = cursor.lastrowid
            
            self.db.commit()
            logging.debug(f"Episoden-Metadaten gespeichert für Staffel ID {season_id}, Episode {episode_number} (ID: {episode_id})")
            return episode_id
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Episoden-Metadaten für Staffel ID {season_id}, Episode {episode_number}: {e}")
            return None

    def get_episodes_for_season(self, season_id):
        """
        Ruft alle Episoden für eine Staffel ab.
        
        Args:
            season_id: Die ID der Staffel
            
        Returns:
            Liste von Dictionaries mit Episoden-Metadaten
        """
        try:
            cursor = self.db.execute("""
                SELECT id, season_id, episode_number, episode_title, url, last_updated
                FROM episode_metadata 
                WHERE season_id = ?
                ORDER BY episode_number
            """, (season_id,))
            
            episodes = []
            for row in cursor.fetchall():
                episodes.append({
                    'id': row[0],
                    'season_id': row[1],
                    'episode_number': row[2],
                    'episode_title': row[3],
                    'url': row[4],
                    'last_updated': row[5]
                })
                
            return episodes
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Episoden für Staffel ID {season_id}: {e}")
            return []

    def save_language_availability(self, episode_id, language, is_available):
        """
        Speichert oder aktualisiert die Verfügbarkeit einer Sprache für eine Episode.
        
        Args:
            episode_id: Die ID der Episode
            language: Die Sprache (z.B. 'German Dub', 'English Sub')
            is_available: Ob die Sprache verfügbar ist (True/False)
            
        Returns:
            Die ID des Verfügbarkeits-Eintrags
        """
        try:
            current_time = int(time.time())
            
            # Prüfen, ob der Eintrag bereits existiert
            cursor = self.db.execute(
                "SELECT id FROM language_availability WHERE episode_id = ? AND language = ?", 
                (episode_id, language)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Aktualisiere den bestehenden Eintrag
                self.db.execute("""
                    UPDATE language_availability 
                    SET is_available = ?, last_checked = ?
                    WHERE id = ?
                """, (1 if is_available else 0, current_time, existing[0]))
                entry_id = existing[0]
            else:
                # Füge einen neuen Eintrag hinzu
                cursor = self.db.execute("""
                    INSERT INTO language_availability 
                    (episode_id, language, is_available, last_checked)
                    VALUES (?, ?, ?, ?)
                """, (episode_id, language, 1 if is_available else 0, current_time))
                entry_id = cursor.lastrowid
            
            self.db.commit()
            logging.debug(f"Sprachverfügbarkeit gespeichert für Episode ID {episode_id}, Sprache {language}: {is_available}")
            return entry_id
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Sprachverfügbarkeit für Episode ID {episode_id}, Sprache {language}: {e}")
            return None

    def get_language_availability(self, episode_id, language=None, max_age=86400):
        """
        Ruft die Verfügbarkeit von Sprachen für eine Episode ab.
        
        Args:
            episode_id: Die ID der Episode
            language: Die spezifische Sprache, die abgefragt werden soll (optional)
            max_age: Maximales Alter der Daten in Sekunden (Standard: 24 Stunden)
            
        Returns:
            Bei language=None: Dictionary mit Sprache als Schlüssel und Verfügbarkeit als Wert
            Bei language spezifiziert: Boolean, ob die Sprache verfügbar ist, oder None wenn nicht bekannt
        """
        try:
            current_time = int(time.time())
            min_time = current_time - max_age
            
            if language:
                # Abfrage für eine spezifische Sprache
                cursor = self.db.execute("""
                    SELECT is_available, last_checked
                    FROM language_availability 
                    WHERE episode_id = ? AND language = ?
                """, (episode_id, language))
                
                row = cursor.fetchone()
                if not row:
                    return None
                    
                # Wenn der Eintrag zu alt ist, gib None zurück
                if row[1] < min_time:
                    return None
                    
                return bool(row[0])
            else:
                # Abfrage für alle Sprachen
                cursor = self.db.execute("""
                    SELECT language, is_available, last_checked
                    FROM language_availability 
                    WHERE episode_id = ?
                """, (episode_id,))
                
                languages = {}
                for row in cursor.fetchall():
                    # Ignoriere zu alte Einträge
                    if row[2] >= min_time:
                        languages[row[0]] = bool(row[1])
                        
                return languages
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Sprachverfügbarkeit für Episode ID {episode_id}: {e}")
            return {} if language is None else None

    def is_language_available(self, slug, season_number, episode_number, language, max_age=86400):
        """
        Überprüft, ob eine bestimmte Sprache für eine Episode verfügbar ist.
        
        Args:
            slug: Der Slug des Animes
            season_number: Die Staffelnummer
            episode_number: Die Episodennummer
            language: Die zu prüfende Sprache
            max_age: Maximales Alter der Daten in Sekunden (Standard: 24 Stunden)
            
        Returns:
            Boolean, ob die Sprache verfügbar ist, oder None wenn nicht im Cache
        """
        try:
            # Hole Anime-Metadaten
            anime_data = self.get_anime_metadata(slug)
            if not anime_data:
                return None
                
            # Hole Staffeln
            seasons = self.get_seasons_for_anime(anime_data['id'])
            season_id = None
            for season in seasons:
                if season['season_number'] == season_number:
                    season_id = season['id']
                    break
                    
            if not season_id:
                return None
                
            # Hole Episoden
            episodes = self.get_episodes_for_season(season_id)
            episode_id = None
            for episode in episodes:
                if episode['episode_number'] == episode_number:
                    episode_id = episode['id']
                    break
                    
            if not episode_id:
                return None
                
            # Prüfe die Sprachverfügbarkeit
            return self.get_language_availability(episode_id, language, max_age)
        except Exception as e:
            logging.error(f"Fehler beim Prüfen der Sprachverfügbarkeit für {slug}, S{season_number}E{episode_number}, {language}: {e}")
            return None

    def get_available_languages(self, slug, season_number, episode_number, max_age=86400):
        """
        Gibt alle verfügbaren Sprachen für eine Episode zurück.
        
        Args:
            slug: Der Slug des Animes
            season_number: Die Staffelnummer
            episode_number: Die Episodennummer
            max_age: Maximales Alter der Daten in Sekunden (Standard: 24 Stunden)
            
        Returns:
            Liste der verfügbaren Sprachen oder leere Liste, wenn nicht im Cache
        """
        try:
            # Hole Anime-Metadaten
            anime_data = self.get_anime_metadata(slug)
            if not anime_data:
                return []
                
            # Hole Staffeln
            seasons = self.get_seasons_for_anime(anime_data['id'])
            season_id = None
            for season in seasons:
                if season['season_number'] == season_number:
                    season_id = season['id']
                    break
                    
            if not season_id:
                return []
                
            # Hole Episoden
            episodes = self.get_episodes_for_season(season_id)
            episode_id = None
            for episode in episodes:
                if episode['episode_number'] == episode_number:
                    episode_id = episode['id']
                    break
                    
            if not episode_id:
                return []
                
            # Prüfe die Sprachverfügbarkeit
            languages = self.get_language_availability(episode_id, None, max_age)
            return [lang for lang, available in languages.items() if available]
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der verfügbaren Sprachen für {slug}, S{season_number}E{episode_number}: {e}")
            return []

    def invalidate_cache_for_anime(self, slug):
        """
        Markiert den Cache für einen Anime als veraltet, indem das last_updated auf 0 gesetzt wird.
        
        Args:
            slug: Der Slug des Animes
            
        Returns:
            Boolean, ob die Operation erfolgreich war
        """
        try:
            # Hole die Anime-ID
            cursor = self.db.execute("SELECT id FROM anime_metadata WHERE slug = ?", (slug,))
            row = cursor.fetchone()
            if not row:
                return False
                
            anime_id = row[0]
            
            # Setze last_updated auf 0, damit der Eintrag als veraltet gilt
            self.db.execute("UPDATE anime_metadata SET last_updated = 0 WHERE id = ?", (anime_id,))
            self.db.commit()
            
            logging.debug(f"Cache für Anime {slug} wurde invalidiert")
            return True
        except Exception as e:
            logging.error(f"Fehler beim Invalidieren des Caches für Anime {slug}: {e}")
            return False

    def get_last_scan_time(self, directory):
        """
        Gibt den Zeitpunkt des letzten Scans für ein bestimmtes Verzeichnis zurück.
        
        Args:
            directory: Der zu prüfende Pfad
            
        Returns:
            Zeitpunkt des letzten Scans als Unixzeit oder None, wenn kein Scan gefunden
        """
        try:
            # Finde alle Überverzeichnisse, die gescannt werden könnten
            potential_dirs = [directory]
            
            # Überverzeichnisse hinzufügen (z.B. für "/home/user/anime/show", auch "/home/user/anime" prüfen)
            parent = os.path.dirname(directory)
            while parent and parent != directory:
                potential_dirs.append(parent)
                directory = parent
                parent = os.path.dirname(directory)
            
            # Suche nach dem neuesten Scan für alle möglichen Verzeichnisse
            query = """
                SELECT MAX(last_scan) 
                FROM scan_history 
                WHERE directory IN ({})
            """.format(','.join(['?'] * len(potential_dirs)))
            
            cursor = self.db.execute(query, potential_dirs)
            row = cursor.fetchone()
            
            if row and row[0]:
                return row[0]
            return None
        except Exception as e:
            logging.error(f"Fehler beim Abrufen des letzten Scan-Zeitpunkts für {directory}: {e}")
            return None


# Globale Instanz für den einfachen Zugriff
_db_instance = None


def get_db() -> EpisodeDatabase:
    """
    Stellt sicher, dass nur eine Datenbankinstanz existiert und gibt diese zurück.

    Returns:
        Datenbankinstanz
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = EpisodeDatabase()
    return _db_instance
