# Auto Source Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the playlist builder discover the current working domain for each source automatically, persisting results to `sources.json`.

**Architecture:** A source registry (`sources.json`) holds candidate domains, a search query, and a validation marker per source. `resolve_source()` tries candidates first, then falls back to DuckDuckGo HTML search, validating each candidate by fetching the page and checking for the marker. Discovered domains are persisted. Scrapers consume the resolved URL.

**Tech Stack:** Python 3.10, requests, BeautifulSoup, GitPython, pytest.

---

### Task 1: Create initial `sources.json`

**Files:**
- Create: `sources.json`

- [ ] **Step 1: Write the file**

```json
{
  "roja": {
    "candidates": ["rojadirectaenvivo.pl"],
    "query": "rojadirecta en vivo",
    "marker": "rojadirecta"
  },
  "futlib": {
    "candidates": ["futbollibre.mx"],
    "query": "futbollibre en vivo",
    "marker": "futbollibre"
  },
  "libpel": {
    "candidates": ["librepelota.com"],
    "query": "librepelota en vivo",
    "marker": "librepelota"
  },
  "pelota1": {
    "candidates": ["pelotalibre1.pe"],
    "query": "pelotalibre en vivo",
    "marker": "pelotalibre"
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add sources.json
git commit -m "feat: add source registry for auto domain discovery"
```

### Task 2: Add discovery helpers and tests (TDD)

**Files:**
- Modify: `pelota_builder.py`
- Create: `tests/test_source_discovery.py`

- [ ] **Step 1: Write failing test for DDG domain extraction**

Create `tests/test_source_discovery.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pelota_builder import _extract_ddg_domains

SAMPLE = """
<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example</a>
<a class="result__a" href="/l/?uddg=https%3A%2F%2Ffoo.bar%2F">Foo</a>
<a class="result__a" href="https://direct.example.org/">Direct</a>
"""

def test_extract_ddg_domains():
    domains = _extract_ddg_domains(SAMPLE, limit=5)
    assert "example.com" in domains
    assert "foo.bar" in domains
    assert "direct.example.org" in domains
    assert "duckduckgo.com" not in domains
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_source_discovery.py -v`
Expected: FAIL (function not defined)

- [ ] **Step 3: Add helpers to pelota_builder.py**

Add imports and functions. Insert after `normalize()`:

```python
import json

SOURCES_FILE = REPO_DIR / "sources.json"

DEFAULT_SOURCES = {
    "roja": {"candidates": ["rojadirectaenvivo.pl"], "query": "rojadirecta en vivo", "marker": "rojadirecta"},
    "futlib": {"candidates": ["futbollibre.mx"], "query": "futbollibre en vivo", "marker": "futbollibre"},
    "libpel": {"candidates": ["librepelota.com"], "query": "librepelota en vivo", "marker": "librepelota"},
    "pelota1": {"candidates": ["pelotalibre1.pe"], "query": "pelotalibre en vivo", "marker": "pelotalibre"},
}

def load_sources():
    if SOURCES_FILE.exists():
        try:
            return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {k: dict(v) for k, v in DEFAULT_SOURCES.items()}

def save_sources(data):
    SOURCES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _domain_ok(url, marker):
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return False
        return marker.lower() in resp.text.lower()
    except Exception:
        return False

def _extract_ddg_domains(html, limit=5):
    from urllib.parse import urlparse, parse_qs, unquote
    domains = []
    seen = set()
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        parsed = urlparse(href)
        host = None
        if "uddg" in parsed.query:
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                real = unquote(qs["uddg"][0])
                host = urlparse(real).netloc
        else:
            host = parsed.netloc
        if not host or "duckduckgo.com" in host:
            continue
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        if host in seen:
            continue
        seen.add(host)
        domains.append(host)
        if len(domains) >= limit:
            break
    return domains

def _search_ddg(query, limit=5):
    try:
        resp = requests.get("https://duckduckgo.com/html/", params={"q": query}, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        return _extract_ddg_domains(resp.text, limit)
    except Exception:
        return []

def resolve_source(key, data):
    info = data.get(key, {})
    candidates = list(info.get("candidates", []))
    marker = info.get("marker", key)
    query = info.get("query", key)
    for domain in candidates:
        url = f"https://{domain}/"
        if _domain_ok(url, marker):
            return url, data
    for domain in _search_ddg(query):
        url = f"https://{domain}/"
        if _domain_ok(url, marker):
            if domain not in candidates:
                candidates.insert(0, domain)
            info["candidates"] = candidates
            data[key] = info
            save_sources(data)
            return url, data
    print(f"Warning: could not resolve source {key}")
    return None, data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_source_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pelota_builder.py tests/test_source_discovery.py
git commit -m "feat: add domain discovery helpers with tests"
```

### Task 3: Integrate discovery into `main()`

**Files:**
- Modify: `pelota_builder.py:main()`

- [ ] **Step 1: Replace hardcoded URL usage**

Update `get_roja_events` signature to accept `url`:

```python
def get_roja_events(url: str) -> list:
    ...
    resp = requests.get(url, timeout=10)
    ...
```

In `main()`, replace:

```python
all_events = []
all_events.extend(get_roja_events())
all_events.extend(get_futbollibre_style_events(FUTLIB_URL, "FutbolLibre"))
...
```

with:

```python
sources = load_sources()
roja_url, sources = resolve_source("roja", sources)
futlib_url, sources = resolve_source("futlib", sources)
libpel_url, sources = resolve_source("libpel", sources)
pelota1_url, sources = resolve_source("pelota1", sources)

all_events = []
if roja_url:
    all_events.extend(get_roja_events(roja_url))
if futlib_url:
    all_events.extend(get_futbollibre_style_events(futlib_url, "FutbolLibre"))
if libpel_url:
    all_events.extend(get_futbollibre_style_events(libpel_url, "LibrePelota"))
if pelota1_url:
    all_events.extend(get_futbollibre_style_events(pelota1_url, "PelotaLibre1"))
```

And fixed channels:

```python
if libpel_url:
    fixed_channels = get_fixed_channels(libpel_url)
else:
    fixed_channels = []
```

- [ ] **Step 2: Compile check**

Run: `python3 -m py_compile pelota_builder.py`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add pelota_builder.py
git commit -m "feat: use auto-discovered source URLs in main"
```

### Task 4: Persist `sources.json` in git step

**Files:**
- Modify: `pelota_builder.py` git commit section
- Modify: `.github/workflows/update-playlist.yml`

- [ ] **Step 1: Update git add in script**

```python
repo.index.add([str(out_file), str(combo_file), str(SOURCES_FILE)])
```

- [ ] **Step 2: Update workflow git add**

```bash
git add eventos.m3u playlist.m3u sources.json
```

- [ ] **Step 3: Commit & push**

```bash
git add pelota_builder.py .github/workflows/update-playlist.yml
git commit -m "chore: persist sources.json in auto-update"
git push
```

### Task 5: Verify

- [ ] Run tests: `pytest tests/test_source_discovery.py -v`
- [ ] Trigger workflow manually and check logs for resolved URLs.

---

Self-review: spec coverage OK. No placeholders. Type consistency: `resolve_source(key, data)` returns `(url, data)` consistently. `get_roja_events(url)` updated.
