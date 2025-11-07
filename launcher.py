#!/usr/bin/env python3
from flask import Flask, render_template_string, request, redirect, url_for, flash
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from collections import Counter
import os, toml, time, requests, subprocess, sys, signal, urllib.parse, socket, logging, threading

app = Flask(__name__)
app.secret_key = 'hud-launcher-secret-key'

CONFIG_PATH = "config.toml"
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
    "auto_start": {
        "auto_start_hud35": True,
        "auto_start_neonwifi": True,
        "check_internet": True
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
            config = toml.load(f)
            for section, values in DEFAULT_CONFIG.items():
                if section not in config:
                    config[section] = values.copy()
                else:
                    for key, value in values.items():
                        if key not in config[section]:
                            config[section][key] = value
            return config
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        toml.dump(config, f)

def setup_logging():
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('hud35.log')
        ]
    )
    return logging.getLogger('Launcher')

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
        return False, None
    try:
        if not os.path.exists(".spotify_cache"):
            return False, None
        sp_oauth = SpotifyOAuth(
            client_id=config["api_keys"]["client_id"],
            client_secret=config["api_keys"]["client_secret"],
            redirect_uri=config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing",
            cache_path=".spotify_cache"
        )
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            return False, None
        if isinstance(token_info, dict):
            access_token = token_info.get('access_token')
        else:
            access_token = token_info
            
        if not access_token:
            return False, None
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            response = requests.get('https://api.spotify.com/v1/me', headers=headers, timeout=5)
            if response.status_code == 200:
                return True, "Valid token"
            else:
                print(f"Token validation failed with status {response.status_code}")
                return False, None
        except Exception as e:
            print(f"Token validation error: {e}")
            return False, None
    except Exception as e:
        print(f"Error checking Spotify auth: {e}")
        return False, None

def is_hud35_running():
    global hud35_process
    if hud35_process is not None:
        if hud35_process.poll() is None:
            return True
        else:
            hud35_process = None
    return False

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
    if '🎵 Now playing:' in log_line:
        try:
            song_part = log_line.split('🎵 Now playing: ')[1].strip()
            if ' -- ' in song_part:
                artist_part, song = song_part.split(' -- ', 1)
            elif ' - ' in song_part:
                artist_part, song = song_part.split(' - ', 1)
            elif ': ' in song_part:
                artist_part, song = song_part.split(': ', 1)
            else:
                artist_part = 'Unknown Artist'
                song = song_part
            artists = [artist.strip() for artist in artist_part.split(',')]
            return {
                'song': song.strip(),
                'artist': artist_part.strip(),
                'artists': artists,
                'full_track': song_part.strip()
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
        last_logged_song = get_last_logged_song()
        if last_logged_song:
            logger.info(f"📝 Last logged song: {last_logged_song}")
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
                        log_song_play(song_info)
        output_thread = threading.Thread(target=log_hud35_output)
        output_thread.daemon = True
        output_thread.start()
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

SETUP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>HUD35 Launcher</title>
    <style>
        :root {
            --bg-primary: #1a1a1a;
            --bg-secondary: #2d2d2d;
            --bg-tertiary: #3d3d3d;
            --text-primary: #ffffff;
            --text-secondary: #b0b0b0;
            --accent-color: #007bff;
            --accent-hover: #0056b3;
            --border-color: #444444;
            --success-bg: #155724;
            --success-border: #c3e6cb;
            --error-bg: #721c24;
            --error-border: #f5c6cb;
            --warning-bg: #856404;
            --warning-border: #ffeaa7;
            --info-bg: #004085;
            --info-border: #b3d7ff;
        }
        [data-theme="light"] {
            --bg-primary: #ffffff;
            --bg-secondary: #f8f9fa;
            --bg-tertiary: #e9ecef;
            --text-primary: #212529;
            --text-secondary: #6c757d;
            --accent-color: #007bff;
            --accent-hover: #0056b3;
            --border-color: #dee2e6;
            --success-bg: #d4edda;
            --success-border: #c3e6cb;
            --error-bg: #f8d7da;
            --error-border: #f5c6cb;
            --warning-bg: #fff3cd;
            --warning-border: #ffeaa7;
            --info-bg: #cce7ff;
            --info-border: #b3d7ff;
        }
        body { 
            font-family: Arial, sans-serif; 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 20px;
            background: var(--bg-primary);
            color: var(--text-primary);
            transition: all 0.3s ease;
        }
        .container {
            background: var(--bg-secondary);
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border: 1px solid var(--border-color);
        }
        h1 { 
            text-align: center; 
            color: var(--text-primary);
            margin-bottom: 30px;
        }
        .form-group { 
            margin-bottom: 20px; 
        }
        label { 
            display: block; 
            margin-bottom: 5px; 
            font-weight: bold;
            color: var(--text-primary);
        }
        input[type="text"], input[type="password"], textarea, select { 
            width: 100%; 
            padding: 10px; 
            border: 1px solid var(--border-color); 
            border-radius: 5px; 
            box-sizing: border-box;
            font-size: 16px;
            background: var(--bg-tertiary);
            color: var(--text-primary);
            transition: all 0.3s ease;
        }
        input[type="text"]:focus, input[type="password"]:focus, textarea:focus, select:focus {
            border-color: var(--accent-color);
            outline: none;
        }
        .section {
            background: var(--bg-tertiary);
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid var(--accent-color);
            transition: all 0.3s ease;
        }
        .section h2 {
            margin-top: 0;
            color: var(--text-primary);
        }
        button { 
            background: var(--accent-color); 
            color: white; 
            border: none; 
            padding: 12px 20px; 
            border-radius: 5px; 
            cursor: pointer; 
            font-size: 16px; 
            width: 100%;
            margin-top: 10px;
            transition: all 0.3s ease;
        }
        button:hover { 
            background: var(--accent-hover); 
        }
        .btn-secondary {
            background: #6c757d;
            margin-top: 5px;
        }
        .btn-success {
            background: #28a745;
            margin-top: 5px;
        }
        .btn-danger {
            background: #dc3545;
            margin-top: 5px;
        }
        .btn-warning {
            background: #ffc107;
            color: #212529;
            margin-top: 5px;
        }
        .status {
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            text-align: center;
            transition: all 0.3s ease;
        }
        .status.success { 
            background: var(--success-bg); 
            color: var(--text-primary); 
            border: 1px solid var(--success-border);
        }
        .status.error { 
            background: var(--error-bg); 
            color: var(--text-primary); 
            border: 1px solid var(--error-border);
        }
        .status.info { 
            background: var(--info-bg); 
            color: var(--text-primary); 
            border: 1px solid var(--info-border);
        }
        .status.warning { 
            background: var(--warning-bg); 
            color: var(--text-primary); 
            border: 1px solid var(--warning-border);
        }
        .app-controls {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 20px 0;
        }
        .control-panel {
            background: var(--bg-secondary);
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        .control-panel h3 {
            margin-top: 0;
            color: var(--text-primary);
            border-bottom: 2px solid var(--accent-color);
            padding-bottom: 10px;
        }
        .toggle-switch {
            display: flex;
            align-items: center;
            margin: 10px 0;
        }
        .toggle-switch input[type="checkbox"] {
            margin-right: 10px;
            transform: scale(1.2);
        }
        .toggle-switch label {
            color: var(--text-primary);
        }
        .app-status {
            text-align: center;
            padding: 15px;
            margin: 10px 0;
            border-radius: 8px;
            background: var(--bg-secondary);
            border: 2px solid var(--border-color);
            transition: all 0.3s ease;
        }
        .app-status.running {
            background: var(--success-bg);
            border-color: var(--success-border);
            color: var(--text-primary);
        }
        .app-status.stopped {
            background: var(--error-bg);
            border-color: var(--error-border);
            color: var(--text-primary);
        }
        .instructions {
            background: var(--info-bg);
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
            font-size: 14px;
            color: var(--text-primary);
            border: 1px solid var(--info-border);
        }
        .instructions a {
            color: var(--text-primary);
            text-decoration: underline;
        }
        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--accent-color);
            color: white;
            border: none;
            padding: 8px 12px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 12px;
            z-index: 1000;
            width: auto;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
        }
        .theme-toggle:hover {
            background: var(--accent-hover);
            transform: scale(1.05);
        }
        small {
            color: var(--text-secondary);
        }
        .settings-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .save-all-button {
            background: #28a745;
            font-size: 18px;
            padding: 15px;
            margin-top: 30px;
        }
        .log-viewer-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            margin-top: 20px;
            padding: 15px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            justify-content: center;
        }
        .log-viewer-controls input {
            width: 80px;
            padding: 8px;
        }
    </style>
</head>
<body data-theme="{{ ui_config.theme }}">
    <button class="theme-toggle" onclick="toggleTheme()">
        {% if ui_config.theme == 'dark' %}
        ☀️
        {% else %}
        🌙
        {% endif %}
    </button>
    <div class="container">
        <h1>HUD35 Launcher</h1>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="status {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <div class="app-controls">
            <div class="control-panel">
                <h3>HUD35 Display</h3>
                <div class="app-status {% if hud35_running %}running{% else %}stopped{% endif %}">
                    Status: {% if hud35_running %}✅ RUNNING{% else %}❌ STOPPED{% endif %}
                </div>
                {% if hud35_running %}
                <form method="POST" action="/stop_hud35">
                    <button type="submit" class="btn-danger">🛑 Stop HUD35</button>
                </form>
                {% else %}
                <form method="POST" action="/start_hud35">
                    <button type="submit" class="btn-success">🚀 Start HUD35</button>
                </form>
                {% endif %}
            </div>
            <div class="control-panel">
                <h3>WiFi Manager</h3>
                <div class="app-status {% if neonwifi_running %}running{% else %}stopped{% endif %}">
                    Status: {% if neonwifi_running %}✅ RUNNING{% else %}❌ STOPPED{% endif %}
                </div>
                {% if neonwifi_running %}
                <form method="POST" action="/stop_neonwifi">
                    <button type="submit" class="btn-danger">🛑 Stop WiFi Manager</button>
                </form>
                {% else %}
                <form method="POST" action="/start_neonwifi">
                    <button type="submit" class="btn-success">🚀 Start WiFi Manager</button>
                </form>
                {% endif %}
            </div>
        </div>
        <div class="log-viewer-controls">
            <a href="/music_stats">
                <button type="button" class="btn-secondary">📊 Music Statistics</button>
            </a>
        </div>
        <form method="POST" action="/save_all_config">
            <div class="section">
                <h2>🔑 API Configuration</h2>
                <div class="instructions">
                    <p><strong>Get your API keys:</strong></p>
                    <p>• <a href="https://openweathermap.org/api" target="_blank">OpenWeatherMap</a> - Free weather API</p>
                    <p>• <a href="https://developers.google.com/maps/documentation/geolocation" target="_blank">Google Geolocation API</a> - Optional, for precise location</p>
                    <p>• <a href="https://developer.spotify.com/dashboard" target="_blank">Spotify Developer Dashboard</a> - For music integration</p>
                </div>
                <div class="settings-grid">
                    <div>
                        <h3>Weather APIs</h3>
                        <div class="form-group">
                            <label for="openweather">OpenWeatherMap API Key:</label>
                            <input type="text" id="openweather" name="openweather" value="{{ config.api_keys.openweather }}" placeholder="Enter your OpenWeatherMap API key">
                        </div>
                        <div class="form-group">
                            <label for="google_geo">Google Geolocation API Key:</label>
                            <input type="text" id="google_geo" name="google_geo" value="{{ config.api_keys.google_geo }}" placeholder="Enter Google Geolocation API key">
                            <small>Optional - for precise location without GPS</small>
                        </div>
                    </div>
                    <div>
                        <h3>Spotify API</h3>
                        {% if spotify_configured %}
                            {% if spotify_authenticated %}
                            <div class="status success">
                                <p>✅ Spotify is authenticated!</p>
                            </div>
                            {% else %}
                            <div class="status warning">
                                <p>⚠️ Spotify credentials saved but not authenticated.</p>
                                <a href="/spotify_auth">
                                    <button type="button" class="btn-warning">🔑 Authenticate Spotify</button>
                                </a>
                            </div>
                            {% endif %}
                        {% endif %}
                        <div class="form-group">
                            <label for="client_id">Spotify Client ID:</label>
                            <input type="text" id="client_id" name="client_id" value="{{ config.api_keys.client_id }}" placeholder="Enter your Spotify Client ID">
                        </div>
                        <div class="form-group">
                            <label for="client_secret">Spotify Client Secret:</label>
                            <input type="password" id="client_secret" name="client_secret" value="{{ config.api_keys.client_secret }}" placeholder="Enter your Spotify Client Secret">
                        </div>
                    </div>
                </div>
            </div>
            <div class="section">
                <h2>📍 Location & Display Settings</h2>
                <div class="settings-grid">
                    <div>
                        <h3>Location Services</h3>
                        <div class="form-group">
                            <label for="fallback_city">Fallback City:</label>
                            <input type="text" id="fallback_city" name="fallback_city" value="{{ config.settings.fallback_city }}" placeholder="e.g., London,UK">
                            <small>Used when location services are unavailable</small>
                        </div>
                        <div class="toggle-switch">
                            <input type="checkbox" id="use_gpsd" name="use_gpsd" {% if config.settings.use_gpsd %}checked{% endif %}>
                            <label for="use_gpsd">Use GPSD for location</label>
                            <small style="display: block; margin-left: 25px; color: var(--text-secondary);">(Requires GPS hardware and gpsd service)</small>
                        </div>
                        <div class="toggle-switch">
                            <input type="checkbox" id="use_google_geo" name="use_google_geo" {% if config.settings.use_google_geo %}checked{% endif %}>
                            <label for="use_google_geo">Use Google Geolocation</label>
                            <small style="display: block; margin-left: 25px; color: var(--text-secondary);">(More accurate than IP-based location)</small>
                        </div>
                    </div>
                    <div>
                        <h3>Display Settings</h3>
                        <div class="form-group">
                            <label for="start_screen">Start Screen:</label>
                            <select id="start_screen" name="start_screen">
                                <option value="weather" {% if config.settings.start_screen == "weather" %}selected{% endif %}>Weather</option>
                                <option value="spotify" {% if config.settings.start_screen == "spotify" %}selected{% endif %}>Spotify</option>
                            </select>
                        </div>
                        <div class="toggle-switch">
                            <input type="checkbox" id="time_display" name="time_display" {% if config.settings.time_display %}checked{% endif %}>
                            <label for="time_display">Show time display</label>
                        </div>
                    </div>
                </div>
            </div>
            <div class="section">
                <h2>⚡ Auto-start Configuration</h2>
                <div class="toggle-switch">
                    <input type="checkbox" id="auto_start_hud35" name="auto_start_hud35" {% if auto_config.auto_start_hud35 %}checked{% endif %}>
                    <label for="auto_start_hud35">Auto-start HUD35 Display on boot</label>
                </div>
                <div class="toggle-switch">
                    <input type="checkbox" id="auto_start_neonwifi" name="auto_start_neonwifi" {% if auto_config.auto_start_neonwifi %}checked{% endif %}>
                    <label for="auto_start_neonwifi">Auto-start WiFi Manager on boot</label>
                </div>
                <div class="toggle-switch">
                    <input type="checkbox" id="check_internet" name="check_internet" {% if auto_config.check_internet %}checked{% endif %}>
                    <label for="check_internet">Wait for internet connection before starting Hud35</label>
                </div>
            </div>
            <button type="submit" class="save-all-button">💾 Save All Settings</button>
        </form>
        <div class="log-viewer-controls">
            <form action="/view_logs" method="GET" style="display: flex; gap: 10px; align-items: center;">
                <button type="submit" class="btn-secondary">📋 View Logs</button>
                <label for="log_lines" style="color: var(--text-primary);">Lines:</label>
                <input type="number" id="log_lines" name="lines" value="100" min="10" max="1000" style="width: 80px;">
            </form>
        </div>
    </div>
    <script>
        function toggleTheme() {
            const currentTheme = document.body.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.body.setAttribute('data-theme', newTheme);
            const button = document.querySelector('.theme-toggle');
            button.innerHTML = newTheme === 'dark' ? '☀️' : '🌙';
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/toggle_theme';
            const themeInput = document.createElement('input');
            themeInput.type = 'hidden';
            themeInput.name = 'theme';
            themeInput.value = newTheme;
            form.appendChild(themeInput);
            document.body.appendChild(form);
            form.submit();
        }
        document.addEventListener('DOMContentLoaded', function() {
            const savedTheme = '{{ ui_config.theme }}' || 'dark';
            document.body.setAttribute('data-theme', savedTheme);
            const button = document.querySelector('.theme-toggle');
            button.innerHTML = savedTheme === 'dark' ? '☀️' : '🌙';
        });
    </script>
</body>
</html>
"""
MUSIC_STATS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Music Statistics</title>
    <style>
        :root {
            --bg-primary: #1a1a1a;
            --bg-secondary: #2d2d2d;
            --bg-tertiary: #3d3d3d;
            --text-primary: #ffffff;
            --text-secondary: #b0b0b0;
            --accent-color: #007bff;
            --accent-hover: #0056b3;
            --border-color: #444444;
            --card-bg: #2d2d2d;
        }
        [data-theme="light"] {
            --bg-primary: #ffffff;
            --bg-secondary: #f8f9fa;
            --bg-tertiary: #e9ecef;
            --text-primary: #212529;
            --text-secondary: #6c757d;
            --accent-color: #007bff;
            --accent-hover: #0056b3;
            --border-color: #dee2e6;
            --card-bg: #f8f9fa;
        }
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--bg-primary);
            color: var(--text-primary);
            transition: all 0.3s ease;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 20px;
            background: var(--bg-secondary);
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        .controls {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .stats-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--card-bg);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid var(--border-color);
        }
        .stat-number {
            font-size: 2em;
            font-weight: bold;
            color: var(--accent-color);
        }
        .stat-label {
            color: var(--text-secondary);
            margin-top: 5px;
        }
        .charts-container {
            display: flex;
            flex-direction: column;
            gap: 30px;
            margin-bottom: 20px;
        }
        .chart-card {
            background: var(--bg-secondary);
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
        }
        .chart-title {
            margin-top: 0;
            margin-bottom: 15px;
            text-align: center;
            color: var(--text-primary);
            flex-shrink: 0;
        }
        .chart-container {
            height: 400px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .bar-chart {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding-right: 5px;
        }
        .bar-item {
            display: flex;
            flex-direction: column;
            margin-bottom: 10px;
            padding: 8px;
            background: var(--bg-tertiary);
            border-radius: 6px;
            border-left: 4px solid var(--accent-color);
        }
        .song-name {
            font-size: 13px;
            font-weight: bold;
            margin-bottom: 4px;
            line-height: 1.3;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }
        .artist-name {
            font-size: 11px;
            color: var(--text-secondary);
            font-style: italic;
            margin-bottom: 6px;
            line-height: 1.2;
        }
        .bar-track-container {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .bar-track {
            flex: 1;
            height: 16px;
            background: var(--border-color);
            border-radius: 8px;
            overflow: hidden;
        }
        .bar-fill {
            height: 100%;
            border-radius: 8px;
            transition: width 0.3s ease;
        }
        .bar-count {
            flex: 0 0 40px;
            text-align: right;
            font-size: 12px;
            font-weight: bold;
            color: var(--text-primary);
        }
        .artist-bar-item {
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            padding: 8px;
            background: var(--bg-tertiary);
            border-radius: 6px;
            border-left: 4px solid var(--accent-color);
        }
        .artist-name-full {
            flex: 0 0 200px;
            font-size: 13px;
            font-weight: bold;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .artist-bar-track {
            flex: 1;
            height: 16px;
            background: var(--border-color);
            border-radius: 8px;
            overflow: hidden;
            margin: 0 10px;
        }
        .artist-bar-fill {
            height: 100%;
            border-radius: 8px;
            transition: width 0.3s ease;
        }
        .artist-bar-count {
            flex: 0 0 40px;
            text-align: right;
            font-size: 12px;
            font-weight: bold;
        }
        input, button, select {
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }
        button {
            background: var(--accent-color);
            border: none;
            cursor: pointer;
            color: white;
        }
        button:hover {
            background: var(--accent-hover);
        }
        .theme-toggle {
            background: var(--accent-color);
            color: white;
            border: none;
            padding: 8px 12px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 12px;
        }
        .theme-toggle:hover {
            background: var(--accent-hover);
        }
        /* Custom scrollbar */
        .bar-chart::-webkit-scrollbar {
            width: 8px;
        }
        .bar-chart::-webkit-scrollbar-track {
            background: var(--bg-tertiary);
            border-radius: 4px;
        }
        .bar-chart::-webkit-scrollbar-thumb {
            background: var(--accent-color);
            border-radius: 4px;
        }
        .bar-chart::-webkit-scrollbar-thumb:hover {
            background: var(--accent-hover);
        }
        @media (max-width: 768px) {
            .header {
                flex-direction: column;
                gap: 15px;
            }
            .artist-name-full {
                flex: 0 0 150px;
            }
            .chart-container {
                min-height: 250px;
                max-height: 350px;
            }
        }
    </style>
</head>
<body data-theme="{{ ui_config.theme }}">
    <div class="container">
        <div class="header">
            <h1>🎵 Music Statistics</h1>
            <div class="controls">
                <form method="GET" style="display: flex; gap: 10px; align-items: center;">
                    <label>Time Period:</label>
                    <select name="period" onchange="this.form.submit()">
                        <option value="1day" {% if period == '1day' %}selected{% endif %}>Last 24 Hours</option>
                        <option value="7days" {% if period == '7days' %}selected{% endif %}>Last 7 Days</option>
                        <option value="30days" {% if period == '30days' %}selected{% endif %}>Last 30 Days</option>
                        <option value="90days" {% if period == '90days' %}selected{% endif %}>Last 90 Days</option>
                        <option value="all" {% if period == 'all' %}selected{% endif %}>All Time</option>
                    </select>
                    <label>Max Items:</label>
                    <input type="number" name="lines" value="{{ lines }}" min="10" max="1000" style="width: 80px;" onchange="this.form.submit()">
                </form>
                <button onclick="location.href='/'">← Back to Launcher</button>
                <button onclick="clearSongLogs()">🗑️ Clear Song Logs</button>
                <button class="theme-toggle" onclick="toggleTheme()">
                    {{ '☀️' if ui_config.theme == 'dark' else '🌙' }}
                </button>
            </div>
        </div>

        <div class="stats-cards">
            <div class="stat-card">
                <div class="stat-number">{{ total_plays }}</div>
                <div class="stat-label">Total Plays</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ unique_songs }}</div>
                <div class="stat-label">Unique Songs</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ unique_artists }}</div>
                <div class="stat-label">Unique Artists</div>
            </div>
        </div>

        <div class="charts-container">
            <!-- Most Played Songs Section -->
            <div class="chart-card">
                <h2 class="chart-title">🎼 Most Played Songs</h2>
                <div class="chart-container">
                    <div class="bar-chart" id="songChart">
                        {% for label, count, color in song_chart_items %}
                        <div class="bar-item">
                            <div class="song-name" title="{{ label }}">{{ loop.index }}. {{ label.split(' - ')[0] if ' - ' in label else label }}</div>
                            <div class="artist-name" title="{{ label.split(' - ')[1] if ' - ' in label else 'Unknown Artist' }}">
                                {{ label.split(' - ')[1] if ' - ' in label else 'Unknown Artist' }}
                            </div>
                            <div class="bar-track-container">
                                <div class="bar-track">
                                    <div class="bar-fill" style="width: {{ (count / song_chart_items[0][1] * 100) if song_chart_items else 0 }}%; background: {{ color }};"></div>
                                </div>
                                <div class="bar-count">{{ count }}</div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <!-- Most Played Artists Section -->
            <div class="chart-card">
                <h2 class="chart-title">🎤 Most Played Artists</h2>
                <div class="chart-container">
                    <div class="bar-chart" id="artistChart">
                        {% for label, count, color in artist_chart_items %}
                        <div class="artist-bar-item">
                            <div class="artist-name-full" title="{{ label }}">{{ loop.index }}. {{ label }}</div>
                            <div class="artist-bar-track">
                                <div class="artist-bar-fill" style="width: {{ (count / artist_chart_items[0][1] * 100) if artist_chart_items else 0 }}%; background: {{ color }};"></div>
                            </div>
                            <div class="artist-bar-count">{{ count }}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function toggleTheme() {
            const currentTheme = document.body.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/toggle_theme';
            const themeInput = document.createElement('input');
            themeInput.type = 'hidden';
            themeInput.name = 'theme';
            themeInput.value = newTheme;
            form.appendChild(themeInput);
            document.body.appendChild(form);
            form.submit();
        }

        function clearSongLogs() {
            if (confirm('Are you sure you want to clear all song history? This cannot be undone.')) {
                fetch('/clear_song_logs', { method: 'POST' })
                    .then(() => {
                        location.reload();
                    });
            }
        }

        // Animate bar fills on load
        document.addEventListener('DOMContentLoaded', function() {
            const bars = document.querySelectorAll('.bar-fill, .artist-bar-fill');
            bars.forEach(bar => {
                const width = bar.style.width;
                bar.style.width = '0%';
                setTimeout(() => {
                    bar.style.width = width;
                }, 100);
            });
        });
    </script>
</body>
</html>
"""

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
    return render_template_string(
        SETUP_HTML, 
        config=config, 
        config_ready=config_ready,
        spotify_configured=spotify_configured,
        spotify_authenticated=spotify_authenticated,
        hud35_running=hud35_running,
        neonwifi_running=neonwifi_running,
        auto_config=auto_config,
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

@app.route('/save_all_config', methods=['POST'])
def save_all_config():
    config = load_config()
    config["api_keys"]["openweather"] = request.form.get('openweather', '')
    config["api_keys"]["google_geo"] = request.form.get('google_geo', '')
    config["api_keys"]["client_id"] = request.form.get('client_id', '')
    config["api_keys"]["client_secret"] = request.form.get('client_secret', '')
    config["settings"]["fallback_city"] = request.form.get('fallback_city', '')
    config["settings"]["start_screen"] = request.form.get('start_screen', 'weather')
    config["settings"]["use_gpsd"] = 'use_gpsd' in request.form
    config["settings"]["use_google_geo"] = 'use_google_geo' in request.form
    config["settings"]["time_display"] = 'time_display' in request.form
    config["auto_start"] = {
        "auto_start_hud35": 'auto_start_hud35' in request.form,
        "auto_start_neonwifi": 'auto_start_neonwifi' in request.form,
        "check_internet": 'check_internet' in request.form
    }
    save_config(config)
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
            scope="user-read-currently-playing",
            cache_path=".spotify_cache",
            show_dialog=True
        )
        auth_url = sp_oauth.get_authorize_url()
        return f"""
        <div style="max-width: 600px; margin: 50px auto; padding: 20px; font-family: Arial;">
            <h2>Spotify Authentication</h2>
            <p>Visit this URL to authenticate:</p>
            <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; word-break: break-all;">
                {auth_url}
            </div>
            <p><a href="{auth_url}" target="_blank">Click here to open</a></p>
            <p>After authenticating, you'll be redirected. Copy the URL and paste it below:</p>
            <form method="POST" action="/process_callback_url">
                <textarea name="callback_url" placeholder="Paste the callback URL here..." style="width: 100%; height: 100px; margin: 10px 0;"></textarea>
                <button type="submit">Process Authentication</button>
            </form>
            <p><a href="/">← Back to setup</a></p>
        </div>
        """
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
            scope="user-read-currently-playing",
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
        return "No log file found", 404
    try:
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if lines > 0 else all_lines
            log_content = ''.join(recent_lines)
    except Exception as e:
        log_content = f"Error reading log file: {str(e)}"
    if live:
        return log_content
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>HUD35 Logs</title>
        <style>
            :root {{
                --bg-primary: #1a1a1a;
                --bg-secondary: #2d2d2d;
                --bg-tertiary: #3d3d3d;
                --text-primary: #ffffff;
                --text-secondary: #b0b0b0;
                --accent-color: #007bff;
                --accent-hover: #0056b3;
                --border-color: #444444;
                --log-bg: #000000;
            }}
            [data-theme="light"] {{
                --bg-primary: #ffffff;
                --bg-secondary: #f8f9fa;
                --bg-tertiary: #e9ecef;
                --text-primary: #212529;
                --text-secondary: #6c757d;
                --accent-color: #007bff;
                --accent-hover: #0056b3;
                --border-color: #dee2e6;
                --log-bg: #f8f9fa;
            }}
            body {{ 
                font-family: Arial, sans-serif; 
                margin: 0;
                padding: 20px;
                background: var(--bg-primary);
                color: var(--text-primary);
                transition: all 0.3s ease;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding: 15px;
                background: var(--bg-secondary);
                border-radius: 8px;
                border: 1px solid var(--border-color);
            }}
            .controls {{
                display: flex;
                gap: 10px;
                align-items: center;
            }}
            input, button, select {{
                padding: 8px 12px;
                border: 1px solid var(--border-color);
                border-radius: 4px;
                background: var(--bg-tertiary);
                color: var(--text-primary);
            }}
            button {{
                background: var(--accent-color);
                border: none;
                cursor: pointer;
                color: white;
            }}
            button:hover {{
                background: var(--accent-hover);
            }}
            .log-container {{
                background: var(--log-bg);
                padding: 15px;
                border-radius: 8px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                white-space: pre-wrap;
                max-height: 70vh;
                overflow-y: auto;
                border: 1px solid var(--border-color);
                color: var(--text-primary);
            }}
            .log-line {{
                margin: 2px 0;
                line-height: 1.4;
            }}
            .log-error {{ color: #ff6b6b; }}
            .log-warning {{ color: #ffd93d; }}
            .log-info {{ color: #6bcbef; }}
            .log-success {{ color: #6bcf7f; }}
            .log-debug {{ color: #a0a0a0; }}
            .theme-toggle {{
                background: var(--accent-color);
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 20px;
                cursor: pointer;
                font-size: 12px;
                margin-left: 10px;
            }}
            .theme-toggle:hover {{
                background: var(--accent-hover);
            }}
        </style>
    </head>
    <body data-theme="{current_theme}">
        <div class="container">
            <div class="header">
                <h2>HUD35 Log Viewer</h2>
                <div class="controls">
                    <form id="linesForm" method="GET" style="display: flex; gap: 10px; align-items: center;">
                        <label for="lines">Lines to show:</label>
                        <input type="number" id="lines" name="lines" value="{lines}" min="10" max="10000" style="width: 80px;">
                        <button type="submit">Update</button>
                    </form>
                    <button onclick="toggleLive()" id="liveBtn">▶️ Start Live</button>
                    <button onclick="location.href='/'">← Back to Launcher</button>
                    <button onclick="clearLogs()">🗑️ Clear Logs</button>
                    <button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">
                        { '☀️' if current_theme == 'dark' else '🌙' }
                    </button>
                </div>
            </div>
            <div class="log-container" id="logContent">
{log_content}
            </div>
        </div>
        <script>
            let liveUpdate = false;
            let updateInterval;
            let currentTheme = '{current_theme}';
            function toggleTheme() {{
                currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                document.body.setAttribute('data-theme', currentTheme);
                const btn = document.getElementById('themeBtn');
                btn.innerHTML = currentTheme === 'dark' ? '☀️' : '🌙';
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/toggle_theme';
                const themeInput = document.createElement('input');
                themeInput.type = 'hidden';
                themeInput.name = 'theme';
                themeInput.value = currentTheme;
                form.appendChild(themeInput);
                document.body.appendChild(form);
                form.submit();
            }}
            function toggleLive() {{
                liveUpdate = !liveUpdate;
                const btn = document.getElementById('liveBtn');
                if (liveUpdate) {{
                    btn.innerHTML = '⏸️ Stop Live';
                    startLiveUpdates();
                }} else {{
                    btn.innerHTML = '▶️ Start Live';
                    stopLiveUpdates();
                }}
            }}
            function startLiveUpdates() {{
                const lines = document.getElementById('lines').value;
                updateInterval = setInterval(() => {{
                    fetch(`/view_logs?lines=${{lines}}&live=true`)
                        .then(response => response.text())
                        .then(data => {{
                            document.getElementById('logContent').innerText = data;
                            colorCodeLogs();
                            scrollToBottom();
                        }});
                }}, 2000);
            }}
            function stopLiveUpdates() {{
                if (updateInterval) {{
                    clearInterval(updateInterval);
                }}
            }}
            function scrollToBottom() {{
                const logContainer = document.getElementById('logContent');
                logContainer.scrollTop = logContainer.scrollHeight;
            }}
            function clearLogs() {{
                if (confirm('Are you sure you want to clear the logs?')) {{
                    fetch('/clear_logs', {{ method: 'POST' }})
                        .then(() => {{
                            document.getElementById('logContent').innerText = 'Logs cleared...';
                            colorCodeLogs();
                        }});
                }}
            }}
            function colorCodeLogs() {{
                const container = document.getElementById('logContent');
                const lines = container.innerText.split('\\n');
                let coloredHTML = '';
                lines.forEach(line => {{
                    let cssClass = 'log-line';
                    if (line.includes('ERROR') || line.includes('❌') || line.toLowerCase().includes('error')) {{
                        cssClass += ' log-error';
                    }} else if (line.includes('WARNING') || line.includes('⚠️') || line.toLowerCase().includes('warning')) {{
                        cssClass += ' log-warning';
                    }} else if (line.includes('INFO') || line.includes('✅') || line.includes('📍') || line.includes('🚀') || line.includes('🔍') || line.includes('⏳') || line.includes('🔧') || line.includes('🧹') || line.toLowerCase().includes('info')) {{
                        cssClass += ' log-info';
                    }} else if (line.includes('SUCCESS') || line.toLowerCase().includes('success')) {{
                        cssClass += ' log-success';
                    }} else if (line.includes('DEBUG') || line.toLowerCase().includes('debug')) {{
                        cssClass += ' log-debug';
                    }}
                    coloredHTML += `<div class="${{cssClass}}">${{line}}</div>`;
                }});
                container.innerHTML = coloredHTML;
            }}
            colorCodeLogs();
            scrollToBottom();
            document.getElementById('linesForm').addEventListener('submit', function(e) {{
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'theme';
                input.value = currentTheme;
                this.appendChild(input);
            }});
        </script>
    </body>
    </html>
    """

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    log_file = 'hud35.log'
    try:
        with open(log_file, 'w') as f:
            f.write('')
        return 'Logs cleared', 200
    except Exception as e:
        return f'Error clearing logs: {str(e)}', 500

@app.route('/music_stats')
def music_stats():
    """Display music statistics with charts"""
    # Load config for theme
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    current_theme = ui_config.get("theme", "dark")
    
    # Get time period from request
    period = request.args.get('period', '7days')
    try:
        lines = int(request.args.get('lines', 1000))
    except:
        lines = 1000
    
    # Load and filter song data
    songs_data = load_song_data(period)
    
    # Generate statistics
    song_stats, artist_stats = generate_music_stats(songs_data)
    
    # Create chart data and pre-zip for template
    song_chart_data = generate_chart_data(song_stats, 'Songs')
    artist_chart_data = generate_chart_data(artist_stats, 'Artists')
    
    # Pre-zip the data for the template
    song_chart_items = list(zip(song_chart_data['labels'], song_chart_data['data'], song_chart_data['colors']))
    artist_chart_items = list(zip(artist_chart_data['labels'], artist_chart_data['data'], artist_chart_data['colors']))
    
    return render_template_string(MUSIC_STATS_HTML, 
                                song_chart_items=song_chart_items,
                                artist_chart_items=artist_chart_items,
                                period=period,
                                lines=lines,
                                total_plays=len(songs_data),
                                unique_songs=len(song_stats),
                                unique_artists=len(artist_stats),
                                ui_config=ui_config)

@app.route('/clear_song_logs', methods=['POST'])
def clear_song_logs():
    try:
        with open('songs.toml', 'w') as f:
            f.write('# Song play history\n')
            f.write('# Generated by HUD35 Launcher\n\n')
        return 'Song logs cleared', 200
    except Exception as e:
        return f'Error clearing song logs: {str(e)}', 500

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

def log_song_play(song_info):
    global last_logged_song
    current_song = song_info.get('full_track', '').strip()
    if last_logged_song and current_song == last_logged_song:
        logger = logging.getLogger('Launcher')
        logger.info(f"⏭️ Skipping duplicate song: {current_song}")
        return
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        song = song_info.get('song', '').replace('"', '\\"')
        artist = song_info.get('artist', '').replace('"', '\\"')
        full_track = song_info.get('full_track', '').replace('"', '\\"')
        artists = song_info.get('artists', [artist])
        with open('songs.toml', 'a') as f:
            f.write("[[play]]\n")
            f.write(f"timestamp = \"{timestamp}\"\n")
            f.write(f"song = \"{song}\"\n")
            f.write(f"artist = \"{artist}\"\n")
            f.write(f"full_track = \"{full_track}\"\n")
            f.write(f"artists = {artists}\n")
            f.write("\n")
        last_logged_song = current_song
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error logging song play: {e}")

def load_song_data(period='7days'):
    if not os.path.exists('songs.toml'):
        return []
    now = datetime.now()
    if period == '1day':
        threshold = now - timedelta(days=1)
    elif period == '7days':
        threshold = now - timedelta(days=7)
    elif period == '30days':
        threshold = now - timedelta(days=30)
    elif period == '90days':
        threshold = now - timedelta(days=90)
    elif period == 'all':
        threshold = datetime.min
    else:
        threshold = now - timedelta(days=7)
    songs_data = []
    try:
        with open('songs.toml', 'r') as f:
            content = f.read()
        data = toml.loads(content)
        plays = data.get('play', [])
        for play in plays:
            try:
                entry_time = datetime.strptime(play['timestamp'], '%Y-%m-%d %H:%M:%S')
                if entry_time >= threshold:
                    songs_data.append(play)
            except (KeyError, ValueError):
                continue
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error loading song data: {e}")
    return songs_data

def generate_music_stats(songs_data):
    song_counter = Counter()
    artist_counter = Counter()
    for entry in songs_data:
        song = entry.get('song', 'Unknown Song')
        artist = entry.get('artist', 'Unknown Artist')
        song_with_artist = f"{song} - {artist}"
        song_counter[song_with_artist] += 1
        artists = entry.get('artists', [])
        if isinstance(artists, str):
            try:
                artists_clean = artists.strip('[]').replace("'", "").replace('"', '')
                artists_list = [a.strip() for a in artists_clean.split(',')] if artists_clean else []
            except:
                artists_list = [artists]
        else:
            artists_list = artists
        for artist_name in artists_list:
            if artist_name and artist_name != 'Unknown Artist':
                artist_counter[artist_name] += 1
    top_songs = dict(song_counter.most_common(20))
    top_artists = dict(artist_counter.most_common(20))
    return top_songs, top_artists

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
    if is_hud35_running():
        stop_hud35()
    if is_neonwifi_running():
        stop_neonwifi()

def signal_handler(sig, frame):
    logger = logging.getLogger('Launcher')
    logger.info("")
    logger.info("Shutting down launcher...")
    cleanup()
    sys.exit(0)

def main():
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
    if lan_ips:
        for ip in lan_ips:
            logger.info(f"📍 Web UI available at: http://{ip}:5000")
    else:
        logger.info("📍 Web UI available at: http://127.0.0.1:5000")
        logger.info("   (Could not detect LAN IP - using localhost)")
    logger.info("⏹️  Press Ctrl+C to stop the hud35")
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except OSError as e:
        if "Address already in use" in str(e):
            logger.info("Port 5000 busy, trying port 5001...")
            if lan_ips:
                for ip in lan_ips:
                    logger.info(f"📍 Web UI available at: http://{ip}:5001")
            else:
                logger.info("📍 Web UI available at: http://127.0.0.1:5001")
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
            app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
        else:
            raise

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    finally:
        cleanup()