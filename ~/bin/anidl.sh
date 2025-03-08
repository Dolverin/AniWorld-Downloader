#!/bin/bash
# aniworld Download-Skript für SSH
# Verwendung: anidl.sh <anime-slug> <episode-nummer> [ausgabe-verzeichnis]

cd ~/AniWorld-Downloader
source .venv/bin/activate

if [ $# -lt 2 ]; then
    echo "Verwendung: anidl.sh <anime-slug> <episode-nummer> [ausgabe-verzeichnis]"
    echo "Beispiel: anidl.sh one-piece 1 ~/Downloads"
    exit 1
fi

ANIME_SLUG="$1"
EPISODE="$2"
OUTPUT_DIR="${3:-~/Downloads}"

# Erstelle das Ausgabeverzeichnis, falls es nicht existiert
mkdir -p "$OUTPUT_DIR"

# Erstelle die URL für die Episode
EPISODE_URL="https://aniworld.to/anime/stream/${ANIME_SLUG}/staffel-1/episode-${EPISODE}"

echo "Starte Download von $ANIME_SLUG Episode $EPISODE nach $OUTPUT_DIR..."
echo "Episode-URL: $EPISODE_URL"

# Wir verwenden jetzt den direkten Modus ohne TUI und übergeben die URL
nohup python -m aniworld -d -s "$ANIME_SLUG" -e "$EPISODE_URL" -a Download -o "$OUTPUT_DIR" > ~/anidl_log.txt 2>&1 &

echo "Download läuft im Hintergrund. Überprüfe den Status mit: tail -f ~/anidl_log.txt" 