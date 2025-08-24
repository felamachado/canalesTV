#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  canales_varios.py   – Generador de varios.m3u (versión avanzada con selenium-wire)
# ──────────────────────────────────────────────────────────────────────────────
"""Construye un playlist M3U con canales sueltos que están incrustados en
páginas (por ejemplo, blogs de TV).

Cómo funciona en cada canal:
1. Descarga la página indicada, busca el primer <iframe> y normaliza el src.
2. Intenta encontrar la URL .m3u8 directamente en el HTML del iframe
   (método rápido).
3. Si no aparece, abre el iframe con **Chromium headless** mediante Selenium
   con selenium-wire y espía las peticiones de red hasta capturar un manifiesto .m3u8.
4. Escribe la entrada EXTINF + URL en ``varios.m3u``.

Editar canales:
---------------
Modificá la lista ``CANALES`` al principio de este archivo:
```python
CANALES = [
    ("Canal 10 UY", "https://elrincondelhinchatv.blogspot.com/p/canal-10_21.html"),
    ("Otro canal",  "https://sitio.com/canal.html"),
]
```

Requisitos:
-----------
* Google Chrome o **Chromium** instalado en el sistema.
* El ejecutable **chromedriver** *compatible* con tu versión de Chrome
  disponible en el ``PATH`` (``which chromedriver`` debe devolver ruta).
* Python packages:
  ``pip install selenium-wire beautifulsoup4 requests``
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional, List, Tuple

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# ---------------------------------------------------------------------------
# Configuración editable
# ---------------------------------------------------------------------------
CANALES: List[Tuple[str, str]] = [
    ("Canal 10 UY", "https://elrincondelhinchatv.blogspot.com/p/canal-10_21.html"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135 Safari/537.36"
    )
}

SALIDA = Path(__file__).with_name("varios.m3u")
LOGS = Path(__file__).with_name("debug_requests.log")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if not urlparse(url).scheme:
        return "https://" + url.lstrip("/")
    return url

def clean_spaces(txt: str) -> str:
    return re.sub(r"\s+", " ", txt).strip()

# ---------------------------------------------------------------------------
# Extracción del iframe y .m3u8
# ---------------------------------------------------------------------------

def extract_iframe(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("iframe", src=True)
    return normalize(tag["src"]) if tag else None

def m3u8_quick(iframe_url: str) -> Optional[str]:
    try:
        txt = requests.get(iframe_url, headers=HEADERS, timeout=10).text
        m = re.search(r'https?:[^\'"\s]+\.m3u8[^\'"\s]*', txt)
        return m.group(0) if m else None
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Selenium‑wire (headless con sniffing de red)
# ---------------------------------------------------------------------------

def _chrome_options() -> Options:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-dev-shm-usage")
    return opts

_DRIVER: Optional[webdriver.Chrome] = None

def _init_driver() -> webdriver.Chrome:
    import os
    from webdriver_manager.chrome import ChromeDriverManager
    
    opts = _chrome_options()
    
    # Try local path first (for local development), fallback to webdriver-manager
    try:
        local_driver_path = '/home/felipe/.wdm/drivers/chromedriver/linux64/139.0.7258.138/chromedriver-linux64/chromedriver'
        if os.path.exists(local_driver_path):
            service = Service(local_driver_path)
        else:
            # Use webdriver-manager for GitHub Actions
            service = Service(ChromeDriverManager().install())
    except:
        # Fallback to webdriver-manager
        service = Service(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=opts)
    driver.scopes = ['.*']
    return driver

def m3u8_slow(iframe_url: str) -> Optional[str]:
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = _init_driver()
    driver = _DRIVER

    try:
        driver.get(iframe_url)
        time.sleep(8)
        lines = []
        for request in driver.requests:
            if request.response:
                lines.append(f"{request.method} {request.url} -> {request.response.status_code}")
            else:
                lines.append(f"{request.method} {request.url} -> NO RESP")
        LOGS.write_text("\n".join(lines), encoding="utf-8")

        # Buscar .m3u8 primero
        for request in driver.requests:
            if ".m3u8" in request.url:
                print(f"  🔍 Found HLS stream: {request.url}")
                return request.url
                
        # Si no encuentra .m3u8, buscar .mpd y usar el tokenizado más reciente
        dash_urls = []
        for request in driver.requests:
            if ".mpd" in request.url:
                dash_urls.append(request.url)
                
        if dash_urls:
            # Usar la URL tokenizada (la más larga es generalmente la más reciente)
            best_dash = max(dash_urls, key=len)
            print(f"  📺 Using DASH stream: {best_dash}")
            return best_dash
    except Exception as e:
        LOGS.write_text(f"ERROR: {e}\n", encoding="utf-8")
        return None
    return None

def capture_m3u8(iframe_url: str) -> Optional[str]:
    iframe_url = normalize(iframe_url)
    return m3u8_quick(iframe_url) or m3u8_slow(iframe_url)

# ---------------------------------------------------------------------------
# Procesar cada canal
# ---------------------------------------------------------------------------

def process_channel(name: str, page_url: str) -> Optional[str]:
    print(f"→ {name:<12} … ", end="", flush=True)
    try:
        html = requests.get(page_url, headers=HEADERS, timeout=15).text
    except Exception as exc:
        print(f"⚠️  {type(exc).__name__}")
        return None

    iframe = extract_iframe(html)
    if not iframe:
        print("sin iframe")
        return None

    m3u8 = capture_m3u8(iframe)
    if not m3u8:
        print("sin .m3u8")
        return None

    print("✔")
    return (
        f'#EXTINF:-1 tvg-name="{name}" group-title="Varios", {name}\n{m3u8}'
    )

# ---------------------------------------------------------------------------
# Guardar playlist
# ---------------------------------------------------------------------------

def save_playlist(entries: List[str]) -> None:
    content = "#EXTM3U\n" + "\n\n".join(entries) + "\n"
    SALIDA.write_text(content, encoding="utf-8")
    print(f"\n✅  Generado {SALIDA.name} con {len(entries)} canales.\n   Ruta: {SALIDA}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    entries: List[str] = []
    for name, url in CANALES:
        ent = process_channel(clean_spaces(name), url)
        if ent:
            entries.append(ent)
    save_playlist(entries)

if __name__ == "__main__":
    main()
