#!/usr/bin/env python3
"""
Sistema de Estacionamiento Inteligente v2
- Deteccion de llegada de auto (motion detection)
- Deteccion de placa con Roboflow API (ML)
- OCR de placa con Roboflow API + fallback Tesseract
- Registro en MySQL (entrada/salida)
- Publicacion MQTT
- Guardado de fotos
"""

import cv2
import numpy as np
import os
import sys
import time
import json
import math
import subprocess
import re
import http.client
import ssl
import threading
import uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------
# CONFIGURACION
# -----------------------------------------------------------

class Config:
    # Roboflow (fallback)
    ROBOFLOW_API_URL = os.getenv("ROBOFLOW_API_URL", "https://infer.roboflow.com")
    ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
    PLATE_DETECTION_MODEL = os.getenv("PLATE_DETECTION_MODEL", "reconocimiento_de_placas/1")
    OCR_MODEL = os.getenv("OCR_MODEL_ID", "license-ocr-qqq6v/3")
    OCR_MIN_CHAR_DISTANCE = 15
    OCR_MAX_CHARS = 8
    OCR_CONFIRMATIONS = 3

    # Tesseract
    TESSERACT_CMD = "/usr/bin/tesseract"

    # OpenCV plate detection
    MIN_PLATE_AREA = 500
    MAX_PLATE_AREA_RATIO = 0.3
    MIN_ASPECT = 1.5
    MAX_ASPECT = 6.0
    CANNY_THRESH1 = 50
    CANNY_THRESH2 = 150
    OCR_UPSCALE = 3

    # Camara
    CAMERA_MOTION_WIDTH = 640
    CAMERA_MOTION_HEIGHT = 480
    CAPTURE_WIDTH = 1920
    CAPTURE_HEIGHT = 1080

    # Deteccion de movimiento
    ROI_X = 0
    ROI_Y = 150
    ROI_W = 640
    ROI_H = 200
    MOTION_THRESHOLD = 3000
    MOTION_MIN_FRAMES = 3
    DETECTION_COOLDOWN = 10

    # Modo operacion
    MODE = os.getenv("MODE", "entry")

    # DB
    DB_ENABLED = True
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_NAME = os.getenv("DB_NAME", "parking_db")
    DB_USER = os.getenv("DB_USER", "ocr_user")
    DB_PASS = os.getenv("DB_PASS", "123456")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))

    # MQTT
    MQTT_ENABLED = False
    MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_TOPIC = os.getenv("MQTT_TOPIC", "ocr/plates/event")

    # GPIO (pluma/barrera)
    GPIO_PIN = int(os.getenv("GPIO_PIN", "17"))
    GATE_OPEN_TIME = float(os.getenv("GATE_OPEN_TIME", "2.0"))

    # GPIO (flash LED externo)
    FLASH_PIN = int(os.getenv("FLASH_PIN", "0"))
    FLASH_ON_TIME = float(os.getenv("FLASH_ON_TIME", "3.0"))

    # Archivos
    PHOTOS_DIR = "capturas_placas"

    # Display
    SHOW_PREVIEW = True

    # QR fallback
    QR_ENABLED = True
    QR_PRINT_CMD = os.getenv("QR_PRINT_CMD", "lp")

    # Archivo de configuracion ROI
    ROI_CONFIG_FILE = "roi_config.json"


# -----------------------------------------------------------
# CAMARA
# -----------------------------------------------------------

class Camera:
    def __init__(self, config=Config):
        self.config = config
        self.cap = None
        self.picam2 = None
        self._type = None
        self._flash = None
        self._init_flash()

    def _init_flash(self):
        self._act = None
        self._gpio = None

        # LED ACT de la Pi (siempre, no requiere cables)
        try:
            with open("/sys/class/leds/ACT/trigger", "w") as f:
                f.write("none")
            self._act = True
            print("[FLASH] LED ACT (Raspberry Pi)")
        except Exception:
            pass

        # GPIO externo (si FLASH_PIN > 0)
        if self.config.FLASH_PIN > 0:
            try:
                import RPi.GPIO as GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.config.FLASH_PIN, GPIO.OUT)
                GPIO.output(self.config.FLASH_PIN, GPIO.LOW)
                self._gpio = GPIO
                print(f"[FLASH] GPIO {self.config.FLASH_PIN}")
            except Exception as e:
                print(f"[FLASH] GPIO no disponible: {e}")

    def flash_on(self):
        if self._act:
            try:
                with open("/sys/class/leds/ACT/brightness", "w") as f:
                    f.write("1")
            except Exception:
                pass
        if self._gpio:
            self._gpio.output(self.config.FLASH_PIN, self._gpio.HIGH)

    def flash_off(self):
        if self._act:
            try:
                with open("/sys/class/leds/ACT/brightness", "w") as f:
                    f.write("0")
            except Exception:
                pass
        if self._gpio:
            self._gpio.output(self.config.FLASH_PIN, self._gpio.LOW)

    def open(self):
        if self._try_picamera2():
            return True
        if self._try_v4l2():
            return True
        if self._try_rpicam_still():
            return True
        return False

    def _try_picamera2(self):
        try:
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            cfg = self.picam2.create_video_configuration(
                main={"size": (self.config.CAMERA_MOTION_WIDTH, self.config.CAMERA_MOTION_HEIGHT), "format": "RGB888"},
                controls={"FrameRate": 15}
            )
            self.picam2.configure(cfg)
            self.picam2.start()
            self._type = "picamera2"
            print(f"[CAM] picamera2: {self.config.CAMERA_MOTION_WIDTH}x{self.config.CAMERA_MOTION_HEIGHT}")
            return True
        except Exception as e:
            print(f"[CAM] picamera2 no disponible: {e}")
            return False

    def _try_v4l2(self):
        for dev_id in range(2):
            cap = cv2.VideoCapture(dev_id, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.CAMERA_MOTION_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.CAMERA_MOTION_HEIGHT)
                self.cap = cap
                self._type = "v4l2"
                print(f"[CAM] V4L2 /dev/video{dev_id}")
                return True
        return False

    def _try_rpicam_still(self):
        try:
            result = subprocess.run(["rpicam-still", "--version"], capture_output=True, timeout=3)
            if result.returncode == 0:
                self._type = "rpicam"
                print("[CAM] rpicam-still")
                return True
        except Exception:
            pass
        return False

    def read(self):
        if self.picam2:
            frame = self.picam2.capture_array()
            if frame is not None:
                return True, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return False, None
        if self.cap:
            return self.cap.read()
        return False, None

    def capture_highres(self, filename):
        ok = False
        self.flash_on()
        time.sleep(0.3)
        try:
            if self._type == "rpicam":
                result = subprocess.run(
                    ["rpicam-still", "-n", "-o", filename,
                     "--width", str(self.config.CAPTURE_WIDTH),
                     "--height", str(self.config.CAPTURE_HEIGHT),
                     "--timeout", "2000", "--nopreview", "--encoding", "jpg"],
                    capture_output=True, timeout=8
                )
                ok = result.returncode == 0 and os.path.exists(filename)
            elif self.picam2:
                self.picam2.stop()
                time.sleep(0.5)
                try:
                    result = subprocess.run(
                        ["rpicam-still", "-n", "-o", filename,
                         "--width", str(self.config.CAPTURE_WIDTH),
                         "--height", str(self.config.CAPTURE_HEIGHT),
                         "--timeout", "2000", "--nopreview", "--encoding", "jpg"],
                        capture_output=True, timeout=8
                    )
                    ok = result.returncode == 0 and os.path.exists(filename)
                finally:
                    self.picam2.start()
            else:
                ret, frame = self.read()
                if ret:
                    cv2.imwrite(filename, frame)
                    ok = True
        finally:
            self.flash_off()
        return ok

    def release(self):
        if self.picam2:
            self.picam2.stop()
        if self.cap:
            self.cap.release()

    def is_opened(self):
        return self.picam2 is not None or (self.cap and self.cap.isOpened()) or self._type == "rpicam"

    def get_type(self):
        return self._type


# -----------------------------------------------------------
# DETECTOR DE MOVIMIENTO
# -----------------------------------------------------------

class MotionDetector:
    def __init__(self, config=Config):
        self.config = config
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=36, detectShadows=True)
        self.motion_count = 0
        self.in_motion = False
        self.last_trigger_time = 0

    def detect(self, frame):
        now = time.time()
        if now - self.last_trigger_time < self.config.DETECTION_COOLDOWN:
            return False

        h, w = frame.shape[:2]
        x = min(self.config.ROI_X, w - 1)
        y = min(self.config.ROI_Y, h - 1)
        rw = min(self.config.ROI_W, w - x)
        rh = min(self.config.ROI_H, h - y)

        roi_frame = frame[y:y+rh, x:x+rw]
        if roi_frame.size == 0:
            return False

        fg_mask = self.bg_subtractor.apply(roi_frame)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        motion_pixels = cv2.countNonZero(fg_mask)

        if motion_pixels > self.config.MOTION_THRESHOLD:
            self.motion_count += 1
            if self.motion_count >= self.config.MOTION_MIN_FRAMES and not self.in_motion:
                self.in_motion = True
                self.last_trigger_time = now
                print(f"[MOTION] Auto detectado! ({motion_pixels} px)")
                return True
        else:
            self.motion_count = max(0, self.motion_count - 1)
            if self.motion_count == 0:
                self.in_motion = False
        return False

    def reset(self):
        self.motion_count = 0
        self.in_motion = False

    def draw_roi(self, frame):
        x, y, w, h = self.config.ROI_X, self.config.ROI_Y, self.config.ROI_W, self.config.ROI_H
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(frame, "ROI Barrera", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        return frame


# -----------------------------------------------------------
# ROBOFLOW PLATE DETECTION + OCR
# -----------------------------------------------------------

def roboflow_infer(image, model_id, api_key, api_url="https://infer.roboflow.com"):
    """Llama a la API de Roboflow con una imagen (multipart upload). Retorna dict con predictions o None."""
    try:
        _, img_encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_bytes = img_encoded.tobytes()

        host = api_url.replace("https://", "").replace("http://", "").split("/")[0]
        path = "/" + model_id + "?api_key=" + api_key

        body = b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"image.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n" + img_bytes + b"\r\n--boundary--\r\n"

        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, context=ctx, timeout=30)
        conn.request("POST", path, body=body, headers={"Content-Type": "multipart/form-data; boundary=boundary"})
        resp = conn.getresponse()
        result = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return result
    except Exception as e:
        print(f"[ROBOFLOW API] Error: {e}")
        return None
    except Exception as e:
        print(f"[ROBOFLOW API] Error: {e}")
        return None

class PlateReader:
    def __init__(self, config=Config):
        self.config = config
        self.last_plates = []

    def find_plate_candidates(self, frame):
        """Encuentra rectangulos con forma de placa usando contornos OpenCV.
        Retorna lista de (x1, y1, x2, y2) ordenados por probabilidad."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Try Canny edge detection
        edges = cv2.Canny(gray, self.config.CANNY_THRESH1, self.config.CANNY_THRESH2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area = cw * ch
            if area < self.config.MIN_PLATE_AREA or area > gray.size * self.config.MAX_PLATE_AREA_RATIO:
                continue
            aspect = cw / ch if ch > 0 else 0
            if aspect < self.config.MIN_ASPECT or aspect > self.config.MAX_ASPECT:
                continue
            # Score: prefer larger, well-proportioned, and centered
            cx, cy = x + cw / 2, y + ch / 2
            center_dist = abs(cx - w / 2) / w + abs(cy - h / 2) / h
            score = area * (aspect if aspect < 4 else 4 / aspect) / (1 + center_dist * 3)
            candidates.append((score, x, y, cw, ch))

        # Try adaptive thresholding as fallback
        if len([c for c in candidates if c[0] > 5000]) < 2:
            th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 51, 2)
            dilate = cv2.dilate(th, np.ones((3, 3), np.uint8), iterations=2)
            cont2, _ = cv2.findContours(dilate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in cont2:
                x, y, cw, ch = cv2.boundingRect(cnt)
                area = cw * ch
                if area < self.config.MIN_PLATE_AREA or area > gray.size * self.config.MAX_PLATE_AREA_RATIO:
                    continue
                aspect = cw / ch if ch > 0 else 0
                if aspect < self.config.MIN_ASPECT or aspect > self.config.MAX_ASPECT:
                    continue
                cx, cy = x + cw / 2, y + ch / 2
                center_dist = abs(cx - w / 2) / w + abs(cy - h / 2) / h
                score = area * (aspect if aspect < 4 else 4 / aspect) / (1 + center_dist * 3)
                candidates.append((score, x, y, cw, ch))

        candidates.sort(key=lambda c: -c[0])
        return [(c[1], c[2], c[1] + c[3], c[2] + c[4]) for c in candidates[:5]]

    def read_plate_tesseract(self, plate_img):
        """Lee texto de la placa con Tesseract. Retorna texto o None."""
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = self.config.TESSERACT_CMD
            gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            # If the crop is tall (includes state text), take middle third
            if h > w * 0.5:
                mid_h = h // 3
                gray = gray[mid_h:2*mid_h, :]

            up = cv2.resize(gray, (w * self.config.OCR_UPSCALE, gray.shape[0] * self.config.OCR_UPSCALE),
                            interpolation=cv2.INTER_CUBIC)
            _, otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            # Try multiple PSM modes, pick best
            texts = []
            for psm in [8, 7, 6, 13]:
                cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
                text = pytesseract.image_to_string(otsu, config=cfg, lang="eng").strip()
                if text:
                    texts.append((psm, text))
                    print(f"[TESSERACT] psm{psm}: '{text}'")

            if texts:
                best = None
                for psm, text in texts:
                    cleaned = clean_plate(text)
                    if validate_plate(cleaned):
                        score = (len(cleaned) == 7, len(cleaned) == 8, len(cleaned), -abs(len(cleaned) - 7))
                        if best is None or score > best[1]:
                            best = (cleaned, score)
                            print(f"[TESSERACT] psm{psm}: '{cleaned}' (candidato)")
                if best:
                    print(f"[TESSERACT] mejor: '{best[0]}'")
                    return best[0]
                return clean_plate(texts[0][1])
        except Exception as e:
            print(f"[TESSERACT] Error: {e}")
        return None

    def read_plate_roboflow(self, plate_img):
        """Lee texto con Roboflow OCR (fallback). Retorna texto o None."""
        predictions = roboflow_infer(
            plate_img, self.config.OCR_MODEL,
            self.config.ROBOFLOW_API_KEY, self.config.ROBOFLOW_API_URL
        )
        if not predictions:
            return None
        try:
            chars = []
            for pred in predictions.get("predictions", []):
                try:
                    x = int(pred["x"] - pred["width"] / 2)
                    char = pred["class"].upper()
                    if char.isalnum():
                        chars.append((x, char))
                except (KeyError, ValueError):
                    continue
            chars.sort(key=lambda c: c[0])
            filtered = []
            prev_x = -self.config.OCR_MIN_CHAR_DISTANCE
            for x, char in chars:
                if x - prev_x > self.config.OCR_MIN_CHAR_DISTANCE:
                    filtered.append(char)
                    prev_x = x
            text = "".join(filtered[:self.config.OCR_MAX_CHARS])
            if text and len(text) >= 4:
                print(f"[ROBOFLOW OCR] '{text}'")
                return text
        except Exception as e:
            print(f"[ROBOFLOW OCR] Error: {e}")
        return None

    def detect_and_read(self, frame):
        """Pipeline principal: detecta placa con OpenCV, lee con Tesseract.
        Retorna (texto, bbox) o (None, None)."""
        best_text = None
        best_bbox = None

        # 1. OpenCV contour candidates + Tesseract
        candidates = self.find_plate_candidates(frame)
        if candidates:
            for bbox in candidates:
                x1, y1, x2, y2 = bbox
                plate_img = frame[y1:y2, x1:x2]
                if plate_img.size == 0:
                    continue
                text = self.read_plate_tesseract(plate_img)
                if text:
                    cleaned = clean_plate(text)
                    if validate_plate(cleaned):
                        print(f"[PLATE] OpenCV + Tesseract: '{cleaned}' en ({x1},{y1})-({x2},{y2})")
                        return cleaned, bbox
                if text and not best_text:
                    best_text, best_bbox = text, bbox

        # 2. Fallback: Tesseract on full image
        if not best_text:
            text = self.read_plate_tesseract(frame)
            if text:
                cleaned = clean_plate(text)
                if validate_plate(cleaned):
                    print(f"[PLATE] Tesseract full frame: '{cleaned}'")
                    return cleaned, None

        # 3. Fallback: Roboflow detection + OCR
        if self.config.ROBOFLOW_API_KEY:
            print("[PLATE] Intentando Roboflow...")
            for bbox in candidates:
                x1, y1, x2, y2 = bbox
                plate_img = frame[y1:y2, x1:x2]
                if plate_img.size == 0:
                    continue
                text = self.read_plate_roboflow(plate_img)
                if text and validate_plate(text):
                    print(f"[PLATE] Roboflow OCR: '{text}'")
                    return text, bbox

        if best_text:
            cleaned = clean_plate(best_text)
            if validate_plate(cleaned):
                return cleaned, best_bbox
            return best_text, best_bbox
        return None, None

    def reset_confirmations(self):
        self.last_plates = []


# -----------------------------------------------------------
# QR FALLBACK
# -----------------------------------------------------------

def generate_qr(data, filepath):
    """Genera imagen QR con el contenido dado. Retorna True si tuvo exito."""
    try:
        import qrcode
        img = qrcode.make(data)
        img.save(filepath)
        print(f"[QR] Generado: {filepath}")
        return True
    except Exception as e:
        print(f"[QR] Error generando QR: {e}")
        return False


def detect_qr(frame):
    """Detecta QR en el frame usando OpenCV. Retorna el texto o None."""
    try:
        detector = cv2.QRCodeDetector()
        text, points, _ = detector.detectAndDecode(frame)
        if text:
            text = text.strip()
            print(f"[QR] Detectado: '{text}'")
            return text
    except Exception as e:
        print(f"[QR] Error detectando: {e}")
    return None


def print_qr(filepath, config):
    """Imprime el archivo QR usando lp u otro comando."""
    if not os.path.exists(filepath):
        return
    cmd = config.QR_PRINT_CMD
    try:
        subprocess.run(cmd.split() + [filepath], capture_output=True, timeout=10)
        print(f"[QR] Enviado a impresion: {cmd} {filepath}")
    except Exception as e:
        print(f"[QR] Error imprimiendo: {e}")


# -----------------------------------------------------------
# VALIDACION DE PLACAS MEXICANAS (fallback Tesseract)
# -----------------------------------------------------------

MEXICAN_PLATE_PATTERNS = [
    r"^[A-Z]{3}\d{4}$", r"^[A-Z]{3}\d{3}$", r"^[A-Z]{2}\d{4}$",
    r"^[A-Z]{2}\d{3}$", r"^[A-Z]{3}\d{3}[A-Z]$", r"^[A-Z]\d{3}[A-Z]{2}$",
    r"^[A-Z]{3}\d{2}[A-Z]$", r"^\d{3}[A-Z]{3}$",
    r"^[A-Z]{3}\d{2}\d{2}$",  # ABC-12-34 (Morelos)
    r"^[A-Z]{3}\d{4}$"       # ABC-1234
]

def validate_plate(plate):
    plate = plate.strip().replace("-", "").replace(" ", "").replace(".", "").upper()
    return any(re.match(p, plate) for p in MEXICAN_PLATE_PATTERNS)

DIGIT_TO_LETTER = {"0": ["O"], "1": ["I", "L"], "2": ["Z"], "4": ["A"], "5": ["S"], "6": ["G"], "7": ["Z", "T", "P"], "8": ["B"]}
LETTER_TO_DIGIT = {"O": ["0"], "I": ["1"], "L": ["1"], "S": ["5"], "B": ["8"], "Z": ["2"], "G": ["6"]}

def clean_plate(plate):
    if not plate:
        return plate
    plate = plate.strip().replace("-", "").replace(" ", "").upper()
    if validate_plate(plate):
        return plate

    candidates = []

    def beam_search(orig_idx, current, skip_allowed):
        if len(current) > 7:
            return
        if len(current) >= 6 and validate_plate(current) and orig_idx >= len(plate):
            if current not in candidates:
                candidates.append(current)
            return
        if orig_idx >= len(plate):
            return
        char = plate[orig_idx]
        if len(current) < 3:
            if char.isalpha():
                beam_search(orig_idx + 1, current + char.upper(), skip_allowed)
            elif char.isdigit():
                for r in DIGIT_TO_LETTER.get(char, [char]):
                    beam_search(orig_idx + 1, current + r, skip_allowed)
            elif char.isalnum():
                beam_search(orig_idx + 1, current + char.upper(), skip_allowed)
            else:
                beam_search(orig_idx + 1, current, skip_allowed)
        else:
            if char.isdigit():
                beam_search(orig_idx + 1, current + char, skip_allowed)
            elif char.isalpha():
                for r in LETTER_TO_DIGIT.get(char, [char]):
                    beam_search(orig_idx + 1, current + r, skip_allowed)
            elif char.isalnum():
                beam_search(orig_idx + 1, current + char, skip_allowed)
            else:
                beam_search(orig_idx + 1, current, skip_allowed)
        if skip_allowed and len(plate) > 7:
            beam_search(orig_idx + 1, current, False)

    beam_search(0, "", True)

    if candidates:
        def score(item):
            idx, c = item
            dist = 0
            for i in range(min(len(plate), len(c))):
                if plate[i] != c[i]:
                    dist += 1
            dist += abs(len(plate) - len(c)) * 2
            return (dist, idx)
        best = min(enumerate(candidates), key=score)[1]
        return best

    for trim in range(1, min(4, len(plate))):
        for side in [plate[:-trim], plate[trim:]]:
            cleaned = ""
            for i, ch in enumerate(side):
                if i < 3 and ch.isdigit():
                    cleaned += DIGIT_TO_LETTER.get(ch, [ch])[0]
                elif i >= 3 and ch.isalpha():
                    cleaned += LETTER_TO_DIGIT.get(ch, [ch])[0]
                else:
                    cleaned += ch
            if len(cleaned) >= 6 and validate_plate(cleaned):
                return cleaned
    return plate

def classify_plate_type(plate):
    plate = plate.strip().replace("-", "").replace(" ", "").upper()
    if re.match(r"^\d{3}[A-Z]{3}$", plate): return "CDMX"
    elif re.match(r"^[A-Z]{3}\d{3}$", plate): return "Estado"
    elif re.match(r"^[A-Z]{3}\d{4}$", plate): return "Estado Nuevo"
    else: return "Otro"


# -----------------------------------------------------------
# FALLBACK TESSERACT
# -----------------------------------------------------------




# -----------------------------------------------------------
# GPIO (PLUMA / BARRERA)
# -----------------------------------------------------------

class GateController:
    def __init__(self, config=Config):
        self.config = config
        self.gpio = None
        self._init_gpio()

    def _init_gpio(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.GPIO_PIN, GPIO.OUT)
            GPIO.output(self.config.GPIO_PIN, GPIO.LOW)
            self.gpio = GPIO
            print(f"[GPIO] Pluma en pin {self.config.GPIO_PIN}")
        except Exception as e:
            print(f"[GPIO] No disponible (solo Raspberry): {e}")

    def open_gate(self):
        if not self.gpio:
            return
        self.gpio.output(self.config.GPIO_PIN, self.gpio.HIGH)
        print(f"[GPIO] Pluma ABIERTA ({self.config.GATE_OPEN_TIME}s)")
        t = threading.Thread(target=self._close_after, daemon=True)
        t.start()

    def _close_after(self):
        time.sleep(self.config.GATE_OPEN_TIME)
        if self.gpio:
            self.gpio.output(self.config.GPIO_PIN, self.gpio.LOW)
            print("[GPIO] Pluma CERRADA")

    def close(self):
        if self.gpio:
            self.gpio.output(self.config.GPIO_PIN, self.gpio.LOW)
            self.gpio.cleanup()
            print("[GPIO] Limpiado")


# -----------------------------------------------------------
# BASE DE DATOS
# -----------------------------------------------------------

class Database:
    def __init__(self, config=Config):
        self.config = config
        self.conn = None

    def connect(self):
        if not self.config.DB_ENABLED:
            return False
        try:
            import mysql.connector
            self.conn = mysql.connector.connect(
                host=self.config.DB_HOST, database=self.config.DB_NAME,
                user=self.config.DB_USER, password=self.config.DB_PASS,
                port=self.config.DB_PORT
            )
            if self.conn and self.conn.is_connected():
                print(f"[DB] Conectado MySQL {self.config.DB_HOST}")
                return True
        except Exception as e:
            print(f"[DB] Error: {e}")
        return False

    def check_active(self, plate):
        if not self.conn: return None
        try:
            cur = self.conn.cursor(dictionary=True)
            cur.execute("""SELECT r.id, r.spot_id, r.entry_time, s.spot_number
                           FROM parking_records r JOIN parking_spots s ON r.spot_id = s.id
                           WHERE r.plate_number = %s AND r.status = 'active'""", (plate,))
            r = cur.fetchone()
            cur.close()
            return r
        except Exception as e:
            print(f"[DB] Error consulta: {e}")
            return None

    def assign_spot(self):
        if not self.conn: return None
        try:
            cur = self.conn.cursor(dictionary=True)
            cur.execute("""SELECT id, spot_number FROM parking_spots
                           WHERE status = 'available' ORDER BY `row_number` ASC, spot_number ASC LIMIT 1""")
            s = cur.fetchone()
            cur.close()
            return s
        except Exception as e:
            print(f"[DB] Error spot: {e}")
            return None

    def check_qr(self, qr_code):
        if not self.conn or not qr_code: return None
        try:
            cur = self.conn.cursor(dictionary=True)
            cur.execute("""SELECT r.id, r.spot_id, r.entry_time, s.spot_number
                           FROM parking_records r JOIN parking_spots s ON r.spot_id = s.id
                           WHERE r.qr_code = %s AND r.status = 'active'""", (qr_code,))
            r = cur.fetchone()
            cur.close()
            return r
        except Exception as e:
            print(f"[DB] Error consulta QR: {e}")
            return None

    def record_entry(self, plate, spot_id, entry_time, qr_code=None):
        if not self.conn: return False
        try:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO parking_records (plate_number, qr_code, spot_id, entry_time, status) VALUES (%s, %s, %s, %s, 'active')",
                        (plate, qr_code, spot_id, entry_time))
            cur.execute("UPDATE parking_spots SET status = 'occupied' WHERE id = %s", (spot_id,))
            self.conn.commit()
            cur.close()
            return True
        except Exception as e:
            print(f"[DB] Error entrada: {e}")
            if self.conn: self.conn.rollback()
            return False

    def record_exit(self, record_id, spot_id):
        if not self.conn: return None, None, None
        try:
            cur = self.conn.cursor(dictionary=True)
            cur.execute("SELECT entry_time FROM parking_records WHERE id = %s", (record_id,))
            rec = cur.fetchone()
            if not rec: return None, None, None
            now = datetime.now()
            diff = now - rec["entry_time"]
            duration = int(diff.total_seconds() / 60)
            cur.execute("SELECT hourly_rate, max_daily_rate, grace_period_minutes FROM pricing_config LIMIT 1")
            cfg = cur.fetchone()
            amount = 0.00
            if cfg:
                grace = cfg["grace_period_minutes"]
                if duration > grace:
                    hours = math.ceil((duration - grace) / 60)
                    amount = hours * cfg["hourly_rate"]
                    if amount > cfg["max_daily_rate"]:
                        amount = cfg["max_daily_rate"]
            cur.execute("UPDATE parking_records SET exit_time=%s, duration_minutes=%s, total_amount=%s, status='completed' WHERE id=%s",
                        (now, duration, amount, record_id))
            cur.execute("UPDATE parking_spots SET status = 'available' WHERE id = %s", (spot_id,))
            self.conn.commit()
            cur.close()
            return amount, duration, now
        except Exception as e:
            print(f"[DB] Error salida: {e}")
            if self.conn: self.conn.rollback()
            return None, None, None

    def get_hourly_rate(self):
        if not self.conn: return None
        try:
            cur = self.conn.cursor(dictionary=True)
            cur.execute("SELECT hourly_rate, max_daily_rate, grace_period_minutes FROM pricing_config LIMIT 1")
            r = cur.fetchone()
            cur.close()
            return r
        except Exception as e:
            print(f"[DB] Error tarifa: {e}")
            return None

    def close(self):
        if self.conn and self.conn.is_connected():
            self.conn.close()


# -----------------------------------------------------------
# MQTT
# -----------------------------------------------------------

class MqttClient:
    def __init__(self, config=Config):
        self.config = config
        self.client = None

    def connect(self):
        if not self.config.MQTT_ENABLED: return False
        try:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(client_id=f"parking_{int(time.time())}")
            self.client.connect(self.config.MQTT_BROKER, self.config.MQTT_PORT, 60)
            self.client.loop_start()
            print(f"[MQTT] Conectado {self.config.MQTT_BROKER}:{self.config.MQTT_PORT}")
            return True
        except Exception as e:
            print(f"[MQTT] Error: {e}")
            return False

    def publish(self, event_type, data):
        if not self.client: return
        payload = json.dumps({"event": event_type, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **data})
        self.client.publish(self.config.MQTT_TOPIC, payload=payload, qos=1)

    def close(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# -----------------------------------------------------------
# SISTEMA PRINCIPAL
# -----------------------------------------------------------

class ParkingSystem:
    def __init__(self, config=Config):
        self.config = config
        self.camera = Camera(config)
        self.motion = MotionDetector(config)
        self.plate_reader = PlateReader(config)
        self.db = Database(config)
        self.mqtt = MqttClient(config)
        self.gate = GateController(config)
        self.running = True
        self.stats = {"detections": 0, "entries": 0, "exits": 0, "errors": 0, "ocr_errors": 0}

    def setup(self, init_camera=True):
        os.makedirs(self.config.PHOTOS_DIR, exist_ok=True)

        if init_camera:
            if not self.camera.open():
                print("[FATAL] No se pudo abrir la camara")
                return False

        # Cargar ROI
        if os.path.exists(self.config.ROI_CONFIG_FILE):
            try:
                with open(self.config.ROI_CONFIG_FILE) as f:
                    roi = json.load(f)
                self.config.ROI_X = roi.get("x", self.config.ROI_X)
                self.config.ROI_Y = roi.get("y", self.config.ROI_Y)
                self.config.ROI_W = roi.get("w", self.config.ROI_W)
                self.config.ROI_H = roi.get("h", self.config.ROI_H)
                print(f"[CONFIG] ROI cargado: {self.config.ROI_X},{self.config.ROI_Y},{self.config.ROI_W},{self.config.ROI_H}")
            except Exception as e:
                print(f"[CONFIG] Error ROI: {e}")

        self.db.connect()
        self.mqtt.connect()
        return True

    def process_car(self, frame):
        ts = datetime.now()
        timestamp = ts.strftime("%Y%m%d_%H%M%S")
        print(f"\n{'='*50}")
        print(f"[SISTEMA] Vehiculo a las {ts.strftime('%H:%M:%S')}")
        print(f"{'='*50}")

        if self.config.SHOW_PREVIEW:
            d = frame.copy()
            cv2.putText(d, "AUTO DETECTADO - CAPTURANDO...", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imshow("Parking System", d)
            for _ in range(5):
                if cv2.waitKey(50) & 0xFF == ord('q'):
                    self.running = False
                    return

        # 1. Capturar foto de alta resolucion
        hires = f"{self.config.PHOTOS_DIR}/{timestamp}_hires.jpg"
        if self.camera.get_type() in ("rpicam", "picamera2"):
            self.camera.capture_highres(hires)
            plate_frame = cv2.imread(hires)
            if plate_frame is None:
                plate_frame = frame
        else:
            plate_frame = frame

        if self.config.SHOW_PREVIEW:
            d2 = plate_frame.copy()
            hf, wf = d2.shape[:2]
            if hf > 480:
                d2 = cv2.resize(d2, (int(wf * 480 / hf), 480))
            cv2.putText(d2, "ANALIZANDO PLACA...", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.imshow("Parking System", d2)
            cv2.waitKey(1)

        # 2. Detectar placa con OpenCV + Tesseract (fallback Roboflow)
        plate_text, bbox = self.plate_reader.detect_and_read(plate_frame)

        # 3. Guardar recorte si hay bbox
        if plate_text and bbox:
            x1, y1, x2, y2 = bbox
            plate_img = plate_frame[y1:y2, x1:x2]
            cv2.imwrite(f"{self.config.PHOTOS_DIR}/{timestamp}_crop.jpg", plate_img)

        if not plate_text:
            print("[OCR] No se pudo leer la placa - intentando QR...")
            qr_text = detect_qr(plate_frame) if self.config.QR_ENABLED else None

            if qr_text:
                plate_text = qr_text
                bbox = None
                print(f"[QR] Usando QR como identificador: '{qr_text}'")
            elif self.config.MODE == "entry" and self.config.QR_ENABLED:
                print("[QR] Generando nuevo QR para entrada sin placa...")
                qr_id = str(uuid.uuid4())
                plate_placeholder = f"QR-{qr_id[:8].upper()}"
                qr_file = f"{self.config.PHOTOS_DIR}/{timestamp}_qr_{qr_id[:8]}.png"
                if generate_qr(qr_id, qr_file):
                    print_qr(qr_file, self.config)
                if self.config.SHOW_PREVIEW:
                    nd = plate_frame.copy()
                    hf, wf = nd.shape[:2]
                    if hf > 480:
                        nd = cv2.resize(nd, (int(wf * 480 / hf), 480))
                    cv2.putText(nd, f"QR GENERADO: {plate_placeholder}", (30, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                    cv2.putText(nd, "Imprimiendo...", (30, 90),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.imshow("Parking System", nd)
                    for _ in range(20):
                        if cv2.waitKey(100) & 0xFF == ord('q'):
                            self.running = False
                            return
                plate_text = plate_placeholder
                self._process_entry(plate_text, ts, plate_frame, qr_code=qr_id)
                self.stats["detections"] += 1
                print()
                return
            else:
                if self.config.SHOW_PREVIEW:
                    nd = plate_frame.copy()
                    hf, wf = nd.shape[:2]
                    if hf > 480:
                        nd = cv2.resize(nd, (int(wf * 480 / hf), 480))
                    cv2.putText(nd, "NO SE DETECTO PLACA", (50, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                    cv2.imshow("Parking System", nd)
                    for _ in range(20):
                        if cv2.waitKey(100) & 0xFF == ord('q'):
                            self.running = False
                            return
                self.stats["errors"] += 1
                return

        # 6. Mostrar resultado
        ptype = classify_plate_type(plate_text)
        if self.config.SHOW_PREVIEW:
            rd = plate_frame.copy()
            hf, wf = rd.shape[:2]
            if hf > 480:
                rd = cv2.resize(rd, (int(wf * 480 / hf), 480))
            if bbox:
                sx = rd.shape[0] / plate_frame.shape[0]
                sy = rd.shape[1] / plate_frame.shape[1]
                cv2.rectangle(rd, (int(bbox[0]*sy), int(bbox[1]*sx)),
                              (int(bbox[2]*sy), int(bbox[3]*sx)), (0, 255, 0), 3)
            cv2.putText(rd, f"PLACA: {plate_text}", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            cv2.putText(rd, ptype, (50, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow("Parking System", rd)
            for _ in range(30):
                if cv2.waitKey(100) & 0xFF == ord('q'):
                    self.running = False
                    return

        # 7. Guardar foto contexto
        if bbox:
            ctx = plate_frame.copy()
            cv2.rectangle(ctx, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 3)
            cv2.putText(ctx, plate_text, (bbox[0], bbox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imwrite(f"{self.config.PHOTOS_DIR}/{timestamp}_{plate_text}_contexto.jpg", ctx)

        self.stats["detections"] += 1

        # 8. Registrar en DB
        if self.db.conn:
            active = self.db.check_active(plate_text)
            if not active and len(plate_text) == 36 and plate_text.count('-') == 4:
                active = self.db.check_qr(plate_text)
            if active:
                self._process_exit(plate_text, active, ts, plate_frame)
            elif self.config.MODE == "exit":
                print(f"[SALIDA] Placa/QR {plate_text} no tiene entrada activa - ignorada")
                self.mqtt.publish("warning", {"plate": plate_text, "reason": "no_active_entry"})
            else:
                self._process_entry(plate_text, ts, plate_frame)
        else:
            print(f"[DB] Sin conexion - Placa {plate_text} no registrada")
        print()

    def _process_entry(self, plate, entry_time, plate_frame=None, qr_code=None):
        spot = self.db.assign_spot()
        if not spot:
            print(f"[DB] ESTACIONAMIENTO LLENO!")
            self.mqtt.publish("full", {"plate": plate})
            return
        if self.db.record_entry(plate, spot["id"], entry_time, qr_code):
            self.stats["entries"] += 1
            rate_info = self.db.get_hourly_rate()
            rate_str = f"${rate_info['hourly_rate']:.2f}/hr" if rate_info else "N/A"
            print(f">>> ENTRADA: {plate} | Lugar: {spot['spot_number']} | Tarifa: {rate_str}")
            self.mqtt.publish("entry", {"plate": plate, "spot": spot["spot_number"],
                                        "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S")})
            if self.config.SHOW_PREVIEW and plate_frame is not None:
                rd = plate_frame.copy()
                hf, wf = rd.shape[:2]
                if hf > 480:
                    rd = cv2.resize(rd, (int(wf * 480 / hf), 480))
                overlay = rd.copy()
                cv2.rectangle(overlay, (0, 0), (rd.shape[1], 130), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.6, rd, 0.4, 0, rd)
                cv2.putText(rd, f"ENTRADA: {plate}", (30, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                cv2.putText(rd, f"Lugar: {spot['spot_number']}   Tarifa: {rate_str}", (30, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
                cv2.putText(rd, "Pluma abriendose...", (30, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                cv2.imshow("Parking System", rd)
                for _ in range(40):
                    if cv2.waitKey(100) & 0xFF == ord('q'):
                        self.running = False
                        return
            self.gate.open_gate()

    def _process_exit(self, plate, active, exit_time, plate_frame=None):
        amount, duration, _ = self.db.record_exit(active["id"], active["spot_id"])
        self.stats["exits"] += 1
        print(f">>> SALIDA: {plate} | Lugar: {active['spot_number']} (desocupado)")
        if duration is not None:
            print(f"    Tiempo: {duration} min | Cobro: ${amount:.2f}")
        self.mqtt.publish("exit", {"plate": plate, "spot": active["spot_number"],
                                   "duration_min": duration, "amount": amount})
        if self.config.SHOW_PREVIEW and plate_frame is not None:
            rd = plate_frame.copy()
            hf, wf = rd.shape[:2]
            if hf > 480:
                rd = cv2.resize(rd, (int(wf * 480 / hf), 480))
            overlay = rd.copy()
            cv2.rectangle(overlay, (0, 0), (rd.shape[1], 160), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, rd, 0.4, 0, rd)
            cv2.putText(rd, f"SALIDA: {plate}", (30, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
            cv2.putText(rd, f"Lugar {active['spot_number']} desocupado", (30, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            if duration is not None:
                hrs = duration // 60
                mins = duration % 60
                time_str = f"{hrs}h {mins}m" if hrs else f"{mins} min"
                cv2.putText(rd, f"Tiempo: {time_str}", (30, 105),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(rd, f"Total a pagar: ${amount:.2f}", (30, 140),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3)
            cv2.imshow("Parking System", rd)
            for _ in range(40):
                if cv2.waitKey(100) & 0xFF == ord('q'):
                    self.running = False
                    return
        self.gate.open_gate()

    def run(self):
        if not self.setup():
            return
        mode_label = "SALIDAS" if self.config.MODE == "exit" else "ENTRADAS"
        print(f"\n[SISTEMA] Monitoreando {mode_label}... Ctrl+C o 'q' para salir\n")
        if not self.config.ROBOFLOW_API_KEY:
            print("[ADVERTENCIA] ROBOFLOW_API_KEY no configurada!")
            print("  Crea un archivo .env con: ROBOFLOW_API_KEY=tu_key")

        frame_count = 0
        motion_count = 0

        try:
            while self.running:
                ret, frame = self.camera.read()
                if not ret:
                    time.sleep(0.5)
                    continue
                frame_count += 1

                if self.motion.detect(frame):
                    motion_count += 1
                    self.process_car(frame)
                    self.motion.reset()
                    self.motion.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                        history=500, varThreshold=36, detectShadows=True)
                    self.plate_reader.reset_confirmations()
                    print(f"[SISTEMA] Cooldown {self.config.DETECTION_COOLDOWN}s...")

                if self.config.SHOW_PREVIEW and frame_count % 2 == 0:
                    d = frame.copy()
                    self.motion.draw_roi(d)
                    cv2.putText(d, f"Autos: {motion_count}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    wait_msg = "ESPERANDO AUTO..." if not self.motion.in_motion else "!!! MOVIMIENTO !!!"
                    cv2.putText(d, wait_msg,
                                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 255, 0) if not self.motion.in_motion else (0, 0, 255), 2)
                    cv2.putText(d, "q = salir", (d.shape[1] - 100, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                    cv2.imshow("Parking System", d)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                time.sleep(0.03)
        except KeyboardInterrupt:
            print("\n[SISTEMA] Ctrl+C detectado")
        self.shutdown()

    def shutdown(self):
        print(f"\n{'='*50}\nRESUMEN\n{'='*50}")
        print(f"  Detecciones: {self.stats['detections']}")
        print(f"  Entradas:    {self.stats['entries']}")
        print(f"  Salidas:     {self.stats['exits']}")
        print(f"  Errores:     {self.stats['errors']}")
        print(f"  OCR errores: {self.stats['ocr_errors']}")
        self.camera.release()
        self.db.close()
        self.mqtt.close()
        self.gate.close()
        cv2.destroyAllWindows()
        print("[SISTEMA] Apagado")


# -----------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------

if __name__ == "__main__":
    config = Config()
    if "--no-db" in sys.argv: config.DB_ENABLED = False
    if "--no-mqtt" in sys.argv: config.MQTT_ENABLED = False
    if "--no-preview" in sys.argv: config.SHOW_PREVIEW = False
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            config.MODE = sys.argv[idx + 1]
    system = ParkingSystem(config)
    if "--single" in sys.argv:
        print("[SISTEMA] Modo single-shot")
        if system.setup(init_camera=False):
            system.camera._type = "rpicam"
            system.camera._init_flash()
            hires = "/tmp/single_shot.jpg"
            system.camera.flash_on()
            time.sleep(0.3)
            r = subprocess.run(["rpicam-still", "-n", "-o", hires,
                               "--width", str(config.CAPTURE_WIDTH),
                               "--height", str(config.CAPTURE_HEIGHT),
                               "--timeout", "2000", "--nopreview", "--encoding", "jpg"],
                              capture_output=True, timeout=10)
            system.camera.flash_off()
            if r.returncode == 0:
                frame = cv2.imread(hires)
                if frame is not None:
                    system.process_car(frame)
            else:
                print("[ERROR] rpicam-still falló:", r.stderr.decode()[:200])
            system.shutdown()
        else:
            print("[ERROR] No se pudo inicializar")
    else:
        system.run()
