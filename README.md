# HUD35 Display System

A Raspberry Pi-based display system that shows weather information and currently playing Spotify tracks on a 480x320 screen. Features automatic background switching based on weather conditions, animated album art, touch screen controls, and a comprehensive web-based management interface.

![HUD35 Display System in action](screenshots/display.gif)

![More Screenshots](screenshots)

## Features

- **Weather Display**: Shows current weather with location detection (GPS, Google Geolocation, or fallback city)
- **Spotify Integration**: Displays currently playing track with album art and artist images
- **Animated Elements**: Album art and artist images bounce around the screen
- **Touch Controls**: Tap the screen to switch between weather and Spotify views
- **Automatic Backgrounds**: Weather-appropriate background images
- **Optimized Performance**: Efficient framebuffer rendering with caching
- **Web Management Interface**: Complete configuration and control via web browser
- **Music Statistics**: Track your listening habits with detailed charts and analytics
- **Auto-start Management**: Configure which services start automatically on boot
- **Real-time Log Viewer**: Monitor application logs with live updates
- **WiFi Management**: Optional WiFi configuration service for easy network setup

## Hardware Requirements

- Raspberry Pi (any model with GPIO)
- 480x320 TFT display connected via SPI
- Touch screen input
- Internet connection
- WiFi adapter (built-in or USB)

## Display Setup (3.5" ILI9486 TFT with Touch)

For setting up the 3.5" ILI9486 TFT display with XPT2046 touch controller:

```bash
sudo apt update
sudo apt install git
git clone https://github.com/Shinigamy19/RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046  
mv RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046 LCD-show
cd LCD-show
chmod +x LCD35-show
sudo ./LCD35-show
```

The system will reboot after installation. The display should now work at the correct resolution (480x320) with touch functionality.

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
sudo apt install python3-pip python3-evdev python3-numpy python3-pil python3-flask python3-toml
sudo pip3 install spotipy --break-system-packages
```

### 3. Run the Installer
```bash
# Make the installer executable and run it
chmod +x install.sh
sudo ./install.sh
```

The installer will:
- Copy all necessary files to `/opt/hud35/`
- Set up the systemd service
- Enable automatic startup

### 4. Complete Setup via Web Interface

After installation, access the web interface to complete configuration:

```bash
http://[YOUR_PI_IP]:5000
```

## Web Management Interface

The HUD35 Launcher provides a comprehensive web interface for easy management:

### Dashboard Features
- **Service Control**: Start/stop HUD35 display and WiFi manager
- **API Configuration**: Enter OpenWeatherMap, Google Geolocation, and Spotify API keys
- **Spotify Authentication**: Complete OAuth flow directly from the web interface
- **Settings Management**: Configure location, display preferences, and auto-start behavior
- **Real-time Status**: See which services are running
- **Theme Support**: Light and dark mode themes
- **Music Statistics**: View detailed charts of your listening history

### Configuration Sections

#### API Keys Setup
1. **OpenWeatherMap**: Get free API key from [OpenWeatherMap](https://openweathermap.org/api)
2. **Google Geolocation**: Optional for precise location (requires Google Cloud project)
3. **Spotify**: Create app in [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

#### Location & Display Settings
- **Fallback City**: Used when location services are unavailable
- **Location Services**: Choose between GPSD, Google Geolocation, or both
- **Start Screen**: Set default view (Weather or Spotify)
- **Time Display**: Toggle clock display on screens

#### Auto-start Configuration
- **HUD35 Display**: Auto-start the main display application
- **WiFi Manager**: Auto-start neonwifi service
- **Internet Check**: Wait for internet before starting HUD35

## Music Statistics

The system automatically tracks your listening history and provides:

- **Total Plays**: Number of songs played
- **Unique Songs & Artists**: Diversity of your listening
- **Top Songs Chart**: Most played tracks with play counts
- **Top Artists Chart**: Most listened-to artists
- **Time Period Filtering**: View stats for 24 hours, 7 days, 30 days, 90 days, or all time
- **Visual Charts**: Color-coded bar charts showing listening patterns

Access music statistics from the main dashboard or directly at `/music_stats`.

## WiFi Management Service

The system includes an optional WiFi management service (`neonwifi.py`) that provides:

### Features
- **Web-based WiFi configuration** - Connect to new networks without SSH
- **Automatic AP mode** - Creates access point when no WiFi is available
- **Connection monitoring** - Automatically restores AP if connection is lost
- **Manual network entry** - Enter any SSID and password
- **Periodic health checks** - Verifies internet connectivity

### Usage
1. **Connect to Access Point**: Look for WiFi network `WiFi-Manager` (open network)
2. **Web Interface**: Visit `http://192.168.42.1` in your browser
3. **Enter Credentials**: Submit your WiFi SSID and password
4. **Automatic Connection**: The system will connect and monitor the connection

## Service Management

### System Commands
```bash
# Start HUD35 Launcher service
sudo systemctl start hud35.service

# Stop HUD35 Launcher service
sudo systemctl stop hud35.service

# Check status
sudo systemctl status hud35.service

# View logs
sudo journalctl -u hud35.service -f

# Enable auto-start on boot
sudo systemctl enable hud35.service
```

### Web Interface Controls
- **Start/Stop Services**: Use the web interface buttons for easy control
- **Configuration Changes**: Save settings instantly without restarting services
- **Live Log Viewer**: Monitor application logs in real-time with color-coded output
- **Theme Switching**: Toggle between light and dark modes

## Manual Operation

If you prefer to run manually instead of as a service:

```bash
# Run the launcher (includes web interface)
python3 launcher.py

# Or run HUD35 directly (no web interface)
python3 hud35.py
```

## Configuration Files

### Primary Configuration (`config.toml`)
Located at `/opt/hud35/config.toml` after installation:

```toml
[api_keys]
openweather = "your_openweather_api_key"
google_geo = "your_google_geo_api_key"  # Optional
client_id = "your_spotify_client_id"
client_secret = "your_spotify_client_secret"
redirect_uri = "http://127.0.0.1:5000"

[settings]
start_screen = "weather"  # or "spotify"
fallback_city = "London,UK"
use_gpsd = true
use_google_geo = true
time_display = true

[auto_start]
auto_start_hud35 = true
auto_start_neonwifi = true
check_internet = true

[ui]
theme = "dark"  # or "light"
```

### Spotify Authentication (`.spotify_cache`)
Automatically created after successful Spotify OAuth authentication.

## Background Images

Place background images in the `bg/` directory. The script uses these files:
- `bg_clear.png` - Clear skies
- `bg_clouds.png` - Cloudy weather
- `bg_rain.png` - Rainy weather
- `bg_snow.png` - Snowy weather
- `bg_storm.png` - Thunderstorms
- `bg_default.png` - Default background
- `no_track.png` - Displayed when no Spotify track is playing

## Touch Controls

- **Tap the screen** to switch between weather and Spotify displays

## File Structure

```
hud35/
├── hud35.py              # Main display application
├── launcher.py           # Web management interface
├── neonwifi.py           # WiFi management service (optional)
├── config.toml           # Configuration file
├── install.sh            # Installation script
├── uninstall.sh          # Uninstallation script
├── songs.toml            # Music statistics data (auto-generated)
├── hud35.log             # Application logs (auto-generated)
├── bg/                   # Background images directory
└── README.md            # This file
```

## Troubleshooting

### Web Interface Issues
- **Port 5000 busy**: The launcher automatically tries port 5001
- **Cannot access web UI**: Check if the service is running with `sudo systemctl status hud35.service`
- **Configuration not saving**: Ensure the `/opt/hud35/` directory has proper permissions

### Spotify Issues
- **Authentication failures**: Use the web interface to re-authenticate Spotify
- **No track info**: Verify Spotify is playing and app has proper permissions
- **Token expiration**: The system automatically refreshes tokens when possible

### Display Issues
- **Blank screen**: Check SPI interface and power to display
- **Touch not working**: Verify touch controller calibration
- **Wrong resolution**: Ensure proper display drivers are installed

### WiFi Service Issues
- **Can't connect to AP**: Ensure no other services are using the WiFi interface
- **Web interface not loading**: Check if neonwifi service is running
- **Connection failures**: Verify NetworkManager is installed and working

## Uninstallation

```bash
sudo ./uninstall.sh
```

This will remove:
- All application files from `/opt/hud35/`
- The systemd service
- Service configurations

*Note: Python dependencies will remain installed.*

## Support

For issues and feature requests, please check:
- Application logs: `sudo journalctl -u hud35.service -f`
- Music statistics: http://127.0.0.1:5000/music_stats