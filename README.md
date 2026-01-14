# CanalesTV Scraper

This is a Python-based streaming media aggregator that automatically scrapes sports events and TV channels from various sources and generates M3U playlist files. The project focuses on Formula 1, Argentine Liga, and Uruguay Liga events, along with various TV channels.

## Features

- **Automated Sports Scraping**: Fetches today's events from Rojadirecta and mirror sites.
- **Smart Filtering**: Automatically includes Formula 1, Liga de Argentina, and Liga de Uruguay while excluding others.
- **TV Channel Aggregation**: Extracts streaming URLs from various sources.
- **Git Integration**: Automatically commits and pushes updates to GitHub.
- **CDN Support**: Purges JSDelivr CDN cache for instant updates.

## Playlist URLs

- **Sports Events**: `eventos.m3u`
- **TV Channels**: `varios.m3u`
- **Combined Playlist**: `playlist.m3u`

## Usage

### Prerequisites

- Python 3.10+
- Chrome/Chromium browser
- `requests`, `beautifulsoup4`, `selenium-wire`, `GitPython`

### Running the Scrapers

```bash
# Scrape sports events and auto-commit to git
python3 pelota_builder.py

# Generate TV channels playlist
python3 canales_varios.py

# Generate DAZN-specific playlist
python3 dazn.py
```

## Configuration

### League Filtering
Modify `pelota_builder.py` to change filtered leagues:
- `EXCLUDED_LEAGUES`: List of leagues to skip
- `INCLUDE_LEAGUES`: Whitelist of leagues to process

### Channel Configuration
Modify `canales_varios.py` or `dazn.py` to add channels:
- `CANALES`: List of tuples `(channel_name, page_url)`

## GitHub Actions

This repository includes a GitHub Action (`update-playlist.yml`) that runs every 30 minutes to:
1. scrape the latest events
2. update `eventos.m3u` and `playlist.m3u`
3. commit and push the changes

You can also trigger this manually from the "Actions" tab in GitHub.
