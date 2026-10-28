# Auto Source Discovery Design

## Goal

Make the playlist builder resilient to domain changes by automatically discovering the current working domain for each sports source (Rojadirecta, FutbolLibre, LibrePelota, PelotaLibre1) instead of relying on hardcoded URLs.

## Scope

- Add domain discovery + validation for the four sources.
- Persist discovered domains to `sources.json` and commit it.
- Keep existing scraping/extraction logic unchanged.
- Do NOT add new scraping sources or change M3U generation.

## Architecture

### Source registry (`sources.json`)

A small JSON file at repo root mapping each source key to:
- `candidates`: list of known mirror domains (ordered, most recent first).
- `query`: DuckDuckGo search query used as fallback.
- `marker`: substring expected in the page HTML to validate a domain (e.g. "rojadirecta", "futbollibre").

Example:
```json
{
  "roja": {"candidates": ["rojadirectaenvivo.pl"], "query": "rojadirecta en vivo", "marker": "rojadirecta"},
  "futlib": {"candidates": ["futbollibre.mx"], "query": "futbollibre en vivo", "marker": "futbollibre"},
  "libpel": {"candidates": ["librepelota.com"], "query": "librepelota en vivo", "marker": "librepelota"},
  "pelota1": {"candidates": ["pelotalibre1.pe"], "query": "pelotalibre en vivo", "marker": "pelotalibre"}
}
```

### Domain resolution (`resolve_source(key)`)

1. For each candidate domain, build URL `https://<domain>/` and fetch with `requests` (timeout 10, follow redirects).
2. If response OK and `marker` (case-insensitive) appears in response text, accept and return URL.
3. If none works, search DuckDuckGo HTML (`https://duckduckgo.com/html/?q=<query>`) and extract up to 5 result domains.
4. Validate each extracted domain with step 2 logic.
5. On first valid domain, prepend it to `candidates` (dedup), save `sources.json`, return URL.
6. If nothing works, return `None` and log a warning; caller skips that source.

### DuckDuckGo domain extraction

Parse result links with regex/BeautifulSoup, extract hostnames, filter out duckduckgo.com and non-http. Pure function, unit-testable.

### Persistence

After resolution, write `sources.json` if changed. The existing git commit/push step in `main()` already commits `eventos.m3u` and `playlist.m3u`; extend it to also commit `sources.json`.

### Integration in `main()`

Replace hardcoded `ROJA_URL`, `FUTLIB_URL`, etc. with calls to `resolve_source(...)`. If `None`, skip that scraper. Log which URL was used.

## Error handling

- Network errors are caught per domain; never abort the whole run.
- If DDG is blocked, fall back to candidates only.
- If all sources fail, script still writes (possibly empty) playlists and exits 0 so the workflow stays green.

## Testing

- Add an assert-based self-check for the DDG domain extraction regex using a small embedded HTML sample.
- No network tests (environment-dependent).

## Risks

- DuckDuckGo HTML format may change; extraction regex needs maintenance.
- Persisting domains could commit a bad domain if validation marker is too weak; marker check mitigates.
- Increased runtime due to probing multiple domains.
