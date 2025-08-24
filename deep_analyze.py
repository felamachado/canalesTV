#!/usr/bin/env python3
"""
Análisis profundo de Canal 10 para encontrar fuentes .m3u8 
"""
import time
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def init_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # Deshabilitar imágenes para ser más rápido
    prefs = {"profile.managed_default_content_settings.images": 2}
    opts.add_experimental_option("prefs", prefs)
    
    driver_path = '/home/felipe/.wdm/drivers/chromedriver/linux64/139.0.7258.138/chromedriver-linux64/chromedriver'
    service = Service(driver_path)
    return webdriver.Chrome(service=service, options=opts)

def test_dash_to_hls_conversion():
    """Prueba convertir URLs DASH tokenizadas a HLS"""
    # URL DASH que sabemos que funciona (de los logs anteriores)
    dash_url = "https://edge7-ccast-sl.cvattv.com.ar/tok_eyJhbGciOiJIUzUxMiIsInR5cCI6IkpXVCJ9.eyJleHAiOiIxNzU2MjI3Njc1Iiwic2lwIjoiMTc5LjI2LjExMS4xNjAiLCJwYXRoIjoiL2xpdmUvYzRlZHMvQ2FuYWwxMF9VUlUvU0FfTGl2ZV9kYXNoX2VuYy8iLCJzZXNzaW9uX2Nkbl9pZCI6ImY2ODVlZDk2ZjZmNmI3MjYiLCJzZXNzaW9uX2lkIjoiIiwiY2xpZW50X2lkIjoiIiwiZGV2aWNlX2lkIjoiIiwibWF4X3Nlc3Npb25zIjowLCJzZXNzaW9uX2R1cmF0aW9uIjowLCJ1cmwiOiJodHRwczovLzIwMS4yMzUuNjYuMTE1IiwiYXVkIjoiMjI0Iiwic291cmNlcyI6Wzg1LDE0NCw4Niw4OF19.MUaU7u4EqzEwEZNap6P9LzohNTG8uObqvpiSyxhHyMVoaWuNyEQ7h4HbE45iP7kttCea-EJFJw4KVRCYM56C4A==/live/c4eds/Canal10_URU/SA_Live_dash_enc/Canal10_URU.mpd"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.7258.138 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://bestleague.one/",
    }
    
    print(f"🔍 Probando conversión DASH → HLS usando URL tokenizada")
    
    # Convertir DASH a HLS reemplazando _dash_enc con _hls_enc y .mpd con .m3u8
    hls_url = dash_url.replace('_dash_enc', '_hls_enc').replace('.mpd', '.m3u8')
    print(f"  → URL HLS convertida: {hls_url}")
    
    try:
        import requests
        resp = requests.get(hls_url, headers=headers, timeout=10, allow_redirects=True)
        print(f"  → Status: {resp.status_code}")
        print(f"  → Final URL: {resp.url}")
        
        if resp.status_code == 200:
            content = resp.text[:500]  # Primeros 500 caracteres
            print(f"  → Content preview: {content}")
            if '#EXTM3U' in content:
                print("  ✅ ¡URL HLS válida encontrada!")
                return resp.url
        else:
            print(f"  ⚠️ Error HTTP: {resp.status_code}")
            
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    return None

def test_base_hls_url():
    """Prueba el URL base de HLS con headers apropiados"""
    base_url = "https://chromecast.cvattv.com.ar/live/c4eds/Canal10_URU/SA_Live_hls_enc/Canal10_URU.m3u8"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.7258.138 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://bestleague.one/",
    }
    
    print(f"🔍 Probando URL base HLS: {base_url}")
    
    try:
        import requests
        resp = requests.get(base_url, headers=headers, timeout=10, allow_redirects=True)
        print(f"  → Status: {resp.status_code}")
        print(f"  → Final URL: {resp.url}")
        
        if resp.status_code == 200:
            content = resp.text[:500]  # Primeros 500 caracteres
            print(f"  → Content preview: {content}")
            if '#EXTM3U' in content:
                print("  ✅ ¡URL HLS válida encontrada!")
                return resp.url
        else:
            print(f"  ⚠️ Error HTTP: {resp.status_code}")
            
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    return None

def analyze_deep(url):
    driver = init_driver()
    
    try:
        print(f"🔍 Analizando: {url}")
        driver.get(url)
        
        # Esperar carga inicial más tiempo
        time.sleep(5)
        
        print("🔍 Analizando todas las peticiones de la página principal...")
        print(f"  → Total peticiones: {len(driver.requests)}")
        
        # Revisar peticiones de la página principal
        for req in driver.requests:
            if any(ext in req.url for ext in ['.m3u8', '.mpd', '.ts']):
                print(f"  🎯 Stream encontrado en página principal: {req.url}")
        
        print("\n🔍 Buscando iframes...")
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"  → Encontrados {len(iframes)} iframes")
        
        for i, iframe in enumerate(iframes):
            try:
                src = iframe.get_attribute("src")
                if not src or 'blogger.com' in src or 'google.com' in src:
                    continue
                    
                print(f"\n  → iframe {i+1}: {src}")
                
                # Abrir iframe en nueva ventana/tab
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])
                
                driver.get(src)
                time.sleep(8)
                
                # Buscar elementos de video
                video_elements = driver.find_elements(By.TAG_NAME, "video")
                print(f"    → Videos encontrados: {len(video_elements)}")
                
                # Buscar todos los tipos de botones de play posibles
                play_selectors = [
                    "button[aria-label*='play']", ".play-button", ".vjs-play-control",
                    ".jwplayer .jw-display-icon-container", ".plyr__control--overlaid",
                    "button.vjs-big-play-button", ".jw-icon-play", ".jw-display-icon-play",
                    "[data-testid*='play']", ".play", ".start", ".iniciar"
                ]
                
                play_buttons = []
                for selector in play_selectors:
                    try:
                        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        play_buttons.extend(buttons)
                    except:
                        continue
                
                print(f"    → Botones de play encontrados: {len(play_buttons)}")
                
                # Simular clics de usuario y esperar
                try:
                    # Click en el centro de la página por si hay overlay invisible
                    driver.execute_script("document.body.click();")
                    time.sleep(1)
                    
                    # Intentar hacer clic en botones visibles
                    for j, btn in enumerate(play_buttons[:5]):
                        try:
                            if btn.is_displayed():
                                print(f"    → Haciendo clic en botón {j+1}")
                                driver.execute_script("arguments[0].scrollIntoView(); arguments[0].click();", btn)
                                time.sleep(3)
                        except Exception as e:
                            continue
                            
                    # Esperar carga de streams
                    print("    → Esperando carga de streams...")
                    time.sleep(10)
                    
                    # Buscar streams en peticiones
                    iframe_requests = []
                    for req in driver.requests:
                        if req.url != src:  # Solo peticiones del iframe, no la página principal
                            iframe_requests.append(req)
                    
                    print(f"    → Peticiones del iframe: {len(iframe_requests)}")
                    
                    m3u8_urls = []
                    mpd_urls = []
                    ts_urls = []
                    
                    for req in iframe_requests:
                        if '.m3u8' in req.url:
                            m3u8_urls.append(req.url)
                        elif '.mpd' in req.url:
                            mpd_urls.append(req.url)
                        elif '.ts' in req.url:
                            ts_urls.append(req.url)
                    
                    print(f"    → URLs .m3u8: {len(m3u8_urls)}")
                    for url in m3u8_urls:
                        print(f"      ✅ {url}")
                    
                    print(f"    → URLs .mpd: {len(mpd_urls)}")  
                    for url in mpd_urls:
                        print(f"      📺 {url}")
                    
                    print(f"    → URLs .ts (segmentos): {len(ts_urls)}")
                    if ts_urls:
                        # Si hay .ts, buscar el .m3u8 base
                        for url in ts_urls[:3]:
                            print(f"      🧩 {url}")
                    
                    if m3u8_urls:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                        return m3u8_urls[0]
                        
                except Exception as e:
                    print(f"    ⚠️ Error en interacciones: {e}")
                
                # Volver a la ventana principal
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                        
            except Exception as e:
                print(f"    ⚠️ Error procesando iframe {i+1}: {e}")
                try:
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                except:
                    pass
                    
        return None
        
    finally:
        driver.quit()

if __name__ == "__main__":
    print("=== Fase 1: Probando conversión DASH tokenizada → HLS ===")
    conversion_result = test_dash_to_hls_conversion()
    
    if conversion_result:
        print(f"\n🎉 ¡Éxito con conversión! Stream: {conversion_result}")
    else:
        print("\n=== Fase 2: Probando URL base HLS ===")
        base_result = test_base_hls_url()
        
        if base_result:
            print(f"\n🎉 ¡Éxito con URL base! Stream: {base_result}")
        else:
            print("\n=== Fase 3: Análisis profundo de la página ===")
            url = "https://elrincondelhinchatv.blogspot.com/p/canal-10_21.html"
            result = analyze_deep(url)
            
            if result:
                print(f"\n🎉 ¡Éxito! Stream encontrado: {result}")
            else:
                print(f"\n⚠️ No se encontraron streams .m3u8")