"""Tkinter front-end: a dark, Zone-styled launcher (layout in the spirit of the Tarkov launcher)."""

import json
import math
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import VERSION, prefix, shortcuts
from .common import Cancelled, events, expand, free_bytes, human
from .config import Config, find_protons
from .installer import EXECUTABLES, Installer

# ---------------------------------------------------------------- palette
BG = "#0d0e0b"
BAR = "#090a07"
PANEL = "#14150f"
PANEL2 = "#1c1e15"
HOVER = "#262819"
FIELD = "#0a0b08"
LINE = "#2d2f23"
TEXT = "#d8d2b6"
MUTED = "#8b8770"
DIM = "#59574a"
AMBER = "#e0a526"
AMBER_HI = "#f4c04a"
AMBER_DK = "#4a3810"
RED = "#cf5a35"
GREEN = "#94b052"
LOG_FG = "#b4c596"


def spaced(text: str) -> str:
    """Letter-spaced caps, military-stencil style."""
    return "  ".join(" ".join(word) for word in text.upper().split())


class Fonts:
    def __init__(self, root):
        fams = set(tkfont.families(root))
        sans = next((f for f in ("Inter", "Cantarell", "DejaVu Sans") if f in fams), "TkDefaultFont")
        mono = next((f for f in ("JetBrainsMono Nerd Font Mono", "DejaVu Sans Mono") if f in fams), "TkFixedFont")
        self.title = (sans, 21, "bold")
        self.sub = (sans, 8, "bold")
        self.tab = (sans, 10, "bold")
        self.panel = (sans, 8, "bold")
        self.body = (sans, 10)
        self.bold = (sans, 10, "bold")
        self.small = (sans, 9)
        self.h1 = (sans, 17, "bold")
        self.h2 = (sans, 11, "bold")
        self.btn = (sans, 10, "bold")
        self.play = (sans, 19, "bold")
        self.status = (sans, 13, "bold")
        self.mono = (mono, 9)


# ---------------------------------------------------------------- widgets
class Btn(tk.Canvas):
    """Flat button with chamfered corners."""

    def __init__(self, master, text, command, kind="secondary", font=None, width=None, height=34, chamfer=8):
        self.bgc = master.cget("bg")
        self.font = font
        self.kind, self.command, self.text = kind, command, text
        self.enabled, self.hover = True, False
        w = width or tkfont.Font(font=font).measure(spaced(text)) + 44
        super().__init__(master, width=w, height=height, bg=self.bgc, highlightthickness=0, cursor="hand2")
        self.w, self.h, self.c = w, height, chamfer
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", lambda e: self._resize(e.width, e.height))
        self.draw()

    def _resize(self, w, h):
        self.w, self.h = w, h
        self.draw()

    def _hover(self, on):
        self.hover = on
        self.draw()

    def _click(self, e):
        if self.enabled and 0 <= e.x <= self.w and 0 <= e.y <= self.h and self.command:
            self.command()

    def configure_btn(self, text=None, enabled=None):
        if text is not None:
            self.text = text
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        self.draw()

    def draw(self):
        self.delete("all")
        w, h, c = self.w - 1, self.h - 1, self.c
        pts = (c, 0, w, 0, w, h - c, w - c, h, 0, h, 0, c)
        hot = self.hover and self.enabled
        if not self.enabled:
            fill, outline, fg = PANEL, LINE, DIM
        elif self.kind == "primary":
            fill, outline, fg = (AMBER_HI if hot else AMBER), (AMBER_HI if hot else AMBER), BAR
        elif self.kind == "danger":
            fill, outline, fg = (HOVER if hot else PANEL2), RED, (AMBER_HI if hot else RED)
        else:
            fill, outline, fg = (HOVER if hot else PANEL2), (AMBER if hot else LINE), (AMBER_HI if hot else TEXT)
        self.create_polygon(pts, fill=fill, outline=outline)
        if self.kind == "primary" and self.enabled and self.h >= 50:
            # hazard notch, bottom-left
            for i in range(3):
                x = 10 + i * 9
                self.create_line(x, h - 4, x + 6, h - 10, fill=BAR if not hot else AMBER_DK, width=3)
        self.create_text(self.w / 2, self.h / 2, text=spaced(self.text), fill=fg, font=self.font)


class Panel(tk.Canvas):
    """Dark PDA-style panel with amber corner brackets and a title strip; put widgets in .body."""

    def __init__(self, master, title, fonts):
        super().__init__(master, bg=BG, highlightthickness=0)
        self.title, self.fonts = title, fonts
        self.body = tk.Frame(self, bg=PANEL)
        self._win = self.create_window(0, 0, window=self.body, anchor="nw")
        self.bind("<Configure>", self._draw)

    def _draw(self, e):
        w, h = e.width, e.height
        self.delete("deco")
        self.create_rectangle(0, 0, w - 1, h - 1, fill=PANEL, outline=LINE, tags="deco")
        L = 14
        for x, y, dx, dy in ((0, 0, 1, 1), (w - 1, 0, -1, 1), (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
            self.create_line(x, y + dy * L, x, y, x + dx * L, y, fill=AMBER, width=2, tags="deco")
        self.create_rectangle(16, 15, 21, 20, fill=AMBER, outline="", tags="deco")
        self.create_text(30, 18, text=spaced(self.title), anchor="w", fill=MUTED, font=self.fonts.panel, tags="deco")
        self.create_line(14, 34, w - 14, 34, fill=LINE, tags="deco")
        self.coords(self._win, 14, 44)
        self.itemconfigure(self._win, width=max(w - 28, 1), height=max(h - 56, 1))
        self.tag_lower("deco")


class Bar(tk.Canvas):
    """Thin segmented progress bar."""

    def __init__(self, master):
        super().__init__(master, height=6, bg=master.cget("bg"), highlightthickness=0)
        self.frac = None
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, frac):
        self.frac = frac
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        self.create_rectangle(0, 1, w, 5, fill=PANEL2, outline="")
        if self.frac is None:
            return
        fill = int(w * max(0.0, min(1.0, self.frac)))
        for x in range(0, fill, 6):
            self.create_rectangle(x, 1, min(x + 4, fill), 5, fill=AMBER, outline="")


def trefoil(canvas, cx, cy, r, color, bg, tags=None):
    for start in (60, 180, 300):
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=60, fill=color, outline="", tags=tags)
    k = r * 0.32
    canvas.create_oval(cx - k, cy - k, cx + k, cy + k, fill=bg, outline="", tags=tags)
    k = r * 0.2
    canvas.create_oval(cx - k, cy - k, cx + k, cy + k, fill=color, outline="", tags=tags)


def trefoil_icon(size=64) -> tk.PhotoImage:
    """Window icon: black trefoil on an amber disc."""
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2
    R = size / 2 - 1
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - c, c - y
            r = math.hypot(dx, dy)
            ang = math.degrees(math.atan2(dy, dx)) % 360
            blade = any((a - 30) % 360 <= ang <= (a + 30) % 360 or ((a - 30) % 360 > (a + 30) % 360 and
                        (ang >= (a - 30) % 360 or ang <= (a + 30) % 360)) for a in (90, 210, 330))
            dark = r <= R * 0.17 or (R * 0.27 <= r <= R * 0.86 and blade)
            row.append("#111108" if dark else AMBER)
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    for y in range(size):
        for x in range(size):
            if math.hypot(x - c, y - c) > R:
                img.transparency_set(x, y, True)
    return img


# ---------------------------------------------------------------- app
class App:
    TABS = ("zone", "mods", "settings")

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = Config()
        self.q = queue.Queue()
        self.worker = None
        self.task = None
        self.game = None
        self.progress = None
        self.last_line = ""
        self.f = Fonts(root)
        root.title("G.A.M.M.A. Launcher")
        root.geometry("1120x700")
        root.minsize(900, 600)
        root.configure(bg=BG)
        try:
            self.icon = trefoil_icon()
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self._style()
        events.log_cb = lambda m: self.q.put(("log", m))
        events.progress_cb = lambda d, t, l: self.q.put(("progress", (d, t, l)))
        self._build()
        self.show("zone")
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)

    # ------------------------------------------------------------ styling
    def _style(self):
        s = ttk.Style(self.root)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Vertical.TScrollbar", troughcolor=PANEL, background=PANEL2, bordercolor=PANEL,
                    arrowcolor=MUTED, lightcolor=PANEL2, darkcolor=PANEL2, gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", HOVER)], arrowcolor=[("active", AMBER)])
        s.configure("TCombobox", fieldbackground=FIELD, background=PANEL2, foreground=TEXT, arrowcolor=AMBER,
                    bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD, insertcolor=AMBER,
                    selectbackground=FIELD, selectforeground=AMBER_HI)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
              bordercolor=[("focus", AMBER)], background=[("active", HOVER)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", AMBER)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BAR)

    def _text(self, master, **kw):
        t = tk.Text(master, bg=PANEL, fg=TEXT, relief="flat", highlightthickness=0, bd=0, wrap="word",
                    padx=4, pady=2, insertbackground=AMBER, selectbackground=AMBER_DK, cursor="arrow", **kw)
        sb = ttk.Scrollbar(master, command=t.yview, style="Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    # ------------------------------------------------------------ layout
    def _build(self):
        self.header = tk.Canvas(self.root, height=66, bg=BAR, highlightthickness=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._draw_header())
        self.stripe = tk.Canvas(self.root, height=5, bg=BAR, highlightthickness=0)
        self.stripe.pack(fill="x")
        self.stripe.bind("<Configure>", lambda e: self._draw_stripe())

        self._build_bottom()

        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(fill="both", expand=True, padx=14, pady=(12, 10))
        self.pages = {"zone": self._page_zone(), "mods": self._page_mods(), "settings": self._page_settings()}

    def _draw_header(self):
        c, f = self.header, self.f
        c.delete("all")
        w = c.winfo_width()
        trefoil(c, 36, 33, 19, AMBER, BAR)
        c.create_text(68, 24, text="G.A.M.M.A.", anchor="w", fill=TEXT, font=f.title)
        c.create_text(70, 49, text=spaced("S.T.A.L.K.E.R.  ·  Linux"), anchor="w", fill=MUTED, font=f.sub)
        x = 300
        self.tab_items = {}
        for name in self.TABS:
            active = name == getattr(self, "current", "zone")
            t = c.create_text(x, 34, text=spaced(name), anchor="w", fill=AMBER if active else MUTED,
                              font=f.tab, tags=(f"tab_{name}",))
            x1, _, x2, _ = c.bbox(t)
            if active:
                c.create_rectangle(x1, 60, x2, 63, fill=AMBER, outline="")
            c.tag_bind(f"tab_{name}", "<Button-1>", lambda e, n=name: self.show(n))
            c.tag_bind(f"tab_{name}", "<Enter>", lambda e, t=t, n=name: c.itemconfigure(
                t, fill=AMBER_HI if n == self.current else TEXT) or c.configure(cursor="hand2"))
            c.tag_bind(f"tab_{name}", "<Leave>", lambda e, t=t, n=name: c.itemconfigure(
                t, fill=AMBER if n == self.current else MUTED) or c.configure(cursor=""))
            x = x2 + 34
        c.create_text(w - 18, 34, text=f"LAUNCHER v{VERSION}", anchor="e", fill=DIM, font=f.sub)

    def _draw_stripe(self):
        c = self.stripe
        c.delete("all")
        w = c.winfo_width()
        c.create_rectangle(0, 0, w, 5, fill=AMBER_DK, outline="")
        for x in range(-10, w + 10, 16):
            c.create_polygon(x, 5, x + 8, 5, x + 13, 0, x + 5, 0, fill=BAR, outline="")

    def _build_bottom(self):
        f = self.f
        bot = tk.Frame(self.root, bg=BAR)
        bot.pack(side="bottom", fill="x")
        tk.Frame(bot, bg=LINE, height=1).pack(fill="x")
        inner = tk.Frame(bot, bg=BAR)
        inner.pack(fill="x", padx=18, pady=14)

        right = tk.Frame(inner, bg=BAR)
        right.pack(side="right")
        self.play_btn = Btn(right, "PLAY", self.on_play, kind="primary", font=f.play, width=230, height=60, chamfer=12)
        self.play_btn.pack(side="right")
        side = tk.Frame(right, bg=BAR)
        side.pack(side="right", padx=(0, 12))
        self.update_btn = Btn(side, "UPDATE", self.on_install, font=f.btn, width=170, height=27, chamfer=6)
        self.update_btn.pack(pady=(0, 6))
        self.mo2_btn = Btn(side, "MOD ORGANIZER", self.on_mo2, font=f.btn, width=170, height=27, chamfer=6)
        self.mo2_btn.pack()
        self.cancel_btn = Btn(side, "CANCEL", self.on_cancel, kind="danger", font=f.btn, width=170, height=27, chamfer=6)

        left = tk.Frame(inner, bg=BAR)
        left.pack(side="left", fill="x", expand=True, padx=(0, 24))
        top = tk.Frame(left, bg=BAR)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=12, height=12, bg=BAR, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self.status_lbl = tk.Label(top, text="", bg=BAR, fg=AMBER, font=f.status, anchor="w")
        self.status_lbl.pack(side="left")
        self.detail_lbl = tk.Label(left, text="", bg=BAR, fg=MUTED, font=f.small, anchor="w")
        self.detail_lbl.pack(fill="x", pady=(4, 6))
        self.bar = Bar(left)
        self.bar.pack(fill="x")

    def _page_zone(self):
        f = self.f
        page = tk.Frame(self.content, bg=BG)
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=0, minsize=330)
        page.rowconfigure(0, weight=1)

        news = Panel(page, "Zone news · G.A.M.M.A. patch notes", f)
        news.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.news = self._text(news.body, font=f.body, spacing1=1, spacing3=3)
        self.news.tag_configure("h1", font=f.h1, foreground=AMBER, spacing1=10, spacing3=6)
        self.news.tag_configure("h2", font=f.h2, foreground=TEXT, spacing1=10, spacing3=4)
        self.news.tag_configure("p", foreground="#bdb79d", lmargin1=2, lmargin2=2)
        self.news.tag_configure("li", foreground="#bdb79d", lmargin1=8, lmargin2=22)
        self.news.tag_configure("muted", foreground=MUTED)

        stat = Panel(page, "Stalker status", f)
        stat.grid(row=0, column=1, sticky="nsew")
        body = stat.body
        body.columnconfigure(1, weight=1)
        self.stat_vals = {}
        rows = ("Anomaly", "Mod Organizer", "Modpack", "Mods", "Notices", "Wine prefix", "Proton", "Free space",
                "Last update")
        for i, key in enumerate(rows):
            tk.Label(body, text=spaced(key), bg=PANEL, fg=DIM, font=f.panel, anchor="w").grid(
                row=i * 2, column=0, sticky="w", pady=(6, 6))
            v = tk.Label(body, text="—", bg=PANEL, fg=TEXT, font=f.bold, anchor="e")
            v.grid(row=i * 2, column=1, sticky="e", padx=(10, 2))
            self.stat_vals[key] = v
            tk.Frame(body, bg=LINE, height=1).grid(row=i * 2 + 1, column=0, columnspan=2, sticky="ew")
        tk.Label(body, text="Good hunting, stalker.", bg=PANEL, fg=DIM, font=f.small).grid(
            row=len(rows) * 2, column=0, columnspan=2, sticky="sw", pady=(14, 0))
        body.rowconfigure(len(rows) * 2, weight=1)
        return page

    def _page_mods(self):
        f = self.f
        page = tk.Frame(self.content, bg=BG)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        ops = Panel(page, "Operations", f)
        ops.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ops.configure(width=270)
        self.op_btns = []
        for text, cmd, tip in (
                ("Install / Update", self.on_install, "Downloads only what changed.\nAlso retries failed mods."),
                ("Repair mods", self.on_repair, "Re-downloads and rebuilds every\nmod that comes from an archive."),
                ("Setup prefix", self.on_prefix, "Reinstalls vcrun2022, d3dx and\nd3dcompiler into the prefix."),
                ("Create shortcuts", self.on_shortcuts, "Desktop + app menu entries."),
                ("Open GAMMA folder", lambda: self._open(self.cfg.gamma_dir), "Mods, profiles, downloads."),
                ("Open logs folder", self._open_logs, "Install log and game crash logs.")):
            b = Btn(ops.body, text, cmd, font=f.btn, width=236, height=32, chamfer=6)
            b.pack(anchor="w", pady=(4, 2))
            tk.Label(ops.body, text=tip, bg=PANEL, fg=DIM, font=f.small, justify="left").pack(anchor="w", pady=(0, 8))
            self.op_btns.append(b)

        logp = Panel(page, "PDA log", f)
        logp.grid(row=0, column=1, sticky="nsew")
        self.log = self._text(logp.body, font=f.mono)
        self.log.configure(bg=FIELD, fg=LOG_FG)
        self.log.tag_configure("err", foreground=RED)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("warn", foreground=AMBER)
        self.log.configure(state="disabled")
        return page

    def _page_settings(self):
        f = self.f
        page = tk.Frame(self.content, bg=BG)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        panel = Panel(page, "Settings", f)
        panel.grid(row=0, column=0, sticky="nsew")
        body = panel.body
        body.columnconfigure(1, weight=1)
        self.vars = {}
        pad = {"pady": 6}

        def row(i, key, label, kind):
            tk.Label(body, text=spaced(label), bg=PANEL, fg=MUTED, font=f.panel, anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 18), **pad)
            v = tk.StringVar(value=self.cfg.get(key, ""))
            v.trace_add("write", lambda *_: self.refresh())
            self.vars[key] = v
            if kind == "combo":
                w = ttk.Combobox(body, textvariable=v, values=find_protons(), font=f.body)
            else:
                w = tk.Entry(body, textvariable=v, bg=FIELD, fg=TEXT, insertbackground=AMBER, relief="flat",
                             highlightthickness=1, highlightbackground=LINE, highlightcolor=AMBER, font=f.body)
            w.grid(row=i, column=1, sticky="ew", ipady=5, **pad)
            Btn(body, "Browse", lambda: self._browse(key, "file" if kind == "file" else "dir"), font=f.sub,
                width=96, height=30, chamfer=5).grid(row=i, column=2, padx=(10, 0), **pad)

        row(0, "anomaly_dir", "Anomaly 1.5.3 folder", "dir")
        row(1, "anomaly_archive", "Anomaly archive (optional)", "file")
        row(2, "gamma_dir", "G.A.M.M.A. folder", "dir")
        row(3, "prefix_dir", "Wine prefix", "dir")
        row(4, "proton_path", "Proton", "combo")

        tk.Frame(body, bg=LINE, height=1).grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)

        tk.Label(body, text=spaced("Renderer"), bg=PANEL, fg=MUTED, font=f.panel).grid(row=6, column=0, sticky="w", **pad)
        self.vars["executable"] = tk.StringVar(value=self.cfg.get("executable"))
        ttk.Combobox(body, textvariable=self.vars["executable"], state="readonly", width=24, font=f.body,
                     values=[t for t, _ in EXECUTABLES[:-1]]).grid(row=6, column=1, sticky="w", ipady=4, **pad)

        tk.Label(body, text=spaced("Parallel downloads"), bg=PANEL, fg=MUTED, font=f.panel).grid(
            row=7, column=0, sticky="w", **pad)
        self.vars["jobs"] = tk.IntVar(value=int(self.cfg.get("jobs", 4)))
        tk.Spinbox(body, from_=1, to=8, width=4, textvariable=self.vars["jobs"], bg=FIELD, fg=TEXT,
                   buttonbackground=PANEL2, relief="flat", highlightthickness=1, highlightbackground=LINE,
                   insertbackground=AMBER, font=f.body).grid(row=7, column=1, sticky="w", ipady=4, **pad)

        for i, (key, label) in enumerate((("keep_archives", "Keep downloaded archives (about 35 GiB more, faster repairs)"),
                                          ("skip_disabled", "Skip mods that are disabled by default (saves space)")), 8):
            self.vars[key] = tk.BooleanVar(value=bool(self.cfg.get(key)))
            tk.Checkbutton(body, text=label, variable=self.vars[key], bg=PANEL, fg=TEXT, selectcolor=FIELD,
                           activebackground=PANEL, activeforeground=AMBER_HI, highlightthickness=0, bd=0,
                           font=f.body, anchor="w").grid(row=i, column=1, columnspan=2, sticky="w", **pad)

        foot = tk.Frame(body, bg=PANEL)
        foot.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        Btn(foot, "Save settings", self.save_settings, kind="primary", font=f.btn, width=190, height=34).pack(side="left")
        self.saved_lbl = tk.Label(foot, text="", bg=PANEL, fg=GREEN, font=f.small)
        self.saved_lbl.pack(side="left", padx=12)
        return page

    def show(self, name):
        self.current = name
        for n, p in self.pages.items():
            if n == name:
                p.pack(fill="both", expand=True)
            else:
                p.pack_forget()
        self._draw_header()
        if name == "zone":
            self.load_news()

    # ------------------------------------------------------------ data
    def _browse(self, key, kind):
        cur = expand(self.vars[key].get() or "~")
        if kind == "dir":
            p = filedialog.askdirectory(initialdir=cur if cur.is_dir() else Path.home())
        else:
            p = filedialog.askopenfilename(initialdir=cur.parent if cur.parent.is_dir() else Path.home(),
                                           filetypes=[("Archives", "*.7z *.zip *.rar"), ("All", "*")])
        if p:
            self.vars[key].set(p)

    def _save(self):
        for k, v in self.vars.items():
            try:
                self.cfg[k] = v.get()
            except tk.TclError:
                pass
        self.cfg.save()

    def save_settings(self):
        self._save()
        self.saved_lbl.configure(text="Saved.")
        self.root.after(2500, lambda: self.saved_lbl.configure(text=""))
        self.refresh()

    def _state(self, gamma: Path) -> dict:
        try:
            return json.loads((gamma / ".gamma-linux" / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def load_news(self):
        if getattr(self, "_news_loaded", None) == self.vars["gamma_dir"].get():
            return
        self._news_loaded = self.vars["gamma_dir"].get()
        notes = expand(self._news_loaded) / ".gamma-linux" / "repos" / "definition" / "Patchnotes.md"
        t = self.news
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not notes.is_file():
            t.insert("end", "No signal from the Zone yet.\n", "h1")
            t.insert("end", "G.A.M.M.A.'s patch notes appear here after the first install.", "muted")
        else:
            for raw in notes.read_text(encoding="utf-8", errors="replace").splitlines()[:900]:
                line = re.sub(r"\*\*|__|`", "", raw).rstrip()
                line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
                if line.startswith("# "):
                    t.insert("end", line[2:].strip().upper() + "\n", "h1")
                elif line.startswith("#"):
                    t.insert("end", line.lstrip("#").strip() + "\n", "h2")
                elif re.match(r"\s*[-*] ", line):
                    t.insert("end", "▪ " + re.sub(r"^\s*[-*] ", "", line) + "\n", "li")
                elif line.strip():
                    t.insert("end", line + "\n", "p")
        t.configure(state="disabled")

    def _modpack_version(self, gamma: Path) -> str:
        notes = gamma / ".gamma-linux" / "repos" / "definition" / "Patchnotes.md"
        try:
            with open(notes, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = re.match(r"#\s*\**\s*(GAMMA\s+[\w.]+)", line)
                    if m:
                        return m.group(1).replace("GAMMA", "G.A.M.M.A.")
        except OSError:
            pass
        return ""

    def refresh(self):
        try:
            g = expand(self.vars["gamma_dir"].get())
            a = expand(self.vars["anomaly_dir"].get())
            pfx = expand(self.vars["prefix_dir"].get())
            proton = self.vars["proton_path"].get()
        except (AttributeError, KeyError):
            return
        st = self._state(g)
        targets = len(st.get("targets", {}))
        anomaly_ok = (a / "bin" / "AnomalyDX11AVX.exe").is_file()
        mo2_ok = (g / "ModOrganizer.exe").is_file()
        self.installed = anomaly_ok and mo2_ok and targets > 0
        marker = pfx / prefix.MARKER
        prefix_ok = marker.is_file() and marker.read_text().split() == prefix.WINETRICKS_VERBS
        warnings = len(st.get("warnings", {}))
        sf = g / ".gamma-linux" / "state.json"
        vals = {
            "Anomaly": ("Found" if anomaly_ok else "Not found", GREEN if anomaly_ok else RED),
            "Mod Organizer": ("Ready" if mo2_ok else "Not installed", GREEN if mo2_ok else MUTED),
            "Modpack": (self._modpack_version(g) or "—", TEXT),
            "Mods": (str(targets) if targets else "—", TEXT),
            "Notices": (f"{warnings} mod(s)" if warnings else "None", AMBER if warnings else MUTED),
            "Wine prefix": ("Ready" if prefix_ok else "Set up on first launch", GREEN if prefix_ok else MUTED),
            "Proton": (Path(proton).name if proton else "Not set", TEXT if proton else RED),
            "Free space": (human(free_bytes(g)), TEXT),
            "Last update": (time.strftime("%d %b %Y, %H:%M", time.localtime(sf.stat().st_mtime))
                            if sf.is_file() else "Never", TEXT),
        }
        for k, (v, color) in vals.items():
            self.stat_vals[k].configure(text=v, fg=color)
        self._status(anomaly_ok)

    def _status(self, anomaly_ok=True):
        running = self.worker is not None and self.worker.is_alive()
        in_game = self.game is not None and self.game.poll() is None
        titles = {"install": "Updating the Zone", "repair": "Repairing mods", "prefix": "Preparing the prefix",
                  "play": "Launching", "mo2": "Starting Mod Organizer", "shortcuts": "Creating shortcuts"}
        if running:
            title, color = titles.get(self.task, "Working"), AMBER
            if self.progress:
                d, t, label = self.progress
                detail = f"{d} / {t}   ·   {label}"
                self.bar.set(d / max(t, 1))
            else:
                detail = self.last_line.strip()[:140]
                self.bar.set(None)
        else:
            self.bar.set(None)
            if in_game:
                title, color, detail = "In the Zone", GREEN, "G.A.M.M.A. is running. Saves are your friend."
            elif not anomaly_ok:
                title, color, detail = "Anomaly not found", RED, "Set your Anomaly 1.5.3 folder in Settings."
            elif not self.installed:
                title, color, detail = "Install required", AMBER, "Press INSTALL to download G.A.M.M.A. (about 100 GiB)."
            else:
                title, color, detail = "Ready", GREEN, "Everything is in place. Press UPDATE now and then."
        self.status_lbl.configure(text=spaced(title), fg=color)
        self.detail_lbl.configure(text=detail)
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 10, 10, fill=color, outline="")
        busy = running or in_game
        self.play_btn.configure_btn(
            text="In game" if in_game else ("Working" if running else ("Play" if self.installed else "Install")),
            enabled=not busy)
        self.mo2_btn.configure_btn(enabled=not busy and self.installed)
        for b in self.op_btns[:4]:
            b.configure_btn(enabled=not busy)
        if running and self.task in ("install", "repair", "prefix"):
            self.update_btn.pack_forget()
            self.cancel_btn.pack(before=self.mo2_btn, pady=(0, 6))
        else:
            self.cancel_btn.pack_forget()
            self.update_btn.pack(before=self.mo2_btn, pady=(0, 6))
            self.update_btn.configure_btn(enabled=not busy)

    # ------------------------------------------------------------ worker
    def _run(self, task, fn):
        if self.worker and self.worker.is_alive():
            return
        self._save()
        events.cancel.clear()
        self.task, self.progress, self.last_line = task, None, ""

        def body():
            try:
                fn()
            except Cancelled:
                events.log("[!] Cancelled. Run it again to continue where it stopped.")
            except Exception as exc:
                events.log(f"[!] ERROR: {exc}")
            finally:
                self.q.put(("done", task))
        self.worker = threading.Thread(target=body, daemon=True)
        self.worker.start()
        self._status()

    def _poll(self):
        changed = False
        try:
            while True:
                kind, data = self.q.get_nowait()
                changed = True
                if kind == "log":
                    self._append(data)
                    if data.strip():
                        self.last_line = data
                elif kind == "progress":
                    self.progress = data
                elif kind == "done":
                    self.worker = None
                    self.progress = None
                    self._news_loaded = None
                    self.refresh()
                    if self.current == "zone":
                        self.load_news()
        except queue.Empty:
            pass
        in_game = self.game is not None and self.game.poll() is None
        if changed or in_game != getattr(self, "_was_in_game", False):
            self._was_in_game = in_game
            self._status()
        self.root.after(150, self._poll)

    def _append(self, msg):
        tag = None
        if "[!]" in msg or "FAILED" in msg:
            tag = "err"
        elif "warning" in msg or "[i]" in msg:
            tag = "warn"
        elif "Good hunting" in msg or msg.startswith("[+]"):
            tag = "ok"
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 5000:
            self.log.delete("1.0", "1000.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_logs(self):
        self._open(self.cfg.data_dir / "logs")
        crash = self.cfg.anomaly_dir / "appdata" / "logs"
        if crash.is_dir():
            self._open(crash)

    # ------------------------------------------------------------ actions
    def on_play(self):
        if not self.installed:
            return self.on_install()

        def go():
            self.game = prefix.launch(self.cfg, self.cfg.get("executable"))
        self._run("play", go)

    def on_install(self):
        self.show("mods")
        self._run("install", lambda: Installer(self.cfg).run())

    def on_repair(self):
        if messagebox.askyesno("Repair mods", "Re-download and rebuild every mod that comes from an archive "
                               "(ModDB / GitHub)? This takes about as long as the first install.\n\n"
                               "Your saves, settings and mod toggles are kept."):
            self.show("mods")
            self._run("repair", lambda: Installer(self.cfg, repair=True).run())

    def on_prefix(self):
        self.show("mods")
        self._run("prefix", lambda: prefix.setup_prefix(self.cfg))

    def on_mo2(self):
        self._run("mo2", lambda: prefix.launch(self.cfg))

    def on_shortcuts(self):
        self._run("shortcuts", lambda: shortcuts.create(self.cfg))

    def on_cancel(self):
        if messagebox.askyesno("Cancel", "Stop the current task? Finished mods are kept."):
            events.cancel.set()

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Quit", "A task is still running. Stop it and quit?\nFinished mods are kept."):
                return
            events.cancel.set()
        try:
            self._save()
        except OSError:
            pass
        self.root.destroy()


def main():
    root = tk.Tk(className="gamma-launcher")
    App(root)
    root.mainloop()
