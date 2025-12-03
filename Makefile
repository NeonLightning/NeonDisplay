VENV_DIR = /opt/neondisplay/venv
SERVICE_NAME = neondisplay
PROJECT_DIR = /opt/neondisplay
SERVICE_FILE = /etc/systemd/system/$(SERVICE_NAME).service
LCD_SHOW_DIR = LCD-show
CONFIG_FILE = /opt/neondisplay/config.toml
GREEN = \033[0;32m
YELLOW = \033[0;33m
RED = \033[0;31m
BLUE = \033[0;34m
NC = \033[0m # No Color

.PHONY: all install system-deps python-packages setup-display setup-service clean status logs help config config-api config-display config-fonts config-buttons config-wifi config-settings view-config reset-config

all: system-deps python-packages config setup-service
	@echo "$(GREEN)Installation complete!$(NC)"
	@echo ""
	@echo "$(YELLOW)Next steps:$(NC)"
	@echo "1. $(YELLOW)Setup config: make config$(NC)"
	@echo "2. $(YELLOW)Run 'make setup-display' to install LCD drivers (will reboot)$(NC)"
	@echo "3. $(YELLOW)Check status: make status$(NC)"
	@echo "4. $(YELLOW)View logs: make logs$(NC)"

system-deps:
	@echo "$(GREEN)Installing system dependencies...$(NC)"
	sudo apt update
	sudo apt install -y python3-pip python3-venv curl hostapd dnsmasq liblcms2-dev libwebp-dev libtiff-dev libopenjp2-7-dev libxcb1-dev libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev git libopenblas-dev libcairo2-dev libdbus-1-dev
	@echo "$(GREEN)Installing uv system-wide...$(NC)"
	curl -LsSf https://astral.sh/uv/install.sh | sh
	sudo mv /root/.local/bin/uv /usr/local/bin/
	sudo mv /root/.local/bin/uvx /usr/local/bin/
	@echo "$(GREEN)System dependencies installed$(NC)"

python-packages:
	@echo "$(GREEN)Setting up Python virtual environment with uv...$(NC)"
	sudo mkdir -p $(PROJECT_DIR)
	sudo chown $$USER:$$USER $(PROJECT_DIR)
	@if [ -d "$(VENV_DIR)" ] && [ -f "$(VENV_DIR)/bin/python3" ]; then \
		echo "$(YELLOW)Virtual environment already exists at $(VENV_DIR), skipping creation.$(NC)"; \
	else \
		uv venv $(VENV_DIR); \
		echo "$(GREEN)Virtual environment created at $(VENV_DIR)$(NC)"; \
	fi
	@echo "$(GREEN)Installing Python packages with uv...$(NC)"
	export UV_CONCURRENT_DOWNLOADS=3
	export UV_CONCURRENT_INSTALLS=3
	export UV_CONCURRENT_BUILDS=3
	bash ./swap.sh
	uv pip install --python $(VENV_DIR)/bin/python spotipy st7789 numpy eink-wave evdev pillow flask pycairo dbus-python setuptools wheel toml rpi.gpio
	@echo "$(GREEN)All Python packages installed in virtual environment$(NC)"
	@echo "$(GREEN)Copying project files...$(NC)"
	cp -r . $(PROJECT_DIR)/
	if [ -f "./waveshare/epdconfig.py" ]; then \
		sudo cp ./waveshare/epdconfig.py $(VENV_DIR)/lib/python3.*/site-packages/waveshare_epd/; \
		echo "$(GREEN)Waveshare config updated in virtual environment$(NC)"; \
	fi

setup-display:
	@echo "$(YELLOW)WARNING: This will install LCD drivers and reboot the system!$(NC)"
	@echo "$(YELLOW)Make sure to save any work before continuing.$(NC)"
	@read -p "Continue? [y/N] " choice; \
	if [ "$$choice" != "y" ] && [ "$$choice" != "Y" ]; then \
		echo "Aborted."; \
		exit 1; \
	fi
	@echo "$(GREEN)Installing LCD display drivers...$(NC)"
	git clone https://github.com/Shinigamy19/RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046   $(LCD_SHOW_DIR)
	cd LCD-show && chmod +x ./*
	sudo ./LCD35-show

setup-service:
	@echo "$(GREEN)Setting up systemd service...$(NC)"
	@if [ -f "neondisplay.service" ]; then \
		echo "$(GREEN)Updating existing neondisplay.service to use virtual environment...$(NC)"; \
		sed 's|/usr/bin/python3|$(VENV_DIR)/bin/python3|' neondisplay.service > neondisplay.service.venv; \
		sudo cp neondisplay.service.venv $(SERVICE_FILE); \
		rm neondisplay.service.venv; \
	else \
		echo "$(YELLOW)No neondisplay.service found, creating one...$(NC)"; \
		echo "[Unit]" > neondisplay.service.tmp; \
		echo "Description=NeonDisplay NeonDisplay Service" >> neondisplay.service.tmp; \
		echo "After=network.target" >> neondisplay.service.tmp; \
		echo "Wants=network.target" >> neondisplay.service.tmp; \
		echo "" >> neondisplay.service.tmp; \
		echo "[Service]" >> neondisplay.service.tmp; \
		echo "Type=simple" >> neondisplay.service.tmp; \
		echo "User=root" >> neondisplay.service.tmp; \
		echo "Group=root" >> neondisplay.service.tmp; \
		echo "WorkingDirectory=$(PROJECT_DIR)" >> neondisplay.service.tmp; \
		echo "ExecStart=$(VENV_DIR)/bin/python3 $(PROJECT_DIR)/neondisplay.py" >> neondisplay.service.tmp; \
		echo "Restart=on-failure" >> neondisplay.service.tmp; \
		echo "RestartSec=5" >> neondisplay.service.tmp; \
		echo "TimeoutStartSec=30" >> neondisplay.service.tmp; \
		echo "StandardOutput=journal" >> neondisplay.service.tmp; \
		echo "StandardError=journal" >> neondisplay.service.tmp; \
		echo "" >> neondisplay.service.tmp; \
		echo "[Install]" >> neondisplay.service.tmp; \
		echo "WantedBy=multi-user.target" >> neondisplay.service.tmp; \
		sudo cp neondisplay.service.tmp $(SERVICE_FILE); \
		rm neondisplay.service.tmp; \
	fi
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE_NAME).service
	@echo "$(GREEN)Systemd service setup complete$(NC)"
	@echo "$(GREEN)Service will use virtual environment at: $(VENV_DIR)$(NC)"

config:
	@echo "$(BLUE)=========================================$(NC)"
	@echo "$(BLUE)      NeonDisplay WALK-THROUGH CONFIGURATION    $(NC)"
	@echo "$(BLUE)=========================================$(NC)"
	@echo "$(YELLOW)This will guide you through all configuration settings$(NC)"
	@echo "$(YELLOW)Press Enter to keep current value, or enter a new value$(NC)"
	@echo "$(BLUE)=========================================$(NC)"
	@read -p "Start configuration walk-through? [y/N] " CONFIRM; \
	if [ "$$CONFIRM" != "y" ] && [ "$$CONFIRM" != "Y" ]; then \
		echo "Configuration cancelled."; \
		exit 0; \
	else \
		echo ""; \
		$(MAKE) config-api; \
		$(MAKE) config-display; \
		$(MAKE) config-wifi; \
		$(MAKE) config-settings; \
		echo ""; \
		echo "$(GREEN)✓ Configuration walk-through complete!$(NC)"; \
		echo "$(GREEN)Current configuration:$(NC)"; \
		$(MAKE) view-config; \
	fi

config-api:
	@echo "$(BLUE)--- API KEYS CONFIGURATION ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_openweather=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('api_keys', {}).get('openweather', ''))" 2>/dev/null || echo ""); \
	current_google_geo=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('api_keys', {}).get('google_geo', ''))" 2>/dev/null || echo ""); \
	current_client_id=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('api_keys', {}).get('client_id', ''))" 2>/dev/null || echo ""); \
	current_client_secret=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('api_keys', {}).get('client_secret', ''))" 2>/dev/null || echo ""); \
	current_redirect_uri=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('api_keys', {}).get('redirect_uri', 'http://127.0.0.1:5000'))" 2>/dev/null || echo "http://127.0.0.1:5000"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "  OpenWeather API Key: $$current_openweather"; \
	read -p "  New OpenWeather API Key: " openweather; \
	openweather=$${openweather:-$$current_openweather}; \
	echo "  Google Geo API Key: $$current_google_geo"; \
	read -p "  New Google Geo API Key: " google_geo; \
	google_geo=$${google_geo:-$$current_google_geo}; \
	echo "  Spotify Client ID: $$current_client_id"; \
	read -p "  New Spotify Client ID: " client_id; \
	client_id=$${client_id:-$$current_client_id}; \
	echo "  Spotify Client Secret: $$current_client_secret"; \
	read -p "  New Spotify Client Secret: " client_secret; \
	client_secret=$${client_secret:-$$current_client_secret}; \
	echo "  Redirect URI: $$current_redirect_uri"; \
	read -p "  New Redirect URI [http://127.0.0.1:5000]: " redirect_uri; \
	redirect_uri=$${redirect_uri:-$$current_redirect_uri}; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['api_keys']['openweather'] = '$$openweather'; config['api_keys']['google_geo'] = '$$google_geo'; config['api_keys']['client_id'] = '$$client_id'; config['api_keys']['client_secret'] = '$$client_secret'; config['api_keys']['redirect_uri'] = '$$redirect_uri'; toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ API keys updated$(NC)"
	@echo ""

config-display:
	@echo "$(BLUE)--- DISPLAY SETTINGS ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_display_type=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('type', 'dummy'))" 2>/dev/null || echo "dummy"); \
	current_framebuffer=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('framebuffer', '/dev/fb1'))" 2>/dev/null || echo "/dev/fb1"); \
	current_rotation=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('rotation', 0))" 2>/dev/null || echo "0"); \
	current_spi_port=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('spi_port', 0))" 2>/dev/null || echo "0"); \
	current_spi_cs=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('spi_cs', 1))" 2>/dev/null || echo "1"); \
	current_dc_pin=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('dc_pin', 9))" 2>/dev/null || echo "9"); \
	current_backlight_pin=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('backlight_pin', 13))" 2>/dev/null || echo "13"); \
	current_st7789_rotation=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('rotation', 0))" 2>/dev/null || echo "0"); \
	current_spi_speed=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('display', {}).get('st7789', {}).get('spi_speed', 60000000))" 2>/dev/null || echo "60000000"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "  Display Type: $$current_display_type"; \
	read -p "  New Display Type (framebuffer, st7789, dummy)[dummy]: " display_type; \
	display_type=$${display_type:-$$current_display_type}; \
	echo "  Framebuffer Device: $$current_framebuffer"; \
	read -p "  New Framebuffer Device [/dev/fb1]: " framebuffer; \
	framebuffer=$${framebuffer:-$$current_framebuffer}; \
	echo "  Rotation: $$current_rotation"; \
	read -p "  New Rotation [0]: " rotation; \
	rotation=$${rotation:-$$current_rotation}; \
	echo "$(YELLOW)ST7789 Settings:$(NC)"; \
	echo "  SPI Port: $$current_spi_port"; \
	read -p "  New SPI Port [0]: " spi_port; \
	spi_port=$${spi_port:-$$current_spi_port}; \
	echo "  SPI CS: $$current_spi_cs"; \
	read -p "  New SPI CS [1]: " spi_cs; \
	spi_cs=$${spi_cs:-$$current_spi_cs}; \
	echo "  DC Pin: $$current_dc_pin"; \
	read -p "  New DC Pin [9]: " dc_pin; \
	dc_pin=$${dc_pin:-$$current_dc_pin}; \
	echo "  Backlight Pin: $$current_backlight_pin"; \
	read -p "  New Backlight Pin [13]: " backlight_pin; \
	backlight_pin=$${backlight_pin:-$$current_backlight_pin}; \
	echo "  ST7789 Rotation: $$current_st7789_rotation"; \
	read -p "  New ST7789 Rotation [0]: " st7789_rotation; \
	st7789_rotation=$${st7789_rotation:-$$current_st7789_rotation}; \
	echo "  SPI Speed: $$current_spi_speed"; \
	read -p "  New SPI Speed [60000000]: " spi_speed; \
	spi_speed=$${spi_speed:-$$current_spi_speed}; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['display']['type'] = '$$display_type'; config['display']['framebuffer'] = '$$framebuffer'; config['display']['rotation'] = int('$$rotation'); config['display']['st7789']['spi_port'] = int('$$spi_port'); config['display']['st7789']['spi_cs'] = int('$$spi_cs'); config['display']['st7789']['dc_pin'] = int('$$dc_pin'); config['display']['st7789']['backlight_pin'] = int('$$backlight_pin'); config['display']['st7789']['rotation'] = int('$$st7789_rotation'); config['display']['st7789']['spi_speed'] = int('$$spi_speed'); toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ Display settings updated$(NC)"
	@echo ""

config-fonts:
	@echo "$(BLUE)--- FONT SETTINGS ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_large_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('large_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"); \
	current_large_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('large_font_size', 36))" 2>/dev/null || echo "36"); \
	current_medium_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('medium_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"); \
	current_medium_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('medium_font_size', 24))" 2>/dev/null || echo "24"); \
	current_small_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('small_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"); \
	current_small_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('small_font_size', 16))" 2>/dev/null || echo "16"); \
	current_spot_large_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_large_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"); \
	current_spot_large_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_large_font_size', 26))" 2>/dev/null || echo "26"); \
	current_spot_medium_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_medium_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"); \
	current_spot_medium_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_medium_font_size', 18))" 2>/dev/null || echo "18"); \
	current_spot_small_font_path=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_small_font_path', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))" 2>/dev/null || echo "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"); \
	current_spot_small_font_size=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('fonts', {}).get('spot_small_font_size', 12))" 2>/dev/null || echo "12"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "$(YELLOW)Main Fonts:$(NC)"; \
	echo "  Large Font Path: $$current_large_font_path"; \
	read -p "  New Large Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf]: " large_font_path; \
	large_font_path=$${large_font_path:-$$current_large_font_path}; \
	echo "  Large Font Size: $$current_large_font_size"; \
	read -p "  New Large Font Size [36]: " large_font_size; \
	large_font_size=$${large_font_size:-$$current_large_font_size}; \
	echo "  Medium Font Path: $$current_medium_font_path"; \
	read -p "  New Medium Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf]: " medium_font_path; \
	medium_font_path=$${medium_font_path:-$$current_medium_font_path}; \
	echo "  Medium Font Size: $$current_medium_font_size"; \
	read -p "  New Medium Font Size [24]: " medium_font_size; \
	medium_font_size=$${medium_font_size:-$$current_medium_font_size}; \
	echo "  Small Font Path: $$current_small_font_path"; \
	read -p "  New Small Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf]: " small_font_path; \
	small_font_path=$${small_font_path:-$$current_small_font_path}; \
	echo "  Small Font Size: $$current_small_font_size"; \
	read -p "  New Small Font Size [16]: " small_font_size; \
	small_font_size=$${small_font_size:-$$current_small_font_size}; \
	echo "$(YELLOW)Spotify Fonts:$(NC)"; \
	echo "  Spotify Large Font Path: $$current_spot_large_font_path"; \
	read -p "  New Spotify Large Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf]: " spot_large_font_path; \
	spot_large_font_path=$${spot_large_font_path:-$$current_spot_large_font_path}; \
	echo "  Spotify Large Font Size: $$current_spot_large_font_size"; \
	read -p "  New Spotify Large Font Size [26]: " spot_large_font_size; \
	spot_large_font_size=$${spot_large_font_size:-$$current_spot_large_font_size}; \
	echo "  Spotify Medium Font Path: $$current_spot_medium_font_path"; \
	read -p "  New Spotify Medium Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf]: " spot_medium_font_path; \
	spot_medium_font_path=$${spot_medium_font_path:-$$current_spot_medium_font_path}; \
	echo "  Spotify Medium Font Size: $$current_spot_medium_font_size"; \
	read -p "  New Spotify Medium Font Size [18]: " spot_medium_font_size; \
	spot_medium_font_size=$${spot_medium_font_size:-$$current_spot_medium_font_size}; \
	echo "  Spotify Small Font Path: $$current_spot_small_font_path"; \
	read -p "  New Spotify Small Font Path [/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf]: " spot_small_font_path; \
	spot_small_font_path=$${spot_small_font_path:-$$current_spot_small_font_path}; \
	echo "  Spotify Small Font Size: $$current_spot_small_font_size"; \
	read -p "  New Spotify Small Font Size [12]: " spot_small_font_size; \
	spot_small_font_size=$${spot_small_font_size:-$$current_spot_small_font_size}; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['fonts']['large_font_path'] = '$$large_font_path'; config['fonts']['large_font_size'] = int('$$large_font_size'); config['fonts']['medium_font_path'] = '$$medium_font_path'; config['fonts']['medium_font_size'] = int('$$medium_font_size'); config['fonts']['small_font_path'] = '$$small_font_path'; config['fonts']['small_font_size'] = int('$$small_font_size'); config['fonts']['spot_large_font_path'] = '$$spot_large_font_path'; config['fonts']['spot_large_font_size'] = int('$$spot_large_font_size'); config['fonts']['spot_medium_font_path'] = '$$spot_medium_font_path'; config['fonts']['spot_medium_font_size'] = int('$$spot_medium_font_size'); config['fonts']['spot_small_font_path'] = '$$spot_small_font_path'; config['fonts']['spot_small_font_size'] = int('$$spot_small_font_size'); toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ Font settings updated$(NC)"
	@echo ""

config-buttons:
	@echo "$(BLUE)--- BUTTON GPIO CONFIGURATION ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_button_a=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('buttons', {}).get('button_a', 5))" 2>/dev/null || echo "5"); \
	current_button_b=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('buttons', {}).get('button_b', 6))" 2>/dev/null || echo "6"); \
	current_button_x=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('buttons', {}).get('button_x', 16))" 2>/dev/null || echo "16"); \
	current_button_y=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('buttons', {}).get('button_y', 24))" 2>/dev/null || echo "24"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "  Button A GPIO Pin: $$current_button_a"; \
	read -p "  New Button A GPIO Pin [5]: " button_a; \
	button_a=$${button_a:-$$current_button_a}; \
	echo "  Button B GPIO Pin: $$current_button_b"; \
	read -p "  New Button B GPIO Pin [6]: " button_b; \
	button_b=$${button_b:-$$current_button_b}; \
	echo "  Button X GPIO Pin: $$current_button_x"; \
	read -p "  New Button X GPIO Pin [16]: " button_x; \
	button_x=$${button_x:-$$current_button_x}; \
	echo "  Button Y GPIO Pin: $$current_button_y"; \
	read -p "  New Button Y GPIO Pin [24]: " button_y; \
	button_y=$${button_y:-$$current_button_y}; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['buttons']['button_a'] = int('$$button_a'); config['buttons']['button_b'] = int('$$button_b'); config['buttons']['button_x'] = int('$$button_x'); config['buttons']['button_y'] = int('$$button_y'); toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ Button GPIO settings updated$(NC)"
	@echo ""

config-wifi:
	@echo "$(BLUE)--- WIFI SETTINGS ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_ap_ssid=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('wifi', {}).get('ap_ssid', 'Neonwifi-Manager'))" 2>/dev/null || echo "Neonwifi-Manager"); \
	current_ap_ip=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('wifi', {}).get('ap_ip', '192.168.42.1'))" 2>/dev/null || echo "192.168.42.1"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "  AP SSID: $$current_ap_ssid"; \
	read -p "  New AP SSID [Neonwifi-Manager]: " ap_ssid; \
	ap_ssid=$${ap_ssid:-$$current_ap_ssid}; \
	echo "  AP IP: $$current_ap_ip"; \
	read -p "  New AP IP [192.168.42.1]: " ap_ip; \
	ap_ip=$${ap_ip:-$$current_ap_ip}; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['wifi']['ap_ssid'] = '$$ap_ssid'; config['wifi']['ap_ip'] = '$$ap_ip'; toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ WiFi settings updated$(NC)"
	@echo ""

config-settings:
	@echo "$(BLUE)--- GENERAL SETTINGS ---$(NC)"
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "$(YELLOW)Creating default config file...$(NC)"; \
		make create-default-config > /dev/null 2>&1; \
	fi
	@current_start_screen=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('start_screen', 'spotify'))" 2>/dev/null || echo "spotify"); \
	current_fallback_city=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('fallback_city', ''))" 2>/dev/null || echo ""); \
	current_clock_type=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('clock', {}).get('type', 'analog'))" 2>/dev/null || echo "analog"); \
	current_clock_background=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('clock', {}).get('background', 'color'))" 2>/dev/null || echo "color"); \
	current_clock_color=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('clock', {}).get('color', 'black'))" 2>/dev/null || echo "black"); \
	current_use_gpsd=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('use_gpsd', True))" 2>/dev/null || echo "True"); \
	current_use_google_geo=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('use_google_geo', True))" 2>/dev/null || echo "True"); \
	current_time_display=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('time_display', True))" 2>/dev/null || echo "True"); \
	current_progressbar_display=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('progressbar_display', True))" 2>/dev/null || echo "True"); \
	current_enable_current_track_display=$$($(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(config.get('settings', {}).get('enable_current_track_display', True))" 2>/dev/null || echo "True"); \
	echo "$(YELLOW)Current values (press Enter to keep):$(NC)"; \
	echo "  Start Screen: $$current_start_screen"; \
	read -p "  New Start Screen [spotify]: " start_screen; \
	start_screen=$${start_screen:-$$current_start_screen}; \
	echo "  Fallback City: $$current_fallback_city"; \
	read -p "  New Fallback City: " fallback_city; \
	fallback_city=$${fallback_city:-$$current_fallback_city}; \
	echo "  Clock Type: $$current_clock_type"; \
	read -p "  New Clock Type [analog]: " clock_type; \
	clock_type=$${clock_type:-$$current_clock_type}; \
	echo "  Clock Background: $$current_clock_background"; \
	read -p "  New Clock Background [color]: " clock_background; \
	clock_background=$${clock_background:-$$current_clock_background}; \
	echo "  Clock Color: $$current_clock_color"; \
	read -p "  New Clock Color [black]: " clock_color; \
	clock_color=$${clock_color:-$$current_clock_color}; \
	echo "$(YELLOW)Enable/Disable Features (y/n, press Enter to keep current):$(NC)"; \
	echo "  Use GPSD: $$current_use_gpsd"; \
	read -p "  Enable GPSD [y]: " use_gpsd; \
	if [ -z "$$use_gpsd" ]; then use_gpsd_bool=$$current_use_gpsd; elif [ "$$use_gpsd" = "y" ] || [ "$$use_gpsd" = "Y" ]; then use_gpsd_bool=True; else use_gpsd_bool=False; fi; \
	echo "  Use Google Geo: $$current_use_google_geo"; \
	read -p "  Enable Google Geo [y]: " use_google_geo; \
	if [ -z "$$use_google_geo" ]; then use_google_geo_bool=$$current_use_google_geo; elif [ "$$use_google_geo" = "y" ] || [ "$$use_google_geo" = "Y" ]; then use_google_geo_bool=True; else use_google_geo_bool=False; fi; \
	echo "  Time Display: $$current_time_display"; \
	read -p "  Enable Time Display [y]: " time_display; \
	if [ -z "$$time_display" ]; then time_display_bool=$$current_time_display; elif [ "$$time_display" = "y" ] || [ "$$time_display" = "Y" ]; then time_display_bool=True; else time_display_bool=False; fi; \
	echo "  Progress Bar Display: $$current_progressbar_display"; \
	read -p "  Enable Progress Bar Display [y]: " progressbar_display; \
	if [ -z "$$progressbar_display" ]; then progressbar_display_bool=$$current_progressbar_display; elif [ "$$progressbar_display" = "y" ] || [ "$$progressbar_display" = "Y" ]; then progressbar_display_bool=True; else progressbar_display_bool=False; fi; \
	echo "  Current Track Display: $$current_enable_current_track_display"; \
	read -p "  Enable Current Track Display [y]: " enable_current_track_display; \
	if [ -z "$$enable_current_track_display" ]; then enable_current_track_display_bool=$$current_enable_current_track_display; elif [ "$$enable_current_track_display" = "y" ] || [ "$$enable_current_track_display" = "Y" ]; then enable_current_track_display_bool=True; else enable_current_track_display_bool=False; fi; \
	$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); config['settings']['start_screen'] = '$$start_screen'; config['settings']['fallback_city'] = '$$fallback_city'; config['settings']['use_gpsd'] = $$use_gpsd_bool; config['settings']['use_google_geo'] = $$use_google_geo_bool; config['settings']['time_display'] = $$time_display_bool; config['settings']['progressbar_display'] = $$progressbar_display_bool; config['settings']['enable_current_track_display'] = $$enable_current_track_display_bool; config['clock']['type'] = '$$clock_type'; config['clock']['background'] = '$$clock_background'; config['clock']['color'] = '$$clock_color'; toml.dump(config, open('$(CONFIG_FILE)', 'w'))"; \
	echo "$(GREEN)✓ General settings updated$(NC)"
	@echo ""

view-config:
	@echo "$(BLUE)--- CURRENT CONFIGURATION ---$(NC)"
	@if [ -f "$(CONFIG_FILE)" ]; then \
		$(VENV_DIR)/bin/python3 -c "import toml; config = toml.load('$(CONFIG_FILE)'); print(toml.dumps(config))"; \
	else \
		echo "$(YELLOW)No configuration file found. Run 'make config' to create one.$(NC)"; \
	fi

reset-config:
	@echo "$(RED)WARNING: This will reset all configuration to defaults!$(NC)"
	@read -p "Are you sure? (y/N): " choice; \
	if [ "$$choice" = "y" ] || [ "$$choice" = "Y" ]; then \
		make create-default-config > /dev/null 2>&1; \
		echo "$(GREEN)✓ Configuration reset to defaults$(NC)"; \
	else \
		echo "Reset cancelled."; \
	fi

create-default-config:
	@$(VENV_DIR)/bin/python3 -c " \
import toml; \
DEFAULT_CONFIG = { \
    'display': { \
        'type': 'framebuffer', \
        'framebuffer': '/dev/fb1', \
        'rotation': 0, \
        'st7789': { \
            'spi_port': 0, \
            'spi_cs': 1, \
            'dc_pin': 9, \
            'backlight_pin': 13, \
            'rotation': 0, \
            'spi_speed': 60000000 \
        } \
    }, \
    'fonts': { \
        'large_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', \
        'large_font_size': 36, \
        'medium_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', \
        'medium_font_size': 24, \
        'small_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', \
        'small_font_size': 16, \
        'spot_large_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', \
        'spot_large_font_size': 26, \
        'spot_medium_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', \
        'spot_medium_font_size': 18, \
        'spot_small_font_path': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', \
        'spot_small_font_size': 12 \
    }, \
    'api_keys': { \
        'openweather': '', \
        'google_geo': '', \
        'client_id': '', \
        'client_secret': '', \
        'redirect_uri': 'http://127.0.0.1:5000' \
    }, \
    'settings': { \
        'framebuffer': '/dev/fb1', \
        'start_screen': 'weather', \
        'fallback_city': '', \
        'use_gpsd': True, \
        'use_google_geo': True, \
        'time_display': True, \
        'progressbar_display': True, \
        'enable_current_track_display': True \
    }, \
    'wifi': { \
        'ap_ssid': 'Neonwifi-Manager', \
        'ap_ip': '192.168.42.1', \
    }, \
    'auto_start': { \
        'auto_start_hud': True, \
        'auto_start_neonwifi': True, \
        'check_internet': True \
    }, \
    'clock': { \
        'type': 'analog', \
        'background': 'color', \
        'color': 'black' \
    }, \
    'buttons': { \
        'button_a': 5, \
        'button_b': 6, \
        'button_x': 16, \
        'button_y': 24 \
    }, \
    'ui': { \
        'theme': 'dark' \
    } \
}; \
with open('$(CONFIG_FILE)', 'w') as f: \
    toml.dump(DEFAULT_CONFIG, f) \
"

start:
	sudo systemctl start $(SERVICE_NAME).service
	@echo "$(GREEN)Service started$(NC)"

stop:
	sudo systemctl stop $(SERVICE_NAME).service
	@echo "$(YELLOW)Service stopped$(NC)"

restart: stop start

status:
	@echo "$(GREEN)Service status:$(NC)"
	sudo systemctl status $(SERVICE_NAME).service

logs:
	@echo "$(GREEN)Service logs (journalctl):$(NC)"
	sudo journalctl -u $(SERVICE_NAME).service -f

tail:
	@echo "$(GREEN)Viewing program logs:$(NC)"
	tail -f /opt/neondisplay/backuplogs/neondisplay.log

update-packages:
	@echo "$(GREEN)Updating Python packages with uv...$(NC)"
	sudo systemctl stop $(SERVICE_NAME).service
	uv pip install --python $(VENV_DIR)/bin/python --upgrade spotipy st7789 eink-wave evdev numpy pillow flask pycairo dbus-python toml
	sudo systemctl start $(SERVICE_NAME).service
	@echo "$(GREEN)Packages updated and service restarted$(NC)"

run:
	@echo "$(GREEN)Running in virtual environment...$(NC)"
	$(VENV_DIR)/bin/python3 neondisplay.py

venv-info:
	@echo "$(GREEN)Virtual environment info:$(NC)"
	@echo "Location: $(VENV_DIR)"
	@echo "Python: $$($(VENV_DIR)/bin/python3 --version)"
	@echo "Package manager: uv"
	@echo ""
	@echo "$(GREEN)Installed packages:$(NC)"
	$(VENV_DIR)/bin/pip list

clean:
	@echo "$(YELLOW)Cleaning up...$(NC)"
	sudo systemctl stop $(SERVICE_NAME).service 2>/dev/null || true
	sudo systemctl disable $(SERVICE_NAME).service 2>/dev/null || true
	sudo rm -f $(SERVICE_FILE)
	sudo systemctl daemon-reload
	sudo rm -rf $(PROJECT_DIR)
	rm -rf LCD-show
	@echo "$(GREEN)Cleanup complete$(NC)"

help:
	@echo "$(GREEN)NeonDisplay Setup Makefile (using uv)$(NC)"
	@echo ""
	@echo "$(YELLOW)Available targets:$(NC)"
	@echo "  $(GREEN)all$(NC)             - Complete installation(not display)"
	@echo "  $(GREEN)system-deps$(NC)     - Install system dependencies and uv"
	@echo "  $(GREEN)python-packages$(NC) - Setup venv and install ALL Python packages via uv"
	@echo "  $(GREEN)setup-service$(NC)   - Setup systemd service using virtual environment"
	@echo "  $(GREEN)setup-display$(NC)   - $(RED)WARNING: Install LCD drivers and reboot$(NC)"
	@echo "  $(GREEN)config$(NC)          - Walk-through configuration (all settings)"
	@echo "  $(GREEN)config-api$(NC)      - Configure API keys"
	@echo "  $(GREEN)config-display$(NC)  - Configure display settings"
	@echo "  $(GREEN)config-fonts$(NC)    - Configure font settings"
	@echo "  $(GREEN)config-buttons$(NC)  - Configure button GPIO pins"
	@echo "  $(GREEN)config-wifi$(NC)     - Configure WiFi settings"
	@echo "  $(GREEN)config-settings$(NC) - Configure general settings"
	@echo "  $(GREEN)view-config$(NC)     - View current configuration"
	@echo "  $(GREEN)reset-config$(NC)    - Reset configuration to defaults"
	@echo ""
	@echo "  $(GREEN)start$(NC)           - Start the service"
	@echo "  $(GREEN)stop$(NC)            - Stop the service"
	@echo "  $(GREEN)restart$(NC)         - Restart the service"
	@echo "  $(GREEN)status$(NC)          - Check service status"
	@echo "  $(GREEN)logs$(NC)            - Follow service logs (journalctl -f)"
	@echo "  $(GREEN)tail$(NC)            - View program logs"
	@echo "  $(GREEN)update-packages$(NC) - Update Python packages with uv"
	@echo "  $(GREEN)run$(NC)             - Run directly in virtual environment (testing)"
	@echo "  $(GREEN)venv-info$(NC)       - Show virtual environment information"
	@echo "  $(GREEN)clean$(NC)           - Remove service and project files"
	@echo "  $(GREEN)help$(NC)            - Show this help message"
	@echo ""
	@echo "$(YELLOW)Recommended workflow:$(NC)"
	@echo "  1. sudo make"
	@echo "  2. make config"
	@echo "  3. make setup-display  $(RED)(will reboot)$(NC)"
	@echo "  4. make start"
	@echo "  5. make status"
	@echo "  6. make logs"
	@echo "  7. make tail"