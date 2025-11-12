#!/usr/bin/env python3
import time, requests, json, evdev, spotipy, colorsys, datetime, os, subprocess, toml, random, sys, copy, math, queue, threading
import  numpy as np
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageStat, ImageColor
from threading import Thread, Event, RLock
from spotipy.oauth2 import SpotifyOAuth

try:
    import st7789
    HAS_ST7789 = True
except ImportError:
    HAS_ST7789 = False
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False
HAS_WAVESHARE_EPD = False

sys.stdout.reconfigure(line_buffering=True)

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
UPDATE_INTERVAL_WEATHER = 3600
GEO_UPDATE_INTERVAL = 3600
SPOTIFY_UPDATE_INTERVAL = 1
SCOPE = "user-read-currently-playing"
USE_GPSD = True
USE_GOOGLE_GEO = True
SCREEN_AREA = SCREEN_WIDTH * SCREEN_HEIGHT
BG_DIR = "./bg"
CLOCK_TYPE = "analog"
CLOCK_BACKGROUND = "color"
CLOCK_COLOR = "black"

DEFAULT_CONFIG = {
    "display": {
        "type": "st7789",
        "framebuffer": "/dev/fb1",
        "rotation": 0,
        "st7789": {
            "spi_port": 0,
            "spi_cs": 1,
            "dc_pin": 9,
            "backlight_pin": 13,
            "rotation": 0,
            "spi_speed": 60000000
        }
    },
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
        "framebuffer": "/dev/fb1",
        "start_screen": "weather",
        "fallback_city": "",
        "use_gpsd": True,
        "use_google_geo": True,
        "time_display": True,
        "progressbar_display": True,
        "enable_current_track_display": True
    },
    "clock": {
        "type": "analog",
        "background": "color",
        "color": "black"
    },
    "buttons": {
        "button_a": 5,
        "button_b": 6,
        "button_x": 16,
        "button_y": 24
    }
}

bg_cache = {}
text_bbox_cache = {}
weather_cache = {}
album_bg_cache = {}
exit_event = Event()
art_lock = RLock()
artist_image_lock = RLock()
scroll_lock = RLock()
st7789_display = None
waveshare_epd = None
waveshare_base_image = None
partial_refresh_count = 0
epd2in13_V3 = None
epdconfig = None
bg_generation_queue = queue.Queue(maxsize=5)
spotify_bg_cache = None
spotify_bg_cache_lock = threading.Lock()
current_album_art_hash = None
current_clock_artwork = None
clock_bg_image = None
clock_bg_lock = threading.Lock()
button_last_press = {5: 0, 6: 0, 16: 0, 24: 0}
_gamma_r = np.array([int(((i / 255.0) ** (1 / 1.5)) * 31 + 0.5) for i in range(256)], dtype=np.uint8)
_gamma_g = np.array([int(((i / 255.0) ** (1 / 1.5)) * 63 + 0.5) for i in range(256)], dtype=np.uint8)
_gamma_b = np.array([int(((i / 255.0) ** (1 / 1.5)) * 31 + 0.5) for i in range(256)], dtype=np.uint8)
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
waveshare_lock = RLock()

def load_config(path="config.toml"):
    if not os.path.exists(path):
        with open(path, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG.copy()
    try:
        with open(path, 'r') as f:
            loaded_config = toml.load(f)
        merged_config = copy.deepcopy(DEFAULT_CONFIG)
        for category in loaded_config:
            if category in merged_config:
                if isinstance(merged_config[category], dict) and isinstance(loaded_config[category], dict):
                    for key in loaded_config[category]:
                        merged_config[category][key] = loaded_config[category][key]
                else:
                    merged_config[category] = loaded_config[category]
            else:
                merged_config[category] = loaded_config[category]
        with open(path, 'w') as f:
            toml.dump(merged_config, f)
        return merged_config
    except Exception as e:
        print(f"Error loading config: {e}, using defaults")
        with open(path, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG.copy()

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
PROGRESSBAR_DISPLAY = config["settings"]["progressbar_display"]
ENABLE_CURRENT_TRACK_DISPLAY = config["settings"]["enable_current_track_display"]
FRAMEBUFFER = config["settings"]["framebuffer"]
BUTTON_A = config["buttons"]["button_a"]
BUTTON_B = config["buttons"]["button_b"]
BUTTON_X = config["buttons"]["button_x"]
BUTTON_Y = config["buttons"]["button_y"]
CLOCK_TYPE = config["clock"]["type"]
CLOCK_BACKGROUND = config["clock"]["background"]
CLOCK_COLOR = config["clock"].get("color", "black")
MIN_DISPLAY_INTERVAL = 0.001
DEBOUNCE_TIME = 0.3

def get_cached_bg(bg_path, size):
    key = (bg_path, size)
    if key not in bg_cache:
        bg_img = Image.open(bg_path).resize(size, Image.BILINEAR)
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
    small_img = img.resize((50, 50), Image.BILINEAR)
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
    if album_art_img.mode != "RGB":
        album_art_img = album_art_img.convert("RGB")
    small_for_color = album_art_img.resize((50, 50), Image.BILINEAR)
    pixels = list(small_for_color.getdata())
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    avg_color = (int(r * 0.7), int(g * 0.7), int(b * 0.7))
    bg = Image.new("RGB", size, avg_color)
    art_size = height
    scaled_art = album_art_img.resize((art_size, art_size), Image.BILINEAR)
    blurred_art = scaled_art.filter(ImageFilter.GaussianBlur(2))
    enhancer = ImageEnhance.Brightness(blurred_art)
    blurred_art = enhancer.enhance(0.6)
    fade_width = min(80, art_size // 4)
    x_coords = np.arange(art_size)
    left_fade_mask = np.where(x_coords < fade_width,
                            255 * ((x_coords / fade_width) ** 0.7),
                            255).astype(np.uint8)
    right_fade_mask = np.where(x_coords > art_size - fade_width,
                            255 * (((art_size - x_coords) / fade_width) ** 0.7),
                            255).astype(np.uint8)
    combined_alpha = np.minimum(left_fade_mask, right_fade_mask)
    mask_array = np.tile(combined_alpha, (art_size, 1))
    mask = Image.fromarray(mask_array, mode='L')
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

def background_generation_worker():
    global spotify_bg_cache, current_album_art_hash, clock_bg_image
    while not exit_event.is_set():
        try:
            album_img, size, bg_type = bg_generation_queue.get(timeout=1)
            if bg_type == "spotify":
                generated_bg = get_cached_background(size, album_img)
                with spotify_bg_cache_lock:
                    spotify_bg_cache = generated_bg.copy() if generated_bg else None
                    current_album_art_hash = id(album_img) if album_img else None
            elif bg_type == "clock":
                clock_bg_result = get_cached_background(size, album_img)
                with clock_bg_lock:
                    clock_bg_image = clock_bg_result.copy() if clock_bg_result else None
            else:
                print(f"Unknown background type requested: {bg_type}")
            bg_generation_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Background generation worker error: {e}")
            bg_generation_queue.task_done()

def request_background_generation(album_img):
    global current_clock_artwork
    if album_img is not None:
        with clock_bg_lock:
            if current_clock_artwork is None or id(album_img) != id(current_clock_artwork):
                current_clock_artwork = album_img.copy()
        try:
            bg_generation_queue.put((album_img, (SCREEN_WIDTH, SCREEN_HEIGHT), "spotify"), block=False)
        except queue.Full:
            print("Spotify background generation queue is full, skipping request.")
        if CLOCK_BACKGROUND == "album":
            try:
                bg_generation_queue.put((album_img, (SCREEN_WIDTH, SCREEN_HEIGHT), "clock"), block=False)
            except queue.Full:
                print("Clock background generation queue is full, skipping request.")
    else:
        with clock_bg_lock:
            current_clock_artwork = None

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
                icon_img.thumbnail((128, 128), Image.BILINEAR)
                img.paste(icon_img, (SCREEN_WIDTH - icon_img.size[0], SCREEN_HEIGHT - icon_img.size[1] - 40), icon_img)
            except Exception:
                pass
        if TIME_DISPLAY:
            now = datetime.datetime.now().strftime("%H:%M")
            time_bbox = get_cached_text_bbox(now, MEDIUM_FONT)
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
        bbox = get_cached_text_bbox(error_text, MEDIUM_FONT)
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
            time_bbox = get_cached_text_bbox(now, MEDIUM_FONT)
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
    bg_to_use = None
    with spotify_bg_cache_lock:
        if spotify_bg_cache is not None and art_img is not None and current_album_art_hash == id(art_img):
            bg_to_use = spotify_bg_cache.copy()
    if bg_to_use is None:
        bg_to_use = get_cached_background((SCREEN_WIDTH, SCREEN_HEIGHT), art_img)
    img = bg_to_use
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
    if PROGRESSBAR_DISPLAY:
        progress_bar_height = 10
        border_width = 2
        progress_bar_y = SCREEN_HEIGHT - progress_bar_height
        time_y_offset = progress_bar_height + border_width + 1
        draw.rectangle([
            0, 
            progress_bar_y - border_width, 
            SCREEN_WIDTH, 
            SCREEN_HEIGHT
        ], fill=(*secondary_color, 150))
        draw.rectangle([
            border_width, 
            progress_bar_y, 
            SCREEN_WIDTH - border_width, 
            SCREEN_HEIGHT
        ], fill=(0, 0, 0, 200))
        if spotify_track and 'current_position' in spotify_track and 'duration' in spotify_track:
            current_pos = spotify_track['current_position']
            duration = spotify_track['duration']
            if duration > 0:
                progress_percent = min(current_pos / duration, 1.0)
            else:
                progress_percent = 0
            progress_width = int((SCREEN_WIDTH - 2 * border_width) * progress_percent)
            draw.rectangle([
                border_width, 
                progress_bar_y, 
                border_width + progress_width, 
                SCREEN_HEIGHT
            ], fill=(*main_color, 180))
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
            time_x = 5
            time_y = SCREEN_HEIGHT - background_height - time_y_offset
            draw.rectangle([time_x, time_y, time_x + background_width, time_y + background_height], fill=(0, 0, 0, 200))
            text_x = time_x + padding
            text_y = time_y + padding - time_bbox[1]
            draw.text((text_x, text_y), time_text, fill=secondary_color, font=SPOT_LARGE_FONT)
    else:
        progress_bar_height = 0
        time_y_offset = 0
        if spotify_track and 'current_position' in spotify_track and 'duration' in spotify_track:
            current_pos = spotify_track['current_position']
            duration = spotify_track['duration']
    if TIME_DISPLAY:
        now = datetime.datetime.now().strftime("%H:%M")
        time_bbox = SPOT_LARGE_FONT.getbbox(now)
        time_width = time_bbox[2] - time_bbox[0]
        time_height = time_bbox[3] - time_bbox[1]
        padding = 5
        background_width = time_width + 2 * padding
        background_height = time_height + 2 * padding
        time_x = SCREEN_WIDTH - background_width - 5
        time_y = SCREEN_HEIGHT - background_height - time_y_offset
        draw.rectangle([time_x, time_y, time_x + background_width, time_y + background_height], fill=(0, 0, 0, 170))
        text_x = time_x + padding
        text_y = time_y + padding - time_bbox[1]
        draw.text((text_x, text_y), now, fill=main_color, font=SPOT_LARGE_FONT)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img

def draw_clock_image():
    global weather_info, clock_bg_image
    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
    avg_color = (128, 128, 128)
    bg_applied = False
    if CLOCK_BACKGROUND == "album":
        with clock_bg_lock:
            bg_to_use = clock_bg_image
        if bg_to_use is not None:
            img.paste(bg_to_use, (0, 0))
            stat = ImageStat.Stat(bg_to_use)
            avg_color = tuple(int(v) for v in stat.mean[:3])
            bg_applied = True
        else:
            try:
                if CLOCK_COLOR:
                    bg_color = ImageColor.getrgb(CLOCK_COLOR)
                else:
                    bg_color = (0, 0, 0)
                img.paste(Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), bg_color))
                avg_color = bg_color
                bg_applied = True
            except Exception:
                img.paste(Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black"))
                avg_color = (0, 0, 0)
                bg_applied = True
    elif CLOCK_BACKGROUND == "weather":
        bg_filename = get_background_path(weather_info)
        if bg_filename:
            bg_path = os.path.join(BG_DIR, bg_filename)
            if os.path.exists(bg_path):
                bg_img = get_cached_bg(bg_path, (SCREEN_WIDTH, SCREEN_HEIGHT))
                img.paste(bg_img, (0, 0))
                stat = ImageStat.Stat(bg_img)
                avg_color = tuple(int(v) for v in stat.mean[:3])
                bg_applied = True
    if not bg_applied:
        try:
            if CLOCK_COLOR:
                bg_color = ImageColor.getrgb(CLOCK_COLOR)
            else:
                hue_shift = (datetime.datetime.now().second / 60.0) % 1.0
                rr, gg, bb = colorsys.hsv_to_rgb(hue_shift, 0.5, 0.2)
                bg_color = (int(rr * 255), int(gg * 255), int(bb * 255))
            img.paste(Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), bg_color))
            avg_color = bg_color
        except Exception:
            img.paste(Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black"))
            avg_color = (0, 0, 0)
    r, g, b = [x / 255.0 for x in avg_color]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    base_hue = (h + 0.5) % 1.0
    contrast_saturation = 0.8 + (0.4 * (1.0 - s))
    contrast_brightness = 0.85 if v < 0.5 else 0.25
    palette = []
    for i in range(5):
        hh = (base_hue + i * 0.18) % 1.0
        rr, gg, bb = colorsys.hsv_to_rgb(hh, contrast_saturation, contrast_brightness)
        rr, gg, bb = int(rr * 255), int(gg * 255), int(bb * 255)
        rr = min(max(rr + (128 - avg_color[0]) // 2, 0), 255)
        gg = min(max(gg + (128 - avg_color[1]) // 2, 0), 255)
        bb = min(max(bb + (128 - avg_color[2]) // 2, 0), 255)
        palette.append((rr, gg, bb))
    face_color, notch_color, hour_color, minute_color, second_color = palette
    draw = ImageDraw.Draw(img)
    now = datetime.datetime.now()
    if CLOCK_TYPE == "analog":
        center_x = SCREEN_WIDTH // 2
        center_y = SCREEN_HEIGHT // 2
        radius = min(SCREEN_WIDTH, SCREEN_HEIGHT) // 2 - 20
        draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                    outline=face_color, width=4)
        for i in range(12):
            angle = math.radians(i * 30)
            x_outer = center_x + radius * math.sin(angle)
            y_outer = center_y - radius * math.cos(angle)
            x_inner = center_x + (radius - 15) * math.sin(angle)
            y_inner = center_y - (radius - 15) * math.cos(angle)
            draw.line((x_inner, y_inner, x_outer, y_outer), fill=notch_color, width=2)
        hour = now.hour % 12 + now.minute / 60.0
        minute = now.minute + now.second / 60.0
        second = now.second
        hour_angle = math.radians((hour / 12.0) * 360)
        minute_angle = math.radians((minute / 60.0) * 360)
        second_angle = math.radians((second / 60.0) * 360)
        draw.line((center_x, center_y,
                    center_x + radius * 0.5 * math.sin(hour_angle),
                    center_y - radius * 0.5 * math.cos(hour_angle)),
                    fill=hour_color, width=10)
        draw.line((center_x, center_y,
                    center_x + radius * 0.7 * math.sin(minute_angle),
                    center_y - radius * 0.7 * math.cos(minute_angle)),
                    fill=minute_color, width=6)
        draw.line((center_x, center_y,
                    center_x + radius * 0.85 * math.sin(second_angle),
                    center_y - radius * 0.85 * math.cos(second_angle)),
                    fill=second_color, width=4)
        draw.ellipse((center_x - 5, center_y - 5, center_x + 5, center_y + 5), fill="white")
    else:
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%A, %B %d, %Y")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        time_bbox = get_cached_text_bbox(time_str, LARGE_FONT)
        time_width = time_bbox[2] - time_bbox[0]
        time_height = time_bbox[3] - time_bbox[1]
        time_x = (SCREEN_WIDTH - time_width) // 2
        time_y = (SCREEN_HEIGHT - time_height) // 2 - 30
        date_bbox = get_cached_text_bbox(date_str, MEDIUM_FONT)
        date_width = date_bbox[2] - date_bbox[0]
        date_x = (SCREEN_WIDTH - date_width) // 2
        date_y = time_y + time_height + 20
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw_text_aliased(draw, img, (time_x, time_y), time_str, LARGE_FONT, face_color)
        draw_text_aliased(draw, img, (date_x, date_y), date_str, MEDIUM_FONT, notch_color)
    return img

def setup_spotify_oauth():
    return SpotifyOAuth(
        client_id=config["api_keys"]["client_id"],
        client_secret=config["api_keys"]["client_secret"],
        redirect_uri=config["api_keys"]["redirect_uri"],
        scope=SCOPE,
        cache_path=".spotify_cache"
    )

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
        img = img.resize((100, 100), Image.BILINEAR)
        with artist_image_lock: artist_image = img
    except Exception:
        with artist_image_lock: artist_image = None

def write_current_track_state(track_data):
    if not ENABLE_CURRENT_TRACK_DISPLAY:
        return
    try:
        state_data = {}
        if track_data:
            state_data['current_track'] = {
                'title': track_data.get('title', 'Unknown Track'),
                'artists': track_data.get('artists', 'Unknown Artist'),
                'album': track_data.get('album', 'Unknown Album'),
                'current_position': track_data.get('current_position', 0),
                'duration': track_data.get('duration', 0),
                'is_playing': track_data.get('is_playing', False),
                'timestamp': time.time()
            }
        else:
            state_data['current_track'] = {
                'title': 'No track playing',
                'artists': '',
                'album': '',
                'current_position': 0,
                'duration': 0,
                'is_playing': False,
                'timestamp': time.time()
            }
        with open('.current_track_state.toml', 'w') as f:
            toml.dump(state_data, f)
    except Exception as e:
        print(f"Error writing track state: {e}")

def initialize_spotify_client():
    if os.path.exists(".spotify_cache"):
        try:
            with open(".spotify_cache", "r") as f:
                cache_content = f.read().strip()
                if not cache_content:
                    os.remove(".spotify_cache")
        except Exception:
            try:
                os.remove(".spotify_cache")
            except:
                pass
    try:
        sp_oauth = setup_spotify_oauth()
        test_token = sp_oauth.get_cached_token()
        if not test_token:
            return None
    except Exception:
        return None
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        return None
    if not isinstance(token_info, dict):
        try:
            os.remove(".spotify_cache")
        except:
            pass
        return None
    if 'access_token' not in token_info:
        return None
    if 'expires_at' not in token_info:
        token_info['expires_at'] = 0
    expires_at = token_info.get('expires_at', 0)
    current_time = time.time()
    if current_time > expires_at - 300:
        refresh_token = token_info.get('refresh_token')
        if not refresh_token:
            try:
                os.remove(".spotify_cache")
            except:
                pass
            return None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                new_token_info = sp_oauth.refresh_access_token(refresh_token)
                if new_token_info and 'access_token' in new_token_info:
                    token_info = new_token_info
                    break
                else:
                    if attempt == max_retries - 1:
                        raise Exception("Invalid token refresh response")
            except Exception:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    time.sleep(wait_time)
                else:
                    if 'access_token' in token_info and current_time < expires_at:
                        pass
                    else:
                        return None
    access_token = token_info.get('access_token')
    if not access_token:
        return None
    return spotipy.Spotify(auth=access_token)

def handle_spotify_error(error, error_count, last_error_time):
    error_count += 1
    last_error_time = time.time()
    if isinstance(error, requests.exceptions.RequestException):
        if "Connection aborted" in str(error) or "RemoteDisconnected" in str(error):
            backoff_time = min(60, 5 * error_count)
        else:
            backoff_time = min(30, 2 ** error_count)
        time.sleep(backoff_time)
    elif isinstance(error, spotipy.exceptions.SpotifyException):
        if error.http_status == 401:
            try:
                os.remove(".spotify_cache")
            except:
                pass
        time.sleep(min(30, 2 ** error_count))
    else:
        time.sleep(min(30, 2 ** error_count))
    return error_count, last_error_time

def extract_track_info(track_data):
    if not track_data or not track_data.get('item'):
        return None
    item = track_data['item']
    artists_list = [artist['name'] for artist in item.get('artists', [])]
    artist_str = ", ".join(artists_list) if artists_list else "Unknown Artist"
    album_str = item['album']['name'] if item.get('album') else "Unknown Album"
    art_url = None
    if item.get('album') and item['album'].get('images'):
        art_url = item['album']['images'][1]['url'] if len(item['album']['images']) > 1 else item['album']['images'][0]['url']
    return {
        "id": item.get('id'),
        "title": item.get('name', "Unknown Track"),
        "artists": artist_str,
        "album": album_str,
        "current_position": track_data.get('progress_ms', 0) // 1000,
        "duration": item.get('duration_ms', 0) // 1000,
        "is_playing": track_data.get('is_playing', False),
        "art_url": art_url,
        "artist_id": item['artists'][0]['id'] if item.get('artists') and len(item['artists']) > 0 else None
    }

def load_and_process_album_art(art_url, track_info, last_art_url, last_album_art_hash):
    global album_art_image, spotify_bg_cache, current_album_art_hash
    if not art_url or art_url == last_art_url:
        return last_art_url, last_album_art_hash
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
        resp = requests.get(art_url, headers=headers, timeout=10)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.thumbnail((150, 150), Image.BILINEAR)
        with art_lock: 
            album_art_image = img
        current_img_hash = id(img)
        if current_img_hash != last_album_art_hash:
            request_background_generation(img)
            last_album_art_hash = current_img_hash
        main_color, secondary_color = get_contrasting_colors(img)
        track_info['main_color'] = main_color
        track_info['secondary_color'] = secondary_color
        last_art_url = art_url
    except Exception:
        with art_lock: 
            album_art_image = None
        with spotify_bg_cache_lock:
            spotify_bg_cache = None
            current_album_art_hash = None
        track_info['main_color'] = (0, 255, 0)
        track_info['secondary_color'] = (0, 255, 255)
        last_art_url = None
    return last_art_url, last_album_art_hash

def setup_track_display(track_info, last_track_id):
    global spotify_track, scrolling_text_cache
    spotify_track = track_info
    write_current_track_state(spotify_track)
    update_spotify_layout(spotify_track)
    scrolling_text_cache.clear()
    for key in ['title', 'artists', 'album']:
        data = track_info.get(key, "")
        if data:
            text_bbox = get_cached_text_bbox(data, SPOT_MEDIUM_FONT)
            text_width = text_bbox[2] - text_bbox[0]
            label_text = "Track:" if key == "title" else "Artists:" if key == "artists" else "Album:"
            label_bbox = get_cached_text_bbox(label_text, SPOT_MEDIUM_FONT)
            label_width = label_bbox[2] - label_bbox[0]
            visible_width = SCREEN_WIDTH - 5 - label_width - 6
            if text_width > visible_width:
                scrolling_img = create_scrolling_text_image(data, SPOT_MEDIUM_FONT, track_info['main_color'], text_width * 2 + 50)
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
    if track_info.get('artist_id'):
        Thread(target=fetch_and_store_artist_image, args=(sp, track_info['artist_id']), daemon=True).start()
    if START_SCREEN == "spotify":
        update_display()
    return track_info['id']

def update_existing_track_progress(track_data):
    global spotify_track
    if not spotify_track:
        return
    old_position = spotify_track.get('current_position', 0)
    new_position = track_data.get('progress_ms', 0) // 1000
    spotify_track['current_position'] = new_position
    spotify_track['is_playing'] = track_data.get('is_playing', False)
    position_diff = abs(new_position - old_position)
    if position_diff >= 5 or spotify_track['is_playing'] != track_data.get('is_playing', False):
        write_current_track_state(spotify_track)

def clear_track_state():
    global spotify_track
    spotify_track = None
    with art_lock: 
        album_art_image = None
    write_current_track_state(None)
    update_spotify_layout(None)
    if START_SCREEN == "spotify":
        update_display()

def spotify_loop():
    global START_SCREEN, spotify_track, sp, album_art_image, scrolling_text_cache
    global spotify_bg_cache, current_album_art_hash
    sp = initialize_spotify_client()
    if sp is None:
        spotify_track = {
            "title": "Spotify Authentication Required",
            "artists": "Run setup to authenticate",
            "album": "HUD35 Setup",
            "current_position": 0,
            "duration": 1,
            "is_playing": False,
            "main_color": (255, 100, 100),
            "secondary_color": (200, 100, 100)
        }
        update_spotify_layout(spotify_track)
        if START_SCREEN == "spotify":
            update_display()
        return
    last_track_id = None
    spotify_error_count = 0
    last_art_url = None
    last_error_time = None
    initial_token_logged = False
    last_album_art_hash = None
    while not exit_event.is_set():
        try:
            current_token = setup_spotify_oauth().get_cached_token()
            if not initial_token_logged and current_token and isinstance(current_token, dict):
                expires_at = current_token.get('expires_at', 0)
                current_time = time.time()
                time_remaining = expires_at - current_time
                initial_token_logged = True
            track = sp.current_user_playing_track()
            if not track or not track.get('item'):
                if spotify_track is not None:
                    clear_track_state()
                time.sleep(SPOTIFY_UPDATE_INTERVAL)
                continue
            if spotify_error_count > 0 and last_error_time is not None:
                if time.time() - last_error_time > 300:
                    spotify_error_count = 0
                    last_error_time = None
            track_info = extract_track_info(track)
            if track_info['id'] != last_track_id or spotify_track is None:
                last_art_url, last_album_art_hash = load_and_process_album_art(
                    track_info['art_url'], track_info, last_art_url, last_album_art_hash
                )
                last_track_id = setup_track_display(track_info, last_track_id)
            else:
                update_existing_track_progress(track)
            if spotify_track and spotify_track.get('is_playing', False):
                current_time = time.time()
                if not hasattr(spotify_loop, 'last_track_write') or current_time - spotify_loop.last_track_write > 30:
                    write_current_track_state(spotify_track)
                    spotify_loop.last_track_write = current_time
        except Exception as e:
            spotify_error_count, last_error_time = handle_spotify_error(e, spotify_error_count, last_error_time)
            if spotify_error_count >= 5:
                clear_track_state()
                if spotify_error_count >= 5:
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
    last_animation_time = time.time()
    while not exit_event.is_set():
        current_time = time.time()
        frame_time = current_time - last_animation_time
        last_animation_time = current_time        
        display_type = config.get("display", {}).get("type", "framebuffer")
        if display_type == "st7789" and HAS_ST7789:
            speed_factor = 0.4
            step_multiplier = 1
        else:
            speed_factor = 0.4
            step_multiplier = 0.8
        needs_update = False
        with art_lock:
            album_img = album_art_image
        if album_img is not None:
            w, h = album_img.size
            x, y = art_pos
            dx, dy = art_velocity
            new_x = x + (dx * frame_time * 60 * speed_factor * step_multiplier)
            new_y = y + (dy * frame_time * 60 * speed_factor * step_multiplier)
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
            new_x = x + (dx * frame_time * 60 * speed_factor * step_multiplier)
            new_y = y + (dy * frame_time * 60 * speed_factor * step_multiplier)
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

def init_st7789_display():
    global st7789_display
    if not HAS_ST7789: return None
    try:
        st7789_config = config["display"].get("st7789", {})
        config_rotation = config["display"].get("rotation", 0)
        st7789_display = st7789.ST7789(
            port=st7789_config.get("spi_port", 0),
            cs=st7789_config.get("spi_cs", 1),
            dc=st7789_config.get("dc_pin", 9),
            backlight=st7789_config.get("backlight_pin", 13),
            width=320,
            height=240,
            rotation=config_rotation,
            spi_speed_hz=st7789_config.get("spi_speed", 60000000)
        )
        print(f"ST7789 display initialized with rotation: {config_rotation}°")
        return st7789_display
    except Exception as e:
        print(f"ST7789 init failed: {e}")
        return None

def display_image_on_st7789(image):
    global st7789_display
    try:
        if st7789_display is None:
            st7789_display = init_st7789_display()
            if st7789_display is None: return
        scaled_image = image.resize((320, 240), Image.BILINEAR)
        if scaled_image.mode != "RGB": 
            scaled_image = scaled_image.convert("RGB")
        st7789_display.display(scaled_image)
    except Exception as e:
        print(f"ST7789 display error: {e}")
        display_image_on_original_fb(image)

def display_image_on_original_fb(image):
    try:
        rotation = config["display"].get("rotation", 0)
        if rotation == 180:
            rotated_image = image.rotate(180, expand=False)
        else:
            rotated_image = image.rotate(rotation, expand=True)
        if rotated_image.mode != "RGB": 
            rotated_image = rotated_image.convert("RGB")
        if rotated_image.size != (SCREEN_WIDTH, SCREEN_HEIGHT):
            full_img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
            x = (SCREEN_WIDTH - rotated_image.width) // 2
            y = (SCREEN_HEIGHT - rotated_image.height) // 2
            full_img.paste(rotated_image, (x, y))
            rotated_image = full_img
        arr = np.array(rotated_image, dtype=np.uint8)
        r = _gamma_r[arr[:, :, 0]].astype(np.uint16)
        g = _gamma_g[arr[:, :, 1]].astype(np.uint16)
        b = _gamma_b[arr[:, :, 2]].astype(np.uint16)
        rgb565 = (r << 11) | (g << 5) | b
        output = np.empty((SCREEN_HEIGHT, SCREEN_WIDTH, 2), dtype=np.uint8)
        output[:, :, 0] = rgb565 & 0xFF
        output[:, :, 1] = (rgb565 >> 8) & 0xFF
        with open(FRAMEBUFFER, "wb") as fb:
            fb.write(output.tobytes())
    except PermissionError:
        print(f"Permission denied for {FRAMEBUFFER} - falling back to ST7789")
        if HAS_ST7789:
            display_image_on_st7789(image)
        else:
            print("No display available")
    except Exception as e:
        print(f"Framebuffer error: {e}")

def find_touchscreen():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "ADS7846" in dev.name or "Touchscreen" in dev.name or "touch" in dev.name.lower(): 
            return dev
    print("Touchscreen not found - touch controls disabled")
    return None

def handle_touch():
    global START_SCREEN
    device = find_touchscreen()
    if device is None:
        while not exit_event.is_set():
            time.sleep(1)
        return
    screen_order = ["weather", "spotify", "time"]
    for event in device.read_loop():
        if exit_event.is_set():
            break
        if event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_TOUCH and event.value == 1:
            current_index = screen_order.index(START_SCREEN)
            START_SCREEN = screen_order[(current_index + 1) % len(screen_order)]
            update_display()

def handle_buttons():
    global START_SCREEN
    if not HAS_GPIO:
        print("GPIO not available - button controls disabled")
        while not exit_event.is_set():
            time.sleep(1)
        return
    GPIO.setmode(GPIO.BCM)
    buttons = [BUTTON_A, BUTTON_B, BUTTON_X, BUTTON_Y]
    for button in buttons:
        try:
            GPIO.setup(button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            if "busy" in str(e).lower():
                print(f"⚠️ GPIO {button} already in use, skipping button setup.")
                return
            else:
                raise
    print("Button handler started:")
    print("A: Switch screens, B: Switch screens, X: Reset art, Y: Toggle time")
    while not exit_event.is_set():
        for button in buttons:
            try:
                if GPIO.input(button) == GPIO.LOW:
                    current_time = time.time()
                    if current_time - button_last_press[button] > DEBOUNCE_TIME:
                        button_last_press[button] = current_time
                        if button == BUTTON_A:
                            START_SCREEN = "spotify"
                            update_display()
                        elif button == BUTTON_B:
                            START_SCREEN = "weather"
                            update_display()
                        elif button == BUTTON_X:
                            if START_SCREEN == "time":
                                update_display()
                        elif button == BUTTON_Y:
                            global TIME_DISPLAY
                            TIME_DISPLAY = not TIME_DISPLAY
                            update_display()
            except Exception:
                pass
        time.sleep(0.1)
    GPIO.cleanup()

def draw_waveshare_simple(weather_info, spotify_track):
    display_width = 250
    display_height = 122
    img = Image.new('1', (display_width, display_height), 255)
    draw = ImageDraw.Draw(img)
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        font_small = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_large = ImageFont.load_default()
    with scroll_lock:
        if not hasattr(draw_waveshare_simple, 'scroll_offset'):
            draw_waveshare_simple.scroll_offset = 0
        if spotify_track:
            title = spotify_track.get('title', 'No Track')
            artist = spotify_track.get('artists', 'Unknown Artist')
            spotify_text = f"{artist} - {title}"
            text_bbox = draw.textbbox((0, 0), spotify_text, font=font_medium)
            text_width = text_bbox[2] - text_bbox[0]
            if text_width > display_width - 10:
                draw_waveshare_simple.scroll_offset -= 4
                if draw_waveshare_simple.scroll_offset < -text_width:
                    draw_waveshare_simple.scroll_offset = display_width
                text_x = draw_waveshare_simple.scroll_offset
            else:
                text_x = (display_width - text_width) // 2
            draw.text((text_x, 5), spotify_text, font=font_medium, fill=0)
        else:
            draw.text((5, 5), "No music playing", font=font_medium, fill=0)
    if weather_info:
        temp_text = f"{weather_info['temp']}°C"
        draw.text((5, 35), temp_text, font=font_large, fill=0)
        city_text = weather_info['city'][:30]
        draw.text((5, 55), city_text, font=font_small, fill=0)
        desc_text = weather_info['description'][:20] 
        draw.text((5, 70), desc_text, font=font_small, fill=0)
        if "icon_id" in weather_info:
            try:
                icon_url = f"http://openweathermap.org/img/wn/{weather_info['icon_id']}.png"
                resp = requests.get(icon_url, timeout=5)
                resp.raise_for_status()
                icon_img = Image.open(BytesIO(resp.content)).convert("RGBA")
                icon_img = icon_img.resize((40, 40), Image.BILINEAR)
                icon_img_bw = icon_img.convert('1')
                img.paste(icon_img_bw, (display_width - 45, 30))
            except Exception as e:
                print(f"Weather icon error: {e}")
    now = datetime.datetime.now().strftime("%H:%M")
    time_bbox = draw.textbbox((0, 0), now, font=font_medium)
    time_width = time_bbox[2] - time_bbox[0]
    draw.text((display_width - time_width - 5, display_height - 20), now, font=font_medium, fill=0)
    return img

def init_waveshare_display():
    global waveshare_epd, waveshare_base_image, partial_refresh_count, HAS_WAVESHARE_EPD, epd2in13_V3, epdconfig
    try:
        if not HAS_WAVESHARE_EPD:
            from waveshare_epd import epd2in13_V3
            import waveshare_epd.epdconfig as epdconfig
            HAS_WAVESHARE_EPD = True
        waveshare_epd = epd2in13_V3.EPD()
        waveshare_epd.init()
        waveshare_epd.Clear(0xFF)
        waveshare_base_image = None
        partial_refresh_count = 0
        print("Waveshare e-paper display initialized")
        return waveshare_epd
    except Exception as e:
        print(f"Waveshare display init failed: {e}")
        return None

def display_image_on_waveshare(image):
    global waveshare_epd, waveshare_base_image, partial_refresh_count, epd2in13_V3, epdconfig
    with waveshare_lock:
        if waveshare_epd is None:
            if not init_waveshare_display():
                return
        try:
            if image.size != (250, 122):
                image = image.resize((250, 122), Image.BILINEAR)
            waveshare_epd.display(waveshare_epd.getbuffer(image))
            waveshare_base_image = image.copy()
            partial_refresh_count = 0
        except Exception as e:
            print(f"Waveshare display error: {e}")
            try:
                waveshare_epd.init()
                waveshare_epd.display(waveshare_epd.getbuffer(image))
                waveshare_base_image = image.copy()
                partial_refresh_count = 0
            except Exception as e2:
                print(f"Failed to reset waveshare display: {e2}")

def display_image_on_framebuffer(image):
    global last_display_time
    now = time.time()
    if now - last_display_time < MIN_DISPLAY_INTERVAL: 
        return
    last_display_time = now
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "st7789" and HAS_ST7789:
        display_image_on_st7789(image)
    elif display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
        display_image_on_waveshare(image)
    else:
        display_image_on_original_fb(image)

def update_display():
    global START_SCREEN
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
        img = draw_waveshare_simple(weather_info, spotify_track)
    else:
        if START_SCREEN == "weather":
            img = draw_weather_image(weather_info)
        elif START_SCREEN == "spotify":
            img = draw_spotify_image(spotify_track)
        elif START_SCREEN == "time":
            img = draw_clock_image()
        else:
            img = draw_clock_image()
    display_image_on_framebuffer(img)

def clear_framebuffer():
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "st7789" and HAS_ST7789 and st7789_display:
        black_img = Image.new("RGB", (320, 240), "black")
        st7789_display.display(black_img)
    elif display_type == "waveshare_epd" and HAS_WAVESHARE_EPD and waveshare_epd:
        white_img = Image.new('1', (250, 122), 255)
        waveshare_epd.display(waveshare_epd.getbuffer(white_img))
        waveshare_epd.sleep()
    else:
        with open(FRAMEBUFFER, "wb") as f:
            f.write(b'\x00\x00' * SCREEN_AREA)

def capture_frames_background():
    time.sleep(30)
    print("📸 Starting non-blocking frame capture...")
    output_dir = "capture_frames"
    os.makedirs(output_dir, exist_ok=True)
    display_type = config.get("display", {}).get("type", "framebuffer")
    for i in range(30):
        if display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
            img = draw_waveshare_simple(weather_info, spotify_track)
            img_rgb = img.convert("RGB")
        else:
            if START_SCREEN == "weather":
                img_rgb = draw_weather_image(weather_info)
            else:
                img_rgb = draw_spotify_image(spotify_track)
        path = os.path.join(output_dir, f"frame_{i:03d}.png")
        img_rgb.save(path)
        print(f"✅ Saved {path}")
        time.sleep(0.5)
    print("⏹️ Capture complete.")

def main():
    Thread(target=background_generation_worker, daemon=True).start()
    Thread(target=weather_loop, daemon=True).start()
    Thread(target=spotify_loop, daemon=True).start()
    Thread(target=handle_touch, daemon=True).start()
    Thread(target=handle_buttons, daemon=True).start()
    Thread(target=animate_images, daemon=True).start()
    Thread(target=animate_text_scroll, daemon=True).start()
    #Thread(target=capture_frames_background, daemon=True).start()
    update_display()
    try:
        while not exit_event.is_set():
            update_display()
    except KeyboardInterrupt:
        pass
    finally:
        exit_event.set()
        clear_framebuffer()

if __name__ == "__main__":
    main()