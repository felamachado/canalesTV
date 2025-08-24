# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based streaming media aggregator that automatically scrapes sports events and TV channels from various sources and generates M3U playlist files. The project focuses on Formula 1, Argentine Liga, and Uruguay Liga events, along with various TV channels.

## Core Architecture

### Main Scripts

- **`pelota_builder.py`**: Primary sports event scraper that fetches today's events from Rojadirecta and mirror sites. Filters events by league (includes Formula 1, Liga de Argentina, Liga de Uruguay; excludes many others). Automatically commits and pushes updates to GitHub with CDN purging.

- **`canales_varios.py`**: TV channel scraper that extracts streaming URLs from embedded iframes on blog pages. Uses both quick HTML parsing and Selenium-wire for network request interception.

- **`dazn.py`**: Similar to canales_varios.py but appears to be DAZN-specific implementation with enhanced DASH-to-HLS conversion capabilities.

### Output Files

- **`eventos.m3u`**: Generated sports events playlist (auto-updated by pelota_builder.py)
- **`varios.m3u`**: Generated TV channels playlist (created by canales_varios.py)
- **`debug_requests.log`**: Network debugging log from Selenium operations

## Common Development Tasks

### Running the Scrapers

```bash
# Scrape sports events and auto-commit to git
python3 pelota_builder.py

# Generate TV channels playlist
python3 canales_varios.py

# Generate DAZN-specific playlist with enhanced format support
python3 dazn.py
```

### Git Operations

The pelota_builder.py script automatically:
- Adds the eventos.m3u file to git staging
- Commits with message "AutoScraper update playlist" 
- Pushes to origin remote
- Purges JSDelivr CDN cache

Manual git operations follow standard patterns. Recent commits show automated updates.

### Configuration

#### League Filtering (pelota_builder.py)
- `EXCLUDED_LEAGUES`: List of leagues to skip
- `INCLUDE_LEAGUES`: Whitelist of leagues to process (overrides exclusions when set)

#### Channel Configuration (canales_varios.py, dazn.py)
- `CANALES`: List of tuples `(channel_name, page_url)` to scrape

#### URLs and Timeouts
- Base URLs for scraping sources
- Selenium wait times and request timeouts
- CDN URLs for JSDelivr integration

## Technical Details

### Web Scraping Strategy
1. **Quick Method**: Parse HTML directly for .m3u8/.mpd URLs using regex
2. **Selenium Method**: Use headless Chrome with selenium-wire to intercept network requests
3. **Format Conversion**: Attempt DASH (.mpd) to HLS (.m3u8) URL transformation

### Dependencies
- `requests`, `beautifulsoup4` for HTTP and HTML parsing  
- `selenium-wire` for browser automation with network interception
- `GitPython` for automated git operations
- Chrome/Chromium browser and compatible chromedriver

### Stream URL Patterns
- Looks for `.m3u8` and `.mpd` extensions in URLs
- Handles protocol-relative URLs (`//domain.com/path`)
- Normalizes URLs to use HTTPS scheme

### Error Handling
- Graceful fallbacks between scraping methods
- Logs network requests to debug file
- Continues processing other channels/events on individual failures

## File Structure Context

The repository is a git repository with automated commits. The main branch receives regular automated updates from the pelota_builder.py script. The project uses JSDelivr CDN for playlist distribution with cache purging after updates.