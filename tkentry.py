#!/usr/bin/env python3
import tkinter as tk
from tkinter import simpledialog
import urllib.request
import urllib.parse
import json
import threading
import time

API = "http://localhost:5100"
REFRESH = 3
CELL = 70


class ManualEntryDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Ingreso Manual")
        self.attributes("-fullscreen", True)
        self.configure(bg="#0d1117")

        frame = tk.Frame(self, bg="#0d1117")
        frame.pack(expand=True)

        tk.Label(frame, text="INGRESO MANUAL", font=("Sans", 36, "bold"),
                 fg="#58a6ff", bg="#0d1117").pack(pady=30)
        tk.Label(frame, text="Escriba la placa del veh\u00edculo", font=("Sans", 18),
                 fg="#8b949e", bg="#0d1117").pack()

        self.entry = tk.Entry(frame, font=("Sans", 48), justify="center",
                              bg="#161b22", fg="#f0f6fc", relief="flat",
                              insertbackground="#58a6ff")
        self.entry.pack(pady=30, ipady=10, padx=40, fill="x")
        self.entry.focus()
        self.entry.bind("<Return>", self.on_submit)
        self.entry.bind("<Escape>", lambda e: self.destroy())

        btn_frame = tk.Frame(frame, bg="#0d1117")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="ACEPTAR", font=("Sans", 20, "bold"),
                  bg="#3fb950", fg="#0d1117", padx=40, pady=10,
                  command=self.on_submit).pack(side="left", padx=10)
        tk.Button(btn_frame, text="CANCELAR", font=("Sans", 20),
                  bg="#30363d", fg="#f0f6fc", padx=40, pady=10,
                  command=self.destroy).pack(side="left", padx=10)

        self.status_label = tk.Label(frame, text="", font=("Sans", 16),
                                     fg="#f0883e", bg="#0d1117")
        self.status_label.pack(pady=10)

    def on_submit(self, event=None):
        plate = self.entry.get().strip().upper()
        if not plate:
            self.status_label.config(text="Ingrese una placa", fg="#f85149")
            return
        self.status_label.config(text="Procesando...", fg="#f0883e")
        self.update()

        try:
            data = json.dumps({"plate": plate}).encode()
            req = urllib.request.Request(API + "/api/manual-entry",
                                         data=data,
                                         headers={"Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
            if resp.get("ok"):
                self.status_label.config(
                    text="\u2714 Lugar #%d asignado a %s" % (resp["spot_number"], plate),
                    fg="#3fb950")
                self.after(1500, self.destroy)
            else:
                self.status_label.config(text="Error: " + resp.get("error", ""), fg="#f85149")
        except Exception as e:
            self.status_label.config(text="Error de conexi\u00f3n", fg="#f85149")


class EntryDisplay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Entrada - Estacionamiento")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#0d1117")
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.avail_var = tk.StringVar(value="--")
        self.occ_var = tk.StringVar(value="--")

        header = tk.Frame(self.root, bg="#161b22", pady=8)
        header.pack(fill="x")

        top_row = tk.Frame(header, bg="#161b22")
        top_row.pack(fill="x", padx=20)

        # Logo on the right side
        logo_canvas = tk.Canvas(top_row, width=60, height=40, bg="#58a6ff",
                                highlightthickness=0, bd=0)
        logo_canvas.create_rectangle(2, 2, 58, 38, outline="#58a6ff", width=0, fill="#58a6ff")
        logo_canvas.create_text(30, 20, text="P", fill="#0d1117",
                                font=("Sans", 22, "bold"))
        logo_canvas.pack(side="right", padx=(10, 0))

        tk.Label(top_row, text="ENTRADA \u2014 Estacionamiento", font=("Sans", 26, "bold"),
                 fg="#58a6ff", bg="#161b22").pack(side="left")
        self.clock_label = tk.Label(header, text="", font=("Sans", 12),
                                    fg="#f0f6fc", bg="#161b22")
        self.clock_label.pack()

        stats = tk.Frame(self.root, bg="#0d1117", pady=8)
        stats.pack()

        self.avail_card = tk.Label(stats, textvariable=self.avail_var, font=("Sans", 32, "bold"),
                                   fg="#3fb950", bg="#161b22", padx=25, pady=4)
        self.avail_card.pack(side="left", padx=12)
        tk.Label(stats, text="DISPONIBLES", font=("Sans", 9),
                 fg="#8b949e", bg="#0d1117").pack(side="left")

        self.occ_card = tk.Label(stats, textvariable=self.occ_var, font=("Sans", 32, "bold"),
                                 fg="#f85149", bg="#161b22", padx=25, pady=4)
        self.occ_card.pack(side="left", padx=12)
        tk.Label(stats, text="OCUPADOS", font=("Sans", 9),
                 fg="#8b949e", bg="#0d1117").pack(side="left")

        self.suggest_frame = tk.Frame(self.root, bg="#0d1117")
        self.suggest_frame.pack(pady=4)
        self.suggest_label = tk.Label(self.suggest_frame, text="", font=("Sans", 12),
                                      fg="#e6edf3", bg="#0d1117")
        self.suggest_label.pack()

        # Manual entry button
        btn_frame = tk.Frame(self.root, bg="#0d1117")
        btn_frame.pack(pady=4)
        tk.Button(btn_frame, text="\u2328 INGRESO MANUAL", font=("Sans", 16, "bold"),
                  bg="#f0883e", fg="#0d1117", padx=30, pady=8,
                  command=self.open_manual_entry).pack()

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
        self.update_data()
        self.update_clock()

    def open_manual_entry(self):
        ManualEntryDialog(self.root)

    def update_clock(self):
        now = time.strftime("%H:%M:%S")
        self.clock_label.config(text=now + "  |  " + time.strftime("%A %d %B %Y"))
        if self.keep_running:
            self.root.after(1000, self.update_clock)

    def fetch(self, path):
        try:
            r = urllib.request.urlopen(API + path, timeout=5)
            return json.loads(r.read())
        except:
            return None

    def render_matrix(self, layout, spots_map):
        for w in self.map_canvas.winfo_children():
            w.destroy()
        self.map_canvas.delete("all")

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
                    self.map_canvas.create_text(
                        x + CELL // 2, y + CELL // 2 - 8,
                        text=str(val), fill="#f0f6fc",
                        font=("Sans", 18, "bold"))
                    self.map_canvas.create_text(
                        x + CELL // 2, y + CELL // 2 + 12,
                        text="LIBRE" if is_avail else "OCUPADO",
                        fill=fg, font=("Sans", 8, "bold"))

        total_w = cols * (CELL + 4)
        total_h = rows * (CELL + 4)
        scr_w = self.root.winfo_screenwidth() - 60
        scr_h = self.root.winfo_screenheight() - 320
        self.map_canvas.config(scrollregion=(0, 0, total_w, total_h),
                               width=min(total_w, scr_w),
                               height=min(total_h, scr_h))

    def update_data(self):
        def work():
            layout = self.fetch("/api/layout")
            spots = self.fetch("/api/spots")

            if layout and "error" not in layout:
                self.layout_data = layout
            if spots and "error" not in spots:
                spots_map = {s["spot_number"]: s for s in spots}
                avail = sum(1 for s in spots if s["status"] == "available")
                occ = len(spots) - avail
                self.root.after(0, lambda: self.avail_var.set(str(avail)))
                self.root.after(0, lambda: self.occ_var.set(str(occ)))

                if avail == 0:
                    self.root.after(0, self.show_full)
                else:
                    self.root.after(0, self.show_map)
                    if self.layout_data:
                        self.root.after(0, lambda: self.render_matrix(self.layout_data, spots_map))
                    first_avail = next((s for s in spots if s["status"] == "available"), None)
                    if first_avail:
                        self.root.after(0, lambda: self.suggest_label.config(
                            text="\u25b6 OCUPE LUGAR #" + str(first_avail["spot_number"]),
                            fg="#3fb950", font=("Sans", 16, "bold")))
                    else:
                        self.root.after(0, lambda: self.suggest_label.config(text=""))

            if self.keep_running:
                threading.Timer(REFRESH, self.update_data).start()

        threading.Thread(target=work, daemon=True).start()

    def show_full(self):
        self.map_canvas.pack_forget()
        self.scrollbar.pack_forget()
        self.full_overlay.pack(expand=True, fill="both")
        self.suggest_label.config(text="")

    def show_map(self):
        self.full_overlay.pack_forget()
        self.map_canvas.pack(side="left", expand=True, fill="both", padx=20, pady=2)
        self.scrollbar.pack(side="right", fill="y")

    def run(self):
        self.root.mainloop()
        self.keep_running = False


if __name__ == "__main__":
    EntryDisplay().run()
