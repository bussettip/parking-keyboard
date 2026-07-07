#!/usr/bin/env python3
"""Corte de caja: recaudado, guarda en DB y muestra historial."""
import paramiko, os
from datetime import datetime

HOST, USER, PASS = "192.168.1.15", "pablo", "polo"

SCRIPT = (
    "python3 << 'PYEOF'\n"
    "import mysql.connector\n"
    "from datetime import datetime\n"
    "conn = mysql.connector.connect(host='localhost', database='parking_db', user='ocr_user', password='123456', port=3306)\n"
    "cur = conn.cursor()\n"
    "# Create table if not exists\n"
    "cur.execute('''\n"
    "    CREATE TABLE IF NOT EXISTS revenue_cuts (\n"
    "        id INT AUTO_INCREMENT PRIMARY KEY,\n"
    "        today DECIMAL(10,2) NOT NULL DEFAULT 0,\n"
    "        week DECIMAL(10,2) NOT NULL DEFAULT 0,\n"
    "        month DECIMAL(10,2) NOT NULL DEFAULT 0,\n"
    "        created_at DATETIME NOT NULL\n"
    "    )\n"
    "''')\n"
    "# Get current revenue\n"
    "cur.execute('''\n"
    "    SELECT\n"
    "        COALESCE(SUM(CASE WHEN DATE(exit_time) = CURDATE() THEN total_amount ELSE 0 END), 0) AS today,\n"
    "        COALESCE(SUM(CASE WHEN YEARWEEK(exit_time) = YEARWEEK(CURDATE()) THEN total_amount ELSE 0 END), 0) AS week,\n"
    "        COALESCE(SUM(CASE WHEN MONTH(exit_time) = MONTH(CURDATE()) AND YEAR(exit_time) = YEAR(CURDATE()) THEN total_amount ELSE 0 END), 0) AS month\n"
    "    FROM parking_records WHERE status = 'completed'\n"
    "''')\n"
    "r = cur.fetchone()\n"
    "now = datetime.now()\n"
    "# Insert cut record\n"
    "cur.execute('INSERT INTO revenue_cuts (today, week, month, created_at) VALUES (%s, %s, %s, %s)', (r[0], r[1], r[2], now))\n"
    "conn.commit()\n"
    "# Get last 10 cuts\n"
    "cur.execute('SELECT created_at, today, week, month FROM revenue_cuts ORDER BY created_at DESC LIMIT 10')\n"
    "cuts = cur.fetchall()\n"
    "conn.close()\n"
    "print('=== CORTE DE CAJA ===')\n"
    "print('Hoy:       $%.2f' % r[0])\n"
    "print('Semana:    $%.2f' % r[1])\n"
    "print('Mes:       $%.2f' % r[2])\n"
    "print('=====================')\n"
    "print()\n"
    "print('Ultimos 10 cortes:')\n"
    "print('%-20s %10s %10s %10s' % ('Fecha', 'Hoy', 'Semana', 'Mes'))\n"
    "print('-' * 52)\n"
    "for c in cuts:\n"
    "    print('%-20s %10.2f %10.2f %10.2f' % (c[0].strftime('%Y-%m-%d %H:%M'), c[1], c[2], c[3]))\n"
    "PYEOF"
)

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    stdin, stdout, stderr = client.exec_command(SCRIPT)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    client.close()
    if err: print(err)
    print(out)
except Exception as e:
    print("Error:", e)
