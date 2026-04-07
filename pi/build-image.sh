#!/bin/bash
# =============================================================================
# Build a custom Raspberry Pi OS image with Vintage TV Commercials pre-installed.
#
# Uses pi-gen (the official Raspberry Pi OS build tool) to create a .img file
# that has everything ready to go — just flash it to an SD card and boot.
#
# Requirements (run on a Linux x86_64 machine or Pi):
#   - Docker (recommended) or: debootstrap, qemu-user-static
#   - ~10GB free disk space
#   - Internet connection
#
# Usage:
#   chmod +x build-image.sh
#   ./build-image.sh
#
# Output:
#   deploy/vintage-commercials-pi5.img.xz
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="/tmp/vintage-pi-build"
PIGEN_DIR="$BUILD_DIR/pi-gen"
STAGE_DIR="$PIGEN_DIR/stage-vintage"
OUTPUT_DIR="$REPO_ROOT/deploy"

echo "============================================"
echo " Building Vintage Commercials Pi OS Image"
echo "============================================"

# --- Clone pi-gen ---
echo "[1/5] Setting up pi-gen..."
mkdir -p "$BUILD_DIR"
if [ ! -d "$PIGEN_DIR" ]; then
    git clone --depth=1 https://github.com/RPi-Distro/pi-gen.git "$PIGEN_DIR"
fi

# --- Configure pi-gen ---
echo "[2/5] Configuring build..."
cat > "$PIGEN_DIR/config" << 'CONFIG'
IMG_NAME=vintage-commercials-pi5
RELEASE=bookworm
TARGET_HOSTNAME=vintage-tv
FIRST_USER_NAME=pi
FIRST_USER_PASS=vintage
ENABLE_SSH=1
LOCALE_DEFAULT=en_US.UTF-8
KEYBOARD_KEYMAP=us
TIMEZONE_DEFAULT=America/New_York
STAGE_LIST="stage0 stage1 stage2 stage-vintage"
CONFIG

# --- Create custom stage ---
echo "[3/5] Creating custom stage..."
mkdir -p "$STAGE_DIR"

# Package list
cat > "$STAGE_DIR/00-packages" << 'PACKAGES'
ffmpeg
python3
python3-venv
python3-pip
python3-dev
python3-opencv
libopencv-dev
git
nginx
deno
PACKAGES

# Pre-install script
mkdir -p "$STAGE_DIR/01-vintage-install"
cat > "$STAGE_DIR/01-vintage-install/00-run-chroot.sh" << 'CHROOT'
#!/bin/bash

APP_DIR="/opt/vintage-commercials"
DATA_DIR="/var/lib/vintage-commercials"
VENV_DIR="$APP_DIR/venv"
REPO_URL="https://github.com/evilgenius79/Vintage-tv-commercials.git"
BRANCH="claude/vintage-commercial-downloader-ZdZfA"

# Create app user
useradd -r -m -d "$DATA_DIR" -s /bin/bash vintage || true

# Clone repo
git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
chown -R vintage:vintage "$APP_DIR"

# Python virtual environment
su - vintage -c "python3 -m venv $VENV_DIR"
su - vintage -c "$VENV_DIR/bin/pip install --upgrade pip"
su - vintage -c "$VENV_DIR/bin/pip install -e $APP_DIR"
su - vintage -c "$VENV_DIR/bin/pip install 'scenedetect[opencv]' Pillow onnxruntime"

# Create data directories
mkdir -p "$DATA_DIR"/{downloads,clips,models}
chown -R vintage:vintage "$DATA_DIR"

# Add vintage-commercials to PATH for all users
echo 'export PATH="/opt/vintage-commercials/venv/bin:$PATH"' > /etc/profile.d/vintage-commercials.sh

# Symlink for convenience
ln -sf "$VENV_DIR/bin/vintage-commercials" /usr/local/bin/vintage-commercials
CHROOT
chmod +x "$STAGE_DIR/01-vintage-install/00-run-chroot.sh"

# Install systemd services
mkdir -p "$STAGE_DIR/02-services"
cat > "$STAGE_DIR/02-services/00-run-chroot.sh" << 'SERVICES'
#!/bin/bash

# Web interface
cat > /etc/systemd/system/vintage-web.service << 'EOF'
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
EOF

# Auto-processor timer
cat > /etc/systemd/system/vintage-processor.service << 'EOF'
[Unit]
Description=Vintage TV Commercials Auto-Processor (Hailo AI)
After=network.target

[Service]
Type=oneshot
User=vintage
Group=vintage
WorkingDirectory=/var/lib/vintage-commercials
Environment=VINTAGE_DB=/var/lib/vintage-commercials/catalog.db
Environment=VINTAGE_DOWNLOADS=/var/lib/vintage-commercials/downloads
ExecStart=/opt/vintage-commercials/venv/bin/vintage-commercials process --clips-dir /var/lib/vintage-commercials/clips
EOF

cat > /etc/systemd/system/vintage-processor.timer << 'EOF'
[Unit]
Description=Run Vintage Commercial Processor every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Nightly scanner
cat > /etc/systemd/system/vintage-scanner.service << 'EOF'
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
EOF

cat > /etc/systemd/system/vintage-scanner.timer << 'EOF'
[Unit]
Description=Run Vintage Commercial Scanner nightly at 2am

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Nginx reverse proxy
cat > /etc/nginx/sites-available/vintage-commercials << 'EOF'
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
EOF

ln -sf /etc/nginx/sites-available/vintage-commercials /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Enable services
systemctl enable vintage-web.service
systemctl enable vintage-processor.timer
systemctl enable vintage-scanner.timer
systemctl enable nginx
SERVICES
chmod +x "$STAGE_DIR/02-services/00-run-chroot.sh"

# First-boot welcome message
mkdir -p "$STAGE_DIR/03-welcome"
cat > "$STAGE_DIR/03-welcome/00-run-chroot.sh" << 'WELCOME'
#!/bin/bash

cat > /etc/motd << 'EOF'

  ╔═══════════════════════════════════════════════╗
  ║   Vintage TV Commercial Downloader            ║
  ║   Raspberry Pi 5 + Hailo-8 Edition            ║
  ╠═══════════════════════════════════════════════╣
  ║                                               ║
  ║   Web UI:  http://<this-pi-ip>                ║
  ║                                               ║
  ║   Commands:                                   ║
  ║     vintage-commercials search "coca cola"    ║
  ║     vintage-commercials batch --decades 1980s ║
  ║     vintage-commercials process               ║
  ║     vintage-commercials web                   ║
  ║                                               ║
  ║   Services:                                   ║
  ║     systemctl status vintage-web              ║
  ║     systemctl status vintage-processor.timer  ║
  ║     systemctl status vintage-scanner.timer    ║
  ║                                               ║
  ╚═══════════════════════════════════════════════╝

EOF
WELCOME
chmod +x "$STAGE_DIR/03-welcome/00-run-chroot.sh"

# Mark stage as exportable
touch "$STAGE_DIR/EXPORT_IMAGE"

# --- Build ---
echo "[4/5] Building image (this takes 15-30 minutes)..."
cd "$PIGEN_DIR"

if command -v docker &>/dev/null; then
    echo "  Using Docker build..."
    ./build-docker.sh
else
    echo "  Using native build..."
    sudo ./build.sh
fi

# --- Copy output ---
echo "[5/5] Copying image..."
mkdir -p "$OUTPUT_DIR"
cp "$PIGEN_DIR/deploy"/*.img.xz "$OUTPUT_DIR/" 2>/dev/null || \
cp "$PIGEN_DIR/deploy"/*.img "$OUTPUT_DIR/" 2>/dev/null || \
echo "  Image file should be in $PIGEN_DIR/deploy/"

echo ""
echo "============================================"
echo " Build complete!"
echo "============================================"
echo ""
echo " Image: $OUTPUT_DIR/vintage-commercials-pi5.img.xz"
echo ""
echo " Flash to SD card:"
echo "   # On Linux/Mac:"
echo "   xz -d vintage-commercials-pi5.img.xz"
echo "   sudo dd if=vintage-commercials-pi5.img of=/dev/sdX bs=4M status=progress"
echo ""
echo "   # Or use Raspberry Pi Imager:"
echo "   https://www.raspberrypi.com/software/"
echo ""
echo " Default login: pi / vintage"
echo " Web UI starts automatically on port 80"
echo ""
