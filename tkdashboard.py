#!/usr/bin/env python3
import tkinter as tk
import urllib.request
import json
import threading
import time
import subprocess
import os
from datetime import datetime

API = "http://localhost:5100"
REFRESH = 3
CELL = 90


class PlateDialog(tk.Toplevel):
    def __init__(self, parent, title, btn_label, btn_color, api_path, preset_plate=""):
        super().__init__(parent)
        self.result = None
        self.api_path = api_path
        self.title(title)
        self.attributes("-fullscreen", True)
        self.configure(bg="#0d1117")

        frame = tk.Frame(self, bg="#0d1117")
        frame.pack(expand=True)

        tk.Label(frame, text=title, font=("Sans", 36, "bold"),
                 fg="#58a6ff", bg="#0d1117").pack(pady=30)
        tk.Label(frame, text="Escriba la placa del veh\u00edculo", font=("Sans", 18),
                 fg="#8b949e", bg="#0d1117").pack()

        self.entry = tk.Entry(frame, font=("Sans", 48), justify="center",
                              bg="#161b22", fg="#f0f6fc", relief="flat",
                              insertbackground="#58a6ff")
        self.entry.pack(pady=30, ipady=10, padx=40, fill="x")
        if preset_plate:
            self.entry.insert(0, preset_plate)
        self.entry.focus()
        self.entry.bind("<Return>", self.on_submit)
        self.entry.bind("<Escape>", lambda e: self.destroy())

        btn_frame = tk.Frame(frame, bg="#0d1117")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text=btn_label, font=("Sans", 20, "bold"),
                  bg=btn_color, fg="#0d1117", padx=40, pady=10,
                  command=self.on_submit).pack(side="left", padx=10)
        tk.Button(btn_frame, text="CANCELAR", font=("Sans", 20),
                  bg="#30363d", fg="#f0f6fc", padx=40, pady=10,
                  command=self.destroy).pack(side="left", padx=10)

        self.status_label = tk.Label(frame, text="", font=("Sans", 16),
                                     fg="#f0883e", bg="#0d1117")
        self.status_label.pack(pady=10)

    def open_ticket(self, record_id):
        ticket_url = API + "/ticket/" + str(record_id)
        subprocess.Popen(
            ["chromium", "--kiosk", "--no-sandbox", "--incognito",
             "--disable-infobars", "--noerrdialogs",
             ticket_url],
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def on_submit(self, event=None):
        plate = self.entry.get().strip().upper()
        if not plate:
            self.status_label.config(text="Ingrese una placa", fg="#f85149")
            return
        self.status_label.config(text="Procesando...", fg="#f0883e")
        self.update()

        try:
            data = json.dumps({"plate": plate}).encode()
            req = urllib.request.Request(API + self.api_path,
                                         data=data,
                                         headers={"Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
            if resp.get("ok"):
                if self.api_path == "/api/manual-entry":
                    msg = "\u2714 Lugar #%d asignado a %s" % (resp["spot_number"], plate)
                else:
                    grace = " (tiempo gratis)" if resp.get("grace_used") else ""
                    lost = " BOLETO PERDIDO" if resp.get("lost_ticket") else ""
                    msg = "\u2714 Lugar #%d liberado - $%.2f%s%s" % (resp["spot"], resp["total"], grace, lost)
                    record_id = resp.get("record_id")
                    if record_id:
                        self.after(500, lambda: self.open_ticket(record_id))
                self.status_label.config(text=msg, fg="#3fb950")
                self.after(2000, self.destroy)
            else:
                self.status_label.config(text="Error: " + resp.get("error", ""), fg="#f85149")
        except Exception as e:
            self.status_label.config(text="Error de conexi\u00f3n", fg="#f85149")


class DashboardDisplay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Control - Estacionamiento")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#0d1117")
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.avail_var = tk.StringVar(value="--")
        self.occ_var = tk.StringVar(value="--")
        self.rate_var = tk.StringVar(value="$50.00/hr")
        self.grace_var = tk.StringVar(value="15 min")
        self.rev_card_var = tk.StringVar(value="$0")
        self.daily_rev_var = tk.StringVar(value="$0")
        self.week_rev_var = tk.StringVar(value="$0")
        self.month_rev_var = tk.StringVar(value="$0")

        rate = 50
        grace = 15

        header = tk.Frame(self.root, bg="#161b22", pady=6)
        header.pack(fill="x")

        top_row = tk.Frame(header, bg="#161b22")
        top_row.pack(fill="x", padx=20)

        logo_canvas = tk.Canvas(top_row, width=60, height=40, bg="#f0883e",
                                highlightthickness=0, bd=0)
        logo_canvas.create_rectangle(2, 2, 58, 38, outline="#f0883e", width=0, fill="#f0883e")
        logo_canvas.create_text(30, 20, text="P", fill="#0d1117",
                                font=("Sans", 22, "bold"))
        logo_canvas.pack(side="right", padx=(10, 0))

        tk.Label(top_row, text="CONTROL \u2014 Estacionamiento", font=("Sans", 26, "bold"),
                 fg="#f0883e", bg="#161b22").pack(side="left")
        self.clock_label = tk.Label(header, text="", font=("Sans", 22, "bold"),
                                    fg="#f0f6fc", bg="#161b22")
        self.clock_label.pack(pady=(0, 4))
        self.date_label = tk.Label(header, text="", font=("Sans", 14),
                                   fg="#8b949e", bg="#161b22")
        self.date_label.pack(pady=(0, 2))

        stats = tk.Frame(self.root, bg="#0d1117", pady=4)
        stats.pack()

        self.avail_card = tk.Label(stats, textvariable=self.avail_var, font=("Sans", 24, "bold"),
                                   fg="#3fb950", bg="#161b22", padx=16, pady=2)
        self.avail_card.pack(side="left", padx=6)
        tk.Label(stats, text="DISP", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left")

        self.occ_card = tk.Label(stats, textvariable=self.occ_var, font=("Sans", 24, "bold"),
                                 fg="#f85149", bg="#161b22", padx=16, pady=2)
        self.occ_card.pack(side="left", padx=6)
        tk.Label(stats, text="OCUP", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left")

        tk.Label(stats, text="Tarifa", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left", padx=(12, 2))
        self.rate_label = tk.Label(stats, textvariable=self.rate_var, font=("Sans", 18, "bold"),
                                   fg="#3fb950", bg="#161b22", padx=12, pady=2)
        self.rate_label.pack(side="left", padx=2)

        tk.Label(stats, text="Gracia", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left", padx=(12, 2))
        self.grace_label = tk.Label(stats, textvariable=self.grace_var, font=("Sans", 14, "bold"),
                                    fg="#f0f6fc", bg="#161b22", padx=12, pady=2)
        self.grace_label.pack(side="left", padx=2)

        tk.Label(stats, text="X Cobrar", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left", padx=(12, 2))
        self.rev_card_label = tk.Label(stats, textvariable=self.rev_card_var, font=("Sans", 18, "bold"),
                                       fg="#d2a8ff", bg="#161b22", padx=12, pady=2)
        self.rev_card_label.pack(side="left", padx=2)

        tk.Label(stats, text="Hoy", font=("Sans", 8),
                 fg="#8b949e", bg="#0d1117").pack(side="left", padx=(12, 2))
        self.daily_rev_label = tk.Label(stats, textvariable=self.daily_rev_var, font=("Sans", 18, "bold"),
                                        fg="#d2a8ff", bg="#161b22", padx=12, pady=2)
        self.daily_rev_label.pack(side="left", padx=2)

        btn_frame = tk.Frame(self.root, bg="#0d1117")
        btn_frame.pack(pady=4)

        tk.Button(btn_frame, text="\u2b06 INGRESO MANUAL", font=("Sans", 14, "bold"),
                  bg="#3fb950", fg="#0d1117", padx=24, pady=6,
                  command=lambda: PlateDialog(self.root, "INGRESO MANUAL",
                                              "INGRESAR", "#3fb950",
                                              "/api/manual-entry")).pack(side="left", padx=6)
        tk.Button(btn_frame, text="\u2b05 SALIDA MANUAL", font=("Sans", 14, "bold"),
                  bg="#f0883e", fg="#0d1117", padx=24, pady=6,
                  command=lambda: PlateDialog(self.root, "SALIDA MANUAL",
                                              "SALIDA", "#f0883e",
                                              "/api/manual-exit")).pack(side="left", padx=6)
        tk.Button(btn_frame, text="\U0001f3ab BOLETO PERDIDO $500", font=("Sans", 14, "bold"),
                  bg="#d2a8ff", fg="#0d1117", padx=24, pady=6,
                  command=lambda: PlateDialog(self.root, "BOLETO PERDIDO - $500",
                                              "COBRAR $500", "#d2a8ff",
                                              "/api/manual-exit-lost")).pack(side="left", padx=6)

        self.full_overlay = tk.Frame(self.root, bg="#1a0000")
        tk.Label(self.full_overlay, text="NO HAY LUGAR", font=("Sans", 50, "bold"),
                 fg="#f85149", bg="#1a0000").pack(expand=True)
        tk.Label(self.full_overlay, text="Espere a que se desocupe un lugar",
                 font=("Sans", 18), fg="#ffa657", bg="#1a0000").pack()

        self.map_canvas = tk.Canvas(self.root, bg="#0d1117", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.map_canvas.yview)
        self.map_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.layout_data = None
        self.keep_running = True

        # footer
        footer = tk.Frame(self.root, bg="#161b22", pady=4)
        footer.pack(side="bottom", fill="x")
        self.footer_label = tk.Label(footer, text="", font=("Sans", 11),
                                     fg="#484f58", bg="#161b22")
        self.footer_label.pack()

        self.update_data()
        self.update_clock()

    def update_clock(self):
        now = time.strftime("%H:%M:%S")
        date = time.strftime("%A %d de %B de %Y")
        self.clock_label.config(text=now)
        self.date_label.config(text=date)
        if self.keep_running:
            self.root.after(1000, self.update_clock)

    def fetch(self, path):
        try:
            r = urllib.request.urlopen(API + path, timeout=5)
            return json.loads(r.read())
        except:
            return None

    def render_matrix(self, layout, spots_map):
        self.map_canvas.delete("all")
        self._click_spots = {}
        rows, cols = layout["rows"], layout["cols"]
        grid_data = layout["grid"]

        for r in range(rows):
            for c in range(cols):
                val = grid_data[r][c]
                x, y = c * (CELL + 4), r * (CELL + 4)
                if val == 0:
                    continue
                elif val == -1:
                    self.map_canvas.create_rectangle(
                        x, y, x + CELL, y + CELL,
                        fill="#1e1e1e", outline="#1e1e1e", width=0)
                else:
                    spot = spots_map.get(val, {})
                    is_avail = spot.get("status", "available") == "available"
                    bg = "#0d2818" if is_avail else "#260e11"
                    border = "#3fb950" if is_avail else "#f85149"
                    fg = "#3fb950" if is_avail else "#f85149"

                    self.map_canvas.create_rectangle(
                        x, y, x + CELL, y + CELL,
                        fill=bg, outline=border, width=2)
                    if not is_avail:
                        plate = spot.get("plate_number", "")
                        cost = spot.get("current_cost", 0) or 0
                        entry_t = spot.get("entry_time", "")
                        entry_display = entry_t[11:16] if len(entry_t) >= 16 else ""
                        date_display = entry_t[8:10] + "/" + entry_t[5:7] if len(entry_t) >= 10 else ""
                        rect = self.map_canvas.create_rectangle(
                            x, y, x + CELL, y + CELL,
                            fill=bg, outline="#f0883e", width=3)
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2 - 24,
                            text=str(val), fill="#f0f6fc",
                            font=("Sans", 16, "bold"))
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2 - 6,
                            text=plate, fill="#f0f6fc",
                            font=("Sans", 9, "bold"))
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2 + 10,
                            text=entry_display + "  " + date_display, fill="#58a6ff",
                            font=("Sans", 8))
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2 + 26,
                            text="$%.2f" % cost, fill="#ffa657",
                            font=("Sans", 9))
                        self._click_spots[rect] = plate
                        self.map_canvas.tag_bind(rect, "<Button-1>", lambda e, p=plate: self.click_exit(p))
                    else:
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2,
                            text=str(val), fill="#f0f6fc",
                            font=("Sans", 18, "bold"))
                        self.map_canvas.create_text(
                            x + CELL // 2, y + CELL // 2 + 16,
                            text="LIBRE", fill=fg,
                            font=("Sans", 10, "bold"))

        total_w = cols * (CELL + 4)
        total_h = rows * (CELL + 4)
        scr_w = self.root.winfo_screenwidth() - 60
        scr_h = self.root.winfo_screenheight() - 320
        self.map_canvas.config(scrollregion=(0, 0, total_w, total_h),
                               width=min(total_w, scr_w),
                               height=min(total_h, scr_h))

    def click_exit(self, plate):
        PlateDialog(self.root, "SALIDA MANUAL - " + plate,
                    "SALIDA", "#f0883e",
                    "/api/manual-exit", plate)

    def update_data(self):
        def work():
            layout = self.fetch("/api/layout")
            spots = self.fetch("/api/spots")
            cfg = self.fetch("/api/config")
            rev = self.fetch("/api/revenue")

            if layout and "error" not in layout:
                self.layout_data = layout
            if spots and "error" not in spots:
                spots_map = {s["spot_number"]: s for s in spots}
                avail = sum(1 for s in spots if s["status"] == "available")
                occ = len(spots) - avail
                total_rev = sum(
                    s.get("current_cost", 0) or 0
                    for s in spots if s["status"] == "occupied"
                )
                self.root.after(0, lambda: self.avail_var.set(str(avail)))
                self.root.after(0, lambda: self.occ_var.set(str(occ)))
                self.root.after(0, lambda: self.rev_card_var.set(
                    "$%.2f" % total_rev if total_rev > 0 else "$0"))

                if avail == 0:
                    self.root.after(0, self.show_full)
                else:
                    self.root.after(0, self.show_map)
                    if self.layout_data:
                        self.root.after(0, lambda: self.render_matrix(self.layout_data, spots_map))

            if cfg and "error" not in cfg:
                rate = float(cfg.get("hourly_rate", 50))
                grace = int(cfg.get("grace_period_minutes", 15))
                self.root.after(0, lambda: self.rate_var.set("$%.2f/hr" % rate))
                self.root.after(0, lambda: self.grace_var.set("%d min" % grace))

            if rev and "error" not in rev:
                self.root.after(0, lambda: self.daily_rev_var.set(
                    "$%.2f" % float(rev.get("today", 0))))
                self.root.after(0, lambda: self.footer_label.config(
                    text="Control manual  |  Semana: $%.2f  |  Mes: $%.2f" % (
                        float(rev.get("week", 0)), float(rev.get("month", 0)))))

            if self.keep_running:
                threading.Timer(REFRESH, self.update_data).start()

        threading.Thread(target=work, daemon=True).start()

    def show_full(self):
        self.map_canvas.pack_forget()
        self.scrollbar.pack_forget()
        self.full_overlay.pack(expand=True, fill="both")

    def show_map(self):
        self.full_overlay.pack_forget()
        self.map_canvas.pack(side="left", expand=True, fill="both", padx=20, pady=2)
        self.scrollbar.pack(side="right", fill="y")

    def run(self):
        self.root.mainloop()
        self.keep_running = False


if __name__ == "__main__":
    DashboardDisplay().run()
