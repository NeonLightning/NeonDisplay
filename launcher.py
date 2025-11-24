#!/usr/bin/env python3
from flask import Flask, request, redirect, url_for, flash, Response, render_template, send_file
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime
from collections import Counter
from functools import wraps
import os, toml, time, requests, subprocess, sys, signal, urllib.parse, socket, logging, threading, json, hashlib, spotipy, io, sqlite3, shutil

app = Flask(__name__)
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
app.secret_key = 'hud-launcher-secret-key'

CONFIG_PATH = "config.toml"
DEFAULT_CONFIG = {
    "display": {
        "type": "framebuffer",
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
    "wifi": {
        "ap_ssid": "Neonwifi-Manager",
        "ap_ip": "192.168.42.1",
    },
    "auto_start": {
        "auto_start_hud35": True,
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
    "logging": {
        "max_log_lines": 10000,
        "max_backup_files": 5
    },
    "ui": {
        "theme": "dark"
    }
}

hud35_process = None
neonwifi_process = None
last_logged_song = None

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(CONFIG_PATH, 'r') as f:
            return toml.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Using default configuration")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        toml.dump(config, f)

def setup_logging():
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    class RobustRotatingFileHandler(logging.Handler):
        def __init__(self, filename, max_lines=10000, max_backups=10):
            self._filename = filename
            self._max_lines = max_lines
            self._max_backups = max_backups
            self._backup_folder = "backuplogs"
            self._current_line_count = 0
            self._ensure_directory_exists()
            self._rotate_if_needed()
            super().__init__()
        def _ensure_directory_exists(self):
            directory = os.path.dirname(self._filename)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            if self._backup_folder and not os.path.exists(self._backup_folder):
                os.makedirs(self._backup_folder, exist_ok=True)
        def _rotate_if_needed(self):
            if not os.path.exists(self._filename):
                self._current_line_count = 0
                return
            try:
                with open(self._filename, 'r') as f:
                    self._current_line_count = sum(1 for _ in f)
                if self._current_line_count >= self._max_lines:
                    self._perform_rotation()
            except Exception as e:
                print(f"Error checking log rotation: {e}")
                self._current_line_count = 0
        def _perform_rotation(self):
            try:
                for i in range(self._max_backups - 1, 0, -1):
                    old_file = os.path.join(self._backup_folder, f"hud35.log.{i}")
                    new_file = os.path.join(self._backup_folder, f"hud35.log.{i+1}")
                    if os.path.exists(old_file):
                        if os.path.exists(new_file):
                            os.remove(new_file)
                        os.rename(old_file, new_file)
                backup_file = os.path.join(self._backup_folder, "hud35.log.1")
                if os.path.exists(self._filename):
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    os.rename(self._filename, backup_file)
                self._current_line_count = 0
                print(f"Log rotated: {self._filename} -> {backup_file}")
            except Exception as e:
                print(f"Error during log rotation: {e}")
        def emit(self, record):
            try:
                msg = self.format(record) + '\n'
                if self._current_line_count >= self._max_lines:
                    self._perform_rotation()
                with open(self._filename, 'a') as f:
                    f.write(msg)
                self._current_line_count += 1
            except Exception as e:
                print(f"Error writing to log file: {e}")
    logger = logging.getLogger('Launcher')
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    try:
        config = load_config()
        log_config = config.get("logging", {})
        max_lines = log_config.get("max_log_lines", 10000)
        max_backups = log_config.get("max_backup_files", 10)
        file_handler = RobustRotatingFileHandler(
            'hud35.log', 
            max_lines=max_lines,
            max_backups=max_backups
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        if not os.path.exists('hud35.log'):
            with open('hud35.log', 'w') as f:
                f.write(f"Log file created at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception as e:
        logger.error(f"Failed to setup file logging: {e}")
    return logger

def check_internet_connection(timeout=5):
    try:
        response = requests.get("http://www.google.com", timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=timeout)
            return True
        except socket.error:
            return False

def wait_for_internet(timeout=60, check_interval=5):
    logger = logging.getLogger('Launcher')
    logger.info("🔍 Waiting for internet connection...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_internet_connection():
            logger.info("✅ Internet connection established")
            return True
        logger.info("⏳ No internet connection, waiting...")
        time.sleep(check_interval)
    logger.error("❌ Internet connection timeout")
    return False

def auto_launch_applications():
    logger = logging.getLogger('Launcher')
    config = load_config()
    auto_config = config.get("auto_start", {})
    logger.info("🔧 Auto-launching applications based on configuration...")
    if auto_config.get("check_internet", True):
        if not wait_for_internet(timeout=30):
            logger.warning("❌ No internet - starting neonwifi if enabled")
            if auto_config.get("auto_start_neonwifi", True):
                start_neonwifi()
            return
    if auto_config.get("auto_start_neonwifi", True):
        start_neonwifi()
    if auto_config.get("auto_start_hud35", True):
        spotify_authenticated, _ = check_spotify_auth()
        config_ready = is_config_ready()
        if config_ready and spotify_authenticated:
            start_hud35()
            logger.info("✅ HUD35 auto-started")
        else:
            logger.warning("⚠️ HUD35 not auto-started: configuration incomplete")

def is_config_ready():
    config = load_config()
    return all([
        config["api_keys"]["openweather"],
        config["api_keys"]["client_id"], 
        config["api_keys"]["client_secret"]
    ])

def check_spotify_auth():
    config = load_config()
    if not config["api_keys"]["client_id"] or not config["api_keys"]["client_secret"]:
        return False, "Missing client credentials"
    try:
        if not os.path.exists(".spotify_cache"):
            return False, "No cached token found"
        sp_oauth = SpotifyOAuth(
            client_id=config["api_keys"]["client_id"],
            client_secret=config["api_keys"]["client_secret"],
            redirect_uri=config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
            cache_path=".spotify_cache"
        )
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            return False, "No valid token found"
        if sp_oauth.is_token_expired(token_info):
            logger = logging.getLogger('Launcher')
            logger.info("Token expired, attempting refresh...")
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            
            if not token_info:
                return False, "Token refresh failed"
        try:
            sp = spotipy.Spotify(auth=token_info['access_token'])
            current_user = sp.current_user()
            return True, f"Authenticated as {current_user.get('display_name', 'Unknown User')}"
        except Exception as e:
            logger = logging.getLogger('Launcher')
            logger.error(f"Token validation failed: {e}")
            return False, f"Token validation failed: {str(e)}"
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error checking Spotify auth: {e}")
        return False, f"Authentication error: {str(e)}"

def get_spotify_client():
    config = load_config()
    if not config["api_keys"]["client_id"] or not config["api_keys"]["client_secret"]:
        return None, "Missing client credentials"
    try:
        sp_oauth = SpotifyOAuth(
            client_id=config["api_keys"]["client_id"],
            client_secret=config["api_keys"]["client_secret"],
            redirect_uri=config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
            cache_path=".spotify_cache"
        )
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            return None, "No valid token available"
        if sp_oauth.is_token_expired(token_info):
            logger = logging.getLogger('Launcher')
            logger.info("Refreshing expired token...")
            try:
                token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                if not token_info:
                    return None, "Failed to refresh token"
            except Exception as e:
                logger.error(f"Token refresh error: {e}")
                return None, f"Token refresh failed: {str(e)}"
        sp = spotipy.Spotify(auth=token_info['access_token'])
        return sp, "Success"
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error creating Spotify client: {e}")
        return None, f"Client creation failed: {str(e)}"

def is_hud35_running():
    global hud35_process
    current_time = time.time()
    if hasattr(is_hud35_running, '_last_check') and current_time - is_hud35_running._last_check < 2:
        return is_hud35_running._cached_result
    if hud35_process is not None:
        if hud35_process.poll() is None:
            result = True
        else:
            hud35_process = None
            result = False
    else:
        try:
            result = bool(subprocess.run(['pgrep', '-f', 'hud35.py'], 
                            capture_output=True, text=True).stdout.strip())
        except Exception:
            result = False
    is_hud35_running._cached_result = result
    is_hud35_running._last_check = current_time
    return result

def is_neonwifi_running():
    global neonwifi_process
    if neonwifi_process is not None:
        if neonwifi_process.poll() is None:
            return True
        else:
            neonwifi_process = None
    try:
        result = subprocess.run(['pgrep', '-f', 'neonwifi.py'], 
                            capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False

def parse_song_from_log(log_line):
    if 'Now playing:' in log_line:
        try:
            if '🎵 Now playing:' in log_line:
                song_part = log_line.split('🎵 Now playing: ')[1].strip()
            else:
                song_part = log_line.split('Now playing: ')[1].strip()
            if ' -- ' in song_part:
                artist_part, song = song_part.split(' -- ', 1)
            elif ' - ' in song_part:
                artist_part, song = song_part.split(' - ', 1)
            else:
                artist_part = 'Unknown Artist'
                song = song_part
            artists = [artist.strip() for artist in artist_part.split(',')]
            return {
                'song': song.strip(),
                'artist': artist_part.strip(),
                'artists': artists,
                'full_track': f"{artist_part} -- {song}".strip()
            }
        except Exception as e:
            logger = logging.getLogger('Launcher')
            logger.error(f"Error parsing song from log: {e}")
            return None
    return None

def start_hud35():
    global hud35_process, last_logged_song
    logger = logging.getLogger('Launcher')
    if is_hud35_running():
        return False, "HUD35 is already running"
    try:
        hud35_process = subprocess.Popen(
            [sys.executable, 'hud35.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        def log_hud35_output():
            for line in iter(hud35_process.stdout.readline, ''):
                if line.strip():
                    logger.info(f"[HUD35] {line.strip()}")
                    song_info = parse_song_from_log(line)
                    if song_info:
                        update_song_count(song_info)
        def monitor_current_track_state():
            while hud35_process and hud35_process.poll() is None:
                log_current_track_state()
                time.sleep(1)
        output_thread = threading.Thread(target=log_hud35_output)
        output_thread.daemon = True
        output_thread.start()
        track_monitor_thread = threading.Thread(target=monitor_current_track_state)
        track_monitor_thread.daemon = True
        track_monitor_thread.start()
        time.sleep(2)
        if hud35_process.poll() is None:
            return True, "HUD35 started successfully"
        else:
            return False, "HUD35 failed to start (check hud35.log for details)"
    except Exception as e:
        logger.error(f"Error starting HUD35: {str(e)}")
        return False, f"Error starting HUD35: {str(e)}"

def stop_hud35():
    global hud35_process, last_logged_song
    logger = logging.getLogger('Launcher')
    if not is_hud35_running():
        return False, "HUD35 is not running"
    try:
        logger.info("Stopping HUD35...")
        hud35_process.terminate()
        try:
            hud35_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            hud35_process.kill()
            hud35_process.wait()
        hud35_process = None
        last_logged_song = None
        try:
            if os.path.exists('.current_track_state.toml'):
                with open('.current_track_state.toml', 'w') as f:
                    empty_state = {
                        'current_track': {
                            'title': 'No track playing',
                            'artists': '',
                            'album': '',
                            'current_position': 0,
                            'duration': 0,
                            'is_playing': False,
                            'timestamp': time.time()
                        }
                    }
                    toml.dump(empty_state, f)
                logger.info("Cleared current track state")
        except Exception as e:
            logger.error(f"Error clearing track state: {e}")
        
        logger.info("HUD35 stopped successfully")
        return True, "HUD35 stopped successfully"
    except Exception as e:
        logger.error(f"Error stopping HUD35: {str(e)}")
        return False, f"Error stopping HUD35: {str(e)}"

def start_neonwifi():
    global neonwifi_process
    logger = logging.getLogger('Launcher')
    if is_neonwifi_running():
        return False, "neonwifi is already running"
    try:
        neonwifi_process = subprocess.Popen(
            [sys.executable, 'neonwifi.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        def log_neonwifi_output():
            for line in iter(neonwifi_process.stdout.readline, ''):
                if line.strip():
                    logger.info(f"[neonwifi] {line.strip()}")
        output_thread = threading.Thread(target=log_neonwifi_output)
        output_thread.daemon = True
        output_thread.start()
        time.sleep(3)
        if neonwifi_process.poll() is None:
            return True, "neonwifi started successfully"
        else:
            return False, "neonwifi failed to start (check hud35.log for details)"
    except Exception as e:
        logger.error(f"Error starting neonwifi: {str(e)}")
        return False, f"Error starting neonwifi: {str(e)}"

def stop_neonwifi():
    global neonwifi_process
    logger = logging.getLogger('Launcher')
    if not is_neonwifi_running():
        return False, "neonwifi is not running"
    try:
        logger.info("Stopping neonwifi...")
        if neonwifi_process:
            neonwifi_process.terminate()
            try:
                neonwifi_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                neonwifi_process.kill()
                neonwifi_process.wait()
            neonwifi_process = None
        subprocess.run(['pkill', '-f', 'neonwifi.py'], check=False)
        time.sleep(2)
        logger.info("neonwifi stopped successfully")
        return True, "neonwifi stopped successfully"
    except Exception as e:
        logger.error(f"Error stopping neonwifi: {str(e)}")
        return False, f"Error stopping neonwifi: {str(e)}"

@app.route('/status/hud35')
def status_hud35():
    return {'running': is_hud35_running()}

@app.route('/status/neonwifi')
def status_neonwifi():
    return {'running': is_neonwifi_running()}

def rate_limit(min_interval=0.5):
    def decorator(f):
        last_called = [0.0]
        @wraps(f)
        def wrapped(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            last_called[0] = time.time()
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.context_processor
def utility_processor():
    return dict(zip=zip)

@app.route('/')
def index():
    config = load_config()
    auto_config = config.get("auto_start", {})
    ui_config = config.get("ui", {"theme": "dark"}) 
    config_ready = is_config_ready()
    spotify_configured = bool(config["api_keys"]["client_id"] and config["api_keys"]["client_secret"])
    spotify_authenticated, _ = check_spotify_auth()
    hud35_running = is_hud35_running()
    neonwifi_running = is_neonwifi_running()
    enable_current_track = config["settings"].get("enable_current_track_display", True)
    return render_template(
        'setup.html', 
        config=config, 
        config_ready=config_ready,
        spotify_configured=spotify_configured,
        spotify_authenticated=spotify_authenticated,
        hud35_running=hud35_running,
        neonwifi_running=neonwifi_running,
        auto_config=auto_config,
        enable_current_track_display=enable_current_track,
        ui_config=ui_config
    )

@app.route('/toggle_theme', methods=['POST'])
def toggle_theme():
    config = load_config()
    new_theme = request.form.get('theme', 'dark')
    if 'ui' not in config:
        config['ui'] = {}
    config['ui']['theme'] = new_theme
    save_config(config)
    return redirect(url_for('index'))

@app.route('/toggle_themeac', methods=['POST'])
def toggle_themeac():
    config = load_config()
    new_theme = request.form.get('theme', 'dark')
    if 'ui' not in config:
        config['ui'] = {}
    config['ui']['theme'] = new_theme
    save_config(config)
    return redirect(url_for('advanced_config'))

@app.route('/save_all_config', methods=['POST'])
def save_all_config():
    config = load_config()
    auto_start_hud35 = 'auto_start_hud35' in request.form
    auto_start_neonwifi = 'auto_start_neonwifi' in request.form
    config["auto_start"] = {
        "auto_start_hud35": auto_start_hud35,
        "auto_start_neonwifi": auto_start_neonwifi
    }
    save_config(config)
    if is_hud35_running():
        stop_hud35()
        time.sleep(3)
    if auto_start_hud35 == True:
        start_hud35()
    if is_neonwifi_running():
        stop_neonwifi()
        time.sleep(3)
    if auto_start_neonwifi == True:
        start_neonwifi()
    flash('success', 'All settings saved successfully!')
    return redirect(url_for('index'))

@app.route('/start_hud35', methods=['POST'])
def start_hud35_route():
    success, message = start_hud35()
    if success:
        flash('success', message)
    else:
        flash('error', message)
    return redirect(url_for('index'))

@app.route('/stop_hud35', methods=['POST'])
def stop_hud35_route():
    success, message = stop_hud35()
    if success:
        flash('success', message)
    else:
        flash('error', message)
    return redirect(url_for('index'))

@app.route('/start_neonwifi', methods=['POST'])
def start_neonwifi_route():
    success, message = start_neonwifi()
    if success:
        flash('success', message)
    else:
        flash('error', message)
    return redirect(url_for('index'))

@app.route('/stop_neonwifi', methods=['POST'])
def stop_neonwifi_route():
    success, message = stop_neonwifi()
    if success:
        flash('success', message)
    else:
        flash('error', message)
    return redirect(url_for('index'))

@app.route('/spotify_auth')
def spotify_auth_page():
    config = load_config()
    if not config["api_keys"]["client_id"] or not config["api_keys"]["client_secret"]:
        flash('error', 'Please save Spotify Client ID and Secret first.')
        return redirect(url_for('index'))
    try:
        sp_oauth = SpotifyOAuth(
            client_id=config["api_keys"]["client_id"],
            client_secret=config["api_keys"]["client_secret"],
            redirect_uri=config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
            cache_path=".spotify_cache",
            show_dialog=True
        )
        auth_url = sp_oauth.get_authorize_url()
        return render_template('spotify_auth.html', auth_url=auth_url)
    except Exception as e:
        flash('error', f'Spotify authentication error: {str(e)}')
        return redirect(url_for('index'))

@app.route('/process_callback_url', methods=['POST'])
def process_callback_url():
    config = load_config()
    callback_url = request.form.get('callback_url', '').strip()
    if not callback_url:
        flash('error', 'Please paste the callback URL')
        return redirect(url_for('spotify_auth_page'))
    try:
        parsed_url = urllib.parse.urlparse(callback_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if 'error' in query_params:
            error = query_params['error'][0]
            flash('error', f'Spotify authentication failed: {error}')
            return redirect(url_for('index'))
        if 'code' not in query_params:
            flash('error', 'No authorization code found in the URL.')
            return redirect(url_for('spotify_auth_page'))
        code = query_params['code'][0]
        sp_oauth = SpotifyOAuth(
            client_id=config["api_keys"]["client_id"],
            client_secret=config["api_keys"]["client_secret"],
            redirect_uri=config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
            cache_path=".spotify_cache"
        )
        token_info = sp_oauth.get_access_token(code)
        if token_info:
            flash('success', 'Spotify authentication successful!')
        else:
            flash('error', 'Spotify authentication failed.')
    except Exception as e:
        flash('error', f'Authentication error: {str(e)}')
        if os.path.exists(".spotify_cache"):
            os.remove(".spotify_cache")
    return redirect(url_for('index'))

@app.route('/view_logs')
def view_logs():
    lines = request.args.get('lines', 100, type=int)
    live = request.args.get('live', False, type=bool)
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    current_theme = ui_config.get("theme", "dark")
    log_file = 'hud35.log'
    if not os.path.exists(log_file):
        log_content = "Log file does not exist. It will be created when there are log messages.\n\n"
        log_content += f"Log file path: {os.path.abspath(log_file)}"
        if live:
            return log_content
        return render_template('logs.html',
            log_content=log_content,
            lines=lines,
            current_theme=current_theme
        )
    try:
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if lines > 0 else all_lines
            log_content = ''.join(recent_lines)
        if not log_content.strip():
            log_content = "Log file exists but is empty. No log messages yet."
    except Exception as e:
        log_content = f"Error reading log file: {str(e)}\n\n"
        log_content += f"Log file path: {os.path.abspath(log_file)}"
    if live:
        return log_content
    return render_template('logs.html',
        log_content=log_content,
        lines=lines,
        current_theme=current_theme
    )

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    log_file = 'hud35.log'
    try:
        backup_folder = "backuplogs"
        clear_option = request.form.get('clear_option', 'current')
        if clear_option == 'all':
            backups_cleared = 0
            for i in range(1, 100):
                backup_file = os.path.join(backup_folder, f"hud35.log.{i}")
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                    backups_cleared += 1
                else:
                    break
            message = f'Backup logs cleared ({backups_cleared} files removed)'
        else:
            with open(log_file, 'w') as f:
                f.write(f"Logs cleared at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            message = 'Current log cleared'
        return message, 200
    except Exception as e:
        return f'Error clearing logs: {str(e)}', 500

@app.route('/music_stats_data')
def music_stats_data():
    try:
        lines = int(request.args.get('lines', 1000))
    except:
        lines = 1000
    song_stats, artist_stats, total_plays, unique_songs, unique_artists = generate_music_stats(None, lines)
    song_chart_data = generate_chart_data(song_stats, 'Songs')
    artist_chart_data = generate_chart_data(artist_stats, 'Artists')
    song_chart_items = list(zip(song_chart_data['labels'], song_chart_data['data'], song_chart_data['colors']))
    artist_chart_items = list(zip(artist_chart_data['labels'], artist_chart_data['data'], artist_chart_data['colors']))
    return {
        'song_chart_items': song_chart_items,
        'artist_chart_items': artist_chart_items,
        'total_plays': total_plays,
        'unique_songs': unique_songs,
        'unique_artists': unique_artists
    }

@app.route('/music_stats')
def music_stats():
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    try:
        lines = int(request.args.get('lines', 1000))
    except:
        lines = 1000
    song_stats, artist_stats, total_plays, unique_songs, unique_artists = generate_music_stats(None, lines)
    song_chart_data = generate_chart_data(song_stats, 'Songs')
    artist_chart_data = generate_chart_data(artist_stats, 'Artists')
    song_chart_items = list(zip(song_chart_data['labels'], song_chart_data['data'], song_chart_data['colors']))
    artist_chart_items = list(zip(artist_chart_data['labels'], artist_chart_data['data'], artist_chart_data['colors']))
    return render_template('music_stats.html', 
                        song_chart_items=song_chart_items,
                        artist_chart_items=artist_chart_items,
                        lines=lines,
                        total_plays=total_plays,
                        unique_songs=unique_songs,
                        unique_artists=unique_artists,
                        ui_config=ui_config)

@app.route('/stream/current_track')
def stream_current_track():
    def generate():
        last_data = None
        update_counter = 0
        while True:
            current_track = get_current_track()
            track_data = {
                'song': current_track['song'],
                'artist': current_track['artist'],
                'album': current_track['album'],
                'progress': current_track['progress'],
                'duration': current_track['duration'],
                'is_playing': current_track['is_playing'],
                'has_track': current_track['has_track'],
                'timestamp': datetime.now().isoformat()
            }
            update_counter += 1
            if track_data != last_data or update_counter >= 3:
                if track_data != last_data:
                    yield f"data: {json.dumps(track_data)}\n\n"
                    last_data = track_data
                update_counter = 0
            time.sleep(0.5)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/current_track')
def api_current_track():
    current_track = get_current_track()
    return {
        'track': current_track,
        'timestamp': datetime.now().isoformat()
    }

@app.route('/current_album_art')
def current_album_art():
    try:
        art_path = 'static/current_album_art.jpg'
        if os.path.exists(art_path):
            return send_file(art_path, mimetype='image/jpeg')
        else:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (300, 300), color=(40, 40, 60))
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 290, 290], outline=(100, 100, 150), width=3)
            draw.text((150, 120), "🎵", fill=(200, 200, 220), anchor="mm")
            draw.text((150, 180), "No Album Art", fill=(150, 150, 170), anchor="mm")
            img_io = io.BytesIO()
            img.save(img_io, 'JPEG', quality=85)
            img_io.seek(0)
            return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error serving album art: {e}")
        try:
            error_img = Image.new('RGB', (300, 300), color=(60, 40, 40))
            draw = ImageDraw.Draw(error_img)
            draw.text((150, 150), "❌ Error", fill=(220, 150, 150), anchor="mm")
            
            img_io = io.BytesIO()
            error_img.save(img_io, 'JPEG')
            img_io.seek(0)
            return send_file(img_io, mimetype='image/jpeg')
        except:
            return "Album art not available", 404

@app.route('/spotify_play', methods=['POST'])
@rate_limit(0.5)
def spotify_play():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.start_playback()
        return {'success': True, 'message': 'Playback started'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Play error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_pause', methods=['POST'])
@rate_limit(0.5)
def spotify_pause():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.pause_playback()
        return {'success': True, 'message': 'Playback paused'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Pause error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_next', methods=['POST'])
@rate_limit(0.5)
def spotify_next():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.next_track()
        return {'success': True, 'message': 'Skipped to next track'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Next track error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_previous', methods=['POST'])
@rate_limit(0.5)
def spotify_previous():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.previous_track()
        return {'success': True, 'message': 'Went to previous track'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Previous track error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_get_volume', methods=['GET'])
def spotify_get_volume():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        playback = sp.current_playback()
        if playback and 'device' in playback:
            current_volume = playback['device'].get('volume_percent', 50)
            return {'success': True, 'volume': current_volume}
        else:
            return {'success': True, 'volume': 50}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Get volume error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_volume', methods=['POST'])
@rate_limit(0.5)
def spotify_volume():
    try:
        volume = request.json.get('volume', 50)
        volume = max(0, min(100, volume))
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.volume(volume)
        return {'success': True, 'message': f'Volume set to {volume}%'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Volume set error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_seek', methods=['POST'])
@rate_limit(0.5)
def spotify_seek():
    try:
        position_ms = request.json.get('position_ms', 0)
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        playback = sp.current_playback()
        if not playback or not playback.get('is_playing', False):
            return {'success': False, 'error': 'No active playback'}
        sp.seek_track(position_ms)
        return {'success': True, 'message': 'Playback position set'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Seek error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_search', methods=['POST'])
@rate_limit(1.0)
def spotify_search():
    try:
        query = request.json.get('query', '').strip()
        if not query:
            return {'success': False, 'error': 'No search query provided'}
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        results = sp.search(q=query, type='track', limit=20)
        tracks = []
        for item in results['tracks']['items']:
            image_url = None
            if item['album']['images']:
                image_url = item['album']['images'][-1]['url'] if item['album']['images'] else None
            duration_ms = item['duration_ms']
            duration_min = duration_ms // 60000
            duration_sec = (duration_ms % 60000) // 1000
            duration_str = f"{duration_min}:{duration_sec:02d}"
            artists = ', '.join([artist['name'] for artist in item['artists']])
            tracks.append({
                'name': item['name'],
                'artists': artists,
                'album': item['album']['name'],
                'duration': duration_str,
                'uri': item['uri'],
                'image_url': image_url
            })
        return {'success': True, 'tracks': tracks}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify search error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_add_to_queue', methods=['POST'])
@rate_limit(0.5)
def spotify_add_to_queue():
    try:
        track_uri = request.json.get('track_uri', '').strip()
        if not track_uri:
            return {'success': False, 'error': 'No track URI provided'}
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.add_to_queue(track_uri)
        return {'success': True, 'message': 'Track added to queue'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify add to queue error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_get_queue', methods=['GET'])
def spotify_get_queue():
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        playback = sp.current_playback()
        queue = sp.queue()
        queue_tracks = []
        if playback and playback.get('item'):
            current_track = playback['item']
            artists = ', '.join([artist['name'] for artist in current_track['artists']])
            image_url = current_track['album']['images'][-1]['url'] if current_track['album']['images'] else None
            queue_tracks.append({
                'name': current_track['name'],
                'artists': artists,
                'album': current_track['album']['name'],
                'uri': current_track['uri'],
                'image_url': image_url,
                'is_current': True
            })
        if queue and queue.get('queue'):
            for track in queue['queue']:
                artists = ', '.join([artist['name'] for artist in track['artists']])
                image_url = track['album']['images'][-1]['url'] if track['album']['images'] else None
                queue_tracks.append({
                    'name': track['name'],
                    'artists': artists,
                    'album': track['album']['name'],
                    'uri': track['uri'],
                    'image_url': image_url,
                    'is_current': False
                })
        return {'success': True, 'queue': queue_tracks}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify get queue error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/spotify_play_track', methods=['POST'])
@rate_limit(0.5)
def spotify_play_track():
    try:
        track_uri = request.json.get('track_uri', '').strip()
        if not track_uri:
            return {'success': False, 'error': 'No track URI provided'}
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        sp.start_playback(uris=[track_uri])
        return {'success': True, 'message': 'Track started'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify play track error: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/search_results')
def search_results():
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    query = request.args.get('query', '')
    tracks_json = request.args.get('tracks', '[]')
    try:
        tracks = json.loads(tracks_json)
    except:
        tracks = []
    return render_template('search_results.html', 
                        query=query, 
                        tracks=tracks,
                        ui_config=ui_config)

@app.route('/clear_song_logs', methods=['POST'])
def clear_song_logs():
    try:
        functions_with_conn = [update_song_count, load_song_counts, generate_music_stats]
        for func in functions_with_conn:
            if hasattr(func, 'db_conn'):
                cursor = func.db_conn.cursor()
                cursor.execute('DELETE FROM song_plays')
                cursor.execute('VACUUM')
                func.db_conn.commit()
        return 'Song logs cleared', 200
    except Exception as e:
        return f'Error clearing song logs: {str(e)}', 500

@app.route('/advanced_config')
def advanced_config():
    config = load_config()
    spotify_configured = bool(config["api_keys"]["client_id"] and config["api_keys"]["client_secret"])
    spotify_authenticated, _ = check_spotify_auth()
    ui_config = config.get("ui", {"theme": "dark"})
    return render_template('advanced_config.html',
            config=config, 
            spotify_configured=spotify_configured,
            spotify_authenticated=spotify_authenticated,
            ui_config=ui_config
        )

@app.route('/save_advanced_config', methods=['POST'])
def save_advanced_config():
    config = load_config()
    try:
        config["api_keys"]["openweather"] = request.form.get('openweather', '').strip()
        config["api_keys"]["google_geo"] = request.form.get('google_geo', '').strip()
        config["api_keys"]["client_id"] = request.form.get('client_id', '').strip()
        config["api_keys"]["client_secret"] = request.form.get('client_secret', '').strip()
        config["api_keys"]["redirect_uri"] = request.form.get('redirect_uri', 'http://127.0.0.1:5000').strip()
        config["settings"]["fallback_city"] = request.form.get('fallback_city', '').strip()
        config["display"]["type"] = request.form.get('display_type', 'framebuffer')
        config["display"]["framebuffer"] = request.form.get('framebuffer_device', '/dev/fb1')
        config["display"]["rotation"] = int(request.form.get('rotation', 0))
        if "st7789" not in config["display"]:
            config["display"]["st7789"] = {}
        config["display"]["st7789"]["spi_port"] = int(request.form.get('spi_port', 0))
        config["display"]["st7789"]["spi_cs"] = int(request.form.get('spi_cs', 1))
        config["display"]["st7789"]["dc_pin"] = int(request.form.get('dc_pin', 9))
        config["display"]["st7789"]["backlight_pin"] = int(request.form.get('backlight_pin', 13))
        config["display"]["st7789"]["spi_speed"] = int(request.form.get('spi_speed', 60000000))
        config["fonts"]["large_font_path"] = request.form.get('large_font_path', '')
        config["fonts"]["large_font_size"] = int(request.form.get('large_font_size', 36))
        config["fonts"]["medium_font_path"] = request.form.get('medium_font_path', '')
        config["fonts"]["medium_font_size"] = int(request.form.get('medium_font_size', 24))
        config["fonts"]["small_font_path"] = request.form.get('small_font_path', '')
        config["fonts"]["small_font_size"] = int(request.form.get('small_font_size', 16))
        config["fonts"]["spot_large_font_path"] = request.form.get('spot_large_font_path', '')
        config["fonts"]["spot_large_font_size"] = int(request.form.get('spot_large_font_size', 26))
        config["fonts"]["spot_medium_font_path"] = request.form.get('spot_medium_font_path', '')
        config["fonts"]["spot_medium_font_size"] = int(request.form.get('spot_medium_font_size', 18))
        config["fonts"]["spot_small_font_path"] = request.form.get('spot_small_font_path', '')
        config["fonts"]["spot_small_font_size"] = int(request.form.get('spot_small_font_size', 12))
        if "buttons" not in config:
            config["buttons"] = {}
        config["buttons"]["button_a"] = int(request.form.get('button_a', 5))
        config["buttons"]["button_b"] = int(request.form.get('button_b', 6))
        config["buttons"]["button_x"] = int(request.form.get('button_x', 16))
        config["buttons"]["button_y"] = int(request.form.get('button_y', 24))
        config["wifi"]["ap_ssid"] = request.form.get('ap_ssid', 'Neonwifi-Manager')
        config["wifi"]["ap_ip"] = request.form.get('ap_ip', '192.168.42.1')
        config["settings"]["progressbar_display"] = 'progressbar_display' in request.form
        config["settings"]["time_display"] = 'time_display' in request.form
        config["settings"]["start_screen"] = request.form.get('start_screen', 'weather')
        config["settings"]["use_gpsd"] = 'use_gpsd' in request.form
        config["settings"]["use_google_geo"] = 'use_google_geo' in request.form
        config["settings"]["enable_current_track_display"] = 'enable_current_track_display' in request.form
        if "logging" not in config:
            config["logging"] = {}
        config["logging"]["max_log_lines"] = int(request.form.get('max_log_lines', 10000))
        config["logging"]["max_backup_files"] = int(request.form.get('max_backup_files', 5))
        config["api_keys"]["redirect_uri"] = request.form.get('redirect_uri', 'http://127.0.0.1:5000')
        config["clock"]["background"] = request.form.get('clock_background', 'color')
        config["clock"]["color"] = request.form.get('clock_color', '#000000')
        config["clock"]["type"] = request.form.get('clock_type', 'digital')
        save_config(config)
        flash('success', 'Advanced configuration saved successfully!')
        def restart_process(process_name, stop_func, start_func, check_func):
            max_wait_time = 10
            wait_interval = 0.5
            if check_func():
                success, message = stop_func()
                if not success:
                    flash('warning', f'Warning stopping {process_name}: {message}')
            start_time = time.time()
            while check_func() and (time.time() - start_time) < max_wait_time:
                time.sleep(wait_interval)
            if check_func():
                flash('warning', f'{process_name} did not stop gracefully, forcing restart')
                if process_name.lower() == 'hud35':
                    subprocess.run(['pkill', '-f', 'hud35.py'], check=False)
                else:
                    subprocess.run(['pkill', '-f', 'neonwifi.py'], check=False)
                time.sleep(2)
            success, message = start_func()
            if not success:
                flash('error', f'Error starting {process_name}: {message}')
        was_hud35_running = is_hud35_running()
        if was_hud35_running:
            restart_process('HUD35', stop_hud35, start_hud35, is_hud35_running)
        was_neonwifi_running = is_neonwifi_running()
        if was_neonwifi_running:
            restart_process('neonwifi', stop_neonwifi, start_neonwifi, is_neonwifi_running)
    except Exception as e:
        flash('error', f'Error saving configuration: {str(e)}')
    return redirect(url_for('advanced_config'))

@app.route('/reset_advanced_config', methods=['POST'])
def reset_advanced_config():
    config = load_config()
    config["display"] = DEFAULT_CONFIG["display"].copy()
    config["fonts"] = DEFAULT_CONFIG["fonts"].copy()
    config["buttons"] = DEFAULT_CONFIG["buttons"].copy()
    preserved_api_keys = config["api_keys"].copy()
    preserved_settings = config["settings"].copy()
    preserved_auto_start = config.get("auto_start", {}).copy()
    preserved_ui = config.get("ui", {}).copy()
    config["api_keys"] = preserved_api_keys
    config["settings"].update({
        "start_screen": "weather",
        "progressbar_display": True,
        "time_display": True,
        "use_gpsd": True,
        "use_google_geo": True
    })
    config["auto_start"] = preserved_auto_start
    config["settings"] = preserved_settings
    config["ui"] = preserved_ui
    save_config(config)
    flash('success', 'Advanced configuration reset to defaults!')
    return redirect(url_for('advanced_config'))

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Endpoint to gracefully shutdown the server"""
    logger = logging.getLogger('Launcher')
    logger.info("Shutting down server via API request")
    shutdown_func = request.environ.get('werkzeug.server.shutdown')
    if shutdown_func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    shutdown_func()
    return 'Server shutting down...'

def get_last_logged_song():
    if not os.path.exists('songs.toml'):
        return None
    try:
        with open('songs.toml', 'r') as f:
            content = f.read()
        data = toml.loads(content)
        plays = data.get('play', [])
        if not plays:
            return None
        last_play = plays[-1]
        return last_play.get('full_track')
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error reading last logged song: {e}")
        return None

def ensure_log_file():
    log_file = 'hud35.log'
    try:
        if not os.path.exists(log_file):
            with open(log_file, 'w') as f:
                f.write(f"Log file created at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            return True
        with open(log_file, 'a') as f:
            f.write(f"Log check at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        return True
    except Exception as e:
        print(f"Log file error: {e}")
        return False

def log_current_track_state():
    global last_logged_song
    try:
        if not os.path.exists('.current_track_state.toml'):
            return
        state_data = toml.load('.current_track_state.toml')
        track_data = state_data.get('current_track', {})
        if not track_data.get('title') or track_data.get('title') in ['No track playing', 'Unknown Track']:
            return
        current_position = track_data.get('current_position', 0)
        duration = track_data.get('duration', 1)
        if duration > 0 and (current_position / duration) < 0.1:
            return        
        artists_data = track_data.get('artists', '')
        artists_list = []
        if isinstance(artists_data, list):
            artists_list = [str(artist).strip() for artist in artists_data if artist and str(artist).strip()]
        elif isinstance(artists_data, str) and artists_data.strip():
            artists_list = [artist.strip() for artist in artists_data.split(',') if artist.strip()]
        else:
            artists_list = ['Unknown Artist']
        if not artists_list:
            artists_list = ['Unknown Artist']
        artist_str = ', '.join(artists_list)
        current_song = f"{artist_str} -- {track_data.get('title', '')}".strip()
        if last_logged_song and current_song == last_logged_song:
            return
        song_info = {
            'song': track_data.get('title', ''),
            'artists': artists_list,
            'full_track': current_song
        }
        update_song_count(song_info)
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error logging from current track state: {e}")

def init_song_database():
    conn = sqlite3.connect('song_stats.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS song_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_hash TEXT UNIQUE,
            song_data TEXT,
            play_count INTEGER DEFAULT 0,
            last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_count ON song_plays(play_count)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON song_plays(song_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_played ON song_plays(last_played)')
    conn.commit()
    return conn

def backup_db_if_needed():
    try:
        backup_file = 'song_stats.db.backup'
        if not os.path.exists(backup_file) or \
            (time.time() - os.path.getmtime(backup_file)) > 1800:
            if os.path.exists('song_stats.db'):
                shutil.copy2('song_stats.db', backup_file)
                logger = logging.getLogger('Launcher')
                logger.info(f"✅ Database backed up to {backup_file}")
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"❌ Database backup failed: {e}")

def update_song_count(song_info):
    global last_logged_song
    logger = logging.getLogger('Launcher')
    current_song = song_info.get('full_track', '').strip()
    if last_logged_song and current_song == last_logged_song:
        return
    songlock = threading.Lock()
    with songlock:
        try:
            if not hasattr(update_song_count, 'db_conn'):
                update_song_count.db_conn = init_song_database()
            if not song_info or not current_song:
                return
            song_hash = hashlib.md5(current_song.encode('utf-8')).hexdigest()[:16]
            cursor = update_song_count.db_conn.cursor()
            cursor.execute('''
                INSERT INTO song_plays (song_hash, song_data, play_count, last_played)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(song_hash) DO UPDATE SET 
                play_count = play_count + 1,
                last_played = datetime('now')
            ''', (song_hash, current_song))
            update_song_count.db_conn.commit()
            backup_db_if_needed()
            last_logged_song = current_song
        except Exception as e:
            logger.error(f"Error updating song count: {e}")

def get_current_track():
    try:
        if not is_hud35_running():
            return {
                'song': 'No track playing',
                'artist': '',
                'album': '',
                'progress': '0:00',
                'duration': '0:00',
                'is_playing': False,
                'has_track': False
            }
        state_file = '.current_track_state.toml'
        if os.path.exists(state_file):
            state_data = toml.load(state_file)
            track_data = state_data.get('current_track', {})
            timestamp = track_data.get('timestamp', 0)
            if time.time() - timestamp < 60:
                progress_sec = track_data.get('current_position', 0)
                duration_sec = track_data.get('duration', 0)
                progress_min = progress_sec // 60
                progress_sec = progress_sec % 60
                duration_min = duration_sec // 60
                duration_sec = duration_sec % 60
                artists = track_data.get('artists', 'Unknown Artist')
                if isinstance(artists, list):
                    artists_str = ', '.join(artists)
                else:
                    artists_str = artists
                return {
                    'song': track_data.get('title', 'Unknown Track'),
                    'artist': artists_str,
                    'album': track_data.get('album', 'Unknown Album'),
                    'progress': f"{progress_min}:{progress_sec:02d}",
                    'duration': f"{duration_min}:{duration_sec:02d}",
                    'is_playing': track_data.get('is_playing', False),
                    'has_track': track_data.get('title') != 'No track playing'
                }
        return {
            'song': 'No track playing',
            'artist': '',
            'album': '',
            'progress': '0:00',
            'duration': '0:00',
            'is_playing': False,
            'has_track': False
        }
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error getting current track: {e}")
        return {
            'song': 'Error loading track',
            'artist': '',
            'album': '',
            'progress': '0:00',
            'duration': '0:00',
            'is_playing': False,
            'has_track': False
        }

def load_song_counts():
    try:
        if not hasattr(load_song_counts, 'db_conn'):
            load_song_counts.db_conn = init_song_database()
        
        cursor = load_song_counts.db_conn.cursor()
        cursor.execute('''
            SELECT song_data, play_count 
            FROM song_plays 
            ORDER BY play_count DESC, last_played DESC
            LIMIT 1000
        ''')
        return dict(cursor.fetchall())
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error loading song counts: {e}")
        return {}

def generate_music_stats(song_counts, max_items=1000):
    try:
        if not hasattr(generate_music_stats, 'db_conn'):
            generate_music_stats.db_conn = init_song_database()
        cursor = generate_music_stats.db_conn.cursor()
        cursor.execute('SELECT SUM(play_count), COUNT(*) FROM song_plays')
        total_plays, unique_songs = cursor.fetchone()
        total_plays = total_plays or 0
        cursor.execute('''
            SELECT COUNT(DISTINCT 
                CASE 
                    WHEN song_data LIKE '% -- %' THEN substr(song_data, 1, instr(song_data, ' -- ') - 1)
                    ELSE 'Unknown Artist'
                END
            ) FROM song_plays
        ''')
        unique_artists = cursor.fetchone()[0] or 0
        cursor.execute('''
            SELECT song_data, play_count 
            FROM song_plays 
            ORDER BY play_count DESC, last_played DESC
            LIMIT ?
        ''', (max_items,))
        song_stats = dict(cursor.fetchall())
        cursor.execute('''
            SELECT 
                CASE 
                    WHEN song_data LIKE '% -- %' THEN substr(song_data, 1, instr(song_data, ' -- ') - 1)
                    ELSE 'Unknown Artist'
                END as artist,
                SUM(play_count) as total_plays
            FROM song_plays 
            GROUP BY artist
            ORDER BY total_plays DESC
            LIMIT ?
        ''', (max_items,))
        artist_stats = dict(cursor.fetchall())
        return song_stats, artist_stats, total_plays, unique_songs, unique_artists
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error generating music stats: {e}")
        return {}, {}, 0, 0, 0

def generate_chart_data(stats, label_type):
    if not stats:
        return {'labels': [], 'data': [], 'colors': []}
    labels = list(stats.keys())
    data = list(stats.values())
    colors = []
    for i in range(len(labels)):
        hue = (i * 137.5) % 360
        colors.append(f'hsl({hue}, 70%, 60%)')
    return {
        'labels': labels,
        'data': data,
        'colors': colors,
        'label_type': label_type
    }

def cleanup():
    logger = logging.getLogger('Launcher')
    global hud35_process, neonwifi_process
    logger.info("🧹 Performing cleanup...")
    functions_with_conn = [update_song_count, load_song_counts, generate_music_stats]
    for func in functions_with_conn:
        if hasattr(func, 'db_conn'):
            try:
                func.db_conn.close()
                logger.info(f"Closed database connection for {func.__name__}")
            except Exception as e:
                logger.error(f"Error closing database connection for {func.__name__}: {e}")
    if hud35_process and hud35_process.poll() is None:
        logger.info("Stopping HUD35 process...")
        hud35_process.terminate()
        try:
            hud35_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("HUD35 didn't terminate gracefully, killing...")
            hud35_process.kill()
            hud35_process.wait()
        hud35_process = None
    if neonwifi_process and neonwifi_process.poll() is None:
        logger.info("Stopping neonwifi process...")
        neonwifi_process.terminate()
        try:
            neonwifi_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("neonwifi didn't terminate gracefully, killing...")
            neonwifi_process.kill()
            neonwifi_process.wait()
        neonwifi_process = None
    subprocess.run(['pkill', '-f', 'hud35.py'], check=False, timeout=5)
    subprocess.run(['pkill', '-f', 'neonwifi.py'], check=False, timeout=5)
    logger.info("Cleanup completed")

def signal_handler(sig, frame):
    logger = logging.getLogger('Launcher')
    logger.info("")
    logger.info("Shutting down launcher...")
    cleanup()
    os._exit(0)

def main():
    ensure_log_file()
    load_config()
    logger = setup_logging()
    logger.info("🚀 Starting HUD35 Launcher")
    def get_lan_ips():
        ips = []
        try:
            hostname = socket.gethostname()
            all_ips = socket.getaddrinfo(hostname, None)
            for addr_info in all_ips:
                ip = addr_info[4][0]
                if '.' in ip and not ip.startswith('127.'):
                    ips.append(ip)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    if local_ip not in ips and not local_ip.startswith('127.'):
                        ips.append(local_ip)
            except:
                pass
        except Exception as e:
            logger.warning(f"Could not determine LAN IP: {e}")
        return list(set(ips))
    lan_ips = get_lan_ips()
    auto_launch_applications()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    import logging as pylogging
    log = pylogging.getLogger('werkzeug')
    log.setLevel(pylogging.WARNING)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    chosen_port = None
    ports_to_try = [5000, 5001]
    for port in ports_to_try:
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(('0.0.0.0', port))
            test_sock.close()
            chosen_port = port
            break
        except OSError as e:
            if "Address already in use" in str(e) or "in use" in str(e).lower():
                logger.debug(f"Port {port} is busy, trying next...")
                continue
            else:
                logger.error(f"Socket error on port {port}: {e}")
                continue
    if chosen_port is None:
        logger.error("❌ Could not find an available port. All ports 5000-5003 are busy.")
        cleanup()
        return
    if lan_ips:
        for ip in lan_ips:
            logger.info(f"📍 Web UI available at: http://{ip}:{chosen_port}")
    else:
        logger.info(f"📍 Web UI available at: http://127.0.0.1:{chosen_port}")
    
    logger.info("⏹️  Press Ctrl+C to stop the launcher")
    try:
        app.run(host='0.0.0.0', port=chosen_port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ Flask server crashed: {e}")
    finally:
        cleanup()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    finally:
        cleanup()