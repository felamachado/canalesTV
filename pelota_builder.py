#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pelota_builder.py – Generador de eventos.m3u desde Rojadirecta con filtrado y agrupación por liga
"""
import re
import time
from pathlib import Path
from git import Repo, exc as git_exc
import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# ───────────── Configuración ─────────────
BASE_URL       = "https://www.rojadirectaenvivo.pl/"
# URLs espejo que ofrecen la agenda
MIRROR_AGENDA  = "https://tarjetarojaa.com/agenda.php"
MIRROR_AGENDA2 = "https://roja-directahd.com/"
# Directorio del repo local donde se realiza el push (asume que aquí está el repositorio git)
REPO_DIR       = Path(__file__).parent
EVENT_FILE     = "eventos.m3u"
CDN_URL        = f"https://cdn.jsdelivr.net/gh/felamachado/canalesTV@main/{EVENT_FILE}"
PURGE_URL      = f"https://purge.jsdelivr.net/gh/felamachado/canalesTV@main/{EVENT_FILE}"
QUICK_TIMEOUT  = 3   # segundos para intento rápido
SLOW_WAIT      = 4   # segundos de espera en Selenium

# Ligas a excluir (no procesar)
EXCLUDED_LEAGUES = [
    "Super Lig", "Liga Endesa", "Super League", "Bundesliga",
    "Liga de Peru", "Liga de Ecuador", "Ligue 1", "Liga de Colombia",
    "Liga de Chile", "MLS", "Liga de Portugal", "NBA",
    "Liga Expansion MX", "Liga de Paraguay", "Liga MX"
]
# Ligas a incluir (solo procesar estas). Vacío = procesar todo menos excluidas.
INCLUDE_LEAGUES = ["Formula 1", "Liga de Argentina", "Liga de Uruguay", "Premier League"]

# ───────────── Helpers ─────────────
def normalize(url: str) -> str:
    """Asegura que la URL tenga esquema y no sea ancla."""
    url = url.strip()
    if not url or url.startswith('#'):
        return ''
    if url.startswith("//"):
        return "https:" + url
    if not re.match(r"^https?://", url):
        return "https://" + url.lstrip("/")
    return url

# ───────────── Extracción de eventos ─────────────
def get_today_events() -> list[tuple[str,str,str,str,str]]:
    """Descarga y parsea la programación de hoy, devuelve tuplas
    (liga, hora, partido, canal, url) aplicando filtros de liga."""
    html = None
    # Intentar fuente principal
    try:
        resp = requests.get(BASE_URL, timeout=10)
        resp.raise_for_status()
        html = resp.text
        print(f"Usando fuente principal: {BASE_URL}")
    except Exception as e:
        print(f"⚠️ Error conectando a {BASE_URL}: {e}")
    # Si falló, intentar mirror 1
    if html is None:
        try:
            resp = requests.get(MIRROR_AGENDA, timeout=10)
            resp.raise_for_status()
            html = resp.text
            print(f"Usando espejo agenda: {MIRROR_AGENDA}")
        except Exception as e:
            print(f"⚠️ Error conectando a mirror {MIRROR_AGENDA}: {e}")
    # Si falló, intentar mirror 2
    if html is None:
        try:
            resp = requests.get(MIRROR_AGENDA2, timeout=10)
            resp.raise_for_status()
            html = resp.text
            print(f"Usando espejo agenda 2: {MIRROR_AGENDA2}")
        except Exception as e:
            print(f"⚠️ Error conectando a mirror 2 {MIRROR_AGENDA2}: {e}")
    if html is None:
        print("⚠️ No se pudo obtener la programación de ninguna fuente.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    events: list[tuple[str,str,str,str,str]] = []

    # Verificar si hay un iframe con agenda (como en roja-directahd.com)
    iframe = soup.find("iframe", src=lambda x: x and "agenda.php" in x)
    if iframe and html and "roja-directahd.com" in resp.url:
        # Obtener la agenda desde el iframe
        iframe_src = iframe.get("src")
        if iframe_src.startswith("/"):
            iframe_url = "https://roja-directahd.com" + iframe_src
        else:
            iframe_url = iframe_src
        try:
            resp_iframe = requests.get(iframe_url, timeout=10)
            resp_iframe.raise_for_status()
            soup = BeautifulSoup(resp_iframe.text, "html.parser")
            print(f"  → Usando iframe agenda: {iframe_url}")
        except Exception as e:
            print(f"  ⚠️ Error cargando iframe {iframe_url}: {e}")

    for li in soup.select("ul.menu > li"):
        t = li.find("span", class_="t")
        if not t:
            continue
        hora = t.text.strip()
        link = li.find("a", recursive=False)
        if not link or not link.contents:
            continue
        raw = link.contents[0].strip()
        if ":" not in raw:
            continue
        liga, partido = map(str.strip, raw.split(":", 1))
        # canales (sin filtros aquí)
        for chan_link in li.select("ul > li > a"):
            href = chan_link.get("href", "").strip()
            # Manejar URLs internas de roja-directahd.com ANTES de normalize
            if href.startswith('/eventos.html'):
                chan_url = "https://roja-directahd.com" + href
            else:
                chan_url = normalize(href)
            if not chan_url:
                continue
            chan_name = chan_link.text.strip()
            events.append((liga, hora, partido, chan_name, chan_url))
    
    # Aplicar filtros DESPUÉS de extraer todos los eventos
    filtered_events = []
    for liga, hora, partido, chan_name, chan_url in events:
        # filtros
        if any(liga.startswith(exc) for exc in EXCLUDED_LEAGUES):
            continue
        if INCLUDE_LEAGUES and not any(liga.startswith(inc) for inc in INCLUDE_LEAGUES):
            continue
        filtered_events.append((liga, hora, partido, chan_name, chan_url))
    
    return filtered_events

# ───────────── Extracción de stream ─────────────
def get_m3u8_simple(url: str) -> str:
    """Intenta rápido buscar '.m3u8' en el HTML"""
    try:
        txt = requests.get(url, timeout=QUICK_TIMEOUT).text
        m = re.search(r"https?://[^'\"\s]+\.m3u8[^'\"\s]*", txt)
        return m.group(0) if m else ''
    except Exception:
        return ''

# ───────────── Selenium‑wire sniffing ─────────────
def init_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver_path = '/home/felipe/.wdm/drivers/chromedriver/linux64/139.0.7258.138/chromedriver-linux64/chromedriver'
    service = Service(driver_path)
    return webdriver.Chrome(service=service, options=opts)

def get_m3u8_selenium(url: str) -> str:
    """Fallback: abre la URL y captura peticiones con '.m3u8'"""
    drv = init_driver()
    drv.get(url)
    time.sleep(SLOW_WAIT)
    stream_url = ''
    for req in drv.requests:
        if '.m3u8' in req.url:
            stream_url = req.url
            break
    drv.quit()
    return stream_url

def get_m3u8_selenium_enhanced(url: str) -> str:
    """Método mejorado para URLs de roja-directahd.com con más interacciones"""
    drv = init_driver()
    try:
        drv.get(url)
        
        # Esperar carga inicial
        time.sleep(2)
        
        # Buscar y hacer clic en elementos comunes de players de video
        try:
            # Intentar hacer clic en el player o elementos de play
            play_elements = drv.find_elements("css selector", 
                "button[aria-label*='play'], .play-button, .vjs-play-control, "
                ".jwplayer .jw-display-icon-container, .plyr__control--overlaid, "
                "button.vjs-big-play-button")
            
            for element in play_elements[:2]:  # Probar máximo 2 elementos
                try:
                    if element.is_displayed() and element.is_enabled():
                        drv.execute_script("arguments[0].click();", element)
                        time.sleep(1)
                        break
                except:
                    continue
        except:
            pass
        
        # Esperar más tiempo para cargar streams
        time.sleep(SLOW_WAIT + 2)
        
        # Buscar .m3u8 URLs en requests
        stream_url = ''
        for req in drv.requests:
            if '.m3u8' in req.url and 'master.m3u8' not in req.url.lower():
                stream_url = req.url
                break
        
        # Si no encontró, buscar master.m3u8 como fallback
        if not stream_url:
            for req in drv.requests:
                if '.m3u8' in req.url:
                    stream_url = req.url
                    break
        
        return stream_url
    
    except Exception as e:
        print(f"  ⚠️ Error en Selenium mejorado: {e}")
        return ''
    finally:
        drv.quit()

# ───────────── Main ─────────────
def main():
    # obtener eventos y ordenar por liga y hora
    events = get_today_events()
    events.sort(key=lambda x: (x[0], x[1]))

    entries = ["#EXTM3U"]
    for liga, hora, partido, chan, url in events:
        try:
            # Método 1: Intento rápido
            stream = get_m3u8_simple(url)
            
            # Método 2: Selenium estándar si no encontró nada
            if not stream:
                stream = get_m3u8_selenium(url)
            
            # Método 3: Selenium mejorado para URLs específicas
            if not stream and (any(domain in url for domain in ['roja-directahd.com', 'rojadirecta']) or url.startswith('/eventos.html')):
                print(f"  → Probando método mejorado para {chan}")
                stream = get_m3u8_selenium_enhanced(url)
            
            if not stream:
                print(f"  ⚠️ sin .m3u8 para {hora} {liga} – {partido} – {chan}")
                continue
            title = f"{hora} {liga} – {partido}"
            entries.append(
                f"#EXTINF:-1 tvg-name=\"{chan}\" group-title=\"{liga}\", {title} – {chan}"
            )
            entries.append(stream)
            print(f"  ✔ {title} – {chan}")
        except Exception as e:
            print(f"  ⚠️ error en {hora} {liga} – {partido} – {chan}: {e}")
            continue

    out = REPO_DIR / EVENT_FILE
    out.write_text("\n".join(entries), encoding="utf-8")
    print(f"Guardado {out} con {len(entries)-1} entradas")

    # Git: push directo al repositorio conocido
    try:
        repo = Repo(REPO_DIR)
        repo.index.add([str(out)])
        repo.index.commit('AutoScraper update playlist')
        repo.remote(name='origin').push()
        requests.get(PURGE_URL)
        print(f"Subido y purgado CDN: {CDN_URL}")
    except git_exc.GitError as git_err:
        print(f"⚠️ Error con Git: {git_err}")
    except Exception as e:
        print(f"⚠️ Error al subir a GitHub: {e}")

if __name__ == '__main__':
    main()
