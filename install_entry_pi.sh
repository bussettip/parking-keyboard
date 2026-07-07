#!/bin/bash
# ============================================================
# install_entry_pi.sh - Instalacion completa Entry Pi
# Sistema de Estacionamiento Inteligente
# ============================================================
# Ejecutar: chmod +x install_entry_pi.sh && ./install_entry_pi.sh

set -e

PI_USER="${SUDO_USER:-$USER}"
PI_HOME=$(eval echo "~$PI_USER")
PROJECT_DIR="$PI_HOME/ocr_python"

echo "============================================"
echo " INSTALACION ENTRY Pi (192.168.1.15)"
echo "============================================"
echo ""

# ── 1. Dependencias del sistema ──────────────────────────
echo "[1/8] Instalando dependencias del sistema..."
sudo apt update
sudo apt install -y \
    python3-opencv \
    python3-picamera2 \
    python3-pip \
    python3-dotenv \
    python3-qrcode \
    python3-mysql.connector \
    tesseract-ocr \
    tesseract-ocr-spa \
    mariadb-server \
    mosquitto mosquitto-clients \
    chromium \
    curl

# ── 2. Dependencias Python ────────────────────────────────
echo "[2/8] Instalando dependencias Python..."
pip3 install --break-system-packages \
    pytesseract \
    paho-mqtt \
    mysql-connector-python \
    paramiko

# ── 3. Crear estructura del proyecto ──────────────────────
echo "[3/8] Creando directorios..."
mkdir -p "$PROJECT_DIR"/capturas_placas
mkdir -p "$PROJECT_DIR"/templates

# ── 4. Crear archivo .env ─────────────────────────────────
echo "[4/8] Creando .env..."
cat > "$PROJECT_DIR/.env" << 'ENVEOF'
# Entry Pi - Config ENTRADA
MODE=entry

# Roboflow API
ROBOFLOW_API_KEY=TI2x65pJYzkKsVKUleLt
ROBOFLOW_API_URL=https://infer.roboflow.com
PLATE_DETECTION_MODEL=reconocimiento-de-placas-vehiculares/reconocimiento_de_placas/1
OCR_MODEL_ID=franz-bpzvh/license-ocr-qqq6v/3

# Database (local)
DB_HOST=localhost
DB_NAME=parking_db
DB_USER=ocr_user
DB_PASS=123456
DB_PORT=3306

# MQTT (local)
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_TOPIC=ocr/plates/event

# GPIO
GPIO_PIN=17
GATE_OPEN_TIME=2.0
FLASH_PIN=22
FLASH_ON_TIME=3.0
ENVEOF
echo "  .env creado"

# ── 5. Configurar base de datos MySQL ─────────────────────
echo "[5/8] Configurando base de datos..."
sudo systemctl enable mariadb
sudo systemctl start mariadb

sudo mariadb <<'SQLEOF'
-- Crear base de datos
CREATE DATABASE IF NOT EXISTS parking_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE parking_db;

-- Tabla de configuracion de precios
CREATE TABLE IF NOT EXISTS pricing_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hourly_rate DECIMAL(10,2) NOT NULL DEFAULT 50.00,
    currency VARCHAR(10) DEFAULT 'MXN',
    grace_period_minutes INT DEFAULT 15,
    max_daily_rate DECIMAL(10,2) DEFAULT 200.00
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO pricing_config (hourly_rate, max_daily_rate) VALUES (50.00, 200.00);

-- Tabla de lugares de estacionamiento
CREATE TABLE IF NOT EXISTS parking_spots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    spot_number INT UNIQUE NOT NULL,
    status ENUM('available', 'occupied') DEFAULT 'available',
    `row_number` INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO parking_spots (spot_number, `row_number`) VALUES
(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
(7, 2), (8, 2), (9, 2), (10, 2), (11, 2), (12, 2);

-- Tabla de registros de entrada/salida
CREATE TABLE IF NOT EXISTS parking_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20) NOT NULL,
    qr_code VARCHAR(36) NULL,
    spot_id INT NOT NULL,
    entry_time DATETIME NOT NULL,
    exit_time DATETIME NULL,
    duration_minutes INT NULL,
    total_amount DECIMAL(10,2) DEFAULT 0.00,
    status ENUM('active', 'completed') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (spot_id) REFERENCES parking_spots(id) ON DELETE CASCADE,
    INDEX idx_plate (plate_number),
    INDEX idx_qr_code (qr_code),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabla de eventos
CREATE TABLE IF NOT EXISTS event_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20),
    event_type ENUM('entry', 'exit', 'error', 'alert') NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Usuario local
CREATE USER IF NOT EXISTS 'ocr_user'@'localhost' IDENTIFIED BY '123456';
GRANT ALL PRIVILEGES ON parking_db.* TO 'ocr_user'@'localhost';

-- Usuario remoto para Exit Pi
CREATE USER IF NOT EXISTS 'ocr_user'@'192.168.1.25' IDENTIFIED BY '123456';
GRANT ALL PRIVILEGES ON parking_db.* TO 'ocr_user'@'192.168.1.25';
FLUSH PRIVILEGES;
SQLEOF

# Habilitar conexion remota MySQL
sudo sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf 2>/dev/null || \
sudo sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/my.cnf 2>/dev/null || true
sudo systemctl restart mariadb

echo "  Base de datos lista: parking_db"
echo "  Usuario: ocr_user / 123456"

# ── 6. Copiar archivos del proyecto ───────────────────────
echo "[6/8] Instalando archivos del proyecto..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Si el script se ejecuta desde el directorio del proyecto,
# copia los archivos; si no, pide que los coloquen
if [ -f "$SCRIPT_DIR/parking_system_roboflow.py" ]; then
    cp "$SCRIPT_DIR/parking_system_roboflow.py" "$PROJECT_DIR/"
    cp "$SCRIPT_DIR/dashboard_server.py" "$PROJECT_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/start_dashboard.sh" "$PROJECT_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR/templates/"* "$PROJECT_DIR/templates/" 2>/dev/null || true
    chmod +x "$PROJECT_DIR/start_dashboard.sh" 2>/dev/null || true
    echo "  Archivos copiados desde $SCRIPT_DIR"
else
    echo "  [!] Archivos del proyecto no encontrados en $SCRIPT_DIR"
    echo "  Coloca los archivos manualmente en $PROJECT_DIR/"
    echo "  parking_system_roboflow.py, dashboard_server.py,"
    echo "  start_dashboard.sh, templates/entry.html, templates/exit.html"
fi

# ── 7. Instalar servicios systemd ──────────────────────────
echo "[7/8] Instalando servicios systemd..."

# Servicio principal de entrada
sudo tee /etc/systemd/system/parking-entry.service > /dev/null <<'EOF'
[Unit]
Description=Sistema Parking - ENTRADA
After=network.target mysql.service mosquitto.service
Wants=mysql.service mosquitto.service

[Service]
ExecStart=/usr/bin/python3 /home/pablo/ocr_python/parking_system_roboflow.py --no-preview
WorkingDirectory=/home/pablo/ocr_python
Restart=always
RestartSec=5
User=pablo

[Install]
WantedBy=multi-user.target
EOF

# Servicio dashboard web
sudo tee /etc/systemd/system/parking-dashboard.service > /dev/null <<'EOF'
[Unit]
Description=Parking Dashboard Display
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=simple
User=pablo
WorkingDirectory=/home/pablo/ocr_python
ExecStart=/home/pablo/ocr_python/start_dashboard.sh
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pablo/.Xauthority

[Install]
WantedBy=multi-user.target
EOF

# Servicio permisos LED ACT
sudo tee /etc/systemd/system/act-led-permissions.service > /dev/null <<'EOF'
[Unit]
Description=Permitir escritura del LED ACT
After=sysinit.target

[Service]
Type=oneshot
ExecStart=/bin/chmod 666 /sys/class/leds/ACT/brightness /sys/class/leds/ACT/trigger
ExecStartPost=/bin/sh -c 'echo none > /sys/class/leds/ACT/trigger'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Crear script start_dashboard.sh si no existe
if [ ! -f "$PROJECT_DIR/start_dashboard.sh" ]; then
    cat > "$PROJECT_DIR/start_dashboard.sh" << 'DASHEOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
pkill -15 chromium 2>/dev/null
sleep 1
python3 dashboard_server.py &
DASH_PID=$!
for i in $(seq 1 15); do
  if curl -s http://localhost:5100 > /dev/null 2>&1; then break; fi
  sleep 0.5
done
KIOSK_DIR="/tmp/chromium-kiosk-$(date +%s)"
chromium --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble \
  --disable-features=TranslateUI --noerrdialogs \
  --user-data-dir="$KIOSK_DIR" http://localhost:5100 &
CHROMIUM_PID=$!
while kill -0 $DASH_PID 2>/dev/null; do
  if ! kill -0 $CHROMIUM_PID 2>/dev/null; then
    KIOSK_DIR="/tmp/chromium-kiosk-$(date +%s)"
    chromium --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble \
      --disable-features=TranslateUI --noerrdialogs \
      --user-data-dir="$KIOSK_DIR" http://localhost:5100 &
    CHROMIUM_PID=$!
  fi
  sleep 5
done
kill $CHROMIUM_PID 2>/dev/null; wait
DASHEOF
    chmod +x "$PROJECT_DIR/start_dashboard.sh"
fi

# Habilitar servicios
sudo systemctl daemon-reload
sudo systemctl enable mariadb mosquitto
sudo systemctl enable parking-entry
sudo systemctl enable parking-dashboard
sudo systemctl enable act-led-permissions
sudo systemctl start mariadb mosquitto 2>/dev/null || true
sudo systemctl start parking-entry 2>/dev/null || true
sudo systemctl start parking-dashboard 2>/dev/null || true
sudo systemctl start act-led-permissions 2>/dev/null || true

echo "  Servicios instalados y habilitados"

# ── 8. Verificacion ───────────────────────────────────────
echo ""
echo "[8/8] Verificando instalacion..."
echo "  Camera:       $(rpicam-hello --version 2>&1 | head -1 || echo 'rpicam-still')"
echo "  Tesseract:    $(tesseract --version 2>&1 | head -1 || echo 'NO')"
echo "  OpenCV:       $(python3 -c 'import cv2; print(cv2.__version__)' 2>/dev/null || echo 'NO')"
echo "  QRCode:       $(python3 -c 'import qrcode; print(\"OK\")' 2>/dev/null || echo 'NO')"
echo "  MariaDB:      $(mariadb --version 2>&1 | head -1 || echo 'NO')"
echo "  Mosquitto:    $(mosquitto -h 2>&1 | head -1 || echo 'NO')"
echo "  Chromium:     $(chromium --version 2>&1 || echo 'NO')"

echo ""
echo "============================================"
echo " INSTALACION COMPLETADA"
echo "============================================"
echo ""
echo "  Directorio: $PROJECT_DIR"
echo "  .env:       $PROJECT_DIR/.env"
echo ""
echo "  Servicios:"
echo "    parking-entry       (lectura de placas)"
echo "    parking-dashboard   (pantalla HDMI)"
echo "    act-led-permissions (flash LED ACT)"
echo "    mariadb             (base de datos)"
echo "    mosquitto           (MQTT broker)"
echo ""
echo "  Dashboard web: http://localhost:5100"
echo ""
echo "  Comandos utiles:"
echo "    sudo journalctl -u parking-entry -f    (ver logs)"
echo "    sudo systemctl restart parking-entry   (reiniciar)"
echo "    python3 parking_system_roboflow.py --single --no-db  (prueba manual)"
echo ""
