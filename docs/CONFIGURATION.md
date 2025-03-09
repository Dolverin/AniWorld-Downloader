# Konfiguration des AniWorld-Downloaders

Der AniWorld-Downloader verwendet ein zentrales Konfigurationssystem, das es Benutzern ermöglicht, verschiedene Aspekte des Programms anzupassen. Diese Dokumentation beschreibt, wie Sie die Konfiguration anpassen können.

## Konfigurationsdatei

Die Standardkonfigurationsdatei befindet sich unter:
```
~/.config/aniworld/config.json
```

Diese Datei wird automatisch erstellt, wenn das Programm zum ersten Mal ausgeführt wird. Sie können diese Datei mit einem beliebigen Texteditor bearbeiten.

## Konfigurationsstruktur

Die Konfigurationsdatei ist in verschiedene Abschnitte unterteilt:

### Allgemeine Einstellungen

```json
"general": {
    "action": "Download",           // Standardaktion (Download, Watch, Syncplay)
    "download_path": "/mnt/Plex",   // Standardpfad für Downloads
    "language": "German Dub",       // Standardsprache (German Dub, English Sub, German Sub)
    "aniskip": false,               // Aniskip standardmäßig aktivieren?
    "keep_watching": false,         // Nach dem Ansehen weitermachen?
    "terminal_size": [90, 38],      // Standardgröße für das Terminal
    "debug_mode": false,            // Debug-Modus aktivieren?
    "log_file_path": "~/aniworld.log" // Pfad zur Logdatei
}
```

### Provider-Einstellungen

```json
"providers": {
    "default_provider": "VOE",      // Standardprovider für Downloads
    "default_watch_provider": "Doodstream", // Standardprovider zum Ansehen
    "provider_priority": [          // Priorität der Provider
        "VOE",
        "Vidoza",
        "Streamtape",
        "Doodstream",
        "Vidmoly",
        "SpeedFiles"
    ]
}
```

### Tor-Einstellungen

```json
"tor": {
    "use_tor": false,              // Tor verwenden?
    "auto_retry": true,            // Automatisch neue IP holen bei Sperre?
    "max_retries": 3               // Maximale Anzahl an Versuchen mit neuer IP
}
```

### Erweiterte Einstellungen

```json
"advanced": {
    "only_direct_link": false,     // Nur direkte Links ausgeben?
    "only_command": false,         // Nur Befehle ausgeben?
    "use_playwright": false,       // Playwright für das Rendering verwenden?
    "proxy": null                  // Proxy-Einstellungen
}
```

## Umgebungsvariablen

Einige Einstellungen können auch über Umgebungsvariablen gesteuert werden:

- `IS_DEBUG_MODE`: Wenn auf "true", "1", "t", "y" oder "yes" gesetzt, wird der Debug-Modus aktiviert. Dies hat Vorrang vor der Konfigurationsdatei.
- `USE_TOR`: Wenn auf "true", "1", "t", "y" oder "yes" gesetzt, wird Tor verwendet. Dies hat Vorrang vor der Konfigurationsdatei.

## Beispiele

### Download-Pfad ändern

Um den Standard-Download-Pfad zu ändern, bearbeiten Sie den Wert "download_path" im Abschnitt "general":

```json
"general": {
    "download_path": "/mein/neuer/pfad"
}
```

### Standard-Sprache ändern

Um die Standardsprache zu ändern, bearbeiten Sie den Wert "language" im Abschnitt "general":

```json
"general": {
    "language": "English Sub"
}
```

### Provider-Priorität ändern

Um die Priorität der Provider zu ändern, bearbeiten Sie das Array "provider_priority" im Abschnitt "providers":

```json
"providers": {
    "provider_priority": [
        "Streamtape",
        "VOE",
        "Doodstream",
        "Vidoza",
        "Vidmoly",
        "SpeedFiles"
    ]
}
```

## Programmatischer Zugriff

Wenn Sie das AniWorld-Downloader-Paket in Ihren eigenen Skripten verwenden, können Sie auf die Konfiguration wie folgt zugreifen:

```python
from aniworld import config

# Konfigurationswert abrufen
download_path = config.get("general", "download_path")

# Konfigurationswert setzen
config.set("general", "download_path", "/neuer/pfad")

# Hilfsfunktionen verwenden
from aniworld.config import get_download_path, get_default_language

path = get_download_path()
language = get_default_language()
``` 