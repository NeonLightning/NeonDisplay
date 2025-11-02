# HUD35 Display System

A Raspberry Pi-based display system that shows weather information and currently playing Spotify tracks on a 480x320 screen. Features automatic background switching based on weather conditions, animated album art, and touch screen controls.

## Features

- **Weather Display**: Shows current weather with location detection (GPS, Google Geolocation, or fallback city)
- **Spotify Integration**: Displays currently playing track with album art and artist images
- **Animated Elements**: Album art and artist images bounce around the screen
- **Touch Controls**: Tap the screen to switch between weather and Spotify views
- **Automatic Backgrounds**: Weather-appropriate background images
- **Optimized Performance**: Efficient framebuffer rendering with caching

## Hardware Requirements

- Raspberry Pi (any model with GPIO)
- 480x320 TFT display connected via SPI
- Touch screen input
- Internet connection

## Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd hud35
```

### 2. Install Dependencies
```bash
# Install system packages
sudo apt update
sudo apt install python3-pip python3-requests python3-spotipy python3-pil python3-evdev python3-toml python3-numpy

# Or install via pip
pip3 install -r requirements.txt
```

### 3. Spotify API Setup

#### Create a Spotify Developer Application
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create App"
4. Fill in:
   - **App Name**: `HUD35 Display` (or any name you prefer)
   - **App Description**: `Display for showing currently playing tracks`
   - **Redirect URI**: `http://127.0.0.1:8080`
5. Click "Create"
6. Note your **Client ID** and **Client Secret**

#### Configure the Application
1. Copy `config.toml` if it doesn't exist (the script will create one automatically)
2. Edit `config.toml` and add your Spotify credentials:
```toml
[api_keys]
client_id = "your_spotify_client_id_here"
client_secret = "your_spotify_client_secret_here"
redirect_uri = "http://127.0.0.1:8080"
```

### 5. OpenWeatherMap API
1. Sign up at [OpenWeatherMap](https://openweathermap.org/api)
2. Get your API key
3. Add to `config.toml`:
```toml
[api_keys]
openweather = "your_openweather_api_key_here"
```

### 6. Google Geolocation API (Optional)
1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Geolocation API
3. Create an API key
4. Add to `config.toml`:
```toml
[api_keys]
google_geo = "your_google_geo_api_key_here"
```

### 7. Initial Spotify Authentication

**This step is required before installing as a service:**

```bash
# Run the script manually first
python3 hud35.py
```

The first time you run it:
- A browser window will open for Spotify authorization
- Log in to your Spotify account if prompted
- Grant permission for the app to access your currently playing track
- The script will create a `.spotify_cache` file with your authentication tokens

Once you see weather and/or Spotify information on your display, press `Ctrl+C` to stop the program.

### 8. Install as a Service

```bash
# Make the installer executable and run it
chmod +x install.sh
sudo ./install.sh
```

The installer will:
- Copy all necessary files to `/opt/hud35/`
- Set up the systemd service
- Enable automatic startup

## Configuration

Edit `/opt/hud35/config.toml` after installation:

### Key Settings

```toml
[settings]
start_screen = "weather"  # or "spotify"
fallback_city = "London"  # Used if GPS location fails
use_gpsd = true           # Use GPSD for location
use_google_geo = true     # Use Google Geolocation as backup
time_display = true       # Show current time
```

### Font Settings
You can customize fonts and sizes in the `[fonts]` section.

## Background Images

Place background images in the `bg/` directory. The script uses these files:
- `bg_clear.png` - Clear skies
- `bg_clouds.png` - Cloudy weather
- `bg_rain.png` - Rainy weather
- `bg_snow.png` - Snowy weather
- `bg_storm.png` - Thunderstorms
- `bg_default.png` - Default background
- `no_track.png` - Displayed when no Spotify track is playing

## Usage

### Manual Operation
```bash
python3 hud35.py
```

### Service Management
```bash
# Start service
sudo systemctl start hud35.service

# Stop service
sudo systemctl stop hud35.service

# Check status
sudo systemctl status hud35.service

# View logs
sudo journalctl -u hud35.service -f
```

### Touch Controls
- **Tap the screen** to switch between weather and Spotify displays

## Uninstallation

```bash
sudo ./uninstall.sh
```

This will remove:
- All application files from `/opt/hud35/`
- The systemd service
- Service configuration

*Note: Python dependencies and your config file will remain.*

## Troubleshooting

### Common Issues

1. **No display output**
   - Check SPI is enabled in `raspi-config`
   - Verify display connections

2. **Spotify not working**
   - Ensure you completed the initial authentication step
   - Check `.spotify_cache` exists and is valid
   - Verify Client ID and Secret in config

3. **Weather not loading**
   - Check internet connection
   - Verify OpenWeatherMap API key
   - Check fallback city is set

4. **Touch not working**
   - Verify touchscreen device is detected
   - Check evdev can access input device

### Logs
View detailed logs with:
```bash
sudo journalctl -u hud35.service -f
```

## File Structure
```
hud35/
├── hud35.py              # Main application
├── config.toml           # Configuration file
├── install.sh            # Installation script
├── uninstall.sh          # Uninstallation script
├── requirements.txt      # Python dependencies
├── bg/                   # Background images directory
└── README.md            # This file
```