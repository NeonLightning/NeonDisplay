# HUD35 Display System

A Raspberry Pi-based display system that shows weather information, currently playing Spotify tracks, and time displays on various screen types. Features automatic background switching based on weather conditions, animated album art, multiple input controls, and a comprehensive web-based management interface.

![Screenshots](screenshots)
## ✨ Key Features

### 🎵 Enhanced Music Statistics & Analytics
- **Comprehensive Tracking**: Automatically logs every song played with timestamps
- **Visual Charts**: Interactive bar charts showing top songs and artists
- **Real-time Updates**: Statistics update automatically as you listen
- **Current Track Display**: Live view of currently playing track with progress bar
- **Data Management**: Clear song history and export capabilities

### 🌤️ Multi-Screen Display System
- **Weather Screen**: Current conditions, temperature, humidity, pressure, and wind
- **Spotify Screen**: Now playing with album art, artist images, and progress tracking
- **Clock Screen**: Analog or digital clock with customizable backgrounds
- **Automatic Backgrounds**: Dynamic backgrounds based on weather conditions or album art

### 🎨 Advanced Display Features
- **Multiple Display Support**:
  - **ST7789** (DisplayHat Mini)
  - **Framebuffer** (Standard TFT 3.5" SPI displays) 
  - **Waveshare E-Paper** (2.13" V3/V4 e-ink displays)
- **Animated Elements**: Album art and artist images with bouncing animation
- **Scrolling Text**: Automatic scrolling for long song titles and artist names
- **Custom Fonts**: Configurable font sizes and paths for different display types

### 🎮 Multiple Input Methods
- **Touch Screen**: Tap anywhere to cycle through screens (weather → spotify → time)
- **4-Button GPIO Support**: Physical buttons for enhanced control:
  - **Button A**: Switch to Spotify screen
  - **Button B**: Switch to Weather screen  
  - **Button X**: Reset image positions (clock screen)
  - **Button Y**: Toggle time display on/off
- **Configurable GPIO**: Customizable button pins in configuration

### ⚙️ Enhanced Configuration & Management
- **Web-Based Configuration UI**: Complete setup via browser interface at `http://your-pi-ip:5000`
- **Real-time Service Control**: Start/stop HUD35 and WiFi manager from web UI
- **Live Log Viewer**: Monitor application logs with color-coded output and live updates
- **Theme Support**: Toggle between light and dark modes in web interface
- **Auto-start Configuration**: Configure which parts start automatically on load

### 🌐 Network & Connectivity
- **Multiple Location Services**: Fallback chain for location detection:
  1. GPSD (hardware GPS)
  2. Google Geolocation API
  3. OpenWeatherMap Geocoding
  4. Manual fallback city
- **WiFi Management**: Built-in access point mode for easy network configuration via `neonwifi.py`
- **Internet Detection**: Smart startup that waits for internet connectivity

### 🎵 Spotify Integration Enhancements
- **Robust Authentication**: Web-based OAuth flow with token refresh
- **Error Recovery**: Automatic reconnection on network errors
- **Artist Image Fetching**: Displays artist photos alongside album art
- **Progress Tracking**: Real-time song progress with formatted time display
- **Background Generation**: Dynamic backgrounds generated from album art colors

### 🕒 Clock Display Options
- **Multiple Clock Types**: Analog or digital clock display
- **Customizable Backgrounds**:
  - Solid color
  - Album art-based
  - Weather-based backgrounds
- **Color Schemes**: Automatic contrasting colors based on background

## 🚀 Installation & Setup
```bash
# Install system dependencies
sudo apt update
sudo apt install python3-pip python3-evdev python3-numpy python3-pil python3-flask

# Install Python packages
sudo pip3 install spotipy toml requests --break-system-packages

# For ST7789 displays (DisplayHat Mini)
sudo pip3 install st7789 --break-system-packages

# For Waveshare E-Paper displays
sudo pip3 install eink-wave --break-system-packages

```

### Display Setup

#### For 3.5" TFT Displays:
```bash
git clone https://github.com/Shinigamy19/RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046
mv RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046 LCD-show
cd LCD-show
chmod +x LCD35-show
sudo ./LCD35-show
```

#### For DisplayHat Mini (ST7789):
- No additional drivers needed - uses ST7789 Python library

#### For Waveshare E-Paper:
- Ensure proper SPI configuration
- Check display compatibility with waveshare_epd library
- use waveshare/epdconfig.py in folder /usr/local/lib/python3.11/dist-packages/waveshare_epd/epdconfig.py

## ⚙️ Configuration

### Web Configuration Interface
After installation, access the web interface:
```bash
http://your-pi-ip-address:5000
```

The web interface provides:
- **API Key Setup**: OpenWeatherMap, Google Geolocation, Spotify
- **Display Configuration**: Screen type, rotation, fonts
- **Service Management**: Start/stop HUD35 and WiFi manager
- **Music Statistics**: View listening history and charts
- **Advanced Settings**: Button mapping, clock options, auto-start

### Manual Configuration
Edit `config.toml` for advanced settings:

## 🎮 Usage

### Starting the System

```bash
python3 launcher.py
```

#### Auto-start (via web interface):
- Configure auto-start in web UI

### Physical Controls
- **Touch Screen**: Tap to cycle through display screens
- **Button A**: Show Spotify screen
- **Button B**: Show Weather screen  
- **Button X**: Reset animations (on clock screen)
- **Button Y**: Toggle time display

### Web Interface Features

#### Main Dashboard (`http://your-pi-ip:5000`)
- Service status and control
- Auto-start configuration
- Quick access to music statistics and logs

#### Music Statistics (`http://your-pi-ip:5000/music_stats`)
- Interactive charts of top songs and artists
- Current track display with progress
- Data export and clearing options

#### Advanced Configuration (`http://your-pi-ip:5000/advanced_config`)
- Complete system configuration
- Display settings, fonts, button mapping
- API key management
- Clock and appearance options

#### Log Viewer (`http://your-pi-ip:5000/view_logs`)
- Real-time log monitoring
- Color-coded log levels
- Live updates and filtering

## 🔧 Service Management

### System Commands
```bash
# Start via launcher
python3 launcher.py

# Start HUD35 display only
python3 hud35.py

# Start WiFi manager only  
python3 neonwifi.py
```

### WiFi Management
The system includes `neonwifi.py` for network configuration:
- Creates access point "Neonwifi-Manager" when no WiFi connected
- Web interface at `http://192.168.42.1` for WiFi setup
- Automatic fallback to AP mode when disconnected

## 🎵 Music Statistics Features

### 📊 Analytics Dashboard
- **Total Plays Counter**: Track how many songs you've played
- **Unique Songs & Artists**: Measure your music diversity
- **Top Charts**: 
  - Most played songs with play counts
  - Most listened-to artists
- **Visual Analytics**: Color-coded bar charts showing listening patterns
- **Live Updates**: Real-time tracking as you listen

### Accessing Music Statistics
1. Open web interface: `http://your-pi-ip:5000`
2. Click "Music Statistics" button
3. View interactive charts of your listening habits

### Logging and Debugging
- Use the web-based log viewer for real-time monitoring
- Check `hud35.log` for detailed application logs
- Enable debug mode in configuration for detailed output

## 📁 File Structure

```
hud35/
├── hud35.py              # Main display application
├── launcher.py           # Web management interface
├── neonwifi.py           # WiFi management
├── config.toml           # Configuration file
├── .spotify_cache        # Spotify authentication cache
├── hud35.log            # Application logs
├── song_counts.toml     # Music statistics data
└── bg/                  # Background images directory
    ├── bg_clear.png
    ├── bg_clouds.png
    └── ...
```
## 📄 License

This project is open source. See LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.
