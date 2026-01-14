#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pelota_builder.py – Generador de eventos.m3u desde Rojadirecta con filtrado y agrupación por liga
"""
import re
import time
import os
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
CDN_URL        = f"https://raw.githubusercontent.com/felamachado/canalesTV/main/{EVENT_FILE}"
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
INCLUDE_LEAGUES = ["Formula 1", "Liga de Argentina", "Liga de Uruguay", "Premier League", "LaLiga"]

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
    opts.add_argument("--disable-web-security")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--window-size=1920,1080")
    
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
    
    return webdriver.Chrome(service=service, options=opts)

def click_play_buttons(drv):
    """Intenta hacer clic en botones de play comunes"""
    try:
        # Selectores comunes de players (Clappr, JWPlayer, HTML5, etc)
        selectors = [
            "button[aria-label*='play']", 
            ".play-button", 
            ".vjs-play-control", 
            ".jw-display-icon-container", 
            ".plyr__control--overlaid", 
            "button.vjs-big-play-button",
            "div[class*='play']",
            "svg[class*='play']"
        ]
        
        # Combinar en un solo selector para eficiencia
        css_selector = ", ".join(selectors)
        
        elements = drv.find_elements("css selector", css_selector)
        
        # Filtrar visibles y clickear (max 2 intentos)
        count = 0
        for el in elements:
            if count >= 2: break
            try:
                if el.is_displayed():
                    drv.execute_script("arguments[0].click();", el)
                    time.sleep(0.5)
                    count += 1
            except:
                pass
    except:
        pass

def get_m3u8_selenium_enhanced(url: str) -> str:
    """Método robusto: busca en iframes, hace clic y espera tráfico"""
    drv = init_driver()
    try:
        drv.set_page_load_timeout(15)
        try:
            drv.get(url)
        except:
            pass # Timeout es común en sitios lentos, seguir igual
        
        # Esperar carga inicial
        time.sleep(3)
        
        # 1. Intentar en frame principal
        click_play_buttons(drv)
        
        # 2. Intentar buscar iframes y clickear dentro
        try:
            iframes = drv.find_elements("tag name", "iframe")
            # Recorrer iframes (limitado a 3 para no tardar mucho)
            for i in range(min(len(iframes), 3)):
                try:
                    # Siempre volver al default antes de cambiar
                    drv.switch_to.default_content()
                    # Re-buscar frames para evitar StaleElement
                    current_iframes = drv.find_elements("tag name", "iframe")
                    if i < len(current_iframes):
                        drv.switch_to.frame(current_iframes[i])
                        click_play_buttons(drv)
                        # También buscar iframes anidados (nivel 2)
                        nested_iframes = drv.find_elements("tag name", "iframe")
                        if nested_iframes:
                            drv.switch_to.frame(nested_iframes[0])
                            click_play_buttons(drv)
                except:
                    continue
        except:
            pass
            
        drv.switch_to.default_content()
        
        # Esperar tráfico generado post-clic
        time.sleep(SLOW_WAIT + 2)
        
        # Buscar .m3u8 URLs en requests capturados
        stream_url = ''
        
        # Prioridad 1: URLs que contengan .m3u8 pero NO master (a veces master falla)
        for req in drv.requests:
            if '.m3u8' in req.url and 'master' not in req.url:
                stream_url = req.url
                break
        
        # Prioridad 2: Cualquier .m3u8
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
        try:
            drv.quit()
        except:
            pass

# ───────────── Combined Playlist Generation ─────────────
def create_combined_playlist(eventos_entries: list[str]) -> None:
    """Crea una playlist combinada con eventos deportivos + canales fijos"""
    varios_file = REPO_DIR / "varios.m3u"
    combined_file = REPO_DIR / "playlist.m3u"
    
    # Leer canales fijos si existe varios.m3u
    canales_fijos = []
    if varios_file.exists():
        try:
            varios_content = varios_file.read_text(encoding="utf-8").strip()
            if varios_content and not varios_content == "#EXTM3U":
                # Extraer solo las entradas (sin #EXTM3U inicial)
                varios_lines = varios_content.split('\n')[1:]  # Skip #EXTM3U
                if varios_lines and any(line.strip() for line in varios_lines):
                    canales_fijos = [line for line in varios_lines if line.strip()]
        except Exception as e:
            print(f"  ⚠️ Error leyendo varios.m3u: {e}")
    
    # Construir playlist combinada
    combined_entries = ["#EXTM3U"]
    
    # Agregar canales fijos primero
    if canales_fijos:
        combined_entries.extend(canales_fijos)
        print(f"  → Agregados {len([l for l in canales_fijos if l.startswith('#EXTINF')])} canales fijos")
    
    # Agregar eventos deportivos (omitir #EXTM3U inicial)
    if len(eventos_entries) > 1:  # Más que solo #EXTM3U
        combined_entries.extend(eventos_entries[1:])  # Skip #EXTM3U
    
    # Guardar playlist combinada
    combined_file.write_text("\n".join(combined_entries), encoding="utf-8")
    total_channels = len([l for l in combined_entries if l.startswith('#EXTINF')])
    print(f"Guardado playlist.m3u combinada con {total_channels} canales totales")

# ───────────── Main ─────────────
def main():
    # obtener eventos y ordenar por liga y hora
    events = get_today_events()
    events.sort(key=lambda x: (x[0], x[1]))

    entries = ["#EXTM3U"]
    for liga, hora, partido, chan, url in events:
        try:
            # Método 1: Intento rápido (requests directo)
            stream = get_m3u8_simple(url)
            
            # Método 2: Selenium Mejorado (fallback general)
            # Se usa para TODO lo que falle en método rápido, ya que cubre iframes y clics
            if not stream:
                print(f"  → Escaneando stream (iframe/click) para: {chan}")
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

    # Guardar eventos.m3u (solo eventos deportivos)
    out = REPO_DIR / EVENT_FILE
    out.write_text("\n".join(entries), encoding="utf-8")
    print(f"Guardado {out} con {len(entries)-1} entradas")
    
    # Crear playlist combinada con canales fijos
    create_combined_playlist(entries)

    # Git: push directo al repositorio conocido
    try:
        repo = Repo(REPO_DIR)
        # Agregar tanto eventos.m3u como playlist.m3u
        files_to_add = [str(out)]
        combined_file = REPO_DIR / "playlist.m3u"
        if combined_file.exists():
            files_to_add.append(str(combined_file))
        
        repo.index.add(files_to_add)
        repo.index.commit('AutoScraper update playlist')
        repo.remote(name='origin').push()
        print(f"Subido a GitHub RAW: {CDN_URL}")
        
        if combined_file.exists():
            combined_url = f"https://raw.githubusercontent.com/felamachado/canalesTV/main/playlist.m3u"
            print(f"Playlist combinada: {combined_url}")
    except git_exc.GitError as git_err:
        print(f"⚠️ Error con Git: {git_err}")
    except Exception as e:
        print(f"⚠️ Error al subir a GitHub: {e}")

if __name__ == '__main__':
    main()
