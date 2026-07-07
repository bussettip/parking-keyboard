#!/usr/bin/env python3
import paramiko, os

PIS = [
    ("192.168.1.15", "pablo", "polo"),
    ("192.168.1.25", "pablo", "polo1234"),
]
BASE = "C:\\Nueva carpeta (4)\\parking_keyboard"
REMOTE_BASE = "/home/pablo/ocr_python"

FILES = [
    "dashboard_server.py",
    "tkdashboard.py",
    "templates/base.html",
    "templates/exit.html",
    "templates/ticket.html",
    "static/logo.svg",
    "parking_layout.json",
]

for HOST, USER, PASS in PIS:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()

    for f in FILES:
        local = os.path.join(BASE, f)
        remote = REMOTE_BASE + "/" + f
        rdir = os.path.dirname(remote)
        try:
            sftp.stat(rdir)
        except:
            sftp.mkdir(rdir)
        try:
            sftp.put(local, remote)
            print("OK  %s - %s" % (HOST, f))
        except Exception as e:
            print("ERR %s - %s: %s" % (HOST, f, e))

    sftp.close()
    stdin, stdout, stderr = client.exec_command("sudo -S systemctl restart parking-dashboard")
    stdin.write(PASS + "\n")
    stdin.flush()
    err = stderr.read().decode().strip()
    client.close()
    if err and "password" not in err.lower():
        print("ERR %s: %s" % (HOST, err))
    else:
        print("OK  %s - parking-dashboard restarted" % HOST)
