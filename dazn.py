#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  canales_varios.py   – Generador de varios.m3u/.mpd (soporta HLS y DASH, y convierte MPD a HLS si es posible)
# ──────────────────────────────────────────────────────────────────────────────
"""Construye un playlist M3U que incluya streams HLS (.m3u8) y DASH (.mpd)
de canales embebidos en páginas usando requests + Selenium-Wire.
Si captura un .mpd, intenta derivar un .m3u8 mediante sustituciones comunes.
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

# ---------------------------------------------------------------------------
# Configuración editable
# ---------------------------------------------------------------------------
CANALES: List[Tuple[str, str]] = [
    ("Canal 10 UY", "https://elrincondelhinchatv.blogspot.com/p/canal-10_21.html?m=1"),
    # Agregar más canales aquí...
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

# ---------------------------------------------------------------------------
# Extracción de iframe y stream
# ---------------------------------------------------------------------------

def extract_iframe(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("iframe", src=True)
    return normalize(tag["src"]) if tag else None


def stream_quick(iframe_url: str) -> Optional[str]:
    """Búsqueda rápida de .m3u8 o .mpd en el HTML del iframe."""
    try:
        txt = requests.get(iframe_url, headers=HEADERS, timeout=10).text
        m = re.search(r"https?://[^'\"\s]+\.(?:m3u8|mpd)[^'\"\s]*", txt)
        return m.group(0) if m else None
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Selenium‑wire (headless) para captura de peticiones
# ---------------------------------------------------------------------------

_DRIVER: Optional[webdriver.Chrome] = None


def _chrome_options() -> Options:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-dev-shm-usage")
    return opts


def _init_driver() -> webdriver.Chrome:
    opts = _chrome_options()
    return webdriver.Chrome(options=opts)


def stream_slow(iframe_url: str) -> Optional[str]:
    """Carga el iframe en Chromium y espía las peticiones para capturar .m3u8 o .mpd."""
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = _init_driver()
    driver = _DRIVER
    try:
        driver.requests.clear()
        driver.get(iframe_url)
        WebDriverWait(driver, 12).until(
            lambda d: any(ext in r.url for r in d.requests for ext in ['.m3u8', '.mpd'])
        )
        LOGS.write_text("\n".join(
            f"{r.method} {r.url} -> {r.response.status_code if r.response else 'NO RESP'}"
            for r in driver.requests
        ), encoding="utf-8")
        for r in driver.requests:
            if any(ext in r.url for ext in ['.m3u8', '.mpd']):
                return r.url
    except Exception:
        return None
    return None


def capture_stream(iframe_url: str) -> Optional[str]:
    iframe_url = normalize(iframe_url)
    url = stream_quick(iframe_url)
    if url:
        return url
    return stream_slow(iframe_url)

# ---------------------------------------------------------------------------
# Conversión DASH (.mpd) a HLS (.m3u8) mediante patrones
# ---------------------------------------------------------------------------

def derive_hls_from_mpd(mpd_url: str) -> Optional[str]:
    """Intenta construir una URL .m3u8 a partir de la .mpd cambiando rutas comunes."""
    # patrones de reemplazo: dash_enc -> hls_enc, extension .mpd -> .m3u8
    candidates = []
    # 1) sustituir _dash_enc por _hls_enc
    candidates.append(mpd_url.replace('_dash_enc', '_hls_enc').replace('.mpd', '.m3u8'))
    # 2) simplemente reemplazar .mpd por .m3u8
    candidates.append(mpd_url.replace('.mpd', '.m3u8'))
    # 3) reemplazar /dash/ por /hls/
    candidates.append(mpd_url.replace('/dash/', '/hls/').replace('.mpd', '.m3u8'))
    for hls in candidates:
        try:
            resp = requests.head(hls, headers=HEADERS, timeout=5)
            if resp.status_code == 200:
                return hls
        except Exception:
            continue
    return None

# ---------------------------------------------------------------------------
# Procesar cada canal y armar EXTINF
# ---------------------------------------------------------------------------

def process_channel(name: str, page_url: str) -> Optional[str]:
    print(f"→ {name:<16} … ", end="", flush=True)
    try:
        html = requests.get(page_url, headers=HEADERS, timeout=15).text
    except Exception as exc:
        print(f"⚠️  {type(exc).__name__}")
        return None

    iframe = extract_iframe(html)
    if not iframe:
        print("sin iframe")
        return None

    stream_url = capture_stream(iframe)
    if not stream_url:
        print("sin stream (.m3u8/.mpd)")
        return None

    # si es DASH (.mpd), intentar derivar HLS
    if stream_url.lower().endswith('.mpd'):
        hls = derive_hls_from_mpd(stream_url)
        if hls:
            print("✔ (mpd→m3u8)", flush=True)
            stream_url = hls
        else:
            print("✔ (mpd, sin hls)", flush=True)
    else:
        print("✔", flush=True)

    return (f'#EXTINF:-1 tvg-name="{name}" group-title="Varios", {name}\n{stream_url}')

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
        ent = process_channel(name, url)
        if ent:
            entries.append(ent)
    if entries:
        save_playlist(entries)
    else:
        print("No se generó ninguna entrada.")

if __name__ == "__main__":
    main()
