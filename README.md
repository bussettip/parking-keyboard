# Sistema de Estacionamiento Inteligente

Sistema para dos Raspberry Pi con cámara que detecta autos, lee placas mexicanas (OpenCV + Tesseract), asigna lugares, calcula cobros y muestra el mapa del estacionamiento en pantalla HDMI.

---

## Arquitectura

```
                    ┌──────────────────────────────┐
                    │      Pi 4 (SALIDA)           │
                    │   192.168.1.15               │
                    │                              │
                    │  ┌────────────────────┐      │
                    │  │  MariaDB (local)   │      │
                    │  │  Mosquitto MQTT    │      │
                    │  └────────────────────┘      │
                    │         │                    │
                    │  ┌──────▼───────────────┐    │
                    │  │  Chromium kiosko     │◄───│── HDMI
                    │  │  dashboard único     │    │
                    │  │  (Entrada + Salida)  │    │
                    │  │  :5100               │    │
                    │  └──────────────────────┘    │
                    └──────────────────────────────┘
```

**Pi 4** corre el dashboard unificado con control manual de entrada y salida.

---

## Dashboard único (Pi 4)

Una sola pantalla en Chromium kiosko con:

- **Barra de Ingreso manual** — input + botón verde `INGRESAR`
- **Barra de Salida manual** — input + botón naranja `SALIDA`
- **Matriz del estacionamiento** en vivo (libre/ocupado con placa y costo)
- **Estadísticas**: Disponibles, Ocupados, Tarifa, Tiempo gratis, Por cobrar, Recaudado hoy
- **Footer**: Semana y Mes acumulados
- **Auto-refresh** cada 3 segundos
- **Evita placas duplicadas** — no permite ingresar una placa que ya está activa
- **Ticket con QR** tras cada salida exitosa

### Archivos del proyecto

| Archivo | Función |
|---|---|
| `parking_system_roboflow.py` | Pipeline principal detección/OCR |
| `dashboard_server.py` | Servidor Flask con APIs REST |
| `start_dashboard.sh` | Lanza Flask + Chromium kiosko |
| `parking_layout.json` | Matriz 10×10 configurable del estacionamiento |
| `templates/base.html` | Template base (CSS/JS compartido) |
| `templates/exit.html` | Dashboard unificado entrada+salida |
| `templates/ticket.html` | Ticket imprimible con QR |
| `static/logo.svg` | Logo corporativo reemplazable |
| `corte.py` | Corte de caja con historial |
| `deploy_all.py` | Despliegue automático vía SSH/SFTP a Pi 4 |

### APIs REST

| Endpoint | Descripción |
|---|---|
| `GET /api/spots` | Lugares con estado, placa, hora, epoch |
| `GET /api/last-entry` | Último ingreso registrado |
| `GET /api/config` | Tarifa, período de gracia |
| `GET /api/revenue` | Recaudado hoy / semana / mes |
| `GET /api/layout` | Matriz del estacionamiento |
| `POST /api/manual-entry` | Ingreso manual: `{"plate":"ABC123"}` |
| `POST /api/manual-exit` | Salida manual: `{"plate":"ABC123"}` |
| `GET /api/ticket/<id>` | Datos del ticket en JSON |
| `GET /ticket/<id>` | Página del ticket con QR |

### `parking_layout.json`

Define la matriz visual del estacionamiento (0=vacío, -1=pasillo, 1..N=lugar).

### Servicios systemd

| Servicio | Función |
|---|---|
| `parking-dashboard` | Flask + Chromium kiosko |
| `parking-entry` | Pipeline detección entrada |
| `parking-exit` | Pipeline detección salida |
| `act-led-permissions` | Permisos LED ACT |

### `.env`

```ini
MODE=exit
DB_HOST=localhost
DB_NAME=parking_db
DB_USER=ocr_user
DB_PASS=123456
```

### Despliegue

```bash
python deploy_all.py
```

Sube los archivos vía SFTP a Pi 4 y reinicia `parking-dashboard`.
