import logging
import os
import platform
import random
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests
import socks
import stem
from stem import Signal
from stem.control import Controller

from aniworld.globals import DEFAULT_USER_AGENT, IS_DEBUG_MODE


class TorClient:
    """
    Verwaltet die Verbindung und Interaktion mit dem Tor-Netzwerk.

    Diese Klasse bietet Funktionen für:
    - Konfiguration des Tor-SOCKS-Proxys für HTTP-Anfragen
    - Wechseln der IP-Adresse über das Tor-Netzwerk
    - Status-Überprüfung der Tor-Verbindung
    """

    def __init__(self, use_tor: bool = False):
        self.use_tor = use_tor
        self.tor_process = None
        self.tor_port = self._find_free_port()
        self.control_port = self._find_free_port(self.tor_port + 1)
        self.data_directory = os.path.join(
            tempfile.gettempdir(), f"aniworld_tor_{
                self.tor_port}")
        self.control_password = self._generate_password()
        self.is_running = False
        self.lock = threading.Lock()
        self.ip_address = None

        # Standardparameter für Tor
        self.max_circuit_dirtiness = 600  # 10 Minuten maximale Circuit-Nutzungsdauer
        self.max_reconnect_attempts = 5

        # Starte Tor-Service wenn aktiviert
        if self.use_tor:
            self.start()

    def _find_free_port(self, start_port: int = 9050) -> int:
        """Findet einen freien Port ab dem angegebenen Port."""
        port = start_port
        while port < 65535:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(('127.0.0.1', port))
                sock.close()
                return port
            except OSError:
                port += 1
                sock.close()
        raise RuntimeError("Konnte keinen freien Port finden")

    def _generate_password(self, length: int = 16) -> str:
        """Generiert ein zufälliges Passwort für die Tor-Steuerung."""
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return ''.join(random.choice(chars) for _ in range(length))

    def start(self) -> bool:
        """Startet den Tor-Dienst und konfiguriert das Netzwerk."""
        if self.is_running:
            return True

        with self.lock:
            if self.is_running:
                return True

            logging.info("Starte Tor-Dienst...")

            # Prüfe, ob Tor installiert ist
            if not self._check_tor_installed():
                logging.error(
                    "Tor ist nicht installiert. Bitte installieren Sie Tor und versuchen Sie es erneut.")
                return False

            # Dateiverzeichnis erstellen, falls nicht vorhanden
            os.makedirs(self.data_directory, exist_ok=True)

            # Hash-Passwort für Tor-Controller generieren
            hashed_password = self._get_hashed_password()
            if not hashed_password:
                logging.error("Konnte kein Hash-Passwort für Tor generieren")
                return False

            # Tor-Konfigurationsdatei erstellen
            config_path = os.path.join(self.data_directory, "torrc")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(f"SocksPort {self.tor_port}\n")
                f.write(f"ControlPort {self.control_port}\n")
                f.write(f"HashedControlPassword {hashed_password}\n")
                f.write(f"DataDirectory {self.data_directory}\n")
                f.write("MaxCircuitDirtiness 600\n")
                f.write("NumEntryGuards 6\n")

            # Tor-Prozess starten
            try:
                if platform.system() == "Windows":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    self.tor_process = subprocess.Popen(
                        ["tor", "-f", config_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo
                    )
                else:
                    self.tor_process = subprocess.Popen(
                        ["tor", "-f", config_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                # Warten, bis Tor gestartet ist
                for _ in range(30):
                    if self._check_tor_running():
                        break
                    time.sleep(1)

                if not self._check_tor_running():
                    logging.error("Tor konnte nicht gestartet werden")
                    self._cleanup()
                    return False

                # IP-Adresse erhalten und Protokollieren
                self.ip_address = self.get_current_ip()
                logging.info(
                    f"Tor erfolgreich gestartet. IP: {
                        self.ip_address}")
                self.is_running = True
                return True

            except (OSError, subprocess.SubprocessError) as e:
                logging.error(f"Fehler beim Starten von Tor: {str(e)}")
                self._cleanup()
                return False

    def _check_tor_installed(self) -> bool:
        """Überprüft, ob Tor auf dem System installiert ist."""
        try:
            result = subprocess.run(
                ["tor", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            return result.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    def _get_hashed_password(self) -> Optional[str]:
        """Generiert ein Hash-Passwort für die Tor-Steuerung."""
        try:
            result = subprocess.run(
                ["tor", "--hash-password", self.control_password],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            output = result.stdout.strip()
            # Hash-Passwort aus der Ausgabe extrahieren
            for line in output.split('\n'):
                if line.startswith("16:"):
                    return line
            return None
        except (subprocess.SubprocessError, OSError) as e:
            logging.error(
                f"Fehler beim Generieren des Hash-Passworts: {str(e)}")
            return None

    def _check_tor_running(self) -> bool:
        """Überprüft, ob der Tor-Dienst läuft und erreichbar ist."""
        try:
            with Controller.from_port(address="127.0.0.1", port=self.control_port) as controller:
                controller.authenticate(password=self.control_password)
                return controller.is_authenticated()
        except (stem.SocketError, stem.connection.AuthenticationFailure):
            return False

    def stop(self) -> None:
        """Beendet den Tor-Dienst."""
        with self.lock:
            if self.is_running and self.tor_process:
                logging.info("Beende Tor-Dienst...")
                try:
                    self.tor_process.terminate()
                    self.tor_process.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    if self.tor_process:
                        self.tor_process.kill()
                finally:
                    self._cleanup()
                    self.is_running = False
                    self.tor_process = None
                    logging.info("Tor-Dienst beendet")

    def _cleanup(self) -> None:
        """Bereinigt temporäre Dateien."""
        try:
            if os.path.exists(self.data_directory):
                import shutil
                shutil.rmtree(self.data_directory, ignore_errors=True)
        except OSError as e:
            logging.warning(
                f"Fehler beim Bereinigen des Tor-Datenverzeichnisses: {str(e)}")

    def get_current_ip(self) -> Optional[str]:
        """Holt die aktuelle IP-Adresse über das Tor-Netzwerk."""
        if not self.is_running:
            return None

        proxies = self.get_proxy_dict()
        try:
            response = requests.get(
                "https://api.ipify.org",
                proxies=proxies,
                timeout=30
            )
            return response.text.strip()
        except requests.RequestException as e:
            logging.error(f"Fehler beim Abrufen der IP-Adresse: {str(e)}")
            return None

    def get_proxy_dict(self) -> Dict[str, str]:
        """Gibt die Proxy-Konfiguration für Tor zurück."""
        return {
            'http': f'socks5h://127.0.0.1:{self.tor_port}',
            'https': f'socks5h://127.0.0.1:{self.tor_port}'
        }

    def get_proxy_url(self) -> str:
        """Gibt die Proxy-URL für Tor zurück."""
        return f'socks5h://127.0.0.1:{self.tor_port}'

    def new_identity(self) -> bool:
        """Ändert die IP-Adresse durch Anfordern einer neuen Tor-Identity."""
        if not self.is_running:
            return False

        with self.lock:
            try:
                logging.info("Tor-IP wird gewechselt...")
                with Controller.from_port(address="127.0.0.1", port=self.control_port) as controller:
                    controller.authenticate(password=self.control_password)
                    controller.signal(Signal.NEWNYM)

                    # Kurz warten, damit die neue Identität erstellt werden
                    # kann
                    time.sleep(2)

                    # IP-Adresse prüfen
                    new_ip = self.get_current_ip()
                    old_ip = self.ip_address

                    if new_ip and new_ip != old_ip:
                        self.ip_address = new_ip
                        logging.info(
                            f"Tor-IP gewechselt: {old_ip} -> {new_ip}")
                        return True
                    elif new_ip == old_ip:
                        logging.warning("Tor-IP hat sich nicht geändert")
                        return False
                    else:
                        logging.error("Konnte neue Tor-IP nicht verifizieren")
                        return False

            except (stem.SocketError, stem.connection.AuthenticationFailure, OSError) as e:
                logging.error(
                    f"Fehler beim Wechseln der Tor-Identität: {str(e)}")
                return False

    def restart_tor(self) -> bool:
        """Startet den Tor-Dienst neu."""
        self.stop()
        time.sleep(2)
        return self.start()

    def setup_requests_session(
            self, session: Optional[requests.Session] = None) -> requests.Session:
        """Konfiguriert eine Requests-Session für die Verwendung von Tor."""
        if session is None:
            session = requests.Session()

        if self.is_running:
            session.proxies = self.get_proxy_dict()

        # Standard User-Agent setzen
        session.headers.update({
            'User-Agent': DEFAULT_USER_AGENT
        })

        return session

    def make_request(self,
                     url: str,
                     method: str = "GET",
                     auto_retry: bool = False,
                     max_retries: int = 3,
                     **kwargs) -> Tuple[Optional[requests.Response], bool]:
        """
        Führt eine HTTP-Anfrage über das Tor-Netzwerk aus.

        Args:
            url: Die URL für die Anfrage
            method: Die HTTP-Methode (GET, POST, etc.)
            auto_retry: Automatischer Neuversuch mit IP-Wechsel bei Fehlern
            max_retries: Maximale Anzahl von Wiederholungsversuchen
            **kwargs: Zusätzliche Parameter für die requests-Bibliothek

        Returns:
            Tuple aus (Response-Objekt, Erfolg-Flag)
        """
        if not self.is_running and self.use_tor:
            if not self.start():
                logging.error("Tor-Dienst konnte nicht gestartet werden")
                return None, False

        session = self.setup_requests_session()
        retry_count = 0
        response = None
        success = False

        # Standardzeitüberschreitung auf 30 Sekunden setzen, wenn nicht anders
        # angegeben
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 30

        while retry_count <= max_retries:
            try:
                response = session.request(method, url, **kwargs)

                # Auf Blockierung oder Captcha prüfen
                if "Deine Anfrage wurde als Spam erkannt." in response.text:
                    if auto_retry and retry_count < max_retries:
                        logging.warning(
                            f"IP blockiert. Wechsle zu neuer Tor-IP. Versuch {retry_count + 1}/{max_retries}")
                        if not self.new_identity():
                            logging.warning(
                                "Konnte IP nicht wechseln, versuche Tor neuzustarten")
                            self.restart_tor()
                        retry_count += 1
                        time.sleep(2)
                        continue
                    else:
                        logging.error(
                            "IP blockiert und auto_retry deaktiviert oder maximale Versuche erreicht")
                        return response, False

                # Erfolgreiche Anfrage
                response.raise_for_status()
                success = True
                break

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.TooManyRedirects) as e:
                if auto_retry and retry_count < max_retries:
                    logging.warning(
                        f"Verbindungsfehler: {
                            str(e)}. Wechsle zu neuer Tor-IP. Versuch {
                            retry_count + 1}/{max_retries}")
                    if not self.new_identity():
                        self.restart_tor()
                    retry_count += 1
                    time.sleep(2)
                else:
                    logging.error(f"Verbindungsfehler: {str(e)}")
                    return None, False

            except requests.exceptions.HTTPError as e:
                if response and response.status_code in [403, 429, 503]:
                    if auto_retry and retry_count < max_retries:
                        logging.warning(
                            f"HTTP-Fehler {
                                response.status_code}: {
                                str(e)}. Wechsle zu neuer Tor-IP. Versuch {
                                retry_count + 1}/{max_retries}")
                        if not self.new_identity():
                            self.restart_tor()
                        retry_count += 1
                        time.sleep(2)
                    else:
                        logging.error(
                            f"HTTP-Fehler {response.status_code}: {str(e)}")
                        return response, False
                else:
                    logging.error(f"HTTP-Fehler: {str(e)}")
                    return response, False

            except Exception as e:
                logging.error(
                    f"Unerwarteter Fehler bei HTTP-Anfrage: {str(e)}")
                return None, False

        return response, success

    def __del__(self):
        """Aufräumen beim Löschen der Instanz."""
        self.stop()


# Globale Instanz des Tor-Clients
_tor_client = None


def get_tor_client(use_tor: bool = False) -> TorClient:
    """Gibt eine globale Instanz des Tor-Clients zurück."""
    global _tor_client
    if _tor_client is None:
        _tor_client = TorClient(use_tor=use_tor)
    elif _tor_client.use_tor != use_tor:
        _tor_client.stop()
        _tor_client = TorClient(use_tor=use_tor)
    return _tor_client
