#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pelota_builder.py – Generador de eventos.m3u desde múltiples fuentes
"""
import re
import time
import os
import json
from pathlib import Path
from git import Repo, exc as git_exc
import requests
from bs4 import BeautifulSoup
try:
    from seleniumwire import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
except Exception:  # allow importing helpers (e.g. tests) without selenium
    webdriver = None
    Options = None
    Service = None
    ChromeDriverManager = None
    By = None

# ───────────── Configuración ─────────────
ROJA_URL       = "https://www.rojadirectaenvivo.pl/"
FUTLIB_URL     = "https://futbollibre.mx/"
LIBPEL_URL     = "https://librepelota.com/"
PELOTA1_URL    = "https://www.pelotalibre1.pe/"

# Directorio del repo local
REPO_DIR       = Path(__file__).parent
EVENT_FILE     = "eventos.m3u"
CDN_URL        = f"https://raw.githubusercontent.com/felamachado/canalesTV/main/{EVENT_FILE}"
SLOW_WAIT      = 4

# Ligas a incluir/excluir
INCLUDE_LEAGUES = []
EXCLUDED_LEAGUES = [
    "Super Lig", "Liga Endesa", "Super League", "Bundesliga",
    "Liga de Peru", "Liga de Ecuador", "Ligue 1", "Liga de Colombia",
    "Liga de Chile", "MLS", "Liga de Portugal", "NBA",
    "Liga Expansion MX", "Liga de Paraguay", "Liga MX"
]

# ───────────── Drivers ─────────────
def init_driver() -> "webdriver.Chrome":
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-web-security")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--window-size=1920,1080")
    
    # Try multiple paths for chromedriver
    paths = [
        '/home/felipe/.wdm/drivers/chromedriver/linux64/143.0.7499.192/chromedriver-linux64/chromedriver',
        '/home/felipe/.wdm/drivers/chromedriver/linux64/139.0.7258.138/chromedriver-linux64/chromedriver',
        '/usr/local/bin/chromedriver',
        '/usr/bin/chromedriver'
    ]
    
    service = None
    for p in paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            try:
                service = Service(p)
                break
            except:
                pass
                
    if not service:
        # Fallback to webdriver-manager
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            print(f"Warning: WebDriver Manager failed: {e}")
            pass

    return webdriver.Chrome(service=service, options=opts) if service else webdriver.Chrome(options=opts)

# ───────────── Scrapers de Eventos ─────────────

def normalize(url: str) -> str:
    if not url or url.startswith('#'): return ''
    if url.startswith("//"): return "https:" + url
    if not url.startswith("http"): return "https://" + url.lstrip("/")
    return url

# ───────────── Descubrimiento de fuentes ─────────────
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
        has_time = re.search(r'\d{2}:\d{2}', resp.text) is not None
        blocked = any(b in resp.text.lower() for b in ["no longer available", "alliance for creativity", "access denied"])
        marker_ok = marker.lower() in resp.text.lower()
        return resp.status_code == 200 and marker_ok and has_time and not blocked
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
        resp = requests.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        return _extract_ddg_domains(resp.text, limit)
    except Exception:
        return []

def _search_bing(query, limit=5):
    from urllib.parse import urlparse
    try:
        resp = requests.get("https://www.bing.com/search", params={"q": query}, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        domains = []
        seen = set()
        soup = BeautifulSoup(resp.text, "html.parser")
        for cite in soup.find_all("cite"):
            text = cite.get_text(" ", strip=True)
            m = re.search(r'https?://([a-zA-Z0-9.-]+)', text)
            if m:
                host = m.group(1)
            else:
                token = text.split()[0] if text.split() else ""
                token = token.split("›")[0].strip()
                host = token
            host = host.lower().strip(".")
            if host.startswith("www."):
                host = host[4:]
            if not host or "." not in host or "bing.com" in host or host in seen:
                continue
            seen.add(host)
            domains.append(host)
            if len(domains) >= limit:
                break
        return domains
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
    ddg_domains = _search_ddg(query)
    if not ddg_domains:
        ddg_domains = _search_bing(query)
    for domain in ddg_domains:
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

def get_roja_events(url: str) -> list:
    """Scraper original de RojaDirecta (basado en HTML estatico si es posible)"""
    events = []
    try:
        print(f"Scraping RojaDirecta: {url}")
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        for li in soup.select("ul.menu > li"):
            t = li.find("span", class_="t")
            if not t: continue
            hora = t.text.strip()
            link = li.find("a", recursive=False)
            if not link or not link.contents: continue
            raw = link.contents[0].strip()
            if ":" not in raw: continue
            liga, partido = map(str.strip, raw.split(":", 1))
            
            for chan_link in li.select("ul > li > a"):
                href = normalize(chan_link.get("href", "").strip())
                if not href: continue
                chan_name = chan_link.text.strip()
                events.append((liga, hora, partido, chan_name, href))
    except Exception as e:
        print(f"Error scraping RojaDirecta: {e}")
    return events

def get_futbollibre_style_events(url: str, source_name: str) -> list:
    """Scraper para sitios tipo FutbolLibre/LibrePelota usando Selenium"""
    events = []
    driver = init_driver()
    try:
        print(f"Scraping {source_name}: {url}")
        driver.get(url)
        time.sleep(5) # Esperar carga de JS
        
        # Buscar enlaces que contengan un tiempo
        # Estrategia: Buscar todos los 'a', chequear si tienen hijo 'time' o texto tipo XX:XX
        links = driver.find_elements(By.TAG_NAME, "a")
        
        for a in links:
            try:
                href = a.get_attribute("href")
                if not href or "#" in href or "whatsapp" in href: continue
                
                # Check for time element or text
                text = a.text
                match = re.search(r'(\d{2}:\d{2})', text)
                
                # Si no encuentra hora en el enlace, buscar en padres (traversal)
                if not match:
                    el = a
                    for _ in range(3): # Subir hasta 3 niveles
                        try:
                            el = el.find_element(By.XPATH, "..")
                            p_txt = el.text
                            match = re.search(r'(\d{2}:\d{2})', p_txt)
                            if match:
                                text = p_txt # Usar texto del contenedor padre
                                break
                        except:
                            break
                
                if match:
                    hora = match.group(1)
                    # Limpiar texto para obtener titulo
                    full_text = text.replace(hora, "").replace("\n", " ").strip()
                    
                    if ":" in full_text:
                        parts = full_text.split(":", 1)
                        liga = parts[0].strip()
                        partido = parts[1].strip()
                    else:
                        liga = "Varios"
                        partido = full_text
                    
                    chan_name = f"{source_name} Stream"
                    events.append((liga, hora, partido, chan_name, href))
            except:
                continue
                
    except Exception as e:
        print(f"Error scraping {source_name}: {e}")
    finally:
        driver.quit()
    return events

def get_fixed_channels(url: str) -> list:
    """Obtiene canales fijos de LibrePelota (barra navegación)"""
    channels = []
    driver = init_driver()
    try:
        print(f"Scraping Fixed Channels from: {url}")
        driver.get(url)
        time.sleep(3)
        
        links = driver.find_elements(By.TAG_NAME, "a")
        seen = set()
        
        for a in links:
            try:
                href = a.get_attribute("href")
                txt = a.text.strip()
                if not href: continue
                
                # Criterio: URL contiene 'en-vivo' y el texto es corto (nombre de canal)
                if "/en-vivo/" in href and len(txt) > 2 and len(txt) < 30 and "partido" not in txt.lower() and "ver" not in txt.lower():
                    if txt not in seen:
                        # Crear entrada M3U provisional (sin stream URL aun)
                        channels.append((txt, href))
                        seen.add(txt)
            except:
                continue
    except Exception as e:
        print(f"Error scraping fixed channels: {e}")
    finally:
        driver.quit()
    return channels

# ───────────── Extracción de Stream (M3U8) ─────────────

def click_play_buttons(drv):
    """Intenta hacer clic en botones de play"""
    try:
        selectors = [
            "button[aria-label*='play']", ".play-button", ".vjs-play-control", 
            ".jw-display-icon-container", ".plyr__control--overlaid", 
            "button.vjs-big-play-button", "div[class*='play']", "svg[class*='play']"
        ]
        elements = drv.find_elements(By.CSS_SELECTOR, ", ".join(selectors))
        count = 0
        for el in elements:
            if count >= 2: break
            try:
                if el.is_displayed():
                    drv.execute_script("arguments[0].click();", el)
                    time.sleep(0.5)
                    count += 1
            except: pass
    except: pass

def extract_m3u8(url: str) -> dict:
    """Extrae el m3u8 de una URL usando Selenium Wire y clics inteligentes. Retorna dict con url y headers."""
    driver = init_driver()
    stream_data = None
    
    try:
        driver.set_page_load_timeout(20)
        try:
            driver.get(url)
        except: pass
        
        time.sleep(3)
        click_play_buttons(driver)
        
        # Buscar iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(min(len(iframes), 3)):
            try:
                driver.switch_to.default_content()
                iframes = driver.find_elements(By.TAG_NAME, "iframe") # refresh
                if i < len(iframes):
                    driver.switch_to.frame(iframes[i])
                    click_play_buttons(driver)
                    # Nested
                    nested = driver.find_elements(By.TAG_NAME, "iframe")
                    if nested:
                        driver.switch_to.frame(nested[0])
                        click_play_buttons(driver)
            except: pass
            
        driver.switch_to.default_content()
        time.sleep(4)
        
        # Capturar requests - Priorizar requests exitosos (status 200)
        candidates = []
        for req in driver.requests:
            if req.response and ('.m3u8' in req.url or '.mpd' in req.url):
                # Filter out master playlists if we can find a specific chunklist, 
                # but many times master is what we want. 
                # Just avoid duplicates and 404s.
                if req.response.status_code in [200, 206]:
                   candidates.append(req)
        
        # Prefer the last successful request (most likely the playing one)
        found_req = candidates[-1] if candidates else None
        
        if found_req:
            # Capture relevant headers for VLC
            headers = found_req.headers
            stream_data = {
                "url": found_req.url,
                "referer": headers.get("Referer", ""),
                "user_agent": headers.get("User-Agent", ""),
                "origin": headers.get("Origin", ""),
                "cookie": headers.get("Cookie", "")
            }
                    
    except Exception as e:
        print(f"Error extracting stream from {url}: {e}")
    finally:
        driver.quit()
    return stream_data

# ───────────── Main ─────────────

def main():
    # 1. Descubrir URLs actuales de las fuentes
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
    
    # 2. Filtrar y ordenar
    unique_events = {} # Key: (hora, partido) -> data
    
    for liga, hora, partido, chan, url in all_events:
        # Filtros Ligas
        if any(exc.lower() in liga.lower() for exc in EXCLUDED_LEAGUES): continue
        if INCLUDE_LEAGUES and not any(inc.lower() in liga.lower() for inc in INCLUDE_LEAGUES): continue
        pass

    # 3. Generar archivo eventos
    entries = ["#EXTM3U"]
    print(f"Total raw events found: {len(all_events)}")
    
    # Ordenar
    all_events.sort(key=lambda x: (x[1], x[0])) # Hora, Liga
    
    # Procesar streams (ESTO LLEVA TIEMPO)
    processed_count = 0
    for liga, hora, partido, chan, url in all_events:
        # Re-aplicar filtro por seguridad
        if any(exc.lower() in liga.lower() for exc in EXCLUDED_LEAGUES): continue
        if INCLUDE_LEAGUES and not any(inc.lower() in liga.lower() for inc in INCLUDE_LEAGUES): continue
        
        print(f"Procesando: {hora} {liga} - {partido}")
        result = extract_m3u8(url)
        if result:
            title = f"{hora} {liga} – {partido}"
            entries.append(f'#EXTINF:-1 tvg-name="{chan}" group-title="{liga}", {title} – {chan}')
            
            # Add VLC specific headers
            if result.get("userAgent"): # Normalize key if needed, using lower camelCase in dict
                entries.append(f'#EXTVLCOPT:http-user-agent={result["userAgent"]}')
            if result.get("referer"):
                entries.append(f'#EXTVLCOPT:http-referrer={result["referer"]}')
            elif result.get("referrer"): # Typo handling
                 entries.append(f'#EXTVLCOPT:http-referrer={result["referrer"]}')
            
            # Use keys from the new extract_m3u8 (user_agent, referer)
            ua = result.get("user_agent")
            ref = result.get("referer")
            origin = result.get("origin")
            cookie = result.get("cookie")
            
            if ua: entries.append(f'#EXTVLCOPT:http-user-agent={ua}')
            if ref: entries.append(f'#EXTVLCOPT:http-referrer={ref}')
            if origin: entries.append(f'#EXTVLCOPT:http-origin={origin}')
            if cookie: entries.append(f'#EXTVLCOPT:http-cookie={cookie}')
            
            entries.append(result["url"])
            processed_count += 1
        else:
            print("  -> No stream found")

    out_file = REPO_DIR / EVENT_FILE
    out_file.write_text("\n".join(entries), encoding="utf-8")
    print(f"Guardado {out_file} con {processed_count} eventos.")
    
    # 4. Canales Fijos (LibrePelota)
    if libpel_url:
        fixed_channels = get_fixed_channels(libpel_url)
    else:
        fixed_channels = []
    fixed_entries = []
    print(f"Procesando {len(fixed_channels)} canales fijos...")
    
    names_count = {}
    for name, url in fixed_channels:
        print(f"  Fixed: {name}")
        result = extract_m3u8(url)
        if result:
            # Handle duplicate names if any
            display_name = name
            if name in names_count:
                names_count[name] += 1
                display_name = f"{name} {names_count[name]}"
            else:
                names_count[name] = 1
                
            fixed_entries.append(f'#EXTINF:-1 group-title="Fijos", {display_name}')
            
            ua = result.get("user_agent")
            ref = result.get("referer")
            origin = result.get("origin")
            cookie = result.get("cookie")
            
            if ua: fixed_entries.append(f'#EXTVLCOPT:http-user-agent={ua}')
            if ref: fixed_entries.append(f'#EXTVLCOPT:http-referrer={ref}')
            if origin: fixed_entries.append(f'#EXTVLCOPT:http-origin={origin}')
            if cookie: fixed_entries.append(f'#EXTVLCOPT:http-cookie={cookie}')
            
            fixed_entries.append(result["url"])
            
    # 5. Combinar Playlist
    combo_entries = ["#EXTM3U"]
    combo_entries.extend(fixed_entries) # Primero fijos
    if len(entries) > 1:
        combo_entries.extend(entries[1:]) # Luego eventos
        
    combo_file = REPO_DIR / "playlist.m3u"
    combo_file.write_text("\n".join(combo_entries), encoding="utf-8")
    print("Playlist combinada generada.")
    
    # 6. Git Push
    try:
        repo = Repo(REPO_DIR)
        repo.index.add([str(out_file), str(combo_file), str(SOURCES_FILE)])
        repo.index.commit(f'Update playlist: {processed_count} events + {len(fixed_entries)//2} fixed')
        repo.remote('origin').push()
        print("Pushed to GitHub.")
    except Exception as e:
        print(f"Git Error: {e}")

if __name__ == '__main__':
    main()
