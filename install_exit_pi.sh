#!/bin/bash
# ============================================================
# install_exit_pi.sh - Instalacion completa Exit Pi
# Sistema de Estacionamiento Inteligente
# ============================================================
# Ejecutar: chmod +x install_exit_pi.sh && ./install_exit_pi.sh
#
# NOTA: Necesita acceso SCP a la Entry Pi (192.168.1.15)
#       para copiar los archivos del proyecto.
# ============================================================

set -e

PI_USER="${SUDO_USER:-$USER}"
PI_HOME=$(eval "echo ~$PI_USER")
PROJECT_DIR="$PI_HOME/ocr_python"
ENTRY_IP="192.168.1.15"
ENTRY_USER="pablo"

echo "============================================"
echo " INSTALACION EXIT Pi (192.168.1.25)"
echo "============================================"
echo ""

# ── 1. Dependencias del sistema ──────────────────────────
echo "[1/7] Instalando dependencias del sistema..."
sudo apt update
sudo apt install -y \
    python3-opencv \
    python3-pip \
    python3-dotenv \
    python3-mysql.connector \
    tesseract-ocr \
    tesseract-ocr-spa \
    chromium \
    curl

# ── 2. Dependencias Python ────────────────────────────────
echo "[2/7] Instalando dependencias Python..."
pip3 install --break-system-packages \
    pytesseract \
    paho-mqtt \
    mysql-connector-python

# ── 3. Crear estructura del proyecto ──────────────────────
echo "[3/7] Creando directorios..."
mkdir -p "$PROJECT_DIR"/capturas_placas
mkdir -p "$PROJECT_DIR"/templates

# ── 4. Crear archivo .env ─────────────────────────────────
echo "[4/7] Creando .env..."
cat > "$PROJECT_DIR/.env" << 'ENVEOF'
# Exit Pi - Config SALIDA
MODE=exit

# Database (Entry Pi)
DB_HOST=192.168.1.15
DB_NAME=parking_db
DB_USER=ocr_user
DB_PASS=123456
DB_PORT=3306

# MQTT (Entry Pi)
MQTT_BROKER=192.168.1.15
MQTT_PORT=1883
MQTT_TOPIC=ocr/plates/event

# Roboflow API
ROBOFLOW_API_KEY=TI2x65pJYzkKsVKUleLt
ROBOFLOW_API_URL=https://infer.roboflow.com
PLATE_DETECTION_MODEL=reconocimiento-de-placas-vehiculares/reconocimiento_de_placas/1
OCR_MODEL_ID=franz-bpzvh/license-ocr-qqq6v/3

# GPIO
GPIO_PIN=17
GATE_OPEN_TIME=2.0
FLASH_PIN=22
FLASH_ON_TIME=3.0
ENVEOF
echo "  .env creado"

# ── 5. Copiar archivos del proyecto ───────────────────────
echo "[5/7] Copiando archivos desde Entry Pi ($ENTRY_IP)..."

# Primero intentar desde el mismo directorio (USB compartido)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COPIED=0

if [ -f "$SCRIPT_DIR/parking_system_roboflow.py" ]; then
    cp "$SCRIPT_DIR/parking_system_roboflow.py" "$PROJECT_DIR/"
    cp "$SCRIPT_DIR/dashboard_server.py" "$PROJECT_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/start_dashboard.sh" "$PROJECT_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR/templates/"* "$PROJECT_DIR/templates/" 2>/dev/null || true
    chmod +x "$PROJECT_DIR/start_dashboard.sh" 2>/dev/null || true
    COPIED=1
    echo "  Archivos copiados desde $SCRIPT_DIR (local)"
fi

# Si no estan localmente, copiar via SCP desde Entry Pi
if [ "$COPIED" -eq 0 ]; then
    echo "  Archivos no encontrados localmente, copiando via SCP..."
    echo "  Necesitas la password de $ENTRY_USER@$ENTRY_IP"
    scp "$ENTRY_USER@$ENTRY_IP:~/ocr_python/parking_system_roboflow.py" "$PROJECT_DIR/"
    scp "$ENTRY_USER@$ENTRY_IP:~/ocr_python/dashboard_server.py" "$PROJECT_DIR/" 2>/dev/null || true
    scp "$ENTRY_USER@$ENTRY_IP:~/ocr_python/start_dashboard.sh" "$PROJECT_DIR/" 2>/dev/null || true
    scp "$ENTRY_USER@$ENTRY_IP:~/ocr_python/templates/entry.html" "$PROJECT_DIR/templates/" 2>/dev/null || true
    scp "$ENTRY_USER@$ENTRY_IP:~/ocr_python/templates/exit.html" "$PROJECT_DIR/templates/" 2>/dev/null || true
    chmod +x "$PROJECT_DIR/start_dashboard.sh" 2>/dev/null || true
    echo "  Archivos copiados via SCP"
fi

# ── 6. Instalar servicios systemd ──────────────────────────
echo "[6/7] Instalando servicios systemd..."

# Servicio principal de salida
sudo tee /etc/systemd/system/parking-exit.service > /dev/null <<'EOF'
[Unit]
Description=Sistema Parking - SALIDA
After=network.target
Wants=

[Service]
ExecStart=/usr/bin/python3 /home/pablo/ocr_python/parking_system_roboflow.py --no-preview --mode exit
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
sudo systemctl enable parking-exit
sudo systemctl enable parking-dashboard 2>/dev/null || true
sudo systemctl enable act-led-permissions
sudo systemctl start parking-exit 2>/dev/null || true
sudo systemctl start parking-dashboard 2>/dev/null || true
sudo systemctl start act-led-permissions 2>/dev/null || true

echo "  Servicios instalados y habilitados"

# ── 7. Verificacion ───────────────────────────────────────
echo ""
echo "[7/7] Verificando instalacion..."
echo "  Tesseract:    $(tesseract --version 2>&1 | head -1 || echo 'NO')"
echo "  OpenCV:       $(python3 -c 'import cv2; print(cv2.__version__)' 2>/dev/null || echo 'NO')"
echo "  Chromium:     $(chromium --version 2>&1 || echo 'NO')"
echo "  Con. MySQL:   $(python3 -c \"import mysql.connector; c=mysql.connector.connect(host='$ENTRY_IP',database='parking_db',user='ocr_user',password='123456'); c.close(); print('OK')\" 2>/dev/null || echo 'SIN CONEXION')"

echo ""
echo "============================================"
echo " INSTALACION COMPLETADA"
echo "============================================"
echo ""
echo "  Directorio: $PROJECT_DIR"
echo "  .env:       $PROJECT_DIR/.env"
echo ""
echo "  Servicios:"
echo "    parking-exit         (lectura de placas)"
echo "    parking-dashboard    (pantalla HDMI)"
echo "    act-led-permissions  (flash LED ACT)"
echo ""
echo "  Dashboard web: http://localhost:5100"
echo ""
echo "  Comandos utiles:"
echo "    sudo journalctl -u parking-exit -f    (ver logs)"
echo "    sudo systemctl restart parking-exit   (reiniciar)"
echo "    python3 parking_system_roboflow.py --single --no-db --mode exit  (prueba manual)"
echo ""
