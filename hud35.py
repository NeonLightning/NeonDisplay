#!/usr/bin/env python3
import time, requests, json, evdev, spotipy, colorsys, datetime, os, subprocess, toml, random, sys
import numpy as np
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from threading import Thread, Event, RLock
from spotipy.oauth2 import SpotifyOAuth

sys.stdout.reconfigure(line_buffering=True) 
FB_DEVICE = "/dev/fb1"
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
UPDATE_INTERVAL_WEATHER = 3600
GEO_UPDATE_INTERVAL = 3600
SPOTIFY_UPDATE_INTERVAL = 2
SCOPE = "user-read-currently-playing"
USE_GPSD = True
USE_GOOGLE_GEO = True
SCREEN_AREA = SCREEN_WIDTH * SCREEN_HEIGHT
RGB565_MASKS = (0xF8, 0xFC, 0xF8)
RGB565_SHIFTS = (8, 3, -3)
BG_DIR = "./bg"
DEFAULT_CONFIG = {
    "fonts": {
        "large_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "large_font_size": 36,
        "medium_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "medium_font_size": 24,
        "small_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "small_font_size": 16,
        "spot_large_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "spot_large_font_size": 26,
        "spot_medium_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "spot_medium_font_size": 18,
        "spot_small_font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "spot_small_font_size": 12
    },
    "api_keys": {
        "openweather": "",
        "google_geo": "",
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:5000"
    },
    "settings": {
        "start_screen": "weather",
        "fallback_city": "",
        "use_gpsd": True,
        "use_google_geo": True,
        "time_display": True
    },
}

bg_cache = {}
text_bbox_cache = {}
weather_cache = {}
album_bg_cache = {}
cached_background = None
current_art_hash = None
exit_event = Event()
art_lock = RLock()
artist_image_lock = RLock()
scroll_lock = RLock()

def load_config(path="config.toml"):
    if not os.path.exists(path):
        with open(path, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG
    try:
        with open(path, 'r') as f:
            return toml.load(f)
    except Exception:
        return DEFAULT_CONFIG

config = load_config()
LARGE_FONT = ImageFont.truetype(config["fonts"]["large_font_path"], config["fonts"]["large_font_size"])
MEDIUM_FONT = ImageFont.truetype(config["fonts"]["medium_font_path"], config["fonts"]["medium_font_size"])
SMALL_FONT = ImageFont.truetype(config["fonts"]["small_font_path"], config["fonts"]["small_font_size"])
SPOT_LARGE_FONT = ImageFont.truetype(config["fonts"]["spot_large_font_path"], config["fonts"]["spot_large_font_size"])
SPOT_MEDIUM_FONT = ImageFont.truetype(config["fonts"]["spot_medium_font_path"], config["fonts"]["spot_medium_font_size"])
SPOT_SMALL_FONT = ImageFont.truetype(config["fonts"]["spot_small_font_path"], config["fonts"]["spot_small_font_size"])
OPENWEATHER_API_KEY = config["api_keys"]["openweather"]
GOOGLE_GEO_API_KEY = config["api_keys"]["google_geo"]
SPOTIFY_CLIENT_ID = config["api_keys"]["client_id"]
SPOTIFY_CLIENT_SECRET = config["api_keys"]["client_secret"]
REDIRECT_URI = config["api_keys"]["redirect_uri"]
START_SCREEN = config["settings"]["start_screen"]
FALLBACK_CITY = config["settings"]["fallback_city"]
USE_GPSD = config["settings"]["use_gpsd"]
USE_GOOGLE_GEO = config["settings"]["use_google_geo"]
TIME_DISPLAY = config["settings"]["time_display"]
GAMMA = 1.5
MIN_DISPLAY_INTERVAL = 0.001
TEXT_METRICS = {}

_gamma_r = np.array([int(((i / 255.0) ** (1 / GAMMA)) * 31 + 0.5) for i in range(256)], dtype=np.uint8)
_gamma_g = np.array([int(((i / 255.0) ** (1 / GAMMA)) * 63 + 0.5) for i in range(256)], dtype=np.uint8)
_gamma_b = np.array([int(((i / 255.0) ** (1 / GAMMA)) * 31 + 0.5) for i in range(256)], dtype=np.uint8)
weather_info = None
spotify_track = None
sp = None
album_art_image = None
artist_image = None
scroll_state = {"title": {"offset": 0, "max_offset": 0, "active": False}, "artists": {"offset": 0, "max_offset": 0, "active": False}, "album": {"offset": 0, "max_offset": 0, "active": False}}
bg_map = {"Clear": "bg_clear.png", "Clouds": "bg_clouds.png", "Rain": "bg_rain.png", "Drizzle": "bg_drizzle.png", "Thunderstorm": "bg_storm.png", "Snow": "bg_snow.png", "Mist": "bg_mist.png", "Fog": "bg_fog.png", "Haze": "bg_haze.png", "Smoke": "bg_smoke.png", "Dust": "bg_dust.png", "Sand": "bg_sand.png", "Ash": "bg_ash.png", "Squall": "bg_squall.png", "Tornado": "bg_tornado.png"}
art_pos = [float(SCREEN_WIDTH - 155), float(SCREEN_HEIGHT - 155)]
artist_pos = [5, float(SCREEN_HEIGHT - 105)]
artist_velocity = [0.7, 0.7]
art_velocity = [1, 1]
artist_on_top = False
spotify_layout_cache = None
scrolling_text_cache = {}
last_display_time = 0

def init_text_metrics():
    global TEXT_METRICS
    TEXT_METRICS = {'time': MEDIUM_FONT.getbbox("00:00"), 'temp_large': LARGE_FONT.getbbox("000°C"), 'feels_like': MEDIUM_FONT.getbbox("Feels like: 000°C"), 'humidity': SMALL_FONT.getbbox("Humidity: 100%"), 'pressure': SMALL_FONT.getbbox("Pressure: 1000 hPa"), 'wind': SMALL_FONT.getbbox("Wind: 00.0 m/s")}
init_text_metrics()

def check_configuration():
    config = load_config()
    missing_keys = []
    if not config["api_keys"]["openweather"]:
        missing_keys.append("OpenWeatherMap API key")
    if not config["api_keys"]["client_id"]:
        missing_keys.append("Spotify Client ID")
    if not config["api_keys"]["client_secret"]:
        missing_keys.append("Spotify Client Secret")
    if missing_keys:
        print("\n" + "="*60)
        print("HUD35 Configuration Required")
        print("="*60)
        print("The following configuration is missing:")
        for key in missing_keys:
            print(f"  - {key}")
        print(f"\nPlease run the setup server:")
        print(f"  python3 setup.py")
        print(f"Then visit: http://localhost:5000")
        print("="*60)
        if os.path.exists("setup.py"):
            response = input("\nStart setup server now? (y/n): ")
            if response.lower() in ['y', 'yes']:
                print("Starting setup server...")
                try:
                    subprocess.run([sys.executable, "setup.py"])
                except Exception as e:
                    print(f"Failed to start setup server: {e}")
        else:
            print("\nSetup script not found. Please create setup.py")
        
        sys.exit(1)
    sp_oauth = SpotifyOAuth(
        client_id=config["api_keys"]["client_id"],
        client_secret=config["api_keys"]["client_secret"],
        redirect_uri=config["api_keys"]["redirect_uri"],
        scope="user-read-currently-playing",
        cache_path=".spotify_cache"
    )
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        print("\n" + "="*60)
        print("Spotify Authentication Required")
        print("="*60)
        print("Spotify credentials are configured but not authenticated.")
        print(f"Please visit: http://localhost:5000/spotify_auth")
        print("="*60)
        if os.path.exists("setup.py"):
            response = input("\nOpen authentication page now? (y/n): ")
            if response.lower() in ['y', 'yes']:
                print("Starting setup server for authentication...")
                try:
                    import threading
                    def start_auth_server():
                        subprocess.run([sys.executable, "setup.py"])
                    auth_thread = threading.Thread(target=start_auth_server, daemon=True)
                    auth_thread.start()
                    time.sleep(3)
                    try:
                        import webbrowser
                        webbrowser.open("http://localhost:5000/spotify_auth")
                    except:
                        print("Please open http://localhost:5000/spotify_auth in your browser")
                    
                    input("Press Enter after completing Spotify authentication...")
                except Exception as e:
                    print(f"Failed to start auth server: {e}")
        sys.exit(1)

def setup_spotify_oauth():
    config = load_config()
    return SpotifyOAuth(
        client_id=config["api_keys"]["client_id"],
        client_secret=config["api_keys"]["client_secret"],
        redirect_uri=config["api_keys"]["redirect_uri"],
        scope=SCOPE,
        cache_path=".spotify_cache"
    )

def get_cached_bg(bg_path, size):
    key = (bg_path, size)
    if key not in bg_cache:
        bg_img = Image.open(bg_path).resize(size, Image.LANCZOS)
        bg_cache[key] = bg_img
    return bg_cache[key]

def get_cached_text_bbox(text, font):
    key = (text, getattr(font, "path", None), getattr(font, "size", None))
    if key not in text_bbox_cache:
        text_bbox_cache[key] = font.getbbox(text)
    return text_bbox_cache[key]

def cleanup_caches():
    global bg_cache, text_bbox_cache, album_bg_cache
    if len(bg_cache) > 10: bg_cache.clear()
    if len(text_bbox_cache) > 100: text_bbox_cache.clear()
    if len(album_bg_cache) > 5:
        keys = list(album_bg_cache.keys())[-3:]
        album_bg_cache = {k: album_bg_cache[k] for k in keys}

def quantize_to_rgb565(r, g, b):
    return (r // 8) * 8, (g // 4) * 4, (b // 8) * 8

def display_image_on_framebuffer(image):
    if image.mode != "RGB": image = image.convert("RGB")
    if image.size != (SCREEN_WIDTH, SCREEN_HEIGHT):
        full_img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
        full_img.paste(image, (0, 0))
        image = full_img
    arr = np.array(image, dtype=np.uint8)
    r = _gamma_r[arr[:, :, 0]].astype(np.uint16)
    g = _gamma_g[arr[:, :, 1]].astype(np.uint16)
    b = _gamma_b[arr[:, :, 2]].astype(np.uint16)
    rgb565 = (r << 11) | (g << 5) | b
    output = np.empty((SCREEN_HEIGHT, SCREEN_WIDTH, 2), dtype=np.uint8)
    output[:, :, 0] = rgb565 & 0xFF
    output[:, :, 1] = (rgb565 >> 8) & 0xFF
    with open(FB_DEVICE, "wb") as fb:
        fb.write(output.tobytes())

def get_location_via_gpsd(timeout=5, debug=True):
    try:
        dev_result = subprocess.run(['gpspipe', '-w', '-n', '2'], capture_output=True, text=True, check=False)
        devices_found = False
        for line in dev_result.stdout.splitlines():
            try:
                js = json.loads(line)
                if js.get("class") == "DEVICES":
                    if js.get("devices"): devices_found = True
                    else: return None, None
            except json.JSONDecodeError:
                continue
        if not devices_found: return None, None
        tpv_result = subprocess.run(['timeout', str(timeout), 'gpspipe', '-w', '-n', '10'], capture_output=True, text=True, check=False)
        if tpv_result.returncode == 124:
            if debug: pass
            return None, None
        elif tpv_result.returncode != 0:
            return None, None
        for line in tpv_result.stdout.splitlines():
            try:
                report = json.loads(line)
                if report.get('class') == 'TPV' and 'lat' in report and 'lon' in report:
                    return report['lat'], report['lon']
            except json.JSONDecodeError:
                continue
        return None, None
    except FileNotFoundError:
        return None, None

def get_location_via_google_geolocation(api_key):
    url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={api_key}"
    try:
        response = requests.post(url, json={}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'location' in data and 'lat' in data['location'] and 'lng' in data['location']:
            return data['location']['lat'], data['location']['lng']
        return None, None
    except requests.exceptions.RequestException:
        return None, None
    except json.JSONDecodeError:
        return None, None
    except KeyError:
        return None, None

def get_location_via_openweathermap_geocoding(api_key, city_name):
    if not city_name: return None, None
    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name}&limit=1&appid={api_key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and len(data) > 0:
            return data[0]['lat'], data[0]['lon']
        return None, None
    except requests.exceptions.RequestException:
        return None, None
    except (KeyError, IndexError):
        return None, None

def get_cached_weather(lat, lon):
    cache_key = f"{lat:.2f}_{lon:.2f}"
    if cache_key in weather_cache:
        cached_data, timestamp = weather_cache[cache_key]
        if time.time() - timestamp < 300:
            return cached_data
    return None

def cache_weather(lat, lon, data):
    weather_cache[f"{lat:.2f}_{lon:.2f}"] = (data, time.time())

def get_weather_data_by_coords(api_key, lat, lon, units):
    if lat is None or lon is None: return None
    cached = get_cached_weather(lat, lon)
    if cached: return cached
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units={units}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        weather_info_local = {"city": data["name"], "country": data["sys"]["country"], "temp": round(data["main"]["temp"]), "feels_like": round(data["main"]["feels_like"]), "description": data["weather"][0]["description"].title(), "humidity": data["main"]["humidity"], "pressure": data["main"]["pressure"], "wind_speed": round(data["wind"]["speed"], 1), "icon_id": data["weather"][0]["icon"], "main": data["weather"][0]["main"].title()}
        cache_weather(lat, lon, weather_info_local)
        return weather_info_local
    except requests.exceptions.RequestException:
        return None
    except KeyError:
        return None

def get_contrasting_colors(img, n=2):
    if img.mode != "RGB": img = img.convert("RGB")
    small_img = img.resize((50, 50), Image.LANCZOS)
    pixels = list(small_img.getdata())
    avg_r = sum(p[0] for p in pixels) // len(pixels)
    avg_g = sum(p[1] for p in pixels) // len(pixels)
    avg_b = sum(p[2] for p in pixels) // len(pixels)
    avg_h, avg_s, avg_v = colorsys.rgb_to_hsv(avg_r/255, avg_g/255, avg_b/255)
    opposite_h = (avg_h + 0.5) % 1.0
    colors = []
    data_saturation = min(0.9, avg_s + 0.3)
    label_saturation = max(0.6, data_saturation - 0.2)
    base_brightness = 0.9 if avg_v < 0.3 else (0.8 if avg_v > 0.7 else 0.85)
    r1, g1, b1 = colorsys.hsv_to_rgb(opposite_h, data_saturation, base_brightness)
    colors.append((int(r1*255), int(g1*255), int(b1*255)))
    if n > 1:
        secondary_h = (opposite_h + 0.12) % 1.0
        label_brightness = base_brightness - 0.05 if base_brightness > 0.7 else base_brightness
        r2, g2, b2 = colorsys.hsv_to_rgb(secondary_h, label_saturation, label_brightness)
        colors.append((int(r2*255), int(g2*255), int(b2*255)))
    return colors[:n]

def make_background_from_art(size, album_art_img):
    width, height = size
    if album_art_img is None:
        bg = Image.new("RGB", size, (40, 40, 60))
        for y in range(height):
            factor = 0.7 + (y / height) * 0.6
            for x in range(width):
                r, g, b = bg.getpixel((x, y))
                bg.putpixel((x, y), (int(r * factor), int(g * factor), int(b * factor)))
        return bg
    if album_art_img.mode != "RGB": album_art_img = album_art_img.convert("RGB")
    small = album_art_img.resize((50, 50), Image.LANCZOS)
    pixels = list(small.getdata())
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    avg_color = (int(r * 0.7), int(g * 0.7), int(b * 0.7))
    bg = Image.new("RGB", size, avg_color)
    art_size = height
    scaled_art = album_art_img.resize((art_size, art_size), Image.LANCZOS)
    blurred_art = scaled_art.filter(ImageFilter.GaussianBlur(4))
    enhancer = ImageEnhance.Brightness(blurred_art)
    blurred_art = enhancer.enhance(0.6)
    fade_width = min(80, art_size // 4)
    mask = Image.new("L", (art_size, art_size), 0)
    for x in range(art_size):
        if x < fade_width:
            progress = x / fade_width
            alpha = int(255 * (progress ** 0.7))
        elif x > art_size - fade_width:
            progress = (art_size - x) / fade_width
            alpha = int(255 * (progress ** 0.7))
        else:
            alpha = 255
        for y in range(art_size):
            mask.putpixel((x, y), alpha)
    art_x = (width - art_size) // 2
    bg.paste(blurred_art, (art_x, 0), mask)
    return bg

def get_cached_background(size, album_art_img):
    global cached_background, current_art_hash, album_bg_cache
    if album_art_img is None:
        return Image.new("RGB", size, "black")
    img_hash = id(album_art_img)
    if img_hash in album_bg_cache:
        bg = album_bg_cache[img_hash]
        if bg.size == size:
            return bg.copy()
    bg = make_background_from_art(size, album_art_img)
    album_bg_cache[img_hash] = bg.copy()
    return bg

def get_background_path(weather_info):
    if not weather_info:
        candidate = "bg_default.png"
    else:
        main = weather_info.get('main', '').capitalize()
        candidate = bg_map.get(main, "bg_default.png")
    full_path = os.path.join(BG_DIR, candidate) if candidate else None
    if full_path and os.path.exists(full_path):
        return candidate
    fallback_path = os.path.join(BG_DIR, "bg_default.png")
    if os.path.exists(fallback_path):
        return "bg_default.png"
    return None

def draw_text_aliased(draw, image, position, text, font, fill):
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(position, text, fill=255, font=font)
    color_layer = Image.new("RGB", image.size, fill)
    image.paste(color_layer, (0, 0), mask)

def draw_weather_image(weather_info):
    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
    bg_filename = get_background_path(weather_info)
    if bg_filename:
        bg_path = os.path.join(BG_DIR, bg_filename)
        bg_img = get_cached_bg(bg_path, (SCREEN_WIDTH, SCREEN_HEIGHT))
        img.paste(bg_img, (0, 0))
    draw = ImageDraw.Draw(img)
    if weather_info:
        text_elements = []
        title = f"{weather_info['city']}, {weather_info['country']}"
        text_elements.append((title, (10, 10), LARGE_FONT, "white"))
        temp_text = f"{weather_info['temp']}°C"
        text_elements.append((temp_text, (10, 60), LARGE_FONT, "cyan"))
        feels_text = f"Feels like: {weather_info['feels_like']}°C"
        text_elements.append((feels_text, (10, 110), MEDIUM_FONT, "lightblue"))
        desc_text = weather_info['description']
        text_elements.append((desc_text, (10, 150), MEDIUM_FONT, "yellow"))
        humidity_text = f"Humidity: {weather_info['humidity']}%"
        text_elements.append((humidity_text, (10, 190), SMALL_FONT, "orange"))
        pressure_text = f"Pressure: {weather_info['pressure']} hPa"
        text_elements.append((pressure_text, (10, 215), SMALL_FONT, "orange"))
        wind_text = f"Wind: {weather_info['wind_speed']} m/s"
        text_elements.append((wind_text, (10, 240), SMALL_FONT, "orange"))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for text, position, font, color in text_elements:
            bbox = get_cached_text_bbox(text, font)
            actual_bbox = (position[0] + bbox[0], position[1] + bbox[1], position[0] + bbox[2], position[1] + bbox[3])
            overlay_draw.rectangle([actual_bbox[0]-5, actual_bbox[1]-5, actual_bbox[2]+5, actual_bbox[3]+5], fill=(0, 0, 0, 200))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        for text, position, font, color in text_elements:
            draw_text_aliased(draw, img, position, text, font, color)
        if "icon_id" in weather_info:
            try:
                icon_url = f"http://openweathermap.org/img/wn/{weather_info['icon_id']}@2x.png"
                resp = requests.get(icon_url, timeout=5)
                resp.raise_for_status()
                icon_img = Image.open(BytesIO(resp.content)).convert("RGBA")
                icon_img.thumbnail((128, 128), Image.LANCZOS)
                img.paste(icon_img, (SCREEN_WIDTH - icon_img.size[0], SCREEN_HEIGHT - icon_img.size[1] - 40), icon_img)
            except Exception:
                pass
        if TIME_DISPLAY:
            now = datetime.datetime.now().strftime("%H:%M")
            time_bbox = TEXT_METRICS['time']
            time_width = time_bbox[2] - time_bbox[0]
            time_height = time_bbox[3] - time_bbox[1]
            x = SCREEN_WIDTH - time_width - 10
            y = SCREEN_HEIGHT - time_height - 10
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rectangle([x-5, y-5, x + time_width + 5, y + time_height + 5], fill=(0, 0, 0,200))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw_text_aliased(draw, img, (x, y), now, MEDIUM_FONT, "gray")
    else:
        error_text = "Failed to fetch weather data."
        bbox = TEXT_METRICS['feels_like']
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (SCREEN_WIDTH - text_width) // 2
        y = (SCREEN_HEIGHT - text_height) // 2
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([x-5, y-5, x + text_width + 5, y + text_height + 5], fill=(0, 0, 0,200))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw_text_aliased(draw, img, (x, y), error_text, MEDIUM_FONT, "red")
        if TIME_DISPLAY:
            now = datetime.datetime.now().strftime("%H:%M")
            time_bbox = TEXT_METRICS['time']
            time_width = time_bbox[2] - time_bbox[0]
            time_height = time_bbox[3] - time_bbox[1]
            time_x = SCREEN_WIDTH - time_width - 10
            time_y = SCREEN_HEIGHT - time_height - 10
            overlay_draw.rectangle([time_x-5, time_y-5, time_x + time_width + 5, time_y + time_height + 5], fill=(0, 0, 0,200))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw_text_aliased(draw, img, (time_x, time_y), now, MEDIUM_FONT, "gray")
    return img

def update_spotify_layout(track_data):
    global spotify_layout_cache
    if not track_data:
        spotify_layout_cache = None
        return
    fields = [("title", "Track  :", track_data.get("title", "")), ("artists", "Artists:", track_data.get("artists", "")), ("album", "Album:", track_data.get("album", ""))]
    layout = []
    y = 5
    padding = 4
    x_offset = 5
    for key, label, data in fields:
        if not data: continue
        label_bbox = get_cached_text_bbox(label, SPOT_MEDIUM_FONT)
        text_bbox = get_cached_text_bbox(data, SPOT_MEDIUM_FONT)
        label_width = label_bbox[2] - label_bbox[0]
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        field_height = max(label_bbox[3] - label_bbox[1], text_height) + padding * 2
        left_boundary = x_offset + label_width + 6
        visible_width = SCREEN_WIDTH - 5 - left_boundary
        layout.append({'key': key, 'label': label, 'data': data, 'y': y, 'field_height': field_height, 'label_width': label_width, 'text_width': text_width, 'left_boundary': left_boundary, 'visible_width': visible_width, 'needs_scroll': text_width > visible_width})
        y += field_height
    spotify_layout_cache = layout

def create_scrolling_text_image(text, font, color, total_width):
    img = Image.new("RGBA", (total_width, font.size + 10), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.text((0, 5), text, font=font, fill=color)
    draw.text((total_width // 2, 5), text, font=font, fill=color)
    return img

def draw_spotify_image(spotify_track):
    global album_art_image, artist_image, artist_on_top
    with art_lock:
        art_img = album_art_image
    img = get_cached_background((SCREEN_WIDTH, SCREEN_HEIGHT), art_img)
    if spotify_track and 'main_color' in spotify_track and 'secondary_color' in spotify_track:
        main_color = spotify_track['main_color']
        secondary_color = spotify_track['secondary_color']
    else:
        if album_art_image:
            main_color, secondary_color = get_contrasting_colors(album_art_image)
        else:
            main_color, secondary_color = (0, 255, 0), (0, 255, 255)
    album_img_to_draw = None
    artist_img_to_draw = None
    album_pos = None
    artist_pos_to_draw = None
    if art_img:
        int_pos = (int(art_pos[0]), int(art_pos[1]))
        if art_img.mode != "RGB":
            bg = Image.new("RGB", art_img.size, "black")
            if art_img.mode in ("RGBA", "LA"):
                bg.paste(art_img, mask=art_img.split()[-1])
            else:
                bg.paste(art_img)
            album_img_to_draw = bg
        else:
            album_img_to_draw = art_img
        album_pos = int_pos
    with artist_image_lock:
        art_img_artist = artist_image
    if art_img_artist:
        int_artist_pos = (int(artist_pos[0]), int(artist_pos[1]))
        if art_img_artist.mode != "RGB":
            bg = Image.new("RGB", art_img_artist.size, "black")
            if art_img_artist.mode in ("RGBA", "LA"):
                bg.paste(art_img_artist, mask=art_img_artist.split()[-1])
            else:
                bg.paste(art_img_artist)
            artist_img_to_draw = bg
        else:
            artist_img_to_draw = art_img_artist
        artist_pos_to_draw = int_artist_pos
    if artist_on_top:
        if album_img_to_draw and album_pos: img.paste(album_img_to_draw, album_pos)
        if artist_img_to_draw and artist_pos_to_draw: img.paste(artist_img_to_draw, artist_pos_to_draw)
    else:
        if artist_img_to_draw and artist_pos_to_draw: img.paste(artist_img_to_draw, artist_pos_to_draw)
        if album_img_to_draw and album_pos: img.paste(album_img_to_draw, album_pos)
    overlay = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    layout = spotify_layout_cache
    if layout:
        for item in layout:
            bg_width = min(item['label_width'] + 6 + item['text_width'] + 6, SCREEN_WIDTH - 5 - 5)
            draw.rectangle([5, item['y'], 5 + bg_width, item['y'] + item['field_height']], fill=(0,0,0,200))
            draw.text((5, item['y'] + 4), item['label'], fill=secondary_color, font=SPOT_MEDIUM_FONT)
            if item['needs_scroll']:
                scrolling_img = scrolling_text_cache.get(item['key'])
                if scrolling_img:
                    offset = scroll_state[item['key']]["offset"]
                    crop_x = offset % (item['text_width'] + 50)
                    cropped = scrolling_img.crop((crop_x, 0, crop_x + item['visible_width'], item['field_height']))
                    draw.rectangle([item['left_boundary'], item['y'], item['left_boundary'] + item['visible_width'], item['y'] + item['field_height']], fill=(0,0,0,200))
                    overlay.paste(cropped, (item['left_boundary'], item['y']), cropped)
                else:
                    draw.text((item['left_boundary'], item['y'] + 4), item['data'], fill=main_color, font=SPOT_MEDIUM_FONT)
            else:
                draw.text((item['left_boundary'], item['y'] + 4), item['data'], fill=main_color, font=SPOT_MEDIUM_FONT)
    else:
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
        if os.path.exists(os.path.join(BG_DIR, "no_track.png")):
            bg_path = os.path.join(BG_DIR, "no_track.png")
            bg_img = get_cached_bg(bg_path, (SCREEN_WIDTH, SCREEN_HEIGHT))
            img.paste(bg_img, (0, 0))
        error_text = "No track playing"
        bbox = get_cached_text_bbox(error_text, MEDIUM_FONT)
        draw.rectangle([5, 5, min(bbox[2]+11, SCREEN_WIDTH-5), bbox[3]+9], fill=(0,0,0,200))
        draw.text((11, 9), error_text, fill="red", font=MEDIUM_FONT)
    if spotify_track and 'current_position' in spotify_track and 'duration' in spotify_track:
        current_pos = spotify_track['current_position']
        duration = spotify_track['duration']
        current_min = current_pos // 60
        current_sec = current_pos % 60
        duration_min = duration // 60
        duration_sec = duration % 60
        time_text = f"{current_min}:{current_sec:02d} / {duration_min}:{duration_sec:02d}"
        time_bbox = SPOT_LARGE_FONT.getbbox(time_text)
        time_width = time_bbox[2] - time_bbox[0]
        time_height = time_bbox[3] - time_bbox[1]
        padding = 5
        background_width = time_width + 2 * padding
        background_height = time_height + 2 * padding
        time_x = 10
        time_y = SCREEN_HEIGHT - background_height - 10
        draw.rectangle([time_x, time_y, time_x + background_width, time_y + background_height], fill=(0, 0, 0, 200))
        text_x = time_x + padding
        text_y = time_y + padding - time_bbox[1]
        draw.text((text_x, text_y), time_text, fill=secondary_color, font=SPOT_LARGE_FONT)
    if TIME_DISPLAY:
        now = datetime.datetime.now().strftime("%H:%M")
        time_bbox = SPOT_LARGE_FONT.getbbox(now)
        time_width = time_bbox[2] - time_bbox[0]
        time_height = time_bbox[3] - time_bbox[1]
        padding = 5
        background_width = time_width + 2 * padding
        background_height = time_height + 2 * padding
        time_x = SCREEN_WIDTH - background_width - 10
        time_y = SCREEN_HEIGHT - background_height - 10
        draw.rectangle([time_x, time_y, time_x + background_width, time_y + background_height], fill=(0, 0, 0, 170))
        text_x = time_x + padding
        text_y = time_y + padding - time_bbox[1]
        draw.text((text_x, text_y), now, fill=main_color, font=SPOT_LARGE_FONT)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img

def create_fallback_art():
    img = Image.new("RGB", (64, 64), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    try:
        draw.text((16, 16), "🎵", fill="white", font=SPOT_MEDIUM_FONT)
    except:
        draw.text((20, 20), "MUSIC", fill="white", font=SPOT_SMALL_FONT)
    return img
FALLBACK_ART = create_fallback_art()

def fetch_and_store_artist_image(sp, artist_id):
    global artist_image
    try:
        artist = sp.artist(artist_id)
        images = artist.get('images', [])
        url = None
        for img in images:
            if abs(img['width'] - 150) <= 20 and abs(img['height'] - 150) <= 20:
                url = img['url']
                break
        if not url and images: url = images[-1]['url']
        if not url:
            with artist_image_lock: artist_image = None
            return
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        if 'image' not in resp.headers.get('content-type', '').lower(): raise ValueError("Not an image")
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        img = img.resize((100, 100), Image.LANCZOS)
        with artist_image_lock: artist_image = img
    except Exception:
        with artist_image_lock: artist_image = None

def spotify_loop():
    global START_SCREEN, spotify_track, sp, album_art_image, scrolling_text_cache
    sp_oauth = setup_spotify_oauth()
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        print("Spotify not authenticated. Please run setup to authenticate.")
        spotify_track = {
            "title": "Spotify Not Configured",
            "artists": "Run setup.py to authenticate",
            "album": "HUD35 Setup Required",
            "current_position": 0,
            "duration": 1,
            "is_playing": False,
            "main_color": (255, 0, 0),
            "secondary_color": (200, 0, 0)
        }
        update_spotify_layout(spotify_track)
        if START_SCREEN == "spotify":
            update_display()
        return
    def get_spotify_client():
        nonlocal token_info
        current_token = sp_oauth.get_cached_token()
        if not current_token:
            print("❌ No cached token found. Re-authentication required.")
            return None
        if isinstance(current_token, dict):
            token_info = current_token
            access_token = token_info.get('access_token')
            expires_at = token_info.get('expires_at', 0)
        else:
            access_token = current_token
            expires_at = time.time() + 3600
        if isinstance(token_info, dict) and expires_at and time.time() > expires_at - 60:
            try:
                if 'refresh_token' in token_info:
                    print("Refreshing Spotify access token...")
                    new_token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                    if isinstance(new_token_info, dict):
                        token_info = new_token_info
                        access_token = token_info.get('access_token')
                    else:
                        access_token = new_token_info
                    print("✅ Spotify token refreshed successfully")
                else:
                    print("❌ No refresh token available. Re-authentication required.")
                    spotify_track = None
                    update_spotify_layout(None)
                    if START_SCREEN == "spotify":
                        update_display()
                    return None
            except Exception as e:
                print(f"❌ Error refreshing Spotify token: {e}")
                spotify_track = None
                update_spotify_layout(None)
                if START_SCREEN == "spotify":
                    update_display()
                return None
        return spotipy.Spotify(auth=access_token)
    sp = get_spotify_client()
    if sp is None:
        print("Failed to initialize Spotify client.")
        return
    last_track_id = None
    spotify_error_count = 0
    last_art_url = None
    last_error_time = None
    print("🎵 Spotify loop started successfully")
    while not exit_event.is_set():
        try:
            sp = get_spotify_client()
            if sp is None:
                time.sleep(10)
                continue
            track = sp.current_user_playing_track()
            if not track or not track.get('item'):
                if spotify_track is not None:
                    spotify_track = None
                    with art_lock: 
                        album_art_image = None
                    with artist_image_lock: 
                        artist_image = None
                    update_spotify_layout(None)
                    if START_SCREEN == "spotify":
                        update_display()
                time.sleep(SPOTIFY_UPDATE_INTERVAL)
                continue
            if spotify_error_count > 0 and last_error_time is not None:
                if time.time() - last_error_time > 300:  # 5 minutes in seconds
                    print("✅ 5 minutes without errors, resetting error count")
                    spotify_error_count = 0
                    last_error_time = None
            item = track['item']
            current_id = item.get('id')
            artists_list = [artist['name'] for artist in item.get('artists', [])]
            artist_str = ", ".join(artists_list) if artists_list else "Unknown Artist"
            album_str = item['album']['name'] if item.get('album') else "Unknown Album"
            current_position = track.get('progress_ms', 0) // 1000
            duration = item.get('duration_ms', 0) // 1000
            new_track = {
                "title": item.get('name', "Unknown Track"),
                "artists": artist_str,
                "album": album_str,
                "current_position": current_position,
                "duration": duration,
                "is_playing": track.get('is_playing', False)
            }
            art_url = None
            if item.get('album') and item['album'].get('images'):
                art_url = item['album']['images'][0]['url']
            force_reload_art = (current_id != last_track_id or 
                            spotify_track is None or 
                            art_url != last_art_url)
            if current_id != last_track_id or spotify_track is None or force_reload_art:
                spotify_track = new_track
                try:
                    if art_url:
                        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
                        resp = requests.get(art_url, headers=headers, timeout=10)
                        resp.raise_for_status()
                        img = Image.open(BytesIO(resp.content)).convert("RGB")
                        img.thumbnail((150, 150), Image.LANCZOS)
                        with art_lock: 
                            album_art_image = img
                        album_bg_cache.clear()
                        main_color, secondary_color = get_contrasting_colors(img)
                        spotify_track['main_color'] = main_color
                        spotify_track['secondary_color'] = secondary_color
                    else:
                        with art_lock: 
                            album_art_image = None
                        spotify_track['main_color'] = (0, 255, 0)
                        spotify_track['secondary_color'] = (0, 255, 255)
                    last_art_url = art_url
                except Exception as e:
                    print(f"❌ Error loading album art: {e}")
                    with art_lock: 
                        album_art_image = None
                    spotify_track['main_color'] = (0, 255, 0)
                    spotify_track['secondary_color'] = (0, 255, 255)
                update_spotify_layout(spotify_track)
                scrolling_text_cache.clear()
                for key in ['title', 'artists', 'album']:
                    data = new_track.get(key, "")
                    if data:
                        text_bbox = get_cached_text_bbox(data, SPOT_MEDIUM_FONT)
                        text_width = text_bbox[2] - text_bbox[0]
                        label_text = "Track:" if key == "title" else "Artists:" if key == "artists" else "Album:"
                        label_bbox = get_cached_text_bbox(label_text, SPOT_MEDIUM_FONT)
                        label_width = label_bbox[2] - label_bbox[0]
                        visible_width = SCREEN_WIDTH - 5 - label_width - 6
                        if text_width > visible_width:
                            scrolling_img = create_scrolling_text_image(data, SPOT_MEDIUM_FONT, spotify_track['main_color'], text_width * 2 + 50)
                            scrolling_text_cache[key] = scrolling_img
                            with scroll_lock:
                                scroll_state[key]["active"] = True
                                scroll_state[key]["max_offset"] = text_width + 50
                                scroll_state[key]["offset"] = 0
                        else:
                            with scroll_lock:
                                scroll_state[key]["active"] = False
                                scroll_state[key]["max_offset"] = 0
                                scroll_state[key]["offset"] = 0
                if item.get('artists') and len(item['artists']) > 0:
                    primary_artist_id = item['artists'][0]['id']
                    Thread(target=fetch_and_store_artist_image, args=(sp, primary_artist_id), daemon=True).start()
                last_track_id = current_id
                if START_SCREEN == "spotify":
                    update_display()
                    print(f"🎵 Now playing: {new_track['artists']} -- {new_track['title']}")
            else:
                spotify_track['current_position'] = track.get('progress_ms', 0) // 1000
                spotify_track['is_playing'] = track.get('is_playing', False)
        except requests.exceptions.RequestException as e:
            spotify_error_count += 1
            last_error_time = time.time()
            print(f"📡 Spotify network error ({spotify_error_count}): {e}")
            time.sleep(min(30, 2 ** spotify_error_count))
        except spotipy.exceptions.SpotifyException as e:
            spotify_error_count += 1
            last_error_time = time.time()
            print(f"🎵 Spotify API error ({spotify_error_count}): {e}")
            if e.http_status == 401:
                print("🔑 Spotify token expired, requiring re-authentication")
                try:
                    os.remove(".spotify_cache")
                except:
                    pass
                spotify_track = None
                update_spotify_layout(None)
                if START_SCREEN == "spotify":
                    update_display()
            time.sleep(min(30, 2 ** spotify_error_count))
        except Exception as e:
            spotify_error_count += 1
            last_error_time = time.time()
            print(f"❌ Unexpected Spotify error ({spotify_error_count}): {e}")
            time.sleep(min(30, 2 ** spotify_error_count))
        if spotify_error_count >= 5:
            print("⚠️ Too many Spotify errors, showing error state")
            spotify_track = None
            with art_lock: 
                album_art_image = None
            update_spotify_layout(None)
            if START_SCREEN == "spotify":
                update_display()
            if spotify_error_count >= 10:
                spotify_error_count = 0
        time.sleep(SPOTIFY_UPDATE_INTERVAL)

def weather_loop():
    global START_SCREEN, weather_info
    lat, lon = None, None
    if USE_GPSD: lat, lon = get_location_via_gpsd(timeout=2)
    if (lat is None or lon is None) and USE_GOOGLE_GEO: lat, lon = get_location_via_google_geolocation(GOOGLE_GEO_API_KEY)
    if lat is None or lon is None:
        lat, lon = get_location_via_openweathermap_geocoding(OPENWEATHER_API_KEY, FALLBACK_CITY)
        if lat is None or lon is None: return
    last_geo = time.time()
    last_weather = 0
    last_display_update = 0
    last_cache_cleanup = time.time()
    while not exit_event.is_set():
        now = time.time()
        if now - last_cache_cleanup > 300:
            cleanup_caches()
            last_cache_cleanup = now
        if now - last_geo > GEO_UPDATE_INTERVAL:
            new_lat, new_lon = None, None
            if USE_GPSD: new_lat, new_lon = get_location_via_gpsd(timeout=2)
            if (new_lat is None or new_lon is None) and USE_GOOGLE_GEO: new_lat, new_lon = get_location_via_google_geolocation(GOOGLE_GEO_API_KEY)
            if new_lat is not None and new_lon is not None: lat, lon = new_lat, new_lon
            last_geo = now
        if now - last_weather > UPDATE_INTERVAL_WEATHER:
            new_weather = get_weather_data_by_coords(OPENWEATHER_API_KEY, lat, lon, "metric")
            if new_weather is not None: weather_info = new_weather
            last_weather = now
        if START_SCREEN == "weather" and now - last_display_update >= 1:
            update_display()
            last_display_update = now
        time.sleep(0.5)

def animate_text_scroll():
    while not exit_event.is_set():
        with scroll_lock:
            for key in scroll_state:
                state = scroll_state[key]
                if state["active"] and state["max_offset"] > 0:
                    state["offset"] += 2
                    if state["offset"] >= state["max_offset"]:
                        state["offset"] = 0
        time.sleep(1/15)

def animate_images():
    global START_SCREEN, art_pos, art_velocity, artist_pos, artist_velocity, artist_on_top
    while not exit_event.is_set():
        needs_update = False
        with art_lock:
            album_img = album_art_image
        if album_img is not None:
            w, h = album_img.size
            x, y = art_pos
            dx, dy = art_velocity
            new_x = x + dx
            new_y = y + dy
            new_dx, new_dy = dx, dy
            if new_x <= 0 or new_x + w >= SCREEN_WIDTH:
                new_dx = -dx
                new_x = max(0.0, min(new_x, float(SCREEN_WIDTH - w)))
            if new_y <= 0 or new_y + h >= SCREEN_HEIGHT:
                new_dy = -dy
                new_y = max(0.0, min(new_y, float(SCREEN_HEIGHT - h)))
            with art_lock:
                art_pos[:] = [new_x, new_y]
                art_velocity[:] = [new_dx, new_dy]
            needs_update = True
        with artist_image_lock:
            artist_img = artist_image
        if artist_img is not None:
            w, h = artist_img.size
            x, y = artist_pos
            dx, dy = artist_velocity
            new_x = x + dx
            new_y = y + dy
            new_dx, new_dy = dx, dy
            bounced = False
            if new_x <= 0 or new_x + w >= SCREEN_WIDTH:
                new_dx = -dx
                new_x = max(0.0, min(new_x, float(SCREEN_WIDTH - w)))
                bounced = True
            if new_y <= 0 or new_y + h >= SCREEN_HEIGHT:
                new_dy = -dy
                new_y = max(0.0, min(new_y, float(SCREEN_HEIGHT - h)))
                bounced = True
            with artist_image_lock:
                artist_pos[:] = [new_x, new_y]
                artist_velocity[:] = [new_dx, new_dy]
            if bounced and random.random() < 0.5:
                artist_on_top = not artist_on_top
                needs_update = True
            needs_update = True
        if needs_update and START_SCREEN == "spotify":
            update_display()
        time.sleep(1/60)

def find_touchscreen():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "ADS7846" in dev.name or "Touchscreen" in dev.name: return dev
    raise RuntimeError("Touchscreen not found")

def handle_touch():
    global START_SCREEN
    device = find_touchscreen()
    for event in device.read_loop():
        if exit_event.is_set(): break
        if event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_TOUCH and event.value == 1:
            START_SCREEN = "spotify" if START_SCREEN == "weather" else "weather"
            update_display()

def update_display():
    global START_SCREEN
    if START_SCREEN == "weather":
        img = draw_weather_image(weather_info)
    else:
        img = draw_spotify_image(spotify_track)
    display_image_on_framebuffer(img)

def clear_framebuffer():
    with open(FB_DEVICE, "wb") as f:
        f.write(b'\x00\x00' * SCREEN_AREA)

def main():
    Thread(target=weather_loop, daemon=True).start()
    Thread(target=spotify_loop, daemon=True).start()
    Thread(target=handle_touch, daemon=True).start()
    Thread(target=animate_images, daemon=True).start()
    Thread(target=animate_text_scroll, daemon=True).start()
    update_display()
    try:
        while not exit_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        exit_event.set()
        clear_framebuffer()

if __name__ == "__main__":
    main()