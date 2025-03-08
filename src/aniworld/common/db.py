#!/usr/bin/env python
# encoding: utf-8

import os
import logging
import sqlite3
import re
import time
from typing import List, Dict, Tuple, Optional
import platform

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


class EpisodeDatabase:
    """
    SQLite-Datenbank zur Indexierung von Episodendateien im Dateisystem.
    Speichert Informationen über Anime, Staffeln, Episoden und Dateinamen.
    """
    
    def __init__(self):
        """Initialisiert die Datenbankverbindung und erstellt die Tabellen, falls nötig."""
        self.db_path = get_database_path()
        self.conn = None
        self.cursor = None
        self.is_indexing = False
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Stellt eine Verbindung zur SQLite-Datenbank her."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row  # Liefert Zeilen als dict-ähnliche Objekte
            self.cursor = self.conn.cursor()
            logging.debug(f"Verbindung zur Datenbank {self.db_path} hergestellt")
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Verbinden zur Datenbank: {e}")
            raise
    
    def close(self):
        """Schließt die Datenbankverbindung."""
        if self.conn:
            self.conn.close()
            logging.debug("Datenbankverbindung geschlossen")
    
    def create_tables(self):
        """Erstellt die erforderlichen Tabellen in der Datenbank, falls sie nicht existieren."""
        try:
            # Tabelle für Episodendateien
            self.cursor.execute('''
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
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_episode_search ON episode_files 
                (title, season, episode, language)
            ''')
            
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_file_path ON episode_files 
                (file_path)
            ''')
            
            # Tabelle für Scan-Verlauf
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY,
                    directory TEXT NOT NULL,
                    last_scan INTEGER NOT NULL
                )
            ''')
            
            self.conn.commit()
            logging.debug("Datenbanktabellen wurden initialisiert")
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Erstellen der Tabellen: {e}")
            self.conn.rollback()
            raise
    
    def scan_directory(self, directory: str, force_rescan: bool = False) -> int:
        """
        Durchsucht ein Verzeichnis nach Episodendateien und aktualisiert den Index.
        
        Args:
            directory: Pfad zum Verzeichnis, das durchsucht werden soll
            force_rescan: Erzwingt vollständigen Rescan unabhängig vom letzten Scan-Zeitpunkt
            
        Returns:
            Anzahl der neu indizierten Dateien
        """
        if not os.path.exists(directory):
            logging.warning(f"Verzeichnis {directory} existiert nicht und kann nicht gescannt werden")
            return 0
        
        # Setze den Indexierungsstatus
        self.is_indexing = True
        
        try:
            # Prüfe, wann das Verzeichnis zuletzt gescannt wurde
            if not force_rescan:
                self.cursor.execute(
                    "SELECT last_scan FROM scan_history WHERE directory = ?", 
                    (directory,)
                )
                result = self.cursor.fetchone()
                
                if result:
                    last_scan = result[0]
                    # Wenn innerhalb der letzten Stunde gescannt und kein force_rescan, überspringe
                    if time.time() - last_scan < 3600:  # 1 Stunde
                        logging.debug(f"Verzeichnis {directory} wurde vor weniger als 1 Stunde gescannt, Scan wird übersprungen")
                        self.is_indexing = False
                        return 0
            
            logging.info(f"DEBUG-SCAN: Starte Indexierung von {directory}")
            
            # Aktuelle Dateien in der Datenbank für dieses Verzeichnis
            try:
                self.cursor.execute(
                    "SELECT id, file_path, last_modified FROM episode_files WHERE file_path LIKE ?", 
                    (f"{directory}%",)
                )
                existing_files = {row['file_path']: (row['id'], row['last_modified']) for row in self.cursor.fetchall()}
                logging.debug(f"DEBUG-SCAN: {len(existing_files)} bereits indizierte Dateien gefunden")
            except Exception as e:
                logging.error(f"DEBUG-SCAN: Fehler beim Abfragen vorhandener Dateien: {e}")
                existing_files = {}
            
            new_files_count = 0
            current_time = int(time.time())
            
            # Rekursiv alle Dateien im Verzeichnis durchsuchen
            try:
                all_files = []
                for root, dirs, files in os.walk(directory):
                    logging.debug(f"DEBUG-SCAN: Durchsuche Verzeichnis: {root} mit {len(files)} Dateien")
                    for file in files:
                        all_files.append((root, file))
                
                logging.debug(f"DEBUG-SCAN: Insgesamt {len(all_files)} Dateien gefunden")
                
                # Verarbeite Dateien
                for i, (root, file) in enumerate(all_files):
                    if i % 100 == 0:
                        logging.debug(f"DEBUG-SCAN: Verarbeite Datei {i}/{len(all_files)}")
                        
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
                            
                            # Datei wurde geändert, also vorhandenen Eintrag löschen
                            self.cursor.execute("DELETE FROM episode_files WHERE id = ?", (file_id,))
                        
                        # Versuche, Anime-Informationen aus dem Dateinamen zu extrahieren
                        logging.debug(f"DEBUG-SCAN: Analysiere Dateiname: {file}")
                        extracted_info = self._parse_filename(file, file_path)
                        if extracted_info:
                            title, season, episode, language = extracted_info
                            logging.debug(f"DEBUG-SCAN: Extrahierte Info: {title}, S{season}E{episode}, {language}")
                            
                            # Neuen Eintrag erstellen
                            try:
                                self.cursor.execute('''
                                    INSERT INTO episode_files 
                                    (title, season, episode, language, file_path, file_name, last_modified, indexed_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    title, season, episode, language, file_path, file, 
                                    file_mtime, current_time
                                ))
                                
                                new_files_count += 1
                                if new_files_count % 100 == 0:
                                    logging.debug(f"DEBUG-SCAN: Bereits {new_files_count} neue Dateien indexiert")
                                    self.conn.commit()  # Zwischenspeichern für große Verzeichnisse
                            except sqlite3.Error as e:
                                logging.error(f"DEBUG-SCAN: Datenbankfehler beim Einfügen von {file_path}: {e}")
                        else:
                            logging.debug(f"DEBUG-SCAN: Keine Anime-Info gefunden in: {file}")
                    
                    except (OSError, sqlite3.Error) as e:
                        logging.error(f"DEBUG-SCAN: Fehler beim Verarbeiten von {file_path}: {e}")
            except Exception as e:
                logging.error(f"DEBUG-SCAN: Unerwarteter Fehler beim Verarbeiten des Verzeichnisses: {e}")
            
            # Lösche Einträge für Dateien, die nicht mehr existieren
            try:
                deleted_count = 0
                for file_path in existing_files:
                    if not os.path.exists(file_path):
                        self.cursor.execute("DELETE FROM episode_files WHERE file_path = ?", (file_path,))
                        deleted_count += 1
                
                logging.debug(f"DEBUG-SCAN: {deleted_count} nicht mehr existierende Dateien aus dem Index entfernt")
            except Exception as e:
                logging.error(f"DEBUG-SCAN: Fehler beim Löschen nicht mehr existierender Dateien: {e}")
            
            # Aktualisiere den Scan-Verlauf
            try:
                self.cursor.execute(
                    "INSERT OR REPLACE INTO scan_history (directory, last_scan) VALUES (?, ?)",
                    (directory, current_time)
                )
                
                self.conn.commit()
                logging.info(f"DEBUG-SCAN: Indexierung abgeschlossen. {new_files_count} neue Dateien indexiert.")
            except Exception as e:
                logging.error(f"DEBUG-SCAN: Fehler beim Aktualisieren des Scan-Verlaufs: {e}")
                
            return new_files_count
        
        except Exception as e:
            logging.error(f"DEBUG-SCAN: Kritischer Fehler bei der Indizierung von {directory}: {str(e)}")
            return 0
        
        finally:
            # Setze den Indexierungsstatus zurück
            self.is_indexing = False
            logging.debug("DEBUG-SCAN: Indizierung abgeschlossen, Status zurückgesetzt")
    
    def is_currently_indexing(self) -> bool:
        """
        Prüft, ob gerade eine Indizierung läuft.
        
        Returns:
            True wenn eine Indizierung läuft, sonst False
        """
        return self.is_indexing
    
    def _parse_filename(self, filename: str, file_path: str) -> Optional[Tuple[str, int, int, str]]:
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
            
            # Ausgeschriebene Staffel/Episode: "Anime Titel Staffel 1 Episode 1 German.mp4"
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
                        # Falls keine Sprachinformation vorhanden, versuche aus dem Dateipfad zu extrahieren
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
            logging.error(f"DEBUG-SCAN: Fehler beim Parsen des Dateinamens {filename}: {e}")
            
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
    
    def episode_exists(self, anime_title: str, season: int, episode: int, language: str) -> bool:
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
        # Wenn wir gerade indizieren, immer False zurückgeben, um Datenbankblockaden zu vermeiden
        if self.is_indexing:
            logging.debug(f"Indexierung läuft, Episode {anime_title} S{season}E{episode} wird als nicht vorhanden markiert")
            return False
            
        sanitized_title = sanitize_path(anime_title)
        
        # Normalisiere die Sprache, da sie in verschiedenen Formen gespeichert sein könnte
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
            f"%{sanitized_title}%", # Titel-Substring
            season,
            episode
        ]
        
        # Füge die Sprachvarianten zu den Parametern hinzu
        for lang in language_variants:
            params.append(f"%{lang}%")
            
        # Führe die Abfrage aus
        self.cursor.execute(query, params)
        result = self.cursor.fetchone()
        
        return result is not None
    
    def get_episode_file(self, anime_title: str, season: int, episode: int, language: str) -> Optional[Dict]:
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
        self.cursor.execute(query, params)
        result = self.cursor.fetchone()
        
        if result:
            return dict(result)
        return None
    
    def get_statistics(self) -> Dict:
        """
        Gibt Statistiken über die indexierten Episoden zurück.
        
        Returns:
            Dict mit Statistiken (Anzahl Animes, Episoden, etc.)
        """
        stats = {}
        
        # Gesamtzahl der indexierten Dateien
        self.cursor.execute("SELECT COUNT(*) FROM episode_files")
        stats['total_files'] = self.cursor.fetchone()[0]
        
        # Anzahl der Animes
        self.cursor.execute("SELECT COUNT(DISTINCT title) FROM episode_files")
        stats['total_anime'] = self.cursor.fetchone()[0]
        
        # Größe der Datenbank
        if os.path.exists(self.db_path):
            stats['database_size_mb'] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        else:
            stats['database_size_mb'] = 0
            
        # Letzte Indizierung
        self.cursor.execute("SELECT MAX(last_scan) FROM scan_history")
        last_scan = self.cursor.fetchone()[0]
        stats['last_indexed'] = last_scan if last_scan else 0
        
        return stats
    
    def maintenance(self):
        """Führt Wartungsarbeiten an der Datenbank durch (Vacuum, Reindex, etc.)."""
        try:
            logging.info("Führe Datenbankwartung durch...")
            self.cursor.execute("VACUUM")
            self.cursor.execute("ANALYZE")
            logging.info("Datenbankwartung abgeschlossen")
        except sqlite3.Error as e:
            logging.error(f"Fehler bei der Datenbankwartung: {e}")


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