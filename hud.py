#!/usr/bin/env python3
import time, requests, json, evdev, spotipy, colorsys, datetime, os, subprocess, toml, random, sys, copy, math, queue, threading, signal, hashlib, functools, concurrent.futures, numpy as np
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageStat, ImageColor
from threading import Thread, Event, RLock
from spotipy.oauth2 import SpotifyOAuth
from functools import lru_cache
sys.stdout.reconfigure(line_buffering=True)

# ============== CONSTANTS ==============

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
UPDATE_INTERVAL_WEATHER = 3600
GEO_UPDATE_INTERVAL = 3600
SCOPE = "user-read-currently-playing user-modify-playback-state user-read-playback-state"
USE_GPSD = True
USE_GOOGLE_GEO = True
SCREEN_AREA = SCREEN_WIDTH * SCREEN_HEIGHT
BG_DIR = "./bg"
CLOCK_TYPE = "analog"
CLOCK_BACKGROUND = "color"
CLOCK_COLOR = "black"
INTERNET_CHECK_INTERVAL = 120
process_executor = None
frame_hash_cache = {}
frame_hash_cache_size = 50

DEFAULT_CONFIG = {
    "display": {
        "type": "dummy",
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
        "sleep_timeout": 300,
        "progressbar_display": True,
        "enable_current_track_display": True
    },
    "wifi": {
        "ap_ssid": "Neonwifi-Manager",
        "ap_ip": "192.168.42.1",
    },
    "auto_start": {
        "auto_start_hud": True,
        "auto_start_neonwifi": True,
        "check_internet": True
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
    },
    "ui": {
        "theme": "dark"
    }
}

# ============== GLOBAL VARIABLES ==============

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
file_write_lock = threading.Lock()
last_activity_time = time.time()
st7789_lock = threading.Lock()
display_sleeping = False
last_saved_album_art_hash = None
internet_available = True
last_internet_check = 0
last_frame_hash = None

# ============== ANIMATION FUNCTIONS ==============

def animate_images():
    global START_SCREEN
    last_animation_time = time.time()
    while not exit_event.is_set():
        if display_sleeping:
            time.sleep(0.5)
            continue
        current_time = time.time()
        frame_time = current_time - last_animation_time
        last_animation_time = current_time        
        needs_update = False
        album_moved = update_album_art_position(frame_time)
        artist_moved, toggled = update_artist_position(frame_time)
        needs_update = album_moved or artist_moved
        if toggled:
            needs_update = True
        if needs_update and START_SCREEN == "spotify":
            update_display()
        time.sleep(ANIMATION_FRAME_TIME)

def animate_text_scroll():
    while not exit_event.is_set():
        if display_sleeping:
            time.sleep(0.5)
            continue
        with scroll_lock:
            for key in scroll_state:
                state = scroll_state[key]
                if state["active"] and state["max_offset"] > 0:
                    state["offset"] += 2
                    if state["offset"] >= state["max_offset"]:
                        state["offset"] = 0
        time.sleep(TEXT_SCROLL_FRAME_TIME)

# ============== BACKGROUND GENERATION FUNCTIONS ==============

def background_generation_worker():
    global spotify_bg_cache, current_album_art_hash, clock_bg_image
    while not exit_event.is_set():
        try:
            album_img, size, bg_type = bg_generation_queue.get(timeout=5)
            if bg_type == "spotify":
                generated_bg = get_cached_background(size, album_img)
                with spotify_bg_cache_lock:
                    spotify_bg_cache = generated_bg.copy() if generated_bg else None
                    current_album_art_hash = id(album_img) if album_img else None
            elif bg_type == "clock":
                clock_bg_result = get_cached_background(size, album_img)
                with clock_bg_lock:
                    clock_bg_image = clock_bg_result.copy() if clock_bg_result else None
            bg_generation_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Background generation worker error: {e}")
            bg_generation_queue.task_done()

def create_fade_mask(art_size, fade_width):
    x_coords = np.arange(art_size)
    left_fade_mask = np.where(x_coords < fade_width,
                            255 * ((x_coords / fade_width) ** 0.7),
                            255).astype(np.uint8)
    right_fade_mask = np.where(x_coords > art_size - fade_width,
                            255 * (((art_size - x_coords) / fade_width) ** 0.7),
                            255).astype(np.uint8)
    combined_alpha = np.minimum(left_fade_mask, right_fade_mask)
    mask_array = np.tile(combined_alpha, (art_size, 1))
    return Image.fromarray(mask_array, mode='L')

def create_gradient_background(size):
    width, height = size
    bg = Image.new("RGB", size, (40, 40, 60))
    for y in range(height):
        factor = 0.7 + (y / height) * 0.6
        for x in range(width):
            r, g, b = bg.getpixel((x, y))
            bg.putpixel((x, y), (int(r * factor), int(g * factor), int(b * factor)))
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

def get_cached_background(size, album_art_img):
    global album_bg_cache
    if album_art_img is None:
        return Image.new("RGB", size, "black")
    img_hash = id(album_art_img)
    if img_hash in album_bg_cache:
        bg = album_bg_cache[img_hash]
        if bg.size == size:
            return bg.copy()
    bg = make_background_from_art(size, album_art_img)
    if len(album_bg_cache) >= 3:
        oldest_key = next(iter(album_bg_cache))
        del album_bg_cache[oldest_key]
    album_bg_cache[img_hash] = bg.copy()
    return bg

def make_background_from_art(size, album_art_img):
    return prepare_album_background(size, album_art_img)

def prepare_album_background(size, album_art_img):
    width, height = size
    if album_art_img is None:
        return create_gradient_background(size)
    if album_art_img.mode != "RGB":
        album_art_img = album_art_img.convert("RGB")
    small_for_color = album_art_img.resize((50, 50), Image.BILINEAR)
    pixels = list(small_for_color.getdata())
    r, g, b = calculate_avg_colors(pixels)
    avg_color = (int(r * 0.7), int(g * 0.7), int(b * 0.7))
    bg = Image.new("RGB", size, avg_color)
    art_size = height
    scaled_art = album_art_img.resize((art_size, art_size), Image.BILINEAR)
    blurred_art = scaled_art.filter(ImageFilter.GaussianBlur(2))
    enhancer = ImageEnhance.Brightness(blurred_art)
    blurred_art = enhancer.enhance(0.6)
    fade_width = min(80, art_size // 4)
    mask = create_fade_mask(art_size, fade_width)
    art_x = (width - art_size) // 2
    bg.paste(blurred_art, (art_x, 0), mask)
    return bg

def request_background_generation(album_img):
    global current_clock_artwork
    if album_img is not None:
        with clock_bg_lock:
            if current_clock_artwork is None or id(album_img) != id(current_clock_artwork):
                current_clock_artwork = album_img.copy()
        current_hash = id(album_img)
        if hasattr(request_background_generation, 'last_queued_hash'):
            if request_background_generation.last_queued_hash == current_hash:
                return
        request_background_generation.last_queued_hash = current_hash
        try:
            bg_generation_queue.put((album_img, (SCREEN_WIDTH, SCREEN_HEIGHT), "spotify"), block=False)
        except queue.Full:
            pass
        if CLOCK_BACKGROUND == "album":
            try:
                bg_generation_queue.put((album_img, (SCREEN_WIDTH, SCREEN_HEIGHT), "clock"), block=False)
            except queue.Full:
                pass
    else:
        with clock_bg_lock:
            current_clock_artwork = None

# ============== BUTTON AND TOUCH FUNCTIONS ==============

def find_touchscreen():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "ADS7846" in dev.name or "Touchscreen" in dev.name or "touch" in dev.name.lower(): 
            return dev
    print("Touchscreen not found - touch controls disabled")
    return None

def handle_buttons():
    global START_SCREEN, display_sleeping
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "waveshare_epd":
        print("Button controls disabled for Waveshare e-paper display")
        while not exit_event.is_set():
            time.sleep(1)
        return
    if not HAS_GPIO:
        print("GPIO not available - button controls disabled")
        while not exit_event.is_set():
            time.sleep(1)
        return
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    buttons = [BUTTON_A, BUTTON_B, BUTTON_X, BUTTON_Y]
    for button in buttons:
        try:
            GPIO.setup(button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            if "busy" in str(e).lower():
                print(f"GPIO {button} already in use, skipping button setup.")
                return
            else:
                raise
    print("Button handler started:")
    print("A: Switch to Clock, B: Switch to Weather, X: Switch to Spotify, Y: Toggle Display On/Off")
    while not exit_event.is_set():
        for button in buttons:
            try:
                if GPIO.input(button) == GPIO.LOW:
                    current_time = time.time()
                    if current_time - button_last_press[button] > DEBOUNCE_TIME:
                        button_last_press[button] = current_time
                        update_activity()
                        if button == BUTTON_A:
                            if START_SCREEN != "time":
                                START_SCREEN = "time"
                                update_display()
                        elif button == BUTTON_B:
                            if START_SCREEN != "weather":
                                START_SCREEN = "weather"
                                update_display()
                        elif button == BUTTON_X:
                            if START_SCREEN != "spotify":
                                START_SCREEN = "spotify"
                                update_display()
                        elif button == BUTTON_Y:
                            if display_sleeping:
                                wake_up_display()
                            else:
                                go_to_sleep()
            except Exception:
                pass
        time.sleep(0.1)
    GPIO.cleanup()

def handle_touch():
    global START_SCREEN
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "waveshare_epd":
        print("Touch controls disabled for Waveshare e-paper display")
        while not exit_event.is_set():
            time.sleep(1)
        return
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
            update_activity()
            update_display()

# ============== CACHE FUNCTIONS ==============

text_bbox_cache_local = {}

@lru_cache(maxsize=50)
def get_cached_bg(bg_path, size):
    return Image.open(bg_path).resize(size, Image.BILINEAR)

@lru_cache(maxsize=100)
def get_cached_text_bbox(text, font_path, font_size):
    font = ImageFont.truetype(font_path, font_size)
    return font.getbbox(text)

def get_cached_text_bbox_font(text, font):
    key = (text, getattr(font, "path", None), getattr(font, "size", None))
    if key not in text_bbox_cache_local:
        text_bbox_cache_local[key] = font.getbbox(text)
    return text_bbox_cache_local[key]

def cache_weather(lat, lon, data):
    weather_cache[f"{lat:.2f}_{lon:.2f}"] = (data, time.time())

def cleanup_caches():
    get_cached_bg.cache_clear()
    get_cached_text_bbox.cache_clear()
    if len(text_bbox_cache_local) > 50:
        text_bbox_cache_local.clear()
    if len(album_bg_cache) > 3:
        keys = list(album_bg_cache.keys())[-3:]
        keep = {k: album_bg_cache[k] for k in keys}
        album_bg_cache.clear()
        album_bg_cache.update(keep)
    if len(scrolling_text_cache) > 3:
        scrolling_text_cache.clear()

def get_cached_weather(lat, lon):
    cache_key = f"{lat:.2f}_{lon:.2f}"
    if cache_key in weather_cache:
        cached_data, timestamp = weather_cache[cache_key]
        if time.time() - timestamp < 300:
            return cached_data
    return None

# ============== CLOCK FUNCTIONS ==============

def draw_analog_clock(img, palette):
    face_color, notch_color, hour_color, minute_color, second_color = palette
    draw = ImageDraw.Draw(img)
    now = datetime.datetime.now()
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

def draw_clock_image():
    img, avg_color = get_clock_background()
    palette = generate_clock_palette(avg_color)
    if CLOCK_TYPE == "analog":
        draw_analog_clock(img, palette)
    else:
        draw_digital_clock(img, palette)
    return img

def draw_digital_clock(img, palette):
    face_color, notch_color, hour_color, minute_color, second_color = palette
    draw = ImageDraw.Draw(img)
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%A, %B %d, %Y")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    time_bbox = get_cached_text_bbox_font(time_str, LARGE_FONT)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    time_x = (SCREEN_WIDTH - time_width) // 2
    time_y = (SCREEN_HEIGHT - time_height) // 2 - 30
    date_bbox = get_cached_text_bbox_font(date_str, MEDIUM_FONT)
    date_width = date_bbox[2] - date_bbox[0]
    date_x = (SCREEN_WIDTH - date_width) // 2
    date_y = time_y + time_height + 20
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw_text_aliased(draw, img, (time_x, time_y), time_str, LARGE_FONT, face_color)
    draw_text_aliased(draw, img, (date_x, date_y), date_str, MEDIUM_FONT, notch_color)

def generate_clock_palette(avg_color):
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
    return palette

def get_clock_background():
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
    return img, avg_color

# ============== COLOR FUNCTIONS ==============

def calculate_avg_colors(pixels):
    avg_r = sum(p[0] for p in pixels) // len(pixels)
    avg_g = sum(p[1] for p in pixels) // len(pixels)
    avg_b = sum(p[2] for p in pixels) // len(pixels)
    return avg_r, avg_g, avg_b

def generate_color_palette(avg_h, avg_s, avg_v, n=2):
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

def get_contrasting_colors(img, n=2):
    if img.mode != "RGB": img = img.convert("RGB")
    small_img = img.resize((50, 50), Image.BILINEAR)
    pixels = list(small_img.getdata())
    avg_r, avg_g, avg_b = calculate_avg_colors(pixels)
    avg_h, avg_s, avg_v = colorsys.rgb_to_hsv(avg_r/255, avg_g/255, avg_b/255)
    return generate_color_palette(avg_h, avg_s, avg_v, n)

# ============== CONFIGURATION FUNCTIONS ==============

def init_process_executor():
    global process_executor
    process_executor = concurrent.futures.ProcessPoolExecutor(max_workers=2)

def load_config(path="config.toml"):
    if not os.path.exists(path):
        with open(path, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return load_config_defaults()
    try:
        with open(path, 'r') as f:
            loaded_config = toml.load(f)
        merged_config = merge_configs(DEFAULT_CONFIG, loaded_config)
        with open(path, 'w') as f:
            toml.dump(merged_config, f)
        return merged_config
    except Exception as e:
        print(f"Error loading config: {e}, using defaults")
        with open(path, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return load_config_defaults()

def load_config_defaults():
    return DEFAULT_CONFIG.copy()

def merge_configs(default_config, loaded_config):
    merged_config = copy.deepcopy(default_config)
    for category in loaded_config:
        if category in merged_config:
            if isinstance(merged_config[category], dict) and isinstance(loaded_config[category], dict):
                for key in loaded_config[category]:
                    merged_config[category][key] = loaded_config[category][key]
            else:
                merged_config[category] = loaded_config[category]
        else:
            merged_config[category] = loaded_config[category]
    return merged_config

# ============== DISPLAY FUNCTIONS ==============

def clear_waveshare_display():
    global waveshare_epd
    if not HAS_WAVESHARE_EPD or waveshare_epd is None:
        return
    
    try:
        waveshare_epd.init()
        white_img = Image.new('1', (250, 122), 255)
        waveshare_epd.display(waveshare_epd.getbuffer(white_img))
        waveshare_epd.sleep()
    except Exception as e:
        print(f"Failed to clear waveshare display: {e}")
        try:
            waveshare_epd.init()
            waveshare_epd.Clear(0xFF)
            waveshare_epd.sleep()
        except Exception as e2:
            print(f"Failed to reset waveshare display: {e2}")

def clear_framebuffer():
    global HAS_ST7789
    display_type = config.get("display", {}).get("type", "framebuffer")
    
    if display_type == "dummy":
        return
    elif display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
        clear_waveshare_display()
        return
    elif display_type == "st7789" and HAS_ST7789 and st7789_display:
        black_img = Image.new("RGB", (320, 240), "black")
        st7789_display.display(black_img)
    else:
        try:
            black_image = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
            display_image_on_original_fb(black_image)
            try:
                with open(FRAMEBUFFER, "wb") as f:
                    black_pixel = b'\x00\x00'
                    f.write(black_pixel * SCREEN_WIDTH * SCREEN_HEIGHT)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                print(f"Direct framebuffer write failed: {e}")
        except Exception as e:
            print(f"Error clearing framebuffer: {e}")
            if HAS_ST7789:
                try:
                    black_img = Image.new("RGB", (320, 240), "black")
                    display_image_on_st7789(black_img)
                except:
                    pass

def compute_frame_hash(image):
    if image.mode != "RGB":
        image = image.convert("RGB")
    small = image.resize((16, 16), Image.BILINEAR)
    data = np.array(small).tobytes()
    return hashlib.md5(data).hexdigest()

def convert_to_1bit_dithered(album_art_img, size=(40, 40)):
    if album_art_img is None:
        return None
    small_img = album_art_img.resize(size, Image.BILINEAR)
    gray_img = small_img.convert('L')
    bw_img = gray_img.convert('1')
    return bw_img

def convert_to_rgb565(image):
    arr = np.array(image, dtype=np.uint8)
    r = _gamma_r[arr[:, :, 0]].astype(np.uint16)
    g = _gamma_g[arr[:, :, 1]].astype(np.uint16)
    b = _gamma_b[arr[:, :, 2]].astype(np.uint16)
    rgb565 = (r << 11) | (g << 5) | b
    output = np.empty((SCREEN_HEIGHT, SCREEN_WIDTH, 2), dtype=np.uint8)
    output[:, :, 0] = rgb565 & 0xFF
    output[:, :, 1] = (rgb565 >> 8) & 0xFF
    return output

def display_image_on_dummy():
    pass

def display_image_on_waveshare(image):
    global waveshare_epd, waveshare_base_image, partial_refresh_count
    with waveshare_lock:
        if waveshare_epd is None:
            if not init_waveshare_display():
                return
        try:
            display_width = 250
            display_height = 122
            if image.size != (display_width, display_height):
                image = image.resize((display_width, display_height), Image.BILINEAR)
            if image.mode != '1':
                image = image.convert('1')
            content_changed = getattr(image, 'content_changed', True)
            if content_changed or partial_refresh_count >= 300:
                waveshare_epd.display(waveshare_epd.getbuffer(image))
                waveshare_base_image = image.copy()
                partial_refresh_count = 0
            else:
                waveshare_epd.displayPartial(waveshare_epd.getbuffer(image))
                partial_refresh_count += 1
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
    frame_hash = compute_frame_hash(image)
    if not should_display_frame(frame_hash):
        return
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "dummy":
        display_image_on_dummy()
    elif display_type == "st7789" and HAS_ST7789:
        display_image_on_st7789(image)
    elif display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
        display_image_on_waveshare(image)
    else:
        display_image_on_original_fb(image)

def display_image_on_original_fb(image):
    try:
        rotated_image = prepare_framebuffer_image(image)
        output = convert_to_rgb565(rotated_image)
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

def display_image_on_st7789(image):
    global st7789_display
    try:
        if st7789_display is None:
            st7789_display = init_st7789_display()
            if st7789_display is None: 
                return
        scaled_image = image.resize((320, 240), Image.BILINEAR)
        if scaled_image.mode != "RGB": 
            scaled_image = scaled_image.convert("RGB")
        with st7789_lock:
            st7789_display.display(scaled_image)
    except Exception as e:
        print(f"ST7789 display error: {e}")
        try:
            st7789_display = init_st7789_display()
        except:
            st7789_display = None

def draw_waveshare(weather_info, spotify_track):
    global waveshare_base_image, partial_refresh_count
    display_width = 250
    display_height = 122
    img = Image.new('1', (display_width, display_height), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, display_width-1, display_height-1], outline=0, width=2)
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except:
        font_small = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_large = ImageFont.load_default()
    content_changed = False
    current_track_id = None
    if spotify_track:
        current_track_id = f"{spotify_track.get('title', '')}_{spotify_track.get('artists', '')}"
    current_weather_id = None
    if weather_info:
        current_weather_id = f"{weather_info.get('city', '')}_{weather_info.get('temp', '')}_{weather_info.get('description', '')}"
    if not hasattr(draw_waveshare, 'last_track_id'):
        draw_waveshare.last_track_id = None
        draw_waveshare.last_weather_id = None
        content_changed = True
    if current_track_id != draw_waveshare.last_track_id:
        content_changed = True
        draw_waveshare.last_track_id = current_track_id
    if current_weather_id != draw_waveshare.last_weather_id:
        content_changed = True
        draw_waveshare.last_weather_id = current_weather_id
    album_art_size = 60
    album_art_x = display_width - album_art_size - 3
    album_art_y = display_height - album_art_size - 20
    if spotify_track:
        artist = spotify_track.get('artists', 'Unknown Artist')
        title = spotify_track.get('title', 'No Track')
        with scroll_lock:
            if not hasattr(draw_waveshare, 'title_scroll_offset'):
                draw_waveshare.title_scroll_offset = 0
                draw_waveshare.artist_scroll_offset = 0
            title_bbox = draw.textbbox((0, 0), title, font=font_medium)
            title_width = title_bbox[2] - title_bbox[0]
            scroll_speed = 4
            if title_width > display_width - 20:
                total_scroll_distance = title_width + 15
                draw_waveshare.title_scroll_offset = (draw_waveshare.title_scroll_offset + scroll_speed) % total_scroll_distance
                title_x = -draw_waveshare.title_scroll_offset
                draw.text((title_x, 8), title, font=font_medium, fill=0)
                draw.text((title_x + total_scroll_distance, 8), title, font=font_medium, fill=0)
            else:
                title_x = (display_width - title_width) // 2
                draw.text((title_x, 8), title, font=font_medium, fill=0)
            artist_bbox = draw.textbbox((0, 0), artist, font=font_medium)
            artist_width = artist_bbox[2] - artist_bbox[0]
            if artist_width > display_width - 20:
                total_scroll_distance = artist_width + 20
                draw_waveshare.artist_scroll_offset = (draw_waveshare.artist_scroll_offset + scroll_speed) % total_scroll_distance
                artist_x = -draw_waveshare.artist_scroll_offset
                draw.text((artist_x, 25), artist, font=font_medium, fill=0)
                draw.text((artist_x + total_scroll_distance, 25), artist, font=font_medium, fill=0)
            else:
                artist_x = (display_width - artist_width) // 2
                draw.text((artist_x, 25), artist, font=font_medium, fill=0)
        with art_lock:
            album_img = album_art_image
        if album_img is not None:
            bw_album_art = convert_to_1bit_dithered(album_img, (album_art_size, album_art_size))
            img.paste(bw_album_art, (album_art_x, album_art_y))
    else:
        if hasattr(draw_waveshare, 'title_scroll_offset'):
            draw_waveshare.title_scroll_offset = 0
            draw_waveshare.artist_scroll_offset = 0
        draw.text((5, 8), "No music playing", font=font_medium, fill=0)
    if weather_info:
        weather_icon_x = 8
        weather_icon_y = display_height - 55
        if weather_info and "cached_icon" in weather_info and weather_info["cached_icon"] is not None:
            try:
                img.paste(weather_info["cached_icon"], (weather_icon_x, weather_icon_y))
            except Exception as e:
                print(f"Error pasting cached weather icon: {e}")
        temp_text = f"{weather_info['temp']}°C"
        draw.text((45, display_height - 55), temp_text, font=font_large, fill=0)
        feels_like_text = f"Feels: {weather_info['feels_like']}°C"
        draw.text((45, display_height - 35), feels_like_text, font=font_small, fill=0)
        desc_text = weather_info['description'][:15]
        draw.text((45, display_height - 20), desc_text, font=font_small, fill=0)
    now = datetime.datetime.now().strftime("%H:%M")
    time_bbox = draw.textbbox((0, 0), now, font=font_medium)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    clock_x = display_width - time_width - 5
    clock_y = display_height - time_height - 8
    draw.text((clock_x, clock_y), now, font=font_medium, fill=0)
    img.content_changed = content_changed
    return img

def draw_text_aliased(draw, image, position, text, font, fill):
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(position, text, fill=255, font=font)
    color_layer = Image.new("RGB", image.size, fill)
    image.paste(color_layer, (0, 0), mask)

def draw_text_with_background(img, text_elements):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for text, position, font, color in text_elements:
        bbox = get_cached_text_bbox_font(text, font)
        actual_bbox = (position[0] + bbox[0], position[1] + bbox[1], position[0] + bbox[2], position[1] + bbox[3])
        overlay_draw.rectangle([actual_bbox[0]-5, actual_bbox[1]-5, actual_bbox[2]+5, actual_bbox[3]+5], fill=(0, 0, 0, 200))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    for text, position, font, color in text_elements:
        draw_text_aliased(draw, img, position, text, font, color)
    return img, draw

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
        print(f"ST7789 display initialized with rotation: {config_rotation}")
        return st7789_display
    except Exception as e:
        print(f"ST7789 init failed: {e}")
        return None

def init_waveshare_display():
    global waveshare_epd, waveshare_base_image, partial_refresh_count
    if not HAS_WAVESHARE_EPD:
        return None
    try:
        print("Attempting to initialize Waveshare display...")
        waveshare_epd = EPD()
        print("Initializing display...")
        waveshare_epd.init()
        waveshare_epd.Clear(0xFF)
        waveshare_base_image = Image.new('1', (250, 122), 255)
        partial_refresh_count = 0
        print("Waveshare e-paper display initialized successfully")
        return waveshare_epd
    except Exception as e:
        print(f"Waveshare display init failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def prepare_framebuffer_image(image):
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
    return rotated_image

def should_display_frame(image_hash):
    global last_frame_hash
    if image_hash == last_frame_hash:
        return False
    last_frame_hash = image_hash
    return True

def update_display():
    global START_SCREEN
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "waveshare_epd" and HAS_WAVESHARE_EPD:
        img = draw_waveshare(weather_info, spotify_track)
    else:
        if START_SCREEN == "weather":
            img = draw_weather_image(weather_info)
        elif START_SCREEN == "spotify":
            if display_sleeping:
                return
            img = draw_spotify_image(spotify_track)
        elif START_SCREEN == "time":
            img = draw_clock_image()
        else:
            img = draw_clock_image()
    display_image_on_framebuffer(img)

# ============== DRAWING FUNCTIONS ==============

def create_scrolling_text_image(text, font, color, total_width):
    img = Image.new("RGBA", (total_width, font.size + 10), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.text((0, 5), text, font=font, fill=color)
    draw.text((total_width // 2, 5), text, font=font, fill=color)
    return img

def create_weather_text_elements(weather_info):
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
    return text_elements

def draw_error_screen(img, error_text):
    bbox = get_cached_text_bbox_font(error_text, MEDIUM_FONT)
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
    return img, draw

def draw_no_track_image():
    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
    if os.path.exists(os.path.join(BG_DIR, "no_track.png")):
        bg_path = os.path.join(BG_DIR, "no_track.png")
        bg_img = get_cached_bg(bg_path, (SCREEN_WIDTH, SCREEN_HEIGHT))
        img.paste(bg_img, (0, 0))
    error_text = "No track playing"
    bbox = get_cached_text_bbox_font(error_text, MEDIUM_FONT)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([5, 5, min(bbox[2]+11, SCREEN_WIDTH-5), bbox[3]+9], fill=(0,0,0,200))
    draw.text((11, 9), error_text, fill="red", font=MEDIUM_FONT)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img

def draw_progress_bar(spotify_track, secondary_color, main_color):
    progress_bar_height = 10
    border_width = 2
    progress_bar_y = SCREEN_HEIGHT - progress_bar_height
    time_y_offset = progress_bar_height + border_width + 1
    overlay = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
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
    return overlay, time_y_offset

def draw_spotify_image(spotify_track):
    if display_sleeping:
        return Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
    art_img, artist_img = prepare_album_and_artist_images()
    bg_to_use = None
    with spotify_bg_cache_lock:
        if spotify_bg_cache is not None and art_img is not None and current_album_art_hash == id(art_img):
            bg_to_use = spotify_bg_cache.copy()
    if bg_to_use is None:
        bg_to_use = get_cached_background((SCREEN_WIDTH, SCREEN_HEIGHT), art_img)
    img = bg_to_use
    main_color, secondary_color = get_spotify_colors(spotify_track, art_img)
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
        img.paste(album_img_to_draw, int_pos)
    if artist_img:
        int_artist_pos = (int(artist_pos[0]), int(artist_pos[1]))
        if artist_img.mode != "RGB":
            bg = Image.new("RGB", artist_img.size, "black")
            if artist_img.mode in ("RGBA", "LA"):
                bg.paste(artist_img, mask=artist_img.split()[-1])
            else:
                bg.paste(artist_img)
            artist_img_to_draw = bg
        else:
            artist_img_to_draw = artist_img
        img.paste(artist_img_to_draw, int_artist_pos)
    overlay = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 0))
    layout = spotify_layout_cache
    if layout:
        overlay = draw_spotify_layout(overlay, layout, spotify_track, main_color, secondary_color)
    else:
        return draw_no_track_image()
    if PROGRESSBAR_DISPLAY:
        progress_overlay, time_y_offset = draw_progress_bar(spotify_track, secondary_color, main_color)
        overlay = Image.alpha_composite(overlay, progress_overlay)
        if spotify_track and 'current_position' in spotify_track and 'duration' in spotify_track:
            current_mins = spotify_track['current_position'] // 60
            current_secs = spotify_track['current_position'] % 60
            total_mins = spotify_track['duration'] // 60
            total_secs = spotify_track['duration'] % 60
            time_text = f"{current_mins}:{current_secs:02d} / {total_mins}:{total_secs:02d}"
            time_bbox = SPOT_MEDIUM_FONT.getbbox(time_text)
            time_width = time_bbox[2] - time_bbox[0]
            time_height = time_bbox[3] - time_bbox[1]
            padding = 4
            box_height = time_height + (padding * 2)
            time_x = 10
            box_y = SCREEN_HEIGHT - box_height - 15
            text_y = box_y + padding - time_bbox[1]
            time_overlay_img = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 0))
            time_draw = ImageDraw.Draw(time_overlay_img)
            time_draw.rectangle([time_x - padding, box_y, time_x + time_width + padding, box_y + box_height], fill=(0, 0, 0, 200))
            time_draw.text((time_x, text_y), time_text, fill=secondary_color, font=SPOT_MEDIUM_FONT)
            overlay = Image.alpha_composite(overlay, time_overlay_img)
    else:
        time_y_offset = 0
    if TIME_DISPLAY:
        now = datetime.datetime.now().strftime("%H:%M")
        time_bbox = SPOT_LARGE_FONT.getbbox(now)
        time_width = time_bbox[2] - time_bbox[0]
        time_x = SCREEN_WIDTH - time_width - 15
        time_y = SCREEN_HEIGHT - 30 - time_y_offset
        time_overlay = draw_time_text(now, SPOT_LARGE_FONT, main_color, time_x, time_y)
        overlay = Image.alpha_composite(overlay, time_overlay)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img

def draw_spotify_layout(overlay, layout, spotify_track, main_color, secondary_color):
    draw = ImageDraw.Draw(overlay)
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
    return overlay

def draw_time_overlay(img, time_str, font):
    time_bbox = get_cached_text_bbox_font(time_str, font)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    x = SCREEN_WIDTH - time_width - 10
    y = SCREEN_HEIGHT - time_height - 10
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([x-5, y-5, x + time_width + 5, y + time_height + 5], fill=(0, 0, 0,200))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw_text_aliased(draw, img, (x, y), time_str, font, "gray")
    return img

def draw_time_text(time_str, font, color, position_x, position_y):
    time_bbox = font.getbbox(time_str)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    padding = 5
    background_width = time_width + 2 * padding
    background_height = time_height + 2 * padding
    overlay = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([position_x, position_y, position_x + background_width, position_y + background_height], fill=(0, 0, 0, 200))
    text_x = position_x + padding
    text_y = position_y + padding - time_bbox[1]
    draw.text((text_x, text_y), time_str, fill=color, font=font)
    return overlay

def draw_waveshare_album_art(img, album_art_img, album_art_x, album_art_y, album_art_size):
    if album_art_img is not None:
        bw_album_art = convert_to_1bit_dithered(album_art_img, (album_art_size, album_art_size))
        img.paste(bw_album_art, (album_art_x, album_art_y))

def draw_waveshare_border(draw, display_width, display_height):
    draw.rectangle([0, 0, display_width-1, display_height-1], outline=0, width=2)

def draw_waveshare_time(draw, font_medium, display_width, display_height):
    now = datetime.datetime.now().strftime("%H:%M")
    time_bbox = draw.textbbox((0, 0), now, font=font_medium)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    clock_x = display_width - time_width - 5
    clock_y = display_height - time_height - 8
    draw.text((clock_x, clock_y), now, font=font_medium, fill=0)

def draw_waveshare_track_info(draw, spotify_track, font_medium, display_width, display_height):
    if not spotify_track:
        if hasattr(draw_waveshare_track_info, 'title_scroll_offset'):
            draw_waveshare_track_info.title_scroll_offset = 0
            draw_waveshare_track_info.artist_scroll_offset = 0
        draw.text((5, 8), "No music playing", font=font_medium, fill=0)
        return
    artist = spotify_track.get('artists', 'Unknown Artist')
    title = spotify_track.get('title', 'No Track')
    with scroll_lock:
        if not hasattr(draw_waveshare_track_info, 'title_scroll_offset'):
            draw_waveshare_track_info.title_scroll_offset = 0
            draw_waveshare_track_info.artist_scroll_offset = 0
        title_bbox = draw.textbbox((0, 0), title, font=font_medium)
        title_width = title_bbox[2] - title_bbox[0]
        scroll_speed = 4
        if title_width > display_width - 20:
            total_scroll_distance = title_width + 15
            draw_waveshare_track_info.title_scroll_offset = (draw_waveshare_track_info.title_scroll_offset + scroll_speed) % total_scroll_distance
            title_x = -draw_waveshare_track_info.title_scroll_offset
            draw.text((title_x, 8), title, font=font_medium, fill=0)
            draw.text((title_x + total_scroll_distance, 8), title, font=font_medium, fill=0)
        else:
            title_x = (display_width - title_width) // 2
            draw.text((title_x, 8), title, font=font_medium, fill=0)
        artist_bbox = draw.textbbox((0, 0), artist, font=font_medium)
        artist_width = artist_bbox[2] - artist_bbox[0]
        if artist_width > display_width - 20:
            total_scroll_distance = artist_width + 20
            draw_waveshare_track_info.artist_scroll_offset = (draw_waveshare_track_info.artist_scroll_offset + scroll_speed) % total_scroll_distance
            artist_x = -draw_waveshare_track_info.artist_scroll_offset
            draw.text((artist_x, 25), artist, font=font_medium, fill=0)
            draw.text((artist_x + total_scroll_distance, 25), artist, font=font_medium, fill=0)
        else:
            artist_x = (display_width - artist_width) // 2
            draw.text((artist_x, 25), artist, font=font_medium, fill=0)

def draw_waveshare_weather_info(draw, weather_info, font_small, font_large, display_height):
    if not weather_info:
        return
    weather_icon_x = 8
    weather_icon_y = display_height - 55
    if "cached_icon" in weather_info and weather_info["cached_icon"] is not None:
        try:
            img.paste(weather_info["cached_icon"], (weather_icon_x, weather_icon_y))
        except Exception as e:
            print(f"Error pasting cached weather icon: {e}")
    temp_text = f"{weather_info['temp']}°C"
    draw.text((45, display_height - 55), temp_text, font=font_large, fill=0)
    feels_like_text = f"Feels: {weather_info['feels_like']}°C"
    draw.text((45, display_height - 35), feels_like_text, font=font_small, fill=0)
    desc_text = weather_info['description'][:15]
    draw.text((45, display_height - 20), desc_text, font=font_small, fill=0)

def draw_weather_icon(img, weather_info):
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
    return img

def draw_weather_image(weather_info):
    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "black")
    bg_filename = get_background_path(weather_info)
    if bg_filename:
        bg_path = os.path.join(BG_DIR, bg_filename)
        bg_img = get_cached_bg(bg_path, (SCREEN_WIDTH, SCREEN_HEIGHT))
        img.paste(bg_img, (0, 0))
    if weather_info:
        text_elements = create_weather_text_elements(weather_info)
        img, draw = draw_text_with_background(img, text_elements)
        img = draw_weather_icon(img, weather_info)
        if TIME_DISPLAY:
            now = datetime.datetime.now().strftime("%H:%M")
            img = draw_time_overlay(img, now, MEDIUM_FONT)
    else:
        error_text = "Failed to fetch weather data."
        img, draw = draw_error_screen(img, error_text)
        if TIME_DISPLAY:
            now = datetime.datetime.now().strftime("%H:%M")
            img = draw_time_overlay(img, now, MEDIUM_FONT)
    return img

# ============== IMAGE POSITION FUNCTIONS ==============

def update_album_art_position(frame_time):
    global art_pos, art_velocity
    with art_lock:
        album_img = album_art_image
    if album_img is not None:
        w, h = album_img.size
        x, y = art_pos
        dx, dy = art_velocity
        new_x = x + (dx * frame_time * 60 * 0.4 * 0.8)
        new_y = y + (dy * frame_time * 60 * 0.4 * 0.8)
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
        return True
    return False

def update_artist_position(frame_time):
    global artist_pos, artist_velocity, artist_on_top
    with artist_image_lock:
        artist_img = artist_image
    if artist_img is not None:
        w, h = artist_img.size
        x, y = artist_pos
        dx, dy = artist_velocity
        new_x = x + (dx * frame_time * 60 * 0.4 * 0.8)
        new_y = y + (dy * frame_time * 60 * 0.4 * 0.8)
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
            return True, True
        return True, False
    return False, False

def wake_up_display():
    global display_sleeping
    if display_sleeping:
        display_sleeping = False
        update_activity()
        update_display()

# ============== INTERNET FUNCTIONS ==============

def check_internet_connection(timeout=5):
    try:
        response = requests.get("http://www.google.com", timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=timeout)
            return True
        except:
            return False

def update_internet_status():
    global internet_available, last_internet_check
    current_time = time.time()
    if current_time - last_internet_check > INTERNET_CHECK_INTERVAL:
        internet_available = check_internet_connection(timeout=3)
        last_internet_check = current_time
    return internet_available

# ============== LOCATION FUNCTIONS ==============

def get_initial_location():
    lat, lon = None, None
    if USE_GPSD: lat, lon = get_location_via_gpsd(timeout=2)
    if (lat is None or lon is None) and USE_GOOGLE_GEO: lat, lon = get_location_via_google_geolocation(GOOGLE_GEO_API_KEY)
    if lat is None or lon is None:
        lat, lon = get_location_via_openweathermap_geocoding(OPENWEATHER_API_KEY, FALLBACK_CITY)
        if lat is None or lon is None: return None, None
    return lat, lon

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
    if not update_internet_status():
        return None, None
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

# ============== LOOP FUNCTIONS ==============

def sleep_monitor_loop():
    last_sleep_check = 0
    while not exit_event.is_set():
        current_time = time.time()
        if display_sleeping:
            if current_time - last_sleep_check >= WAKEUP_CHECK_INTERVAL:
                check_sleep_state()
                last_sleep_check = current_time
            time.sleep(1)
        else:
            check_sleep_state()
            last_sleep_check = current_time
            time.sleep(5)

def spotify_loop():
    global START_SCREEN, spotify_track, sp, album_art_image, scrolling_text_cache, last_art_url, last_api_call, consecutive_no_track_count
    last_successful_write = 0
    write_interval = 0.5
    last_api_call = 0
    last_art_url = None
    consecutive_no_track_count = 0
    max_consecutive_no_track = 15
    previous_track_id = None
    load_previous_track_state()
    is_first_track_after_startup = True
    if not initialize_spotify_client_or_auth():
        return
    last_track_id = None
    api_error_count = 0
    while not exit_event.is_set():
        current_time = time.time()
        current_check_interval = calculate_check_interval(api_error_count, spotify_track, consecutive_no_track_count, max_consecutive_no_track)
        time_since_last_api = current_time - last_api_call
        if time_since_last_api < current_check_interval:
            time.sleep(0.5)
            continue
        try:
            last_api_call = current_time
            track = sp.current_playback()
            api_error_count = 0
            if not track or not track.get('item'):
                last_successful_write = handle_no_track_playing(current_time, last_successful_write, write_interval)
                continue
            last_successful_write, last_track_id, is_first_track_after_startup = handle_track_update(current_time, last_successful_write, write_interval, track, last_track_id, is_first_track_after_startup, previous_track_id)
        except spotipy.exceptions.SpotifyException as e:
            api_error_count += 1
            if not handle_spotify_api_errors(e, api_error_count):
                return
        except requests.exceptions.Timeout:
            api_error_count += 1
            print(f"Spotify API timeout (attempt {api_error_count}), will retry with backoff")
            last_api_call = time.time()
        except requests.exceptions.ConnectionError as e:
            api_error_count += 1
            if api_error_count >= 3:
                if "Connection reset" in str(e) or "Connection aborted" in str(e):
                    print(f"Connection reset during token refresh (attempt {api_error_count}), retrying...")
                else:
                    print(f"Spotify connection error (attempt {api_error_count}): {e}")
            if "Connection reset" in str(e) or "Connection aborted" in str(e):
                time.sleep(2)
            last_api_call = time.time()
        except Exception as e:
            api_error_count += 1
            print(f"Unexpected Spotify error (attempt {api_error_count}): {e}")
            last_api_call = time.time()

def weather_loop():
    global START_SCREEN, weather_info
    lat, lon = get_initial_location()
    if lat is None or lon is None: return
    last_geo = time.time()
    last_weather = 0
    last_display_update = 0
    last_cache_cleanup = time.time()
    GEO_UPDATE_INTERVAL = 900
    while not exit_event.is_set():
        now = time.time()
        if now - last_cache_cleanup > 600:
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
            if new_weather is not None: 
                weather_info = new_weather
                write_weather_state(weather_info)
                weather_info = update_weather_icon(weather_info)
            last_weather = now
        if START_SCREEN == "weather" and now - last_display_update >= 1:
            update_display()
            last_display_update = now
        time.sleep(2)

# ============== CLEANUP FUNCTIONS ==============

def cleanup_album_art():
    try:
        if os.path.exists('static/current_album_art.jpg'):
            os.remove('static/current_album_art.jpg')
    except Exception as e:
        print(f"Error cleaning up album art: {e}")

def cleanup_scroll_state():
    with scroll_lock:
        for key in scroll_state:
            scroll_state[key]["offset"] = 0
            scroll_state[key]["active"] = False

def signal_handler(sig, frame):
    print(f"Received signal {sig}, shutting down quickly...")
    exit_event.set()

def go_to_sleep():
    global display_sleeping, last_display_time
    if not display_sleeping:
        display_sleeping = True
        try:
            if display_type == "st7789" and HAS_ST7789 and st7789_display:
                black_img = Image.new("RGB", (320, 240), "black")
                with st7789_lock:
                    st7789_display.display(black_img)
            time.sleep(0.05)
        except:
            pass
        last_display_time = 0
        clear_framebuffer()

# ============== PREPARE FUNCTIONS ==============

def prepare_album_and_artist_images():
    with art_lock:
        art_img = album_art_image
    with artist_image_lock:
        art_img_artist = artist_image
    return art_img, art_img_artist

def prepare_track_data(track):
    item = track['item']
    artists_list = [artist['name'] for artist in item.get('artists', [])]
    artist_str = ", ".join(artists_list) if artists_list else "Unknown Artist"
    album_str = item['album']['name'] if item.get('album') else "Unknown Album"
    current_position = track.get('progress_ms', 0) // 1000
    duration = item.get('duration_ms', 0) // 1000
    is_playing = track.get('is_playing', False)
    shuffle_state = track.get('shuffle_state', False)
    device = track.get('device', {})
    volume_percent = device.get('volume_percent', 50) if device else 50
    device_name = device.get('name', '') if device else ''
    device_active = device is not None
    return {
        "title": item.get('name', "Unknown Track"),
        "artists": artist_str,
        "album": album_str,
        "current_position": current_position,
        "duration": duration,
        "is_playing": is_playing,
        "shuffle_state": shuffle_state,
        "volume_percent": volume_percent,
        "device_name": device_name,
        "device_active": device_active
    }

def prepare_track_state_data(track_data):
    if track_data:
        return {
            'current_track': {
                'title': track_data.get('title', 'Unknown Track') or "Unknown Track",
                'artists': track_data.get('artists', 'Unknown Artist') or "Unknown Artist",
                'album': track_data.get('album', 'Unknown Album') or "Unknown Album",
                'current_position': int(track_data.get('current_position', 0)),
                'duration': int(track_data.get('duration', 0)),
                'is_playing': bool(track_data.get('is_playing', False)),
                'timestamp': time.time(),
                'shuffle_state': bool(track_data.get('shuffle_state', False)),
                'volume_percent': int(track_data.get('volume_percent', 50)),
                'device_name': track_data.get('device_name', ''),
                'device_active': bool(track_data.get('device_active', False))
            }
        }
    else:
        return {
            'current_track': {
                'title': 'No track playing',
                'artists': '',
                'album': '',
                'current_position': 0,
                'duration': 0,
                'is_playing': False,
                'timestamp': time.time(),
                'shuffle_state': False,
                'volume_percent': 50,
                'device_name': '',
                'device_active': False
            }
        }

def prepare_weather_response_data(data):
    return {
        "city": data["name"],
        "country": data["sys"]["country"],
        "temp": round(data["main"]["temp"]),
        "feels_like": round(data["main"]["feels_like"]),
        "description": data["weather"][0]["description"].title(),
        "humidity": data["main"]["humidity"],
        "pressure": data["main"]["pressure"],
        "wind_speed": round(data["wind"]["speed"], 1),
        "icon_id": data["weather"][0]["icon"],
        "main": data["weather"][0]["main"].title()
    }

def prepare_weather_state_data(weather_data):
    if weather_data:
        return {
            'weather': {
                'city': weather_data.get('city', 'Unknown'),
                'country': weather_data.get('country', ''),
                'temp': weather_data.get('temp', 0),
                'feels_like': weather_data.get('feels_like', 0),
                'description': weather_data.get('description', 'Unknown'),
                'icon_id': weather_data.get('icon_id', ''),
                'main': weather_data.get('main', ''),
                'humidity': weather_data.get('humidity', 0),
                'pressure': weather_data.get('pressure', 0),
                'wind_speed': weather_data.get('wind_speed', 0),
                'timestamp': time.time()
            }
        }
    else:
        return {
            'weather': {
                'city': 'No weather data',
                'country': '',
                'temp': 0,
                'feels_like': 0,
                'description': 'Failed to fetch',
                'icon_id': '',
                'main': '',
                'humidity': 0,
                'pressure': 0,
                'wind_speed': 0,
                'timestamp': time.time()
            }
        }

# ============== SLEEP FUNCTIONS ==============

def check_sleep_state():
    global display_sleeping, START_SCREEN
    if START_SCREEN != "spotify":
        if display_sleeping:
            wake_up_display()
        return
    current_time = time.time()
    music_playing = spotify_track and spotify_track.get('is_playing', False)
    if display_sleeping:
        if music_playing:
            wake_up_display()
    else:
        if not music_playing and current_time - last_activity_time >= SLEEP_TIMEOUT:
            go_to_sleep()

def go_to_sleep():
    global display_sleeping, last_display_time
    if not display_sleeping:
        display_sleeping = True
        time.sleep(0.05)
        last_display_time = 0
        clear_framebuffer()

def wake_up_display():
    global display_sleeping
    if display_sleeping:
        display_sleeping = False
        update_activity()
        update_display()

# ============== SPOTIFY FUNCTIONS ==============

def authenticate_spotify_interactive():
    print("\n" + "="*60)
    print("Spotify Authentication Required")
    print("="*60)
    sp_oauth = setup_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    print(f"Please visit this URL to authenticate:")
    print(f"{auth_url}")
    print("\nAfter authorization, you'll be redirected to a URL.")
    print("Paste that full redirect URL here:")
    try:
        redirect_url = input().strip()
        token_info = sp_oauth.get_access_token(redirect_url)
        if token_info:
            sp = spotipy.Spotify(auth_manager=sp_oauth)
            sp.current_user()
            print("Authentication successful!")
            return sp
        else:
            print("Failed to get access token")
            return None
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

def calculate_check_interval(api_error_count, spotify_track, consecutive_no_track_count, max_consecutive_no_track):
    if api_error_count > 0:
        return min(10 * (2 ** min(api_error_count-1, 2)), 60)
    elif spotify_track and spotify_track.get('is_playing', False):
        return 2
    else:
        if consecutive_no_track_count >= max_consecutive_no_track:
            return 30
        else:
            return 2

def fetch_album_art_with_retry(art_url, max_retries=2):
    for art_attempt in range(max_retries):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
            resp = requests.get(art_url, headers=headers, timeout=15)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.thumbnail((150, 150), Image.NEAREST)
            return img
        except Exception as e:
            if art_attempt < max_retries - 1:
                wait_time = (art_attempt + 1) * 2
                print(f"Album art fetch attempt {art_attempt + 1} failed: {e}, retrying in {wait_time}s")
                time.sleep(wait_time)
            else:
                print(f"Album art fetch failed after {max_retries} attempts: {e}")
                return None

def fetch_and_process_album_art(art_url, spotify_track, item, is_continuation):
    global last_art_url, album_art_image
    if not is_continuation:
        try:
            if art_url:
                img = fetch_album_art_with_retry(art_url)
                if img:
                    with art_lock: 
                        album_art_image = img
                    save_current_album_art(img)
                    request_background_generation(img)
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
                if img:
                    save_current_album_art(img)
            else:
                with art_lock: 
                    album_art_image = None
                spotify_track['main_color'] = (0, 255, 0)
                spotify_track['secondary_color'] = (0, 255, 255)
                save_current_album_art(None)
        except Exception as e:
            print(f"Error loading album art: {e}")
            with art_lock: 
                album_art_image = None
            spotify_track['main_color'] = (0, 255, 0)
            spotify_track['secondary_color'] = (0, 255, 255)
        update_spotify_layout(spotify_track)
        scrolling_text_cache.clear()
        setup_scrolling_text_for_track(spotify_track)
        if item.get('artists') and len(item['artists']) > 0:
            primary_artist_id = item['artists'][0]['id']
            Thread(target=fetch_and_store_artist_image, args=(sp, primary_artist_id), daemon=True).start()
    else:
        if album_art_image:
            main_color, secondary_color = get_contrasting_colors(album_art_image)
            spotify_track['main_color'] = main_color
            spotify_track['secondary_color'] = secondary_color
        else:
            spotify_track['main_color'] = (0, 255, 0)
            spotify_track['secondary_color'] = (0, 255, 255)
        update_spotify_layout(spotify_track)

def fetch_and_store_artist_image(sp, artist_id):
    global artist_image
    if not artist_id:
        with artist_image_lock: 
            artist_image = None
        return
    max_retries = 3
    for attempt in range(max_retries):
        try:
            artist = sp.artist(artist_id)
            images = artist.get('images', [])
            if not images:
                with artist_image_lock: 
                    artist_image = None
                return
            url = None
            for img in images:
                if abs(img['width'] - 150) <= 20 and abs(img['height'] - 150) <= 20:
                    url = img['url']
                    break
            if not url:
                url = images[-1]['url']
            if not url:
                with artist_image_lock: 
                    artist_image = None
                return
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            if 'image' not in resp.headers.get('content-type', '').lower(): 
                raise ValueError("Not an image")
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            img = img.resize((100, 100), Image.BILINEAR)
            with artist_image_lock: 
                artist_image = img
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                print(f"Artist image fetch attempt {attempt + 1} failed: {e}, retrying in {wait_time}s")
                time.sleep(wait_time)
            else:
                if "NoneType" not in str(e):
                    print(f"Artist image fetch failed after {max_retries} attempts: {e}")
                with artist_image_lock: 
                    artist_image = None

def get_spotify_colors(spotify_track, album_art_image):
    if spotify_track and 'main_color' in spotify_track and 'secondary_color' in spotify_track:
        return spotify_track['main_color'], spotify_track['secondary_color']
    else:
        if album_art_image:
            return get_contrasting_colors(album_art_image)
        else:
            return (0, 255, 0), (0, 255, 255)

def handle_no_track_playing(current_time, last_successful_write, write_interval):
    global spotify_track, consecutive_no_track_count
    consecutive_no_track_count += 1
    if spotify_track is not None:
        spotify_track = None
        with art_lock: 
            album_art_image = None
        cleanup_album_art()
        if current_time - last_successful_write >= write_interval:
            write_current_track_state(None)
            last_successful_write = current_time
        update_spotify_layout(None)
        if START_SCREEN == "spotify":
            update_display()
    return last_successful_write

def handle_spotify_api_errors(e, api_error_count):
    global spotify_track, last_api_call
    if e.http_status == 429:
        print("Spotify API rate limit hit, backing off for 60 seconds...")
        time.sleep(60)
        last_api_call = time.time() 
    elif e.http_status == 401:
        print("Spotify token expired - spotipy should handle refresh automatically")
        last_api_call = time.time()
    else:
        print(f"Spotify API error (attempt {api_error_count}): {e}")
        last_api_call = time.time()
    return True

def handle_track_update(current_time, last_successful_write, write_interval, track, last_track_id, is_first_track_after_startup, previous_track_id):
    global spotify_track, consecutive_no_track_count, last_art_url
    consecutive_no_track_count = 0
    new_track = prepare_track_data(track)
    current_track_id = f"{new_track['title']}_{new_track['artists']}"
    is_continuation = (is_first_track_after_startup and previous_track_id and current_track_id == previous_track_id)
    track_changed = track['item'].get('id') != last_track_id or spotify_track is None
    art_url = None
    if track['item'].get('album') and track['item']['album'].get('images'):
        art_url = track['item']['album']['images'][0]['url']
    art_changed = art_url != last_art_url
    if track_changed or art_changed or spotify_track is None:
        spotify_track = new_track
        update_activity()
        if current_time - last_successful_write >= write_interval:
            write_current_track_state(spotify_track)
            last_successful_write = current_time
        fetch_and_process_album_art(art_url, spotify_track, track['item'], is_continuation)
        last_track_id = track['item'].get('id')
        is_first_track_after_startup = False
        if START_SCREEN == "spotify":
            update_display()
    else:
        old_playing_state = spotify_track.get('is_playing', False) if spotify_track else False
        spotify_track['current_position'] = new_track['current_position']
        spotify_track['is_playing'] = new_track['is_playing']
        playing_state_changed = new_track['is_playing'] != old_playing_state
        if playing_state_changed and new_track['is_playing']:
            update_activity()
        should_write = False
        if playing_state_changed:
            should_write = True
        elif new_track['is_playing'] and current_time - last_successful_write >= write_interval:
            should_write = True
        elif not new_track['is_playing'] and current_time - last_successful_write >= 0.5:
            should_write = True
        if START_SCREEN == "spotify":
            update_display()
        if should_write:
            write_current_track_state(spotify_track)
            last_successful_write = current_time
    return last_successful_write, last_track_id, is_first_track_after_startup

def initialize_spotify_client():
    sp_oauth = setup_spotify_oauth()
    try:
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            return None
        if sp_oauth.is_token_expired(token_info):
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        sp = spotipy.Spotify(auth_manager=sp_oauth)
        sp.current_user()
        return sp
    except Exception as e:
        print(f"Spotify authentication failed: {e}")
        return None

def initialize_spotify_client_or_auth():
    global sp, spotify_track
    sp = initialize_spotify_client()
    if sp is None:
        sp = authenticate_spotify_interactive()
    if sp is None:
        spotify_track = {
            "title": "Spotify Authentication Required",
            "artists": "Authentication failed - restart to retry",
            "album": "HUD Setup",
            "current_position": 0,
            "duration": 1,
            "is_playing": False,
            "main_color": (255, 100, 100),
            "secondary_color": (200, 100, 100)
        }
        update_spotify_layout(spotify_track)
        if START_SCREEN == "spotify":
            update_display()
        return False
    return True

def load_previous_track_state():
    global previous_track_id
    previous_track_id = None
    try:
        if os.path.exists('.current_track_state.toml'):
            with open('.current_track_state.toml', 'r') as f:
                previous_state = toml.load(f)
                previous_track = previous_state.get('current_track', {})
                if previous_track.get('title') and previous_track.get('title') != 'No track playing':
                    previous_track_id = f"{previous_track.get('title', '')}_{previous_track.get('artists', '')}"
    except Exception as e:
        pass

def save_current_album_art(album_art_image, track_data=None):
    global last_saved_album_art_hash
    try:
        os.makedirs('static', exist_ok=True)
        if album_art_image is None:
            if os.path.exists('static/current_album_art.jpg'):
                os.remove('static/current_album_art.jpg')
                last_saved_album_art_hash = None
            return
        display_size = (300, 300)
        resized_art = album_art_image.resize(display_size, Image.NEAREST)
        resized_art.save('static/current_album_art.jpg', 'JPEG', quality=85)
        last_saved_album_art_hash = hash(album_art_image.tobytes())
    except Exception as e:
        print(f"Error saving album art for web: {e}")

def setup_scrolling_text_for_track(track_data):
    for key in ['title', 'artists', 'album']:
        data = track_data.get(key, "")
        if data:
            text_bbox = get_cached_text_bbox_font(data, SPOT_MEDIUM_FONT)
            text_width = text_bbox[2] - text_bbox[0]
            label_text = "Track:" if key == "title" else "Artists:" if key == "artists" else "Album:"
            label_bbox = get_cached_text_bbox_font(label_text, SPOT_MEDIUM_FONT)
            label_width = label_bbox[2] - label_bbox[0]
            visible_width = SCREEN_WIDTH - 5 - label_width - 6
            if text_width > visible_width:
                scrolling_img = create_scrolling_text_image(data, SPOT_MEDIUM_FONT, track_data['main_color'], text_width * 2 + 50)
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

def setup_spotify_oauth():
    return SpotifyOAuth(
        client_id=config["api_keys"]["client_id"],
        client_secret=config["api_keys"]["client_secret"],
        redirect_uri=config["api_keys"]["redirect_uri"],
        scope=SCOPE,
        cache_path=".spotify_cache",
        open_browser=False,
        show_dialog=False
    )

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
        label_bbox = get_cached_text_bbox_font(label, SPOT_MEDIUM_FONT)
        text_bbox = get_cached_text_bbox_font(data, SPOT_MEDIUM_FONT)
        label_width = label_bbox[2] - label_bbox[0]
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        field_height = max(label_bbox[3] - label_bbox[1], text_height) + padding * 2
        left_boundary = x_offset + label_width + 6
        visible_width = SCREEN_WIDTH - 5 - left_boundary
        layout.append({'key': key, 'label': label, 'data': data, 'y': y, 'field_height': field_height, 'label_width': label_width, 'text_width': text_width, 'left_boundary': left_boundary, 'visible_width': visible_width, 'needs_scroll': text_width > visible_width})
        y += field_height
    spotify_layout_cache = layout

# ============== STATE FUNCTIONS ==============

def update_activity():
    global last_activity_time, display_sleeping
    last_activity_time = time.time()
    if display_sleeping:
        display_sleeping = False

# ============== TOML FUNCTIONS ==============

def validate_and_write_toml(data, temp_path, final_path):
    if os.path.exists(temp_path):
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    toml.loads(content)
                    os.replace(temp_path, final_path)
                    return True
        except Exception as e:
            print(f"TOML validation failed: {e}")
            try:
                os.remove(temp_path)
            except:
                pass
    return False

def write_current_track_state(track_data):
    if not ENABLE_CURRENT_TRACK_DISPLAY:
        return
    with file_write_lock:
        try:
            state_data = prepare_track_state_data(track_data)
            for key, value in state_data['current_track'].items():
                if value is None:
                    state_data['current_track'][key] = ""
                elif isinstance(value, str) and '\n' in value:
                    state_data['current_track'][key] = value.replace('\n', ' ')
            temp_path = '.current_track_state.toml.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                toml.dump(state_data, f)
            if validate_and_write_toml(state_data, temp_path, '.current_track_state.toml'):
                return
            fallback_data = {
                'current_track': {
                    'title': 'Error writing state',
                    'artists': '',
                    'album': '',
                    'current_position': 0,
                    'duration': 0,
                    'is_playing': False,
                    'timestamp': time.time()
                }
            }
            with open('.current_track_state.toml', 'w', encoding='utf-8') as f:
                toml.dump(fallback_data, f)
        except Exception as e:
            print(f"Critical error writing track state: {e}")
            try:
                basic_data = {
                    'current_track': {
                        'title': 'Write Error',
                        'artists': '',
                        'album': '',
                        'current_position': 0,
                        'duration': 0,
                        'is_playing': False,
                        'timestamp': time.time()
                    }
                }
                with open('.current_track_state.toml', 'w', encoding='utf-8') as f:
                    toml.dump(basic_data, f)
            except:
                pass

def write_weather_state(weather_data):
    with file_write_lock:
        try:
            state_data = prepare_weather_state_data(weather_data)
            temp_path = '.weather_state.toml.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                toml.dump(state_data, f)
            if validate_and_write_toml(state_data, temp_path, '.weather_state.toml'):
                return
            fallback_data = {
                'weather': {
                    'city': 'Error',
                    'country': '',
                    'temp': 0,
                    'feels_like': 0,
                    'description': 'Error writing state',
                    'timestamp': time.time()
                }
            }
            with open('.weather_state.toml', 'w', encoding='utf-8') as f:
                toml.dump(fallback_data, f)
        except Exception as e:
            print(f"Error writing weather state: {e}")

# ============== WEATHER FUNCTIONS ==============

def get_weather_data_by_coords(api_key, lat, lon, units):
    if not update_internet_status():
        print("Skipping weather update - no internet")
        cache_key = f"{lat:.2f}_{lon:.2f}"
        if cache_key in weather_cache:
            return weather_cache[cache_key][0]
        return None
    if lat is None or lon is None: return None
    cache_key = f"{lat:.2f}_{lon:.2f}"
    current_time = time.time()
    if cache_key in weather_cache:
        cached_data, timestamp = weather_cache[cache_key]
        if current_time - timestamp < 600:
            return cached_data
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units={units}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 429:
            print("Weather API rate limit approached, extending cache")
            if cache_key in weather_cache:
                return weather_cache[cache_key][0]
            return None
        response.raise_for_status()
        data = response.json()
        weather_info_local = prepare_weather_response_data(data)
        weather_cache[cache_key] = (weather_info_local, current_time)
        return weather_info_local
    except requests.exceptions.RequestException as e:
        print(f"Weather API error: {e}")
        if cache_key in weather_cache:
            return weather_cache[cache_key][0]
        return None
    except KeyError:
        return None

def update_weather_icon(weather_info):
    if weather_info and "icon_id" in weather_info:
        try:
            icon_url = f"http://openweathermap.org/img/wn/{weather_info['icon_id']}.png"
            resp = requests.get(icon_url, timeout=5)
            resp.raise_for_status()
            icon_img = Image.open(BytesIO(resp.content)).convert("RGBA")
            icon_img = icon_img.resize((30, 30), Image.BILINEAR)
            icon_img_bw = icon_img.convert('1')
            weather_info['cached_icon'] = icon_img_bw
        except Exception as e:
            print(f"Weather icon fetch error: {e}")
            weather_info['cached_icon'] = None
    else:
        weather_info['cached_icon'] = None
    return weather_info

# ============== CONFIG LOADING AND INITIALIZATION ==============

config = load_config()
HAS_WAVESHARE_EPD = False
HAS_ST7789 = False
HAS_GPIO = False
EPD = None
display_type = config.get("display", {}).get("type", "framebuffer")
if display_type == "waveshare_epd":
    try:
        from waveshare_epd.epd2in13_V3 import EPD
        HAS_WAVESHARE_EPD = True
        print("Waveshare EPD module loaded successfully")
        print("Note: GPIO buttons and touch are disabled for e-paper display")
    except ImportError as e:
        print(f"Waveshare EPD import failed (module not found): {e}")
        HAS_WAVESHARE_EPD = False
        EPD = None
    except Exception as e:
        print(f"Waveshare EPD import failed: {e}")
        HAS_WAVESHARE_EPD = False
        EPD = None
    HAS_GPIO = False
else:
    try:
        import RPi.GPIO as GPIO
        HAS_GPIO = True
        print("RPi.GPIO loaded for button controls")
    except ImportError:
        print("RPi.GPIO not available - button controls will be disabled")
        HAS_GPIO = False
    except Exception as e:
        print(f"GPIO import failed: {e}")
        HAS_GPIO = False
    if display_type == "st7789":
        try:
            import st7789
            HAS_ST7789 = True
            print("ST7789 module loaded successfully")
        except ImportError:
            print("ST7789 module not found")
            HAS_ST7789 = False
if display_type == "st7789":
    ANIMATION_FPS = 30
    TEXT_SCROLL_FPS = 30
elif display_type == "waveshare_epd":
    ANIMATION_FPS = 2
    TEXT_SCROLL_FPS = 2
else:
    ANIMATION_FPS = 15
    TEXT_SCROLL_FPS = 15
ANIMATION_FRAME_TIME = 1.0 / ANIMATION_FPS
TEXT_SCROLL_FRAME_TIME = 1.0 / TEXT_SCROLL_FPS
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
SLEEP_TIMEOUT = config["settings"]["sleep_timeout"]
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
WAKEUP_CHECK_INTERVAL = 10

# ============== MAIN ==============

def main():
    global START_SCREEN, spotify_track
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    init_process_executor()
    Thread(target=background_generation_worker, daemon=True).start()
    Thread(target=weather_loop, daemon=True).start()
    Thread(target=spotify_loop, daemon=True).start()
    Thread(target=handle_touch, daemon=True).start()
    Thread(target=handle_buttons, daemon=True).start()
    Thread(target=animate_images, daemon=True).start()
    Thread(target=animate_text_scroll, daemon=True).start()
    Thread(target=sleep_monitor_loop, daemon=True).start() 
    update_display()
    screen_update_intervals = {
        "weather": 30.0,
        "spotify": 0.5,
        "time": 1.0
    }
    display_type = config.get("display", {}).get("type", "framebuffer")
    if display_type == "waveshare_epd":
        screen_update_intervals = {
            "weather": 30.0,
            "spotify": 0.1,
            "time": 1.0 
        }
        print("E-paper display detected - using slower refresh rates")
    last_display_update = 0
    try:
        while not exit_event.is_set():
            current_time = time.time()
            current_interval = screen_update_intervals.get(START_SCREEN, 1.0)
            if not display_sleeping and current_time - last_display_update >= current_interval:
                update_display()
                last_display_update = current_time
            time.sleep(0.1) 
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        print("Starting cleanup...")
        exit_event.set()
        time.sleep(0.5)
        display_type = config.get("display", {}).get("type", "framebuffer")
        if display_type == "waveshare_epd":
            if waveshare_epd is not None:
                try:
                    print("Putting Waveshare display to sleep...")
                    waveshare_epd.init()
                    waveshare_epd.Clear(0xFF)
                    waveshare_epd.sleep()
                    print("Waveshare display cleaned up")
                except Exception as e:
                    print(f"Waveshare cleanup error: {e}")
        elif display_type == "st7789":
            if st7789_display is not None:
                try:
                    black_img = Image.new("RGB", (320, 240), "black")
                    st7789_display.display(black_img)
                    print("ST7789 display cleared")
                except Exception as e:
                    print(f"ST7789 cleanup error: {e}")
        else:
            clear_framebuffer()
        if HAS_GPIO and display_type != "waveshare_epd":
            try:
                GPIO.setwarnings(False)
                GPIO.cleanup()
                print("GPIO cleaned up")
            except Exception as e:
                print(f"GPIO cleanup error: {e}")
        cleanup_scroll_state()
        if process_executor:
            try:
                process_executor.shutdown(wait=False)
            except:
                pass
        print("Cleanup complete")

if __name__ == "__main__":
    main()