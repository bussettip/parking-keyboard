#!/usr/bin/env python3
"""
Dashboard web server for Parking System.
Serves a real-time HTML map of parking spots for entry/exit displays.
"""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from functools import wraps

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

MODE = os.getenv("MODE", "exit")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "parking_db")
DB_USER = os.getenv("DB_USER", "ocr_user")
DB_PASS = os.getenv("DB_PASS", "123456")
DB_PORT = int(os.getenv("DB_PORT", "3306"))

app.secret_key = os.getenv("SECRET_KEY", "parking-secret-key-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def get_db():
    import mysql.connector
    return mysql.connector.connect(
        host=DB_HOST, database=DB_NAME,
        user=DB_USER, password=DB_PASS, port=DB_PORT,
        connect_timeout=5
    )


def get_spots():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT s.id, s.spot_number, s.status, s.row_number,
               r.plate_number, r.entry_time,
               UNIX_TIMESTAMP(r.entry_time) * 1000 AS entry_epoch
        FROM parking_spots s
        LEFT JOIN parking_records r ON s.id = r.spot_id AND r.status = 'active'
        ORDER BY s.row_number, s.spot_number
    """)
    spots = cur.fetchall()
    cur.execute("SELECT hourly_rate, grace_period_minutes FROM pricing_config LIMIT 1")
    cfg = cur.fetchone()
    rate = float(cfg["hourly_rate"]) if cfg else 50.0
    grace = int(cfg["grace_period_minutes"]) if cfg else 15
    now = datetime.now()
    for s in spots:
        if s["entry_time"]:
            s["entry_time"] = s["entry_time"].strftime("%Y-%m-%d %H:%M:%S")
        epoch = s["entry_epoch"]
        if epoch:
            epoch = int(epoch)
            diff_mins = (now - datetime.fromtimestamp(epoch / 1000)).total_seconds() / 60.0
            s["current_cost"] = 0 if diff_mins <= grace else round((diff_mins - grace) * (rate / 60), 2)
        else:
            epoch = 0
            s["current_cost"] = 0
        s["entry_epoch"] = epoch
    conn.close()
    return spots


def get_last_entry():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT r.spot_id, s.spot_number, r.plate_number, r.entry_time,
               UNIX_TIMESTAMP(r.entry_time) * 1000 AS entry_epoch
        FROM parking_records r
        JOIN parking_spots s ON r.spot_id = s.id
        WHERE r.status = 'active'
        ORDER BY r.entry_time DESC
        LIMIT 1
    """)
    last = cur.fetchone()
    if last and last["entry_time"]:
        last["entry_time"] = last["entry_time"].strftime("%Y-%m-%d %H:%M:%S")
        last["entry_epoch"] = int(last["entry_epoch"]) if last["entry_epoch"] else 0
    conn.close()
    return last


def get_revenue():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN DATE(exit_time) = CURDATE() THEN total_amount ELSE 0 END), 0) AS today,
            COALESCE(SUM(CASE WHEN YEARWEEK(exit_time) = YEARWEEK(CURDATE()) THEN total_amount ELSE 0 END), 0) AS week,
            COALESCE(SUM(CASE WHEN MONTH(exit_time) = MONTH(CURDATE()) AND YEAR(exit_time) = YEAR(CURDATE()) THEN total_amount ELSE 0 END), 0) AS month
        FROM parking_records
        WHERE status = 'completed'
    """)
    rev = cur.fetchone()
    conn.close()
    return rev


def get_config():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT hourly_rate, max_daily_rate, grace_period_minutes FROM pricing_config LIMIT 1")
    cfg = cur.fetchone()
    conn.close()
    return cfg


@app.route("/api/spots")
def api_spots():
    try:
        return jsonify(get_spots())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/last-entry")
def api_last_entry():
    try:
        return jsonify(get_last_entry() or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/revenue")
def api_revenue():
    try:
        return jsonify(get_revenue() or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config")
def api_config():
    try:
        cfg = get_config()
        return jsonify(cfg or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


LAYOUT_PATH = os.path.join(os.path.dirname(__file__), "parking_layout.json")


@app.route("/api/layout")
def api_layout():
    try:
        if not os.path.exists(LAYOUT_PATH):
            return jsonify({"rows": 0, "cols": 0, "grid": []})
        with open(LAYOUT_PATH) as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/manual-entry", methods=["POST"])
def manual_entry():
    try:
        data = request.get_json()
        plate = data.get("plate", "").upper().strip()
        if not plate:
            return jsonify({"error": "Placa requerida"}), 400

        conn = get_db()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM parking_records WHERE plate_number = %s AND status = 'active'", (plate,))
        if cur.fetchone():
            conn.close()
            return jsonify({"error": "Esa placa ya esta estacionada"}), 400

        cur.execute("SELECT id, spot_number FROM parking_spots WHERE status='available' ORDER BY spot_number LIMIT 1")
        spot = cur.fetchone()
        if not spot:
            conn.close()
            return jsonify({"error": "No hay lugares disponibles"}), 400

        now = datetime.now()
        cur.execute("INSERT INTO parking_records (spot_id, plate_number, entry_time, status) VALUES (%s, %s, %s, 'active')",
                    (spot["id"], plate, now))
        cur.execute("UPDATE parking_spots SET status='occupied' WHERE id=%s", (spot["id"],))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "spot_number": spot["spot_number"], "plate": plate})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/manual-exit", methods=["POST"])
def manual_exit():
    try:
        data = request.get_json()
        plate = data.get("plate", "").upper().strip()
        if not plate:
            return jsonify({"error": "Placa requerida"}), 400

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT r.id, r.spot_id, r.plate_number, r.entry_time, s.spot_number
            FROM parking_records r
            JOIN parking_spots s ON r.spot_id = s.id
            WHERE r.plate_number = %s AND r.status = 'active'
            ORDER BY r.entry_time DESC LIMIT 1
        """, (plate,))
        rec = cur.fetchone()
        if not rec:
            conn.close()
            return jsonify({"error": "No hay registro activo para esa placa"}), 404

        entry = rec["entry_time"]
        now = datetime.now()
        diff_mins = (now - entry).total_seconds() / 60.0

        cur.execute("SELECT hourly_rate, grace_period_minutes FROM pricing_config LIMIT 1")
        cfg = cur.fetchone()
        rate = float(cfg["hourly_rate"]) if cfg else 50.0
        grace = int(cfg["grace_period_minutes"]) if cfg else 15

        total = 0 if diff_mins <= grace else round((diff_mins - grace) * (rate / 60), 2)

        cur.execute("UPDATE parking_records SET exit_time=%s, total_amount=%s, status='completed' WHERE id=%s",
                    (now, total, rec["id"]))
        cur.execute("UPDATE parking_spots SET status='available' WHERE id=%s", (rec["spot_id"],))
        conn.commit()
        conn.close()

        mins = int(diff_mins)
        return jsonify({
            "ok": True, "record_id": rec["id"],
            "spot": rec["spot_number"], "plate": rec["plate_number"],
            "minutes": mins, "total": total, "grace_used": diff_mins <= grace
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


LOST_TICKET_FEE = 500


@app.route("/api/manual-exit-lost", methods=["POST"])
def manual_exit_lost():
    try:
        data = request.get_json()
        plate = data.get("plate", "").upper().strip()
        if not plate:
            return jsonify({"error": "Placa requerida"}), 400

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT r.id, r.spot_id, r.plate_number, r.entry_time, s.spot_number
            FROM parking_records r
            JOIN parking_spots s ON r.spot_id = s.id
            WHERE r.plate_number = %s AND r.status = 'active'
            ORDER BY r.entry_time DESC LIMIT 1
        """, (plate,))
        rec = cur.fetchone()
        if not rec:
            conn.close()
            return jsonify({"error": "No hay registro activo para esa placa"}), 404

        now = datetime.now()
        entry = rec["entry_time"]
        diff_mins = int((now - entry).total_seconds() / 60.0)
        total = LOST_TICKET_FEE

        cur.execute("UPDATE parking_records SET exit_time=%s, total_amount=%s, status='completed' WHERE id=%s",
                    (now, total, rec["id"]))
        cur.execute("UPDATE parking_spots SET status='available' WHERE id=%s", (rec["spot_id"],))
        conn.commit()
        conn.close()

        return jsonify({
            "ok": True, "record_id": rec["id"],
            "spot": rec["spot_number"], "plate": rec["plate_number"],
            "minutes": diff_mins, "total": total, "lost_ticket": True
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ticket/<int:record_id>")
def api_ticket(record_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT r.id, r.plate_number, r.entry_time, r.exit_time, r.total_amount,
                   s.spot_number
            FROM parking_records r
            JOIN parking_spots s ON r.spot_id = s.id
            WHERE r.id = %s
        """, (record_id,))
        rec = cur.fetchone()
        conn.close()
        if not rec:
            return jsonify({"error": "No encontrado"}), 404
        entry = rec["entry_time"]
        exit_t = rec["exit_time"]
        mins = int((exit_t - entry).total_seconds() / 60) if entry and exit_t else 0
        return jsonify({
            "id": rec["id"], "plate": rec["plate_number"],
            "spot": rec["spot_number"],
            "entry": entry.strftime("%Y-%m-%d %H:%M") if entry else "",
            "exit": exit_t.strftime("%Y-%m-%d %H:%M") if exit_t else "",
            "duration": "%d min" % mins,
            "total": float(rec["total_amount"]) if rec["total_amount"] else 0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ticket/<int:record_id>")
def ticket_page(record_id):
    return render_template("ticket.html", record_id=record_id)


@app.route("/")
def index():
    return render_template(f"{MODE}.html", mode=MODE)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Contraseña incorrecta")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS total FROM parking_records")
        total_records = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(*) AS active FROM parking_records WHERE status='active'")
        active_records = cur.fetchone()["active"]
        cur.execute("SELECT COUNT(*) AS available FROM parking_spots WHERE status='available'")
        available = cur.fetchone()["available"]
        rev = get_revenue()
        last_records = []
        cur.execute("""
            SELECT r.id, r.plate_number, s.spot_number, r.entry_time, r.exit_time, r.total_amount, r.status
            FROM parking_records r
            JOIN parking_spots s ON r.spot_id = s.id
            ORDER BY r.created_at DESC LIMIT 20
        """)
        last_records = cur.fetchall()
        conn.close()
        return render_template("admin_dashboard.html", total_records=total_records,
                               active_records=active_records, available=available, revenue=rev,
                               last_records=last_records)
    except Exception as e:
        return render_template("admin_dashboard.html", error=str(e))


@app.route("/admin/records")
@login_required
def admin_records():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT r.id, r.plate_number, s.spot_number, r.entry_time, r.exit_time,
                   r.duration_minutes, r.total_amount, r.status
            FROM parking_records r
            JOIN parking_spots s ON r.spot_id = s.id
            ORDER BY r.created_at DESC LIMIT 200
        """)
        records = cur.fetchall()
        conn.close()
        return render_template("admin_records.html", records=records)
    except Exception as e:
        return render_template("admin_records.html", error=str(e))


@app.route("/admin/cuts")
@login_required
def admin_cuts():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM revenue_cuts ORDER BY created_at DESC LIMIT 50")
        cuts = cur.fetchall()
        conn.close()
        return render_template("admin_cuts.html", cuts=cuts)
    except Exception as e:
        return render_template("admin_cuts.html", error=str(e))


@app.route("/admin/corte", methods=["POST"])
@login_required
def admin_corte():
    try:
        from datetime import datetime
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN DATE(exit_time) = CURDATE() THEN total_amount ELSE 0 END), 0) AS today,
                COALESCE(SUM(CASE WHEN YEARWEEK(exit_time) = YEARWEEK(CURDATE()) THEN total_amount ELSE 0 END), 0) AS week,
                COALESCE(SUM(CASE WHEN MONTH(exit_time) = MONTH(CURDATE()) AND YEAR(exit_time) = YEAR(CURDATE()) THEN total_amount ELSE 0 END), 0) AS month
            FROM parking_records WHERE status = 'completed'
        """)
        r = cur.fetchone()
        cur.execute("INSERT INTO revenue_cuts (today, week, month, created_at) VALUES (%s, %s, %s, %s)",
                    (r["today"], r["week"], r["month"], datetime.now()))
        conn.commit()
        conn.close()
        return redirect(url_for("admin_cuts"))
    except Exception as e:
        return render_template("admin_cuts.html", error=str(e))


@app.route("/admin/config", methods=["GET", "POST"])
@login_required
def admin_config():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        if request.method == "POST":
            rate = float(request.form.get("hourly_rate", 50))
            max_rate = float(request.form.get("max_daily_rate", 200))
            grace = int(request.form.get("grace_period_minutes", 15))
            cur.execute("UPDATE pricing_config SET hourly_rate=%s, max_daily_rate=%s, grace_period_minutes=%s",
                        (rate, max_rate, grace))
            conn.commit()
        cur.execute("SELECT * FROM pricing_config LIMIT 1")
        cfg = cur.fetchone()
        conn.close()
        return render_template("admin_config.html", config=cfg)
    except Exception as e:
        return render_template("admin_config.html", error=str(e))


@app.route("/admin/event-log")
@login_required
def admin_event_log():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM event_log ORDER BY created_at DESC LIMIT 200")
        events = cur.fetchall()
        conn.close()
        return render_template("admin_event_log.html", events=events)
    except Exception as e:
        return render_template("admin_event_log.html", error=str(e))


def init_db():
    for attempt in range(30):
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS pricing_config (
                id INT AUTO_INCREMENT PRIMARY KEY,
                hourly_rate DECIMAL(10,2) NOT NULL DEFAULT 50.00,
                currency VARCHAR(10) DEFAULT 'MXN',
                grace_period_minutes INT DEFAULT 15,
                max_daily_rate DECIMAL(10,2) DEFAULT 200.00
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS parking_spots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                spot_number INT UNIQUE NOT NULL,
                status ENUM('available', 'occupied') DEFAULT 'available',
                `row_number` INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS parking_records (
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS event_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                plate_number VARCHAR(20),
                event_type ENUM('entry', 'exit', 'error', 'alert') NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS revenue_cuts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                today DECIMAL(10,2) NOT NULL DEFAULT 0,
                week DECIMAL(10,2) NOT NULL DEFAULT 0,
                month DECIMAL(10,2) NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("INSERT IGNORE INTO pricing_config (hourly_rate, max_daily_rate) VALUES (50.00, 200.00)")
            for i in range(1, 13):
                rn = 1 if i <= 6 else 2
                cur.execute("INSERT IGNORE INTO parking_spots (id, spot_number, `row_number`) VALUES (%s, %s, %s)", (i, i, rn))
            conn.commit()
            conn.close()
            print("[DB] Tablas creadas/verificadas")
            return
        except Exception as e:
            print(f"[DB] Esperando base de datos... ({e})")
            import time
            time.sleep(2)
    print("[DB] No se pudo conectar a la base de datos")
    sys.exit(1)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5100
    init_db()
    print(f"[DASHBOARD] Mode={MODE} http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
