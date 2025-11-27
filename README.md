# NeonDisplay

A comprehensive Raspberry Pi-based display system with weather information, Spotify integration, and web-based control interface.
For 3.5" TFT, Display Hat Mini, and Waveshare 2.13" e-ink screens.

## 🌟 Features
![Screenshots](screenshots)

### Display Modes
- **Weather Display**: Current weather conditions with forecasts
- **Spotify Integration**: Now playing display with progress bars
- **Clock Display**: Digital and analog clocks with customizable backgrounds
- Waveshare_epd has a different design with all three at once

### Music Integration
- **Spotify Control**: Play, pause, skip tracks, and control volume
- **Music Statistics**: Track play counts and artist statistics
- **Search & Queue**: Search Spotify and manage playback queue
- **Current Track Display**: Real-time now playing information

### Web Interface
- **Responsive Design**: Works on desktop and mobile devices
- **Dark/Light Theme**: Toggle between themes
- **Real-time Updates**: Live track information and system status
- **Configuration Management**: Web-based configuration interface

### Hardware Support
- **Supported Display Types**: 
  - Framebuffer (TFT 3.5")
  - ST7789 (DisplayHatMini)
  - Waveshare E-Paper
- **GPIO Button Control**: Configurable physical buttons for st7789
- **Touch Control**: Touch support for 3.5" tft
- **GPS Integration**: Location services with GPSD support

## 🛠️ Hardware Requirements

- Raspberry Pi
- Supported display (3.5" TFT, ST7789, or E-Paper)(optional)
- Internet connection (WiFi or Ethernet)
- Optional: GPS module for location services

## 📦 Installation

### Quick Install
```bash
# Clone the repository
https://github.com/NeonLightning/NeonDisplay.git
cd Hud35

# Run complete installation (excluding display drivers)
sudo make
```

### Step-by-Step Installation
1. **System Dependencies**
   ```bash
   make system-deps
   ```

2. **Python Environment & Packages**
   ```bash
   make python-packages
   ```

3. **Display Setup** (⚠️ **Will reboot system**)
   ```bash
   make setup-display
   ```

4. **System Service Setup**
   ```bash
   make setup-service
   ```

5. **Configuration**
   ```bash
   make config
   ```

## ⚙️ Configuration

### API Keys Setup
You'll need to configure the following API keys:

- **OpenWeatherMap**: Free weather API key
- **Spotify**: Client ID and Secret for music integration
- **Google Geolocation**: Optional, for precise location

### Configuration Methods

**Web Interface** (Recommended and needed to authenticate):
- Access the web UI after installation
- Navigate to "Advanced Configuration"
- Fill in API keys and settings

**Command Line**:
```bash
# Interactive configuration walk-through
make config

# Individual configuration sections
make config-api
make config-display
make config-fonts
make config-buttons
make config-wifi
make config-settings
```

### Key Configuration Sections

- **API Configuration**: Weather and Spotify API keys
- **Display Settings**: Screen type, rotation, timeout
- **Font Configuration**: Custom fonts for different display elements
- **Button Mapping**: GPIO pins for physical buttons
- **WiFi Settings**: Access point configuration
- **Clock Appearance**: Digital/analog with background options

## 🚀 Usage

### Starting the System
```bash
# Start the service
make start

# Check status
make status

# View logs
make logs
```

### Web Interface
After starting, access the web interface at:
```
http://[raspberry-pi-ip]:5000
```

### Service Management
```bash
# Start/stop/restart service
make start
make stop
make restart

# View real-time logs
make tail
```

## 🎵 Spotify Integration

### Authentication
1. Create a Spotify Developer application
2. Set redirect URI to `http://127.0.0.1:5000`
3. Enter Client ID and Secret in configuration
4. Authenticate through the web interface

### Features
- Now playing display with progress bars
- Playback controls (play, pause, skip, volume)
- Search and add to queue
- Music statistics and play history

## 📊 Music Statistics

Access detailed music statistics at:
```
http://[raspberry-pi-ip]:5000/music_stats
```

Features:
- Most played songs and artists
- Total play counts
- Interactive bar charts

## 🔧 Advanced Features

### Display Types
- **Framebuffer**: Standard TFT displays
- **ST7789**: For DisplayHatMini with SPI configuration
- **Waveshare E-Paper 2.13"**: E-ink displays
- **Dummy Display**: No screen enabled

### Location Services
- **GPSD**: Hardware GPS with gpsd service
- **Google Geolocation**: Network-based location
- **Fallback City**: Manual location setting

## 🛠️ Maintenance

### Updating Packages
```bash
make update-packages
```

### Viewing Configuration
```bash
make view-config
```

### Resetting Configuration
```bash
make reset-config
```

### Complete Cleanup
```bash
make clean
```

## 🐛 Troubleshooting

### Common Issues

**Display Not Working**:
- Run `make setup-display` for driver installation
- Check display type in configuration
- Verify framebuffer device path

**Spotify Authentication Fails**:
- Verify Client ID and Secret
- Check redirect URI matches exactly
- Ensure proper scopes are requested

**Service Won't Start**:
- Check logs: `make logs` or `make tail`
- Verify Python dependencies: `make venv-info`
- Check configuration: `make view-config`

**No Internet Connection**:
- WiFi manager will start access point
- Connect to "Neonwifi-Manager" to configure WiFi

### Logs and Debugging

```bash
# Service logs (systemd)
make logs

# Application logs
make tail

# Service status
make status
```
**Note**: The display driver installation (`make setup-display`) will reboot your system. Ensure you save any work before proceeding.