#!/usr/bin/env python3
from flask import Flask, request, redirect, url_for, flash, Response, render_template, send_file, jsonify
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime
from collections import Counter
from functools import wraps
from logging.handlers import RotatingFileHandler
import os, toml, time, requests, subprocess, sys, signal, urllib.parse, socket, logging, threading, json, hashlib, spotipy, io, sqlite3, shutil, re, random

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

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
    "api_keys": {
        "openweather": "",
        "google_geo": "",
        "client_id": "",
        "client_secret": "",
        "lastfm": "",
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
        "rescan_time": 600
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
        "button_y": 24,
        "button_a_action": "clock",
        "button_b_action": "weather",
        "button_x_action": "spotify",
        "button_y_action": "toggle_display",
        "button_a_command": "",
        "button_b_command": "",
        "button_x_command": "",
        "button_y_command": ""
    },
    "logging": {
        "max_log_lines": 10000,
        "max_backup_files": 5
    },
    "ui": {
        "theme": "dark",
        "css_file": "colors.css"
    },
    "api_status": {}
}

hud_process = None
neonwifi_process = None
last_logged_song = None

# ============== HELPER FUNCTIONS ==============

def delete_existing_playlist(playlist_name, sp):
    user_id = sp.current_user()["id"]
    logger = logging.getLogger('Launcher')
    all_playlists = []
    results = sp.current_user_playlists(limit=50)
    all_playlists.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        all_playlists.extend(results['items'])
    matching_playlists = []
    for playlist in all_playlists:
        if (playlist['name'].lower() == playlist_name.lower() and 
            playlist['owner']['id'] == user_id):
            matching_playlists.append(playlist)
    deleted_count = 0
    for playlist in matching_playlists:
        try:
            sp.current_user_unfollow_playlist(playlist['id'])
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete playlist via Spotipy: {e}")
            try:
                headers = {
                    'Authorization': f'Bearer {sp.auth_manager.get_access_token()["access_token"]}'
                }
                url = f"https://api.spotify.com/v1/playlists/{playlist['id']}/followers"
                response = requests.delete(url, headers=headers)
                if response.status_code == 200:
                    deleted_count += 1
                else:
                    logger.error(f"Direct API deletion failed: {response.status_code}")
            except Exception as e2:
                logger.error(f"❌ All deletion methods failed: {e2}")
    return deleted_count

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

def get_active_device(sp):
    try:
        devices = sp.devices()
        if devices and 'devices' in devices:
            for device in devices['devices']:
                if device.get('is_active', False):
                    return device['id']
            if devices['devices']:
                return devices['devices'][0]['id']
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error getting active device: {e}")
    return None

def get_lastfm_similar_tracks(artist_name, track_name, api_key, limit=50):
    if not api_key:
        return []
    lastfm_url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "track.getsimilar",
        "artist": artist_name,
        "track": track_name,
        "api_key": api_key,
        "format": "json",
        "limit": limit
    }
    try:
        response = requests.get(lastfm_url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            similar_tracks = data.get("similartracks", {}).get("track", [])
            return similar_tracks
        else:
            logger = logging.getLogger('Launcher')
            logger.error(f"Last.fm API error: {response.status_code}")
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Last.fm request error: {e}")
    return []

def parse_track_input(input_string):
    separators = [' --- ']
    for sep in separators:
        if sep in input_string:
            parts = input_string.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    for sep in [' - ', ' by ']:
        if sep in input_string:
            idx = input_string.rfind(sep)
            if idx != -1:
                track_name = input_string[:idx].strip()
                artist_name = input_string[idx + len(sep):].strip()
                return track_name, artist_name
    return input_string.strip(), None

def play_playlist(playlist_uri, sp, device_id=None):
    try:
        if not device_id:
            device_id = get_active_device(sp)
        if not device_id:
            logger = logging.getLogger('Launcher')
            logger.warning("No active Spotify device found")
            return False
        sp.start_playback(device_id=device_id, context_uri=playlist_uri)
        return True
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error playing playlist: {e}")
        return False

def rate_limit(min_interval=1):
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

def search_lyrics_for_track(track_name, artist_name):
    try:
        api_url = "https://lrclib.net/api/search"
        params = {
            'track_name': track_name,
            'artist_name': artist_name
        }
        logger = logging.getLogger('Launcher')
        response = requests.get(api_url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json()
            if results:
                first_result = results[0]
                lyrics_id = first_result.get('id')
                if lyrics_id:
                    lyrics_response = requests.get(f"https://lrclib.net/api/get/{lyrics_id}", timeout=10)
                    if lyrics_response.status_code == 200:
                        lyrics_data = lyrics_response.json()
                        return {
                            'success': True,
                            'lyrics': lyrics_data.get('syncedLyrics', ''),
                            'plain_lyrics': lyrics_data.get('plainLyrics', ''),
                            'track_name': lyrics_data.get('trackName', track_name),
                            'artist_name': lyrics_data.get('artistName', artist_name),
                            'album_name': lyrics_data.get('albumName', ''),
                            'duration': lyrics_data.get('duration', 0)
                        }
            return {'success': False, 'error': 'No lyrics found for this track'}
        else:
            logger.error(f"LRCLib API error: {response.status_code}")
            return {'success': False, 'error': f'API returned status code {response.status_code}'}
    except requests.RequestException as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Lyrics search network error: {e}")
        return {'success': False, 'error': f'Network error: {str(e)}'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Lyrics search unexpected error: {e}")
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

def search_spotify_track(track_name, artist_name, sp):
    try:
        result = sp.search(q=f"track:{track_name} artist:{artist_name}", type='track', limit=1)
        items = result['tracks']['items']
        if items:
            return items[0]['id']
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error searching Spotify track: {e}")
    return None

def search_spotify_track_ids(track_list, sp):
    spotify_track_ids = []
    logger = logging.getLogger('Launcher')
    for track in track_list:
        name = track.get('name', '')
        artist = track.get('artist', {}).get('name', '')
        if not name or not artist:
            continue
        try:
            result = sp.search(q=f"track:{name} artist:{artist}", type='track', limit=1)
            items = result['tracks']['items']
            if items:
                track_id = items[0]['id']
                spotify_track_ids.append(track_id)
            else:
                logger.info(f"  Not found on Spotify: {name} by {artist}")
        except Exception as e:
            logger.error(f"  Error searching for {name} by {artist}: {e}")
    return spotify_track_ids

# ============== CONFIGURATION ROUTES ==============

@app.route('/')
def index():
    config = load_config()
    auto_config = config.get("auto_start", {})
    ui_config = config.get("ui", {"theme": "dark"}) 
    config_ready = is_config_ready()
    spotify_configured = bool(config["api_keys"]["client_id"] and config["api_keys"]["client_secret"])
    spotify_authenticated, _ = check_spotify_auth()
    hud_running = is_hud_running()
    neonwifi_running = is_neonwifi_running()
    enable_current_track = config["settings"].get("enable_current_track_display", True)
    return render_template(
        'setup.html', 
        config=config, 
        config_ready=config_ready,
        spotify_configured=spotify_configured,
        spotify_authenticated=spotify_authenticated,
        hud_running=hud_running,
        neonwifi_running=neonwifi_running,
        auto_config=auto_config,
        enable_current_track_display=enable_current_track,
        ui_config=ui_config
    )

@app.route('/advanced_config')
def advanced_config():
    config = load_config()
    ui_config = config.get("ui", DEFAULT_CONFIG["ui"])
    available_css = get_available_css_files()
    spotify_configured = bool(config["api_keys"]["client_id"] and config["api_keys"]["client_secret"])
    spotify_authenticated, _ = check_spotify_auth()
    if 'css_file' not in ui_config or ui_config['css_file'] not in available_css:
        ui_config['css_file'] = DEFAULT_CONFIG["ui"]["css_file"]
    return render_template('advanced_config.html', config=config, ui_config=ui_config, available_css=available_css,spotify_configured=spotify_configured, spotify_authenticated=spotify_authenticated)

@app.route('/check_display_change', methods=['POST'])
def check_display_change():
    current_display = load_config().get("display", {}).get("type", "framebuffer")
    new_display = request.json.get('new_display_type')
    needs_modification = False
    message = ""
    if current_display != "framebuffer" and new_display == "framebuffer":
        needs_modification = True
        message = "Switching to framebuffer display will uncomment 'dtoverlay=tft35a:rotate=90' in /boot/config.txt. A reboot will be required for changes to take effect."
    elif current_display == "framebuffer" and new_display != "framebuffer":
        needs_modification = True
        message = "Switching from framebuffer display will comment out 'dtoverlay=tft35a:rotate=90' in /boot/config.txt. A reboot will be required(unless to dummy) for changes to take effect."
    elif new_display != current_display:
        message = "Changing display type will require a reset of hud for changes to take effect."
    return jsonify({
        'needs_modification': needs_modification,
        'message': message,
        'requires_reboot': new_display != current_display
    })

@app.route('/reset_advanced_config', methods=['POST'])
def reset_advanced_config():
    config = load_config()
    config["display"] = DEFAULT_CONFIG["display"].copy()
    config["api_keys"] = DEFAULT_CONFIG["api_keys"].copy()
    config["settings"] = DEFAULT_CONFIG["settings"].copy()
    config["wifi"] = DEFAULT_CONFIG["wifi"].copy()
    config["buttons"] = DEFAULT_CONFIG["buttons"].copy()
    config["logging"] = DEFAULT_CONFIG["logging"].copy()
    config["clock"] = DEFAULT_CONFIG["clock"].copy()
    preserved_ui = config.get("ui", {}).copy()
    preserved_auto_start = config.get("auto_start", {}).copy()
    config["ui"] = preserved_ui
    config["auto_start"] = preserved_auto_start
    save_config(config)
    flash('success', 'Advanced configuration reset to defaults!')
    return redirect(url_for('advanced_config'))

@app.route('/save_all_config', methods=['POST'])
def save_all_config():
    config = load_config()
    auto_start_hud = 'auto_start_hud' in request.form
    auto_start_neonwifi = 'auto_start_neonwifi' in request.form
    config["auto_start"] = {
        "auto_start_hud": auto_start_hud,
        "auto_start_neonwifi": auto_start_neonwifi
    }
    save_config(config)
    if is_hud_running():
        stop_hud()
        time.sleep(3)
    if auto_start_hud == True:
        start_hud()
    if is_neonwifi_running():
        stop_neonwifi()
        time.sleep(3)
    if auto_start_neonwifi == True:
        start_neonwifi()
    flash('success', 'All settings saved successfully!')
    return redirect(url_for('index'))

@app.route('/save_advanced_config', methods=['POST'])
def save_advanced_config():
    config = load_config()
    auto_start_hud = 'auto_start_hud' in request.form
    auto_start_neonwifi = 'auto_start_neonwifi' in request.form
    if "ui" not in config:
        config["ui"] = {}
    if "api_status" not in config:
        config["api_status"] = {}
    available_css = get_available_css_files()
    selected_css = request.form.get('css_file')
    if selected_css and selected_css in available_css:
        config["ui"]["css_file"] = selected_css
    else:
        config["ui"]["css_file"] = DEFAULT_CONFIG["ui"]["css_file"]
    openweather_key = request.form.get('openweather', '').strip()
    google_geo_key = request.form.get('google_geo', '').strip()
    fallback_input = request.form.get('fallback_city', '').strip()
    normalized_fallback = ""
    if fallback_input:
        is_valid_fallback, fallback_message, normalized_fallback = validate_fallback_city_input(
            fallback_input,
            openweather_key or config["api_keys"].get("openweather", "")
        )
        if not is_valid_fallback:
            config["api_status"]["fallback_city"] = _build_api_status("error", fallback_message)
            save_config(config)
            flash(fallback_message, 'error')
            return redirect(url_for('advanced_config'))
        config["api_status"]["fallback_city"] = _build_api_status("success", f"Using {normalized_fallback}")
    else:
        config["api_status"]["fallback_city"] = _build_api_status("info", "No fallback city set")
    try:
        old_display_type = config.get("display", {}).get("type", "framebuffer")
        new_display_type = request.form.get('display_type', 'framebuffer')
        modify_boot = False
        if old_display_type != new_display_type:
            if request.form.get('modify_boot_config') == 'true':
                modify_boot = True
        config["api_keys"]["openweather"] = openweather_key
        config["api_keys"]["google_geo"] = google_geo_key
        config["api_keys"]["client_id"] = request.form.get('client_id', '').strip()
        config["api_keys"]["client_secret"] = request.form.get('client_secret', '').strip()
        config["api_keys"]["redirect_uri"] = request.form.get('redirect_uri', 'http://127.0.0.1:5000').strip()
        config["api_keys"]["lastfm"] = request.form.get('lastfm', '').strip()
        config["settings"]["fallback_city"] = normalized_fallback
        config["display"]["type"] = new_display_type
        config["display"]["framebuffer"] = request.form.get('framebuffer_device', '/dev/fb1')
        config["display"]["rotation"] = int(request.form.get('rotation', 0))
        if "st7789" not in config["display"]:
            config["display"]["st7789"] = {}
        config["display"]["st7789"]["spi_port"] = int(request.form.get('spi_port', 0))
        config["display"]["st7789"]["spi_cs"] = int(request.form.get('spi_cs', 1))
        config["display"]["st7789"]["dc_pin"] = int(request.form.get('dc_pin', 9))
        config["display"]["st7789"]["backlight_pin"] = int(request.form.get('backlight_pin', 13))
        config["display"]["st7789"]["spi_speed"] = int(request.form.get('spi_speed', 60000000))
        if "buttons" not in config:
            config["buttons"] = {}
        config["buttons"]["button_a"] = int(request.form.get('button_a', 5))
        config["buttons"]["button_b"] = int(request.form.get('button_b', 6))
        config["buttons"]["button_x"] = int(request.form.get('button_x', 16))
        config["buttons"]["button_y"] = int(request.form.get('button_y', 24))
        config["buttons"]["button_a_action"] = request.form.get('button_a_action', 'clock')
        config["buttons"]["button_b_action"] = request.form.get('button_b_action', 'weather')
        config["buttons"]["button_x_action"] = request.form.get('button_x_action', 'spotify')
        config["buttons"]["button_y_action"] = request.form.get('button_y_action', 'toggle_display')
        config["buttons"]["button_a_command"] = request.form.get('button_a_command', '').strip()
        config["buttons"]["button_b_command"] = request.form.get('button_b_command', '').strip()
        config["buttons"]["button_x_command"] = request.form.get('button_x_command', '').strip()
        config["buttons"]["button_y_command"] = request.form.get('button_y_command', '').strip()
        config["wifi"]["ap_ssid"] = request.form.get('ap_ssid', 'Neonwifi-Manager')
        config["wifi"]["ap_ip"] = request.form.get('ap_ip', '192.168.42.1')
        config["wifi"]["rescan_time"] = int(request.form.get('rescan_time', 600))
        config["settings"]["progressbar_display"] = 'progressbar_display' in request.form
        config["settings"]["time_display"] = 'time_display' in request.form
        config["settings"]["start_screen"] = request.form.get('start_screen', 'weather')
        config["settings"]["use_gpsd"] = 'use_gpsd' in request.form
        use_google_geo = 'use_google_geo' in request.form
        config["settings"]["use_google_geo"] = use_google_geo
        config["settings"]["enable_current_track_display"] = 'enable_current_track_display' in request.form
        if "logging" not in config:
            config["logging"] = {}
        config["logging"]["max_log_lines"] = int(request.form.get('max_log_lines', 10000))
        config["logging"]["max_backup_files"] = int(request.form.get('max_backup_files', 5))
        config["api_keys"]["redirect_uri"] = request.form.get('redirect_uri', 'http://127.0.0.1:5000')
        config["clock"]["background"] = request.form.get('clock_background', 'color')
        config["clock"]["color"] = request.form.get('clock_color', '#000000')
        config["clock"]["type"] = request.form.get('clock_type', 'digital')
        config["auto_start"] = {
            "auto_start_hud": auto_start_hud,
            "auto_start_neonwifi": auto_start_neonwifi,
            "check_internet": 'check_internet' in request.form
        }
        if use_google_geo:
            if google_geo_key:
                success, status_message = validate_google_geo_api_key(google_geo_key)
                status_state = "success" if success else "error"
            else:
                status_state = "error"
                status_message = "Google Geolocation enabled but no API key configured"
        else:
            if google_geo_key:
                status_state = "info"
                status_message = "Google Geolocation disabled (key stored but unused)"
            else:
                status_state = "info"
                status_message = "Google Geolocation disabled"
        config["api_status"]["google_geo"] = _build_api_status(status_state, status_message)
        if modify_boot and old_display_type != new_display_type:
            enable_fb = (new_display_type == "framebuffer")
            success, message = modify_boot_config(enable_fb)
            if success:
                flash(f'Configuration saved! {message} Please restart hud for display changes to take effect.', 'success')
            else:
                flash(f'Configuration saved but boot config modification failed: {message}', 'warning')
        elif old_display_type != new_display_type:
            flash('Configuration saved! Please restart hud for display changes to take effect.', 'success')
        else:
            flash('Advanced configuration saved successfully!', 'success')
        save_config(config)
        restart_processes_after_config()
    except Exception as e:
        flash(f'Error saving configuration: {str(e)}', 'error')
    return redirect(url_for('advanced_config'))

@app.route('/toggle_theme', methods=['POST'])
def toggle_theme():
    config = load_config()
    new_theme = request.form.get('theme', 'dark')
    if 'ui' not in config:
        config['ui'] = {}
    config['ui']['theme'] = new_theme
    save_config(config)
    return redirect(request.referrer or url_for('index'))

# ============== APPLICATION CONTROL ROUTES ==============

@app.route('/start_hud', methods=['POST'])
def start_hud_route():
    success, message = start_hud()
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

@app.route('/stop_hud', methods=['POST'])
def stop_hud_route():
    success, message = stop_hud()
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

# ============== SPOTIFY AUTHENTICATION ROUTES ==============

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
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative",
            cache_path=".spotify_cache",
            show_dialog=True
        )
        auth_url = sp_oauth.get_authorize_url()
        ui_config = config.get("ui", DEFAULT_CONFIG["ui"])
        return render_template('spotify_auth.html', auth_url=auth_url, ui_config=ui_config)
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
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative",
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

# ============== SPOTIFY CONTROL ROUTES ==============

@app.route('/spotify_create_similar_playlist', methods=['POST'])
@rate_limit(2.0)
def spotify_create_similar_playlist():
    logger = logging.getLogger('Launcher')
    try:
        track_name = request.json.get('track_name', '').strip()
        artist_name = request.json.get('artist_name', '').strip()
        if not track_name or not artist_name:
            current_track = get_current_track()
            if not current_track.get('has_track'):
                return jsonify({'success': False, 'error': 'No track currently playing and no track specified'})
            track_name = current_track['song']
            artist_name = current_track['artist']
            if '(' in artist_name:
                artist_name = artist_name.split('(')[0].strip()
        logger.info(f"Creating similar playlist for: {track_name} by {artist_name}")
        sp, message = get_spotify_client()
        if not sp:
            return jsonify({'success': False, 'error': message})
        config = load_config()
        lastfm_key = config["api_keys"].get("lastfm", "")
        if not lastfm_key:
            return jsonify({'success': False, 'error': 'Last.fm API key not configured'})
        original_track_id = search_spotify_track(track_name, artist_name, sp)
        if not original_track_id:
            return jsonify({'success': False, 'error': f'Track "{track_name}" by {artist_name} not found on Spotify'})
        similar_tracks = get_lastfm_similar_tracks(artist_name, track_name, lastfm_key, limit=75)
        if not similar_tracks:
            logger.warning(f"No similar tracks found on Last.fm for: {track_name} by {artist_name}")
            return jsonify({'success': False, 'error': 'No similar tracks found on Last.fm'})
        not_found_count = 0
        spotify_track_ids = []
        logger.info("Searching for similar tracks on Spotify...")
        for track in similar_tracks:
            name = track.get('name', '')
            artist = track.get('artist', {}).get('name', '')
            if not name or not artist:
                continue
            try:
                result = sp.search(q=f"track:{name} artist:{artist}", type='track', limit=1)
                items = result['tracks']['items']
                if items:
                    track_id = items[0]['id']
                    spotify_track_ids.append(track_id)
                else:
                    logger.info(f"  Not found on Spotify: {name} by {artist}")
                    not_found_count += 1
            except Exception as e:
                logger.error(f"  Error searching for {name} by {artist}: {e}")
                not_found_count += 1
        extra_songs_needed = not_found_count
        extra_track_ids = []
        if extra_songs_needed > 0 and spotify_track_ids:
            logger.info(f"Adding {extra_songs_needed} extra song(s) to compensate for {not_found_count} not found")
            extra_similar_tracks = get_lastfm_similar_tracks(artist_name, track_name, lastfm_key, limit=75 + extra_songs_needed * 2)
            if extra_similar_tracks:
                already_tried = {(track.get('name', '').lower(), track.get('artist', {}).get('name', '').lower()) for track in similar_tracks}
                for extra_track in extra_similar_tracks:
                    if len(extra_track_ids) >= extra_songs_needed:
                        break
                    name = extra_track.get('name', '')
                    artist = extra_track.get('artist', {}).get('name', '')
                    if not name or not artist:
                        continue
                    if (name.lower(), artist.lower()) in already_tried:
                        continue
                    try:
                        result = sp.search(q=f"track:{name} artist:{artist}", type='track', limit=1)
                        items = result['tracks']['items']
                        if items:
                            track_id = items[0]['id']
                            if track_id not in spotify_track_ids and track_id not in extra_track_ids:
                                extra_track_ids.append(track_id)
                                logger.info(f"  Found extra track: {name} by {artist}")
                    except Exception as e:
                        logger.error(f"  Error searching for extra track {name} by {artist}: {e}")
        all_track_ids = [original_track_id] + spotify_track_ids + extra_track_ids
        random.shuffle(spotify_track_ids)
        all_track_ids = [original_track_id] + spotify_track_ids + extra_track_ids
        playlist_name = f"NeonDisplay Recommends"
        deleted_count = delete_existing_playlist(playlist_name, sp)
        user_id = sp.current_user()["id"]
        description = (f"Tracks similar to {track_name} by {artist_name} - Generated by NeonDisplay ")
        playlist = sp.user_playlist_create(
            user=user_id,
            name=playlist_name,
            public=False,
            description=description
        )
        if all_track_ids:
            for i in range(0, len(all_track_ids), 100):
                batch = all_track_ids[i:i+100]
                sp.user_playlist_add_tracks(user_id, playlist["id"], batch)
            time.sleep(1)
            play_success = play_playlist(playlist['uri'], sp)
            return jsonify({
                'success': True,
                'message': f'Created playlist "{playlist_name}" with {len(all_track_ids)} tracks',
                'playlist_name': playlist_name,
                'playlist_url': playlist['external_urls']['spotify'],
                'track_count': len(all_track_ids),
                'found_count': len(spotify_track_ids),
                'not_found_count': not_found_count,
                'extra_added_count': len(extra_track_ids),
                'auto_played': play_success,
                'random_order': True
            })
        else:
            return jsonify({'success': False, 'error': 'No tracks to add to playlist'})
    except Exception as e:
        logger.error(f"Error creating similar playlist: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error creating playlist: {str(e)}'})

@app.route('/spotify_generate_from_input', methods=['POST'])
@rate_limit(2.0)
def spotify_generate_from_input():
    logger = logging.getLogger('Launcher')
    try:
        input_string = request.json.get('input_string', '').strip()
        if not input_string:
            return jsonify({'success': False, 'error': 'No input string provided'})
        track_name, artist_name = parse_track_input(input_string)
        if artist_name is None:
            sp, message = get_spotify_client()
            if not sp:
                return jsonify({'success': False, 'error': message})
            result = sp.search(q=f"track:{track_name}", type='track', limit=1)
            items = result['tracks']['items']
            if not items:
                return jsonify({'success': False, 'error': f'Track "{track_name}" not found on Spotify'})
            track_name = items[0]['name']
            artist_name = items[0]['artists'][0]['name']
        sp, message = get_spotify_client()
        if not sp:
            return jsonify({'success': False, 'error': message})
        config = load_config()
        lastfm_key = config["api_keys"].get("lastfm", "")
        if not lastfm_key:
            return jsonify({'success': False, 'error': 'Last.fm API key not configured'})
        original_track_id = search_spotify_track(track_name, artist_name, sp)
        if not original_track_id:
            return jsonify({'success': False, 'error': f'Track "{track_name}" by {artist_name} not found on Spotify'})
        similar_tracks = get_lastfm_similar_tracks(artist_name, track_name, lastfm_key, limit=75)
        if not similar_tracks:
            logger.warning(f"No similar tracks found on Last.fm for: {track_name} by {artist_name}")
            return jsonify({'success': False, 'error': 'No similar tracks found on Last.fm'})
        not_found_count = 0
        spotify_track_ids = []
        logger.info("Searching for similar tracks on Spotify...")
        for track in similar_tracks:
            name = track.get('name', '')
            artist = track.get('artist', {}).get('name', '')
            if not name or not artist:
                continue
            try:
                result = sp.search(q=f"track:{name} artist:{artist}", type='track', limit=1)
                items = result['tracks']['items']
                if items:
                    track_id = items[0]['id']
                    spotify_track_ids.append(track_id)
                else:
                    logger.info(f"  Not found on Spotify: {name} by {artist}")
                    not_found_count += 1
            except Exception as e:
                logger.error(f"  Error searching for {name} by {artist}: {e}")
                not_found_count += 1
        extra_songs_needed = not_found_count
        extra_track_ids = []
        if extra_songs_needed > 0 and spotify_track_ids:
            logger.info(f"Adding {extra_songs_needed} extra song(s) to compensate for {not_found_count} not found")
            extra_similar_tracks = get_lastfm_similar_tracks(artist_name, track_name, lastfm_key, limit=75 + extra_songs_needed * 2)
            if extra_similar_tracks:
                already_tried = {(track.get('name', '').lower(), track.get('artist', {}).get('name', '').lower()) for track in similar_tracks}
                for extra_track in extra_similar_tracks:
                    if len(extra_track_ids) >= extra_songs_needed:
                        break
                    name = extra_track.get('name', '')
                    artist = extra_track.get('artist', {}).get('name', '')
                    if not name or not artist:
                        continue
                    if (name.lower(), artist.lower()) in already_tried:
                        continue
                    try:
                        result = sp.search(q=f"track:{name} artist:{artist}", type='track', limit=1)
                        items = result['tracks']['items']
                        if items:
                            track_id = items[0]['id']
                            if track_id not in spotify_track_ids and track_id not in extra_track_ids:
                                extra_track_ids.append(track_id)
                                logger.info(f"  Found extra track: {name} by {artist}")
                    except Exception as e:
                        logger.error(f"  Error searching for extra track {name} by {artist}: {e}")
        all_track_ids = [original_track_id] + spotify_track_ids + extra_track_ids
        random.shuffle(spotify_track_ids)
        all_track_ids = [original_track_id] + spotify_track_ids + extra_track_ids
        playlist_name = f"NeonDisplay Recommends"
        deleted_count = delete_existing_playlist(playlist_name, sp)
        user_id = sp.current_user()["id"]
        description = (f"Tracks similar to {track_name} by {artist_name} - Generated by NeonDisplay ")
        playlist = sp.user_playlist_create(
            user=user_id,
            name=playlist_name,
            public=False,
            description=description
        )
        if all_track_ids:
            for i in range(0, len(all_track_ids), 100):
                batch = all_track_ids[i:i+100]
                sp.user_playlist_add_tracks(user_id, playlist["id"], batch)
            time.sleep(1)
            play_success = play_playlist(playlist['uri'], sp)
            return jsonify({
                'success': True,
                'message': f'Created playlist "{playlist_name}" with {len(all_track_ids)} tracks',
                'playlist_name': playlist_name,
                'playlist_url': playlist['external_urls']['spotify'],
                'track_count': len(all_track_ids),
                'found_count': len(spotify_track_ids),
                'not_found_count': not_found_count,
                'extra_added_count': len(extra_track_ids),
                'auto_played': play_success,
                'random_order': True
            })
        else:
            return jsonify({'success': False, 'error': 'No tracks to add to playlist'})
    except Exception as e:
        logger.error(f"Error generating playlist from input: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/spotify_next', methods=['POST'])
@rate_limit(0.5)
def spotify_next():
    if not check_internet_connection(timeout=3):
        return {'success': False, 'error': 'No internet connection'}
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

@app.route('/spotify_play', methods=['POST'])
@rate_limit(0.5)
def spotify_play():
    if not check_internet_connection(timeout=3):
        return {'success': False, 'error': 'No internet connection'}
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

@app.route('/spotify_play_context', methods=['POST'])
@rate_limit(0.5)
def spotify_play_context():
    logger = logging.getLogger('Launcher')
    try:
        context_uri = request.json.get('uri')
        name = request.json.get('name', 'Unknown Context')
        sp, message = get_spotify_client()
        if not sp:
            flash(message, 'error')
            return jsonify({'success': False, 'error': message})
        sp.start_playback(context_uri=context_uri)
        logger.info(f"▶ Started playback of context: {name} ({context_uri})")
        flash(f'Playing: {name}', 'success')
        return jsonify({'success': True, 'message': f'Started playing {name}'})
    except Exception as e:
        error_message = f"Spotify play context error: {str(e)}"
        logger.error(error_message)
        flash(f'Error playing playlist/context: {str(e)}', 'error')
        return jsonify({'success': False, 'error': error_message})

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

@app.route('/spotify_previous', methods=['POST'])
@rate_limit(0.5)
def spotify_previous():
    if not check_internet_connection(timeout=3):
        return {'success': False, 'error': 'No internet connection'}
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

@app.route('/spotify_shuffle_queue', methods=['POST'])
@rate_limit(0.5)
def spotify_shuffle_queue():
    logger = logging.getLogger('Launcher')
    try:
        sp, message = get_spotify_client()
        if not sp:
            return jsonify({'success': False, 'error': message})
        current_state = sp.current_playback()
        shuffle_state = not current_state.get('shuffle_state', False) if current_state else True
        sp.shuffle(shuffle_state)
        action = "Enabled shuffle" if shuffle_state else "Disabled shuffle"
        logger.info(f"🔀 {action}")
        return jsonify({'success': True, 'message': f'{action} for playback.'})
    except Exception as e:
        error_message = f"Spotify shuffle error: {str(e)}"
        logger.error(error_message)
        return jsonify({'success': False, 'error': error_message})

@app.route('/spotify_shuffle_toggle', methods=['POST'])
def spotify_shuffle_toggle():
    logger = logging.getLogger('Launcher')
    try:
        sp, message = get_spotify_client()
        if not sp:
            return {'success': False, 'error': message}
        playback = sp.current_playback()
        if not playback:
            return {'success': False, 'error': 'No active device'}
        current = playback.get("shuffle_state", False)
        if current:
            new_state = False
        else:
            new_state = True
        try:
            sp.shuffle(new_state)
            current_position_ms = playback.get('progress_ms', 0)
            if current_position_ms is not None:
                try:
                    time.sleep(0.3)
                    sp.seek_track(current_position_ms)
                except:
                    pass
            time.sleep(0.5)
            updated_playback = sp.current_playback()
            actual_state = updated_playback.get("shuffle_state", new_state) if updated_playback else new_state
            return {
                "success": True,
                "requested_state": int(actual_state),
                "message": f"Shuffle {'ON' if actual_state else 'OFF'}"
            }
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 404:
                logger.warning(f"Shuffle API error (possibly Smart Shuffle): {e}")
                if new_state == False:
                    return {
                        "success": True,
                        "requested_state": 0,
                        "message": "Shuffle OFF"
                    }
                else:
                    return {
                        "success": False,
                        "error": "Cannot enable shuffle. Smart Shuffle may be active. Please disable it in Spotify app.",
                        "is_smart_shuffle": True
                    }
            else:
                raise
    except Exception as e:
        logger.error(f"Shuffle toggle error: {e}")
        return {"success": False, "error": str(e)}

@app.route('/spotify_volume', methods=['POST'])
@rate_limit(0.5)
def spotify_volume():
    if not check_internet_connection(timeout=3):
        return {'success': False, 'error': 'No internet connection'}
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

# ============== SPOTIFY DATA ROUTES ==============

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

@app.route('/spotify_skip_to_track', methods=['POST'])
@rate_limit(0.5)
def spotify_skip_to_track():
    logger = logging.getLogger('Launcher')
    try:
        track_uri = request.json.get('track_uri', '').strip()
        if not track_uri:
            logger.error("No track URI provided")
            return jsonify({'success': False, 'error': 'No track URI provided'})
        track_name = request.json.get('track_name', 'Unknown Track')
        logger.info(f"Attempting to skip to track: {track_name} ({track_uri})")
        sp, message = get_spotify_client()
        if not sp:
            logger.error(f"Spotify client error: {message}")
            return jsonify({'success': False, 'error': message})
        current_playback = sp.current_playback()
        if not current_playback:
            logger.error("No active playback")
            return jsonify({'success': False, 'error': 'No active playback'})
        current_track = current_playback.get('item')
        if current_track and current_track.get('uri') == track_uri:
            logger.info("Track is already playing")
            return jsonify({'success': True, 'message': 'Track is already playing'})
        try:
            queue = sp.queue()
            queue_tracks = queue.get('queue', []) if queue else []
            found_index = -1
            for i, queue_track in enumerate(queue_tracks):
                if queue_track.get('uri') == track_uri:
                    found_index = i
                    break
            if found_index >= 0:
                logger.info(f"Track found at position {found_index + 1} in queue")
                for _ in range(found_index + 1):
                    sp.next_track()
                    time.sleep(0.3)
                logger.info(f"Skipped to track at position {found_index + 1}")
                return jsonify({
                    'success': True, 
                    'message': f'Now playing "{track_name}"'
                })
        except Exception as e:
            logger.warning(f"Error checking queue: {e}")
        logger.info(f"Track not in immediate queue, playing directly")
        sp.start_playback(uris=[track_uri])
        return jsonify({
            'success': True, 
            'message': f'Playing "{track_name}"'
        })
    except Exception as e:
        logger.error(f"General error in skip_to_track: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/spotify_device_status', methods=['GET'])
def spotify_device_status():
    try:
        if os.path.exists('.current_track_state.toml'):
            state_data = toml.load('.current_track_state.toml')
            device_status = state_data.get('device_status', {})
            if device_status:
                return {
                    'success': True,
                    'has_active_device': device_status.get('has_active_device', False),
                    'device_name': device_status.get('device_name', ''),
                    'cached': True
                }
            track_data = state_data.get('current_track', {})
            timestamp = track_data.get('timestamp', 0)
            if time.time() - timestamp < 5:
                has_device = track_data.get('device_active', False)
                device_name = track_data.get('device_name', '')
                return {
                    'success': True,
                    'has_active_device': has_device,
                    'device_name': device_name if has_device else None,
                    'cached': True
                }
        return {'success': False, 'has_active_device': False, 'error': 'No cached device status'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error checking device status: {e}")
        return {'success': False, 'has_active_device': False, 'error': str(e)}

@app.route('/spotify_get_queue', methods=['GET'])
def spotify_get_queue():
    try:
        if os.path.exists('.current_track_state.toml'):
            state_data = toml.load('.current_track_state.toml')
            queue_data = state_data.get('queue', [])
            current_track = state_data.get('current_track', {})
            timestamp = current_track.get('timestamp', 0)
            if queue_data and (time.time() - timestamp < 10):
                return jsonify({'success': True, 'queue': queue_data, 'cached': True})
        return jsonify({
            'success': True, 
            'queue': [],
            'cached': False,
            'message': 'Queue updating...'
        })
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify get queue error: {str(e)}")
        return jsonify({
            'success': True,
            'queue': [],
            'cached': False,
            'error': str(e)
        })

@app.route('/spotify_get_shuffle_state', methods=['GET'])
def spotify_get_shuffle_state():
    try:
        if os.path.exists('.current_track_state.toml'):
            state = toml.load('.current_track_state.toml')
            track = state.get("current_track", {})
            timestamp = track.get("timestamp", 0)
            shuffle = track.get("shuffle_state", False)
            if time.time() - timestamp < 30:
                return jsonify({
                    "success": True,
                    "is_shuffling": shuffle,
                    "cached": True,
                    "timestamp": timestamp
                })
        return jsonify({"success": False, "error": "No state"})
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error getting shuffle state: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/spotify_get_volume', methods=['GET'])
def spotify_get_volume():
    try:
        if os.path.exists('.current_track_state.toml'):
            state_data = toml.load('.current_track_state.toml')
            track_data = state_data.get('current_track', {})
            cached_volume = track_data.get('volume_percent')
            if cached_volume is not None:
                return jsonify({'success': True, 'volume': cached_volume, 'cached': True})
        return jsonify({'success': True, 'volume': 50, 'cached': False})
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Get volume error: {str(e)}")
        return jsonify({'success': False, 'error': str(e), 'volume': 50})

@app.route('/spotify_search', methods=['POST'])
@rate_limit(1.0)
def spotify_search():
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    try:
        query = request.form.get('query', '').strip()
        if not query:
            flash('Please enter a search term', 'error')
            return render_template('search_results.html', 
                                query='', 
                                tracks=[],
                                playlists=[],
                                ui_config=ui_config)
        sp, message = get_spotify_client()
        if not sp:
            flash(f'Spotify error: {message}', 'error')
            return render_template('search_results.html', 
                                query=query, 
                                tracks=[],
                                playlists=[],
                                ui_config=ui_config)
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
        return render_template('search_results.html', 
                            query=query, 
                            tracks=tracks,
                            playlists=[],
                            ui_config=ui_config)
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Spotify search error: {str(e)}")
        flash(f'Search error: {str(e)}', 'error')
        return render_template('search_results.html', 
                            query=request.form.get('query', ''), 
                            tracks=[],
                            playlists=[],
                            ui_config=ui_config)

@app.route('/spotify_search_playlist', methods=['POST'])
@rate_limit(1.0)
def spotify_search_playlist():
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    logger = logging.getLogger('Launcher')
    try:
        query = request.form.get('query', '').strip()
        if not query:
            flash('Please enter a playlist name', 'error')
            return render_template('search_results.html', 
                                query='', 
                                tracks=[],
                                playlists=[],
                                ui_config=ui_config)
        sp, message = get_spotify_client()
        if not sp:
            flash(f'Spotify error: {message}', 'error')
            return render_template('search_results.html', 
                                query=query, 
                                tracks=[],
                                playlists=[],
                                ui_config=ui_config)
        results = sp.search(q=query, type='playlist', limit=20)
        playlists = []
        if results and 'playlists' in results and results['playlists']['items']:
            for item in results['playlists']['items']:
                if not item: continue
                image_url = None
                if item['images']:
                    image_url = item['images'][0]['url']
                playlists.append({
                    'name': item['name'],
                    'owner': item['owner']['display_name'],
                    'tracks_total': item['tracks']['total'],
                    'uri': item['uri'],
                    'image_url': image_url
                })
        return render_template('search_results.html', 
                            query=query, 
                            tracks=[],
                            playlists=playlists,
                            ui_config=ui_config)
    except Exception as e:
        logger.error(f"Spotify playlist search error: {str(e)}")
        flash(f'Playlist search error: {str(e)}', 'error')
        return render_template('search_results.html', 
                            query=request.form.get('query', ''), 
                            tracks=[],
                            playlists=[],
                            ui_config=ui_config)

# ============== WEATHER AND DATA ROUTES ==============

@app.route('/api/current_weather')
def api_current_weather():
    try:
        weather_file = '.weather_state.toml'
        if os.path.exists(weather_file):
            state_data = toml.load(weather_file)
            weather_data = state_data.get('weather', {})
            timestamp = weather_data.get('timestamp', 0)
            if time.time() - timestamp < 7200:
                return {
                    'success': True,
                    'weather': weather_data,
                    'timestamp': datetime.now().isoformat()
                }
        return {
            'success': True,
            'weather': {
                'city': 'Weather data loading...',
                'temp': 0,
                'description': 'Please wait',
                'icon_id': '',
                'timestamp': time.time()
            },
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error getting weather data: {e}")
        return {
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

@app.route('/api/current_track')
def api_current_track():
    current_track = get_current_track()
    return {
        'track': current_track,
        'timestamp': datetime.now().isoformat()
    }

# ============== LOG AND STATS ROUTES ==============

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    backup_folder = "backuplogs"
    log_file = os.path.join(backup_folder, 'neondisplay.log')
    try:
        clear_option = request.form.get('clear_option', 'current')
        if clear_option == 'all':
            backups_cleared = 0
            for i in range(1, 100):
                backup_file = os.path.join(backup_folder, f"neondisplay.log.{i}")
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                    backups_cleared += 1
                else:
                    break
            message = f'Backup logs cleared ({backups_cleared} files removed)'
        else:
            logger = logging.getLogger('Launcher')
            for handler in logger.handlers[:]:
                if isinstance(handler, RotatingFileHandler):
                    handler.close()
                    logger.removeHandler(handler)
            if os.path.exists(log_file):
                os.remove(log_file)
            config = load_config()
            log_config = config.get("logging", {})
            max_lines = log_config.get("max_log_lines", 10000)
            max_bytes = max_lines * 100  
            backup_count = log_config.get("max_backup_files", 5)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes, 
                backupCount=backup_count
            )
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            message = 'Current log cleared successfully'
        return message, 200
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f'Error clearing logs: {str(e)}')
        return f'Error clearing logs: {str(e)}', 500

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

@app.route('/music_stats')
def music_stats():
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    try:
        lines = int(request.args.get('lines', 1000))
    except:
        lines = 1000
    song_stats, artist_stats, total_plays, unique_songs, unique_artists = generate_music_stats(lines)
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

@app.route('/music_stats_data')
def music_stats_data():
    try:
        lines = int(request.args.get('lines', 1000))
    except:
        lines = 1000
    song_stats, artist_stats, total_plays, unique_songs, unique_artists = generate_music_stats(lines)
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

@app.route('/view_logs')
def view_logs():
    lines = request.args.get('lines', 100, type=int)
    live = request.args.get('live', False, type=bool)
    config = load_config()
    ui_config = config.get("ui", {"theme": "dark"})
    current_theme = ui_config.get("theme", "dark")
    backup_folder = "backuplogs"
    log_file = os.path.join(backup_folder, 'neondisplay.log')
    backup_count = count_backup_logs()
    if not os.path.exists(log_file):
        log_content = "Log file does not exist. It will be created when there are log messages.\n\n"
        log_content += f"Log file path: {os.path.abspath(log_file)}"
        if live:
            return log_content
        return render_template('logs.html',
            log_content=log_content,
            lines=lines,
            current_theme=current_theme,
            ui_config=ui_config,
            backup_count=backup_count
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
        current_theme=current_theme,
        ui_config=ui_config,
        backup_count=backup_count
    )

# ============== LYRICS ROUTES ==============

@app.route('/lyrics/current')
def get_current_track_lyrics():
    try:
        current_track = get_current_track()
        if not current_track.get('has_track') or current_track.get('song') in ['No track playing', 'Error loading track']:
            return {'success': False, 'error': 'No track currently playing'}
        track_name = current_track['song']
        artist_name = current_track['artist']
        if '(' in artist_name:
            artist_name = artist_name.split('(')[0].strip()
        result = search_lyrics_for_track(track_name, artist_name)
        return result
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Current track lyrics error: {e}")
        return {'success': False, 'error': f'Error getting current track lyrics: {str(e)}'}

@app.route('/lyrics/search')
def search_lyrics():
    track_name = request.args.get('track_name', '').strip()
    artist_name = request.args.get('artist_name', '').strip()
    if not track_name or not artist_name:
        return {'success': False, 'error': 'Track name and artist name are required'}
    try:
        api_url = f"https://lrclib.net/api/search"
        params = {'track_name': track_name,'artist_name': artist_name}
        response = requests.get(api_url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json()
            if results:
                first_result = results[0]
                lyrics_id = first_result.get('id')
                if lyrics_id:
                    lyrics_response = requests.get(f"https://lrclib.net/api/get/{lyrics_id}", timeout=10)
                    if lyrics_response.status_code == 200:
                        lyrics_data = lyrics_response.json()
                        return {'success': True,'lyrics': lyrics_data.get('syncedLyrics', ''),'plain_lyrics': lyrics_data.get('plainLyrics', ''),'track_name': lyrics_data.get('trackName', track_name),'artist_name': lyrics_data.get('artistName', artist_name),'album_name': lyrics_data.get('albumName', ''),'duration': lyrics_data.get('duration', 0)}
            return {'success': False, 'error': 'No lyrics found for this track'}
        else:
            return {'success': False, 'error': f'API returned status code {response.status_code}'}
    except requests.RequestException as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Lyrics search error: {e}")
        return {'success': False, 'error': f'Network error: {str(e)}'}
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Lyrics search unexpected error: {e}")
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

# ============== MISCELLANEOUS ROUTES ==============

@app.context_processor
def utility_processor():
    return dict(zip=zip)

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
    playlists_json = request.args.get('playlists', '[]')
    try:
        playlists = json.loads(playlists_json)
    except:
        playlists = []
    return render_template('search_results.html', 
                        query=query, 
                        tracks=tracks,
                        playlists=playlists,
                        ui_config=ui_config)

@app.route('/status/hud')
def status_hud():
    return {'running': is_hud_running()}

@app.route('/status/neonwifi')
def status_neonwifi():
    return {'running': is_neonwifi_running()}

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
            time.sleep(2)
    return Response(generate(), mimetype='text/event-stream')

# ============== CONFIGURATION FUNCTIONS ==============
    
def get_available_css_files():
    static_dir = app.static_folder 
    if not os.path.isdir(static_dir):
        return ["colors.css"] 
    css_files = [f for f in os.listdir(static_dir) if f.endswith('.css')]
    if not css_files:
        return ["colors.css"] 
    css_files.sort() 
    return css_files

def is_config_ready():
    config = load_config()
    return all([
        config["api_keys"]["openweather"],
        config["api_keys"]["client_id"], 
        config["api_keys"]["client_secret"],
    ])

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f:
            toml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = toml.load(f)
            if "api_status" not in config:
                config["api_status"] = {}
            return config
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Using default configuration")
        return DEFAULT_CONFIG.copy()


def _build_api_status(state, message):
    return {
        "state": state,
        "message": message,
        "checked_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    }


def validate_google_geo_api_key(api_key):
    if not api_key:
        return False, "No API key configured"
    url = "https://www.googleapis.com/geolocation/v1/geolocate"
    try:
        response = requests.post(f"{url}?key={api_key}", json={}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            accuracy = data.get("accuracy")
            if accuracy is not None:
                return True, f"Success (±{int(accuracy)}m accuracy)"
            return True, "Success"
        try:
            error_payload = response.json()
            message = error_payload.get('error', {}).get('message', response.text)
        except ValueError:
            message = response.text
        return False, f"{response.status_code}: {message.strip()}"
    except requests.exceptions.RequestException as exc:
        return False, f"Request failed: {exc}"


def validate_fallback_city_input(city_value, openweather_key):
    if not city_value:
        return False, "Fallback city is required in the format City,Country or City,State,Country", None
    parts = [part.strip() for part in city_value.split(',') if part.strip()]
    if len(parts) < 2:
        return False, "Fallback city must include at least City and Country (e.g., London,UK)", None
    if len(parts) > 3:
        return False, "Too many commas. Use City,Country or City,State,Country", None
    city = parts[0]
    state = None
    if len(parts) == 2:
        country = parts[1]
    else:
        state = parts[1]
        country = parts[2]
    if len(country) != 2 or not country.isalpha():
        return False, "Country must be a two-letter ISO code (e.g., US, UK, DE)", None
    country = country.upper()
    if state:
        if len(state) != 2 or not state.isalpha():
            return False, "State must be a two-letter code (e.g., IA, CA)", None
        state = state.upper()
    normalized_parts = [city]
    if state:
        normalized_parts.append(state)
    normalized_parts.append(country)
    normalized_value = ", ".join(normalized_parts)
    if not openweather_key:
        return False, "OpenWeather API key required to validate fallback city", None
    try:
        response = requests.get(
            "http://api.openweathermap.org/geo/1.0/direct",
            params={"q": normalized_value, "limit": 1, "appid": openweather_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            return False, "Error. Format: City, Country. For US: City, State, Country.", None
        return True, "Fallback city validated with OpenWeather", normalized_value
    except requests.exceptions.RequestException as exc:
        return False, f"Failed to validate fallback city: {exc}", None

def modify_boot_config(enable_framebuffer):
    logger = logging.getLogger('Launcher')
    overlay_line = "dtoverlay=tft35a:rotate=90"
    try:
        with open('/boot/config.txt', 'r') as f:
            lines = f.readlines()
        shutil.copy2('/boot/config.txt', '/boot/config.txt.backup')
        logger.info("Created backup at /boot/config.txt.backup")
        modified = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if enable_framebuffer:
                if stripped == f'#{overlay_line}':
                    new_lines.append(f'{overlay_line}\n')
                    modified = True
                elif stripped == overlay_line:
                    new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                if stripped == overlay_line:
                    new_lines.append(f'#{overlay_line}\n')
                    modified = True
                elif stripped == f'#{overlay_line}':
                    new_lines.append(line)
                else:
                    new_lines.append(line)
        if enable_framebuffer and not any(overlay_line in line for line in lines):
            new_lines.append(f'\n# TFT Display Configuration\n')
            new_lines.append(f'{overlay_line}\n')
            modified = True
        if modified:
            with open('/boot/config.txt', 'w') as f:
                f.writelines(new_lines)
            return True, "Successfully modified /boot/config.txt"
        else:
            return True, "/boot/config.txt already in correct state"
    except PermissionError:
        error_msg = "Permission denied. Run with sudo or adjust permissions."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Error modifying /boot/config.txt: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        toml.dump(config, f)

# ============== SPOTIFY FUNCTIONS ==============

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
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative",
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
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative",
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

def safe_check_spotify_auth():
    if not check_internet_connection(timeout=3):
        return False, "No internet connection"
    return check_spotify_auth()

# ============== PROCESS MANAGEMENT FUNCTIONS ==============

def is_hud_running():
    global hud_process
    if hud_process is not None:
        if hud_process.poll() is None:
            result = True
        else:
            hud_process = None
            result = False
    else:
        try:
            result = bool(subprocess.run(['pgrep', '-f', 'hud.py'], 
                            capture_output=True, text=True).stdout.strip())
        except Exception:
            result = False
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

def start_hud():
    global hud_process, last_logged_song
    logger = logging.getLogger('Launcher')
    if is_hud_running():
        return False, "HUD is already running"
    try:
        hud_process = subprocess.Popen(
            [sys.executable, 'hud.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        def log_hud_output():
            for line in iter(hud_process.stdout.readline, ''):
                if line.strip():
                    logger.info(f"[HUD] {line.strip()}")
                    song_info = parse_song_from_log(line)
                    if song_info:
                        update_song_count(song_info)
        def monitor_current_track_state():
            while hud_process and hud_process.poll() is None:
                log_current_track_state()
                time.sleep(2)
        output_thread = threading.Thread(target=log_hud_output)
        output_thread.daemon = True
        output_thread.start()
        track_monitor_thread = threading.Thread(target=monitor_current_track_state)
        track_monitor_thread.daemon = True
        track_monitor_thread.start()
        time.sleep(2)
        if hud_process.poll() is None:
            return True, "HUD started successfully"
        else:
            return False, "HUD failed to start (check neondisplay.log for details)"
    except Exception as e:
        logger.error(f"Error starting HUD: {str(e)}")
        return False, f"Error starting HUD: {str(e)}"

def stop_hud():
    global hud_process, last_logged_song
    logger = logging.getLogger('Launcher')
    if not is_hud_running():
        return False, "HUD is not running"
    try:
        logger.info("Stopping HUD...")
        hud_process.terminate()
        try:
            hud_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            hud_process.kill()
            hud_process.wait()
        hud_process = None
        last_logged_song = None
        clear_track_state_file()
        logger.info("HUD stopped successfully")
        return True, "HUD stopped successfully"
    except Exception as e:
        logger.error(f"Error stopping HUD: {str(e)}")
        return False, f"Error stopping HUD: {str(e)}"

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
            return False, "neonwifi failed to start (check neondisplay.log for details)"
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

# ============== NETWORK FUNCTIONS ==============

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

# ============== AUTO-LAUNCH FUNCTIONS ==============

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
    if auto_config.get("auto_start_hud", True):
        spotify_authenticated, _ = check_spotify_auth()
        config_ready = is_config_ready()
        if config_ready and spotify_authenticated:
            start_hud()
            logger.info("✅ HUD auto-started")
        else:
            logger.warning("⚠️ HUD not auto-started: configuration incomplete")

def restart_processes_after_config():
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
            if process_name.lower() == 'hud':
                subprocess.run(['pkill', '-f', 'hud.py'], check=False)
            else:
                subprocess.run(['pkill', '-f', 'neonwifi.py'], check=False)
            time.sleep(2)
        success, message = start_func()
        if not success:
            flash('error', f'Error starting {process_name}: {message}')
    was_hud_running = is_hud_running()
    if was_hud_running:
        restart_process('HUD', stop_hud, start_hud, is_hud_running)
    was_neonwifi_running = is_neonwifi_running()
    if was_neonwifi_running:
        restart_process('neonwifi', stop_neonwifi, start_neonwifi, is_neonwifi_running)

# ============== LOGGING FUNCTIONS ==============

def setup_logging():
    logging.getLogger().handlers = []
    logger = logging.getLogger('Launcher')
    logger.handlers = []
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    try:
        config = load_config()
        log_config = config.get("logging", {})
        max_lines = log_config.get("max_log_lines", 10000)
        max_bytes = max_lines * 100  
        backup_count = log_config.get("max_backup_files", 5)
        backup_folder = "backuplogs"
        os.makedirs(backup_folder, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(backup_folder, 'neondisplay.log'),
            maxBytes=max_bytes, 
            backupCount=backup_count
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        log_file_path = os.path.join(backup_folder, 'neondisplay.log')
        if not os.path.exists(log_file_path) or os.path.getsize(log_file_path) == 0:
            with open(log_file_path, 'a') as f:
                f.write(f"Log file initialized at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        logger.info("✅ Logging system initialized - console and file handlers active")
    except Exception as e:
        print(f"Failed to setup file logging: {e}")
        logger.error(f"File logging setup failed: {e}")
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.WARNING)
    if not werkzeug_logger.handlers:
        console_handler_werkzeug = logging.StreamHandler(sys.stdout)
        console_handler_werkzeug.setLevel(logging.WARNING)
        werkzeug_logger.addHandler(console_handler_werkzeug)
    return logger

def ensure_log_file():
    backup_folder = "backuplogs"
    log_file = os.path.join(backup_folder, 'neondisplay.log')
    try:
        os.makedirs(backup_folder, exist_ok=True)
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

def count_backup_logs():
    backup_folder = "backuplogs"
    count = 0
    try:
        if os.path.exists(backup_folder):
            for filename in os.listdir(backup_folder):
                if filename.startswith("neondisplay.log."):
                    count += 1
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error counting backup logs: {e}")
    return count

# ============== MUSIC TRACKING FUNCTIONS ==============

def parse_song_from_log(log_line):
    if 'Now playing:' in log_line:
        try:
            if '🎵 Now playing:' in log_line:
                song_part = log_line.split('🎵 Now playing: ')[1].strip()
            else:
                song_part = log_line.split('Now playing: ')[1].strip()
            separators = [' -- ', ' - ', ' – ']
            artist_part = 'Unknown Artist'
            song = song_part
            for separator in separators:
                if separator in song_part:
                    artist_part, song = song_part.split(separator, 1)
                    break
            artists = []
            if artist_part != 'Unknown Artist':
                artists = [artist.strip() for artist in artist_part.split(',')]
                artists = [artist for artist in artists if artist]
            if not artists:
                artists = ['Unknown Artist']
                artist_part = 'Unknown Artist'
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

def get_current_track():
    try:
        if not is_hud_running():
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

def clear_track_state_file():
    logger = logging.getLogger('Launcher')
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

# ============== SONG DATABASE FUNCTIONS ==============

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
song_db_conn = init_song_database()

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
    if not hasattr(update_song_count, 'lock'):
        update_song_count.lock = threading.Lock()
    with update_song_count.lock:
        try:
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
            if not song_info or not current_song:
                conn.close()
                return
            song_hash = hashlib.md5(current_song.encode('utf-8')).hexdigest()[:16]
            cursor.execute('''
                INSERT INTO song_plays (song_hash, song_data, play_count, last_played)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(song_hash) DO UPDATE SET 
                play_count = play_count + 1,
                last_played = datetime('now')
            ''', (song_hash, current_song))
            conn.commit()
            conn.close()
            backup_db_if_needed()
            last_logged_song = current_song
        except Exception as e:
            logger.error(f"Error updating song count: {e}")
            try:
                conn.close()
            except:
                pass

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

def load_song_counts():
    try:
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
        cursor.execute('''
            SELECT song_data, play_count 
            FROM song_plays 
            ORDER BY play_count DESC, last_played DESC
            LIMIT 1000
        ''')
        result = dict(cursor.fetchall())
        conn.close()
        return result
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error loading song counts: {e}")
        try:
            conn.close()
        except:
            pass
        return {}

def generate_music_stats(max_items=1000):
    try:
        conn = sqlite3.connect('song_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT SUM(play_count), COUNT(*) FROM song_plays')
        total_plays, unique_songs = cursor.fetchone()
        total_plays = total_plays or 0
        cursor.execute('''
            SELECT song_data, play_count 
            FROM song_plays 
            ORDER BY play_count DESC, last_played DESC
            LIMIT ?
        ''', (max_items,))
        song_stats = {}
        for song_data, play_count in cursor.fetchall():
            song_stats[song_data] = play_count
        cursor.execute('SELECT song_data, play_count FROM song_plays')
        artist_stats = {}
        all_artists_set = set()
        for song_data, play_count in cursor.fetchall():
            if ' -- ' in song_data:
                artist_part = song_data.split(' -- ')[0].strip()
                artists = [artist.strip() for artist in artist_part.split(',')]
                for artist in artists:
                    if artist:
                        artist_stats[artist] = artist_stats.get(artist, 0) + play_count
                        all_artists_set.add(artist)
            else:
                unknown_artist = 'Unknown Artist'
                artist_stats[unknown_artist] = artist_stats.get(unknown_artist, 0) + play_count
                all_artists_set.add(unknown_artist)
        sorted_artists = sorted(artist_stats.items(), key=lambda x: x[1], reverse=True)
        artist_stats = dict(sorted_artists[:max_items])
        unique_artists = len(all_artists_set)
        conn.close()
        return song_stats, artist_stats, total_plays, unique_songs, unique_artists
    except Exception as e:
        logger = logging.getLogger('Launcher')
        logger.error(f"Error generating music stats: {e}")
        try:
            conn.close()
        except:
            pass
        return {}, {}, 0, 0, 0

# ============== CLEANUP AND SIGNAL HANDLING ==============

def cleanup():
    logger = logging.getLogger('Launcher')
    global hud_process, neonwifi_process
    logger.info("🧹 Performing cleanup...")
    functions_with_conn = [update_song_count, load_song_counts, generate_music_stats]
    for func in functions_with_conn:
        if hasattr(func, 'db_conn'):
            try:
                func.db_conn.close()
                logger.info(f"Closed database connection for {func.__name__}")
            except Exception as e:
                logger.error(f"Error closing database connection for {func.__name__}: {e}")
    if hud_process and hud_process.poll() is None:
        logger.info("Stopping HUD process...")
        hud_process.terminate()
        try:
            hud_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("HUD didn't terminate gracefully, killing...")
            hud_process.kill()
            hud_process.wait()
        hud_process = None
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
    subprocess.run(['pkill', '-f', 'hud.py'], check=False, timeout=5)
    subprocess.run(['pkill', '-f', 'neonwifi.py'], check=False, timeout=5)
    logger.info("Cleanup completed")

def signal_handler(sig, frame):
    logger = logging.getLogger('Launcher')
    logger.info("")
    logger.info("Shutting down launcher...")
    cleanup()
    os._exit(0)

# ============== MAIN FUNCTION ==============

def main():
    ensure_log_file()
    load_config()
    logger = setup_logging()
    logger.info("🚀 Starting HUD Launcher")
    init_song_database()
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