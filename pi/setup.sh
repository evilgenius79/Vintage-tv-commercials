#!/bin/bash
# =============================================================================
# Vintage TV Commercial Downloader — Raspberry Pi 5 + Hailo-8 Setup Script
#
# Run this on a fresh Raspberry Pi OS (64-bit Bookworm) installation.
# It installs all dependencies, configures services, and gets everything
# running as an always-on commercial processing station.
#
# Usage:
#   curl -sSL <this-url> | bash
#   # or
#   chmod +x setup.sh && ./setup.sh
# =============================================================================

set -euo pipefail

APP_DIR="/opt/vintage-commercials"
DATA_DIR="/var/lib/vintage-commercials"
VENV_DIR="$APP_DIR/venv"
USER="vintage"
REPO_URL="https://github.com/evilgenius79/Vintage-tv-commercials.git"
BRANCH="claude/vintage-commercial-downloader-ZdZfA"

echo "============================================"
echo " Vintage TV Commercial Downloader"
echo " Raspberry Pi 5 + Hailo-8 Setup"
echo "============================================"
echo ""

# --- System packages ---
echo "[1/8] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg \
    git \
    deno \
    libopencv-dev python3-opencv \
    libgstreamer1.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    nginx \
    2>/dev/null

# --- Hailo SDK ---
echo "[2/8] Setting up Hailo-8 SDK..."
if [ -f /usr/lib/libhailort.so ] || dpkg -l | grep -q hailort; then
    echo "  Hailo RT already installed"
else
    echo "  Installing HailoRT..."
    # Hailo provides a .deb for Pi 5
    if [ -f /tmp/hailort.deb ]; then
        sudo dpkg -i /tmp/hailort.deb || sudo apt-get install -f -y
    else
        echo "  NOTE: Download the HailoRT .deb from https://hailo.ai/developer-zone/"
        echo "        Place it at /tmp/hailort.deb and re-run this script."
        echo "        Continuing without Hailo (CPU mode will be used)..."
    fi
fi

# Install hailo_platform Python package if available
if python3 -c "import hailo_platform" 2>/dev/null; then
    echo "  Hailo Python SDK already installed"
else
    pip3 install hailort 2>/dev/null || echo "  Hailo Python SDK not available (CPU fallback OK)"
fi

# --- Create app user ---
echo "[3/8] Creating application user..."
if ! id "$USER" &>/dev/null; then
    sudo useradd -r -m -d "$DATA_DIR" -s /bin/bash "$USER"
fi

# --- Clone/update repo ---
echo "[4/8] Setting up application..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    sudo -u "$USER" git pull origin "$BRANCH" 2>/dev/null || true
else
    sudo git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    sudo chown -R "$USER":"$USER" "$APP_DIR"
fi

# --- Python virtual environment ---
echo "[5/8] Setting up Python environment..."
if [ ! -d "$VENV_DIR" ]; then
    sudo -u "$USER" python3 -m venv "$VENV_DIR"
fi

sudo -u "$USER" "$VENV_DIR/bin/pip" install --upgrade pip -q
sudo -u "$USER" "$VENV_DIR/bin/pip" install -e "$APP_DIR" -q
sudo -u "$USER" "$VENV_DIR/bin/pip" install "scenedetect[opencv]" Pillow onnxruntime -q

# --- Create data directories ---
echo "[6/8] Creating data directories..."
sudo mkdir -p "$DATA_DIR"/{downloads,clips,models}
sudo chown -R "$USER":"$USER" "$DATA_DIR"

# --- Install systemd services ---
echo "[7/8] Installing systemd services..."

# Web interface service
sudo tee /etc/systemd/system/vintage-web.service > /dev/null << 'UNIT'
[Unit]
Description=Vintage TV Commercials Web Interface
After=network.target

[Service]
Type=simple
User=vintage
Group=vintage
WorkingDirectory=/var/lib/vintage-commercials
Environment=VINTAGE_DB=/var/lib/vintage-commercials/catalog.db
Environment=VINTAGE_DOWNLOADS=/var/lib/vintage-commercials/downloads
ExecStart=/opt/vintage-commercials/venv/bin/vintage-commercials web --host 0.0.0.0 --port 5000 --no-browser
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# Auto-processor service — watches for new downloads and processes them
sudo tee /etc/systemd/system/vintage-processor.service > /dev/null << 'UNIT'
[Unit]
Description=Vintage TV Commercials Auto-Processor (Hailo AI)
After=network.target vintage-web.service

[Service]
Type=oneshot
User=vintage
Group=vintage
WorkingDirectory=/var/lib/vintage-commercials
Environment=VINTAGE_DB=/var/lib/vintage-commercials/catalog.db
Environment=VINTAGE_DOWNLOADS=/var/lib/vintage-commercials/downloads
ExecStart=/opt/vintage-commercials/venv/bin/vintage-commercials process --clips-dir /var/lib/vintage-commercials/clips

[Install]
WantedBy=multi-user.target
UNIT

# Timer to run the processor every 30 minutes
sudo tee /etc/systemd/system/vintage-processor.timer > /dev/null << 'UNIT'
[Unit]
Description=Run Vintage Commercial Processor every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

# Nightly batch scanner — searches for new commercials at 2am
sudo tee /etc/systemd/system/vintage-scanner.service > /dev/null << 'UNIT'
[Unit]
Description=Vintage TV Commercials Nightly Scanner
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=vintage
Group=vintage
WorkingDirectory=/var/lib/vintage-commercials
Environment=VINTAGE_DB=/var/lib/vintage-commercials/catalog.db
Environment=VINTAGE_DOWNLOADS=/var/lib/vintage-commercials/downloads
ExecStart=/opt/vintage-commercials/venv/bin/vintage-commercials batch --db /var/lib/vintage-commercials/catalog.db
UNIT

sudo tee /etc/systemd/system/vintage-scanner.timer > /dev/null << 'UNIT'
[Unit]
Description=Run Vintage Commercial Scanner nightly at 2am

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT

# --- Nginx reverse proxy (port 80 -> 5000) ---
sudo tee /etc/nginx/sites-available/vintage-commercials > /dev/null << 'NGINX'
server {
    listen 80;
    server_name _;

    client_max_body_size 0;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    location /video/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_buffering off;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/vintage-commercials /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# --- Enable and start services ---
echo "[8/8] Starting services..."
sudo systemctl daemon-reload
sudo systemctl enable --now vintage-web.service
sudo systemctl enable --now vintage-processor.timer
sudo systemctl enable --now vintage-scanner.timer
sudo systemctl restart nginx

# --- Print summary ---
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "============================================"
echo " Setup complete!"
echo "============================================"
echo ""
echo " Web interface:   http://$IP"
echo " Data directory:  $DATA_DIR"
echo " Downloads:       $DATA_DIR/downloads"
echo " Clips:           $DATA_DIR/clips"
echo " Database:        $DATA_DIR/catalog.db"
echo ""
echo " Services:"
echo "   vintage-web.service       — Web UI (always on)"
echo "   vintage-processor.timer   — Auto-split every 30min"
echo "   vintage-scanner.timer     — Nightly batch search at 2am"
echo ""
echo " Commands:"
echo "   vintage-commercials search 'coca cola' --decade 1980s"
echo "   vintage-commercials batch --decades 1980s,1990s"
echo "   vintage-commercials process"
echo "   vintage-commercials split downloads/some_compilation.mp4"
echo ""
if python3 -c "import hailo_platform" 2>/dev/null; then
    echo " Hailo-8: DETECTED (26 TOPS hardware acceleration enabled)"
else
    echo " Hailo-8: Not detected (using CPU mode)"
    echo "   To enable: install HailoRT and place .hef model in $DATA_DIR/models/"
fi
echo ""
