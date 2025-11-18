# Makefile for HUD35 Setup with Virtual Environment

VENV_DIR = /opt/hud35/venv
SERVICE_NAME = hud35
PROJECT_DIR = /opt/hud35
SERVICE_FILE = /etc/systemd/system/$(SERVICE_NAME).service
LCD_SHOW_DIR = LCD-show

# Colors for output
GREEN = \033[0;32m
YELLOW = \033[0;33m
RED = \033[0;31m
NC = \033[0m # No Color

.PHONY: all install system-deps python-packages setup-display setup-service clean status logs help

# Default target - full installation
all: system-deps python-packages setup-service
	@echo "$(GREEN)Installation complete!$(NC)"
	@echo ""
	@echo "$(YELLOW)Next steps:$(NC)"
	@echo "1. $(YELLOW)Run 'make setup-display' to install LCD drivers (will reboot)$(NC)"
	@echo "2. $(YELLOW)Check status: make status$(NC)"
	@echo "3. $(YELLOW)View logs: make logs$(NC)"

# Install system dependencies (only system libraries, no Python packages)
system-deps:
	@echo "$(GREEN)Installing system dependencies...$(NC)"
	sudo apt update
	sudo apt install -y python3-pip python3-venv
	# Install only system libraries needed for Python package compilation
	sudo apt install -y libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev git
	sudo apt install -y liblcms2-dev libwebp-dev libtiff-dev libopenjp2-7-dev libxcb1-dev
	sudo apt install -y libopenblas-dev libcairo2-dev libdbus-1-dev
	@echo "$(GREEN)System dependencies installed$(NC)"

# Create virtual environment and install ALL Python packages via pip
python-packages: system-deps
	@echo "$(GREEN)Setting up Python virtual environment...$(NC)"
	sudo mkdir -p $(PROJECT_DIR)
	sudo chown $$USER:$$USER $(PROJECT_DIR)
	
	# Create virtual environment
	python3 -m venv $(VENV_DIR)
	
	# Install ALL packages in virtual environment (no apt Python packages)
	@echo "$(GREEN)Installing Python packages in virtual environment...$(NC)"
	$(VENV_DIR)/bin/pip install --upgrade pip
	$(VENV_DIR)/bin/pip install spotipy st7789 eink-wave
	$(VENV_DIR)/bin/pip install evdev numpy pillow waitress
	$(VENV_DIR)/bin/pip install pycairo dbus-python
	$(VENV_DIR)/bin/pip install toml
	
	# Install any additional dependencies that might be needed
	$(VENV_DIR)/bin/pip install setuptools wheel
	
	@echo "$(GREEN)All Python packages installed in virtual environment$(NC)"
	
	# Copy project files
	@echo "$(GREEN)Copying project files...$(NC)"
	cp -r . $(PROJECT_DIR)/
	
	# Fix waveshare config in virtual environment
	if [ -f "./waveshare/epdconfig.py" ]; then \
		sudo cp ./waveshare/epdconfig.py $(VENV_DIR)/lib/python3.*/site-packages/waveshare_epd/; \
		echo "$(GREEN)Waveshare config updated in virtual environment$(NC)"; \
	fi

# Setup LCD display drivers (WARNING: will reboot)
setup-display:
	@echo "$(YELLOW)WARNING: This will install LCD drivers and reboot the system!$(NC)"
	@echo "$(YELLOW)Make sure to save any work before continuing.$(NC)"
	@read -p "Continue? [y/N] " choice; \
	if [ "$$choice" != "y" ] && [ "$$choice" != "Y" ]; then \
		echo "Aborted."; \
		exit 1; \
	fi
	@echo "$(GREEN)Installing LCD display drivers...$(NC)"
	git clone https://github.com/Shinigamy19/RaspberryPi3bplus-3.5inch-displayA-ILI9486-MPI3501-XPT2046 $(LCD_SHOW_DIR)
	mv $(LCD_SHOW_DIR) LCD-show
	cd LCD-show && chmod +x ./*
	sudo ./LCD35-show
	# System will reboot after this

# Setup systemd service using virtual environment - UPDATED FOR YOUR SERVICE FILE
setup-service: python-packages
	@echo "$(GREEN)Setting up systemd service...$(NC)"
	
	# Update your service file to use the virtual environment Python
	@if [ -f "hud35.service" ]; then \
		echo "$(GREEN)Updating existing hud35.service to use virtual environment...$(NC)"; \
		sed 's|/usr/bin/python3|$(VENV_DIR)/bin/python3|' hud35.service > hud35.service.venv; \
		sudo cp hud35.service.venv $(SERVICE_FILE); \
		rm hud35.service.venv; \
	else \
		echo "$(YELLOW)No hud35.service found, creating one...$(NC)"; \
		echo "[Unit]" > hud35.service.tmp; \
		echo "Description=HUD35 Launcher Service" >> hud35.service.tmp; \
		echo "After=network.target" >> hud35.service.tmp; \
		echo "Wants=network.target" >> hud35.service.tmp; \
		echo "" >> hud35.service.tmp; \
		echo "[Service]" >> hud35.service.tmp; \
		echo "Type=simple" >> hud35.service.tmp; \
		echo "User=root" >> hud35.service.tmp; \
		echo "Group=root" >> hud35.service.tmp; \
		echo "WorkingDirectory=$(PROJECT_DIR)" >> hud35.service.tmp; \
		echo "ExecStart=$(VENV_DIR)/bin/python3 $(PROJECT_DIR)/launcher.py" >> hud35.service.tmp; \
		echo "Restart=on-failure" >> hud35.service.tmp; \
		echo "RestartSec=10" >> hud35.service.tmp; \
		echo "StandardOutput=journal" >> hud35.service.tmp; \
		echo "StandardError=journal" >> hud35.service.tmp; \
		echo "" >> hud35.service.tmp; \
		echo "[Install]" >> hud35.service.tmp; \
		echo "WantedBy=multi-user.target" >> hud35.service.tmp; \
		sudo cp hud35.service.tmp $(SERVICE_FILE); \
		rm hud35.service.tmp; \
	fi
	
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE_NAME).service
	
	@echo "$(GREEN)Systemd service setup complete$(NC)"
	@echo "$(GREEN)Service will use virtual environment at: $(VENV_DIR)$(NC)"

# Start the service
start:
	sudo systemctl start $(SERVICE_NAME).service
	@echo "$(GREEN)Service started$(NC)"

# Stop the service
stop:
	sudo systemctl stop $(SERVICE_NAME).service
	@echo "$(YELLOW)Service stopped$(NC)"

# Restart the service
restart: stop start

# Check service status
status:
	@echo "$(GREEN)Service status:$(NC)"
	sudo systemctl status $(SERVICE_NAME).service

# View service logs via journalctl (since you use journal)
logs:
	@echo "$(GREEN)Service logs (journalctl):$(NC)"
	sudo journalctl -u $(SERVICE_NAME).service -f

# View last 50 lines of logs
tail:
	@echo "$(GREEN)Viewing program logs:$(NC)"
	tail -f /opt/hud35/hud35.log

# Update Python packages (after service is setup)
update-packages:
	@echo "$(GREEN)Updating Python packages in virtual environment...$(NC)"
	sudo systemctl stop $(SERVICE_NAME).service
	$(VENV_DIR)/bin/pip install --upgrade spotipy st7789 eink-wave evdev numpy pillow flask
	sudo systemctl start $(SERVICE_NAME).service
	@echo "$(GREEN)Packages updated and service restarted$(NC)"

# Run Python script directly in virtual environment (for testing)
run:
	@echo "$(GREEN)Running in virtual environment...$(NC)"
	$(VENV_DIR)/bin/python3 launcher.py

# Show virtual environment info
venv-info:
	@echo "$(GREEN)Virtual environment info:$(NC)"
	@echo "Location: $(VENV_DIR)"
	@echo "Python: $$($(VENV_DIR)/bin/python3 --version)"
	@echo "Pip: $$($(VENV_DIR)/bin/pip --version)"
	@echo ""
	@echo "$(GREEN)Installed packages:$(NC)"
	$(VENV_DIR)/bin/pip list

# Clean up (remove service and project files)
clean:
	@echo "$(YELLOW)Cleaning up...$(NC)"
	sudo systemctl stop $(SERVICE_NAME).service 2>/dev/null || true
	sudo systemctl disable $(SERVICE_NAME).service 2>/dev/null || true
	sudo rm -f $(SERVICE_FILE)
	sudo systemctl daemon-reload
	sudo rm -rf $(PROJECT_DIR)
	rm -rf LCD-show
	@echo "$(GREEN)Cleanup complete$(NC)"

# Show this help
help:
	@echo "$(GREEN)HUD35 Setup Makefile (Virtual Environment Only)$(NC)"
	@echo ""
	@echo "$(YELLOW)Available targets:$(NC)"
	@echo "  $(GREEN)all$(NC)             - Complete installation"
	@echo "  $(GREEN)system-deps$(NC)     - Install system dependencies only"
	@echo "  $(GREEN)python-packages$(NC) - Setup venv and install ALL Python packages via pip"
	@echo "  $(GREEN)setup-service$(NC)   - Setup systemd service using virtual environment"
	@echo "  $(GREEN)setup-display$(NC)   - $(RED)WARNING: Install LCD drivers and reboot$(NC)"
	@echo ""
	@echo "  $(GREEN)start$(NC)           - Start the service"
	@echo "  $(GREEN)stop$(NC)            - Stop the service"
	@echo "  $(GREEN)restart$(NC)         - Restart the service"
	@echo "  $(GREEN)status$(NC)          - Check service status"
	@echo "  $(GREEN)logs$(NC)            - Follow service logs (journalctl -f)"
	@echo "  $(GREEN)tail$(NC)            - View program logs"
	@echo "  $(GREEN)update-packages$(NC) - Update Python packages in venv"
	@echo "  $(GREEN)run$(NC)             - Run directly in virtual environment (testing)"
	@echo "  $(GREEN)venv-info$(NC)       - Show virtual environment information"
	@echo "  $(GREEN)clean$(NC)           - Remove service and project files"
	@echo "  $(GREEN)help$(NC)            - Show this help message"
	@echo ""
	@echo "$(YELLOW)Key features:$(NC)"
	@echo "  • All Python packages installed in virtual environment"
	@echo "  • No system Python packages used via apt"
	@echo "  • Service runs from virtual environment"
	@echo "  • Uses your existing service file structure"
	@echo ""
	@echo "$(YELLOW)Recommended workflow:$(NC)"
	@echo "  1. make all"
	@echo "  2. make setup-display  $(RED)(will reboot)$(NC)"
	@echo "  3. make start"
	@echo "  4. make status"
	@echo "  5. make logs"