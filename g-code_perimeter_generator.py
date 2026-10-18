import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from perimeter_core import FEED_UNITS, GcodeError, perimeter_path, process

try:
    import sv_ttk  # Sun Valley theme (Windows 11 look)
except ImportError:
    sv_ttk = None

APP_NAME = "GcodePerimeterGenerator"
FILETYPES = [("G-code files", "*.txt *.nc *.tap *.ngc *.cnc"), ("All files", "*.*")]
UNIT_CHOICES = {"Auto (G20 / G21)": "auto", "Inch": "inch", "mm": "mm"}

# Dark palette used by the canvas / text widgets (matches the Sun Valley dark theme)
C_BG = "#1c1c1c"
C_PANEL = "#2b2b2b"
C_TEXT = "#e6e6e6"
C_MUTED = "#9a9a9a"
C_CUT = "#4fc3f7"
C_PERIM = "#ffa726"
C_ORIGIN = "#ef5350"
C_RAPID = "#5a5a5a"


# Paths
#-----------------------------------------------------------------------
def resource_path(name):
    """Works from source and from a PyInstaller exe (files unpacked to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "machine_option.json")


def set_icon(window):
    try:
        window.iconbitmap(resource_path("iconn.ico"))
    except tk.TclError:
        pass  # .ico is Windows-only; never crash over an icon


_FALLBACK_SIZES = {"title": 16, "subtitle": 12}


def ui_font(kind):
    """'title' or 'subtitle': the theme's fonts when Sun Valley is loaded, else a bold default font."""
    name = {"title": "SunValleyTitleFont", "subtitle": "SunValleySubtitleFont"}[kind]
    if name in tkfont.names():
        return name
    return (tkfont.nametofont("TkDefaultFont").actual("family"), _FALLBACK_SIZES[kind], "bold")


def mono_font():
    if sys.platform == "win32":
        return ("Consolas", 10)
    return (tkfont.nametofont("TkFixedFont").actual("family"), 9)


# Options
#-----------------------------------------------------------------------
DEFAULT_OPTIONS = {"feed_rate": "inch/min", "file_units": "auto", "last_feed": "150", "last_dir": ""}


def load_machine_options():
    options = dict(DEFAULT_OPTIONS)
    for path in (config_path(), "machine_option.json"):  # 2nd = file left by the old version
        try:
            with open(path, "r") as f:
                options.update(json.load(f))
            break
        except (OSError, ValueError):
            continue
    if options.get("feed_rate") not in FEED_UNITS:
        options["feed_rate"] = DEFAULT_OPTIONS["feed_rate"]
    if options.get("file_units") not in UNIT_CHOICES.values():
        options["file_units"] = "auto"
    return options


def save_machine_options(options):
    try:
        with open(config_path(), "w") as f:
            json.dump(options, f, indent=2)
    except OSError as e:
        messagebox.showerror("Error", f"Could not save options:\n{e}")


# Preview drawing
#-----------------------------------------------------------------------
def draw_preview(canvas, info):
    """Cut paths in blue, perimeter dry run in orange, X0 Y0 as a red cross."""
    canvas.delete("all")
    small = "SunValleyCaptionFont" if "SunValleyCaptionFont" in tkfont.names() else "TkDefaultFont"
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 20 or h < 20:
        return
    path = perimeter_path(info)
    xs = [p[0] for p in path] + [0.0]
    ys = [p[1] for p in path] + [0.0]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    margin = 50
    scale = min((w - 2 * margin) / ((max_x - min_x) or 1), (h - 2 * margin) / ((max_y - min_y) or 1))
    ox = (w - (max_x - min_x) * scale) / 2
    oy = (h - (max_y - min_y) * scale) / 2

    def pt(x, y):
        return ox + (x - min_x) * scale, h - (oy + (y - min_y) * scale)

    def flat(points):
        return [c for p in points for c in pt(*p)]

    # light grid every "nice" step
    span = max(max_x - min_x, max_y - min_y) or 1
    step = 10 ** int(f"{span:e}".split("e")[1])
    if span / step < 3:
        step /= 5
    gx = (min_x // step) * step
    while gx <= max_x:
        canvas.create_line(*pt(gx, min_y), *pt(gx, max_y), fill="#262626")
        gx += step
    gy = (min_y // step) * step
    while gy <= max_y:
        canvas.create_line(*pt(min_x, gy), *pt(max_x, gy), fill="#262626")
        gy += step

    for seg in info["rapids"]:
        canvas.create_line(*flat(seg), fill=C_RAPID, dash=(2, 4))
    for seg in info["cuts"]:
        canvas.create_line(*flat(seg), fill=C_CUT, width=2, capstyle="round", joinstyle="round")
    canvas.create_line(*flat(path), fill=C_PERIM, width=2, dash=(8, 4), arrow="last", arrowshape=(12, 14, 5))
    sx, sy = pt(*path[0])
    canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, outline=C_PERIM, width=2)
    zx, zy = pt(0, 0)
    canvas.create_line(zx - 9, zy, zx + 9, zy, fill=C_ORIGIN, width=2)
    canvas.create_line(zx, zy - 9, zx, zy + 9, fill=C_ORIGIN, width=2)
    canvas.create_text(zx + 8, zy + 6, text="X0 Y0", fill=C_ORIGIN, anchor="nw", font=small)

    # legend
    y = 14
    for color, label, dash in ((C_CUT, "Cut", None), (C_PERIM, "Perimeter dry run", (6, 3)), (C_ORIGIN, "X0 Y0", None)):
        canvas.create_line(14, y, 34, y, fill=color, width=2, dash=dash)
        canvas.create_text(42, y, text=label, fill=C_TEXT, anchor="w", font=small)
        y += 22


# Preview and save
#-----------------------------------------------------------------------
def stat(parent, title, value, col):
    box = ttk.Frame(parent, style="Card.TFrame", padding=(14, 8))
    box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
    parent.columnconfigure(col, weight=1)
    ttk.Label(box, text=title, foreground=C_MUTED).pack(anchor="w")
    ttk.Label(box, text=value, font=ui_font("subtitle")).pack(anchor="w")


def preview_and_save(file_path, app):
    options = app.options
    try:
        feed = float(app.feed_var.get())
        if feed <= 0:
            raise ValueError
    except ValueError:
        messagebox.showerror("Error", "Invalid feed rate. Please enter a number greater than 0.")
        return

    try:
        with open(file_path, "r", encoding="latin-1", newline="") as f:
            lines = f.readlines()
        default_units = None if options["file_units"] == "auto" else options["file_units"]
        new_lines, info, notes = process(lines, feed, options["feed_rate"], default_units)
    except (OSError, GcodeError) as e:
        messagebox.showerror("Error", str(e))
        return

    options["last_feed"] = app.feed_var.get()
    options["last_dir"] = os.path.dirname(file_path)
    save_machine_options(options)

    u = "in" if info["file_units"] == "inch" else "mm"
    win = tk.Toplevel(app.root)
    win.title(f"Preview - {os.path.basename(file_path)}")
    win.geometry("1150x720")
    win.minsize(760, 480)
    set_icon(win)

    outer = ttk.Frame(win, padding=16)
    outer.pack(expand=True, fill="both")

    head = ttk.Frame(outer)
    head.pack(fill="x")
    ttk.Label(head, text=os.path.basename(file_path), font=ui_font("title")).pack(anchor="w")
    ttk.Label(head, text="   ".join(notes), foreground=C_MUTED).pack(anchor="w", pady=(2, 10))

    stats = ttk.Frame(outer)
    stats.pack(fill="x", pady=(0, 12))
    stat(stats, "Size", f"{info['max_x'] - info['min_x']:.3f} x {info['max_y'] - info['min_y']:.3f} {u}", 0)
    stat(stats, "X range", f"{info['min_x']:.3f}  to  {info['max_x']:.3f}", 1)
    stat(stats, "Y range", f"{info['min_y']:.3f}  to  {info['max_y']:.3f}", 2)
    stat(stats, "Dry run feed", f"{info['feed_out']:.1f} {u}/min", 3)

    buttons = ttk.Frame(outer)
    buttons.pack(side="bottom", fill="x", pady=(12, 0))

    panes = ttk.PanedWindow(outer, orient="horizontal")
    panes.pack(expand=True, fill="both")

    canvas = tk.Canvas(panes, bg=C_BG, highlightthickness=0, width=640)
    panes.add(canvas, weight=3)
    canvas.bind("<Configure>", lambda e: draw_preview(canvas, info))

    text_frame = ttk.Frame(panes)
    panes.add(text_frame, weight=2)
    yscroll = ttk.Scrollbar(text_frame)
    yscroll.pack(side="right", fill="y")
    xscroll = ttk.Scrollbar(text_frame, orient="horizontal")
    xscroll.pack(side="bottom", fill="x")
    text = tk.Text(text_frame, wrap="none", yscrollcommand=yscroll.set, xscrollcommand=xscroll.set,
                   bg=C_PANEL, fg=C_TEXT, insertbackground=C_TEXT, relief="flat", borderwidth=0,
                   padx=10, pady=8, width=40, font=mono_font())
    text.pack(expand=True, fill="both")
    yscroll.config(command=text.yview)
    xscroll.config(command=text.xview)
    text.insert("1.0", "".join(new_lines).replace("\r\n", "\n"))
    text.tag_configure("block", background="#4a3a12", foreground="#ffd27f")
    start = text.search("PERIMETER DRY RUN START", "1.0")
    end = text.search("PERIMETER DRY RUN END", "1.0")
    if start and end:
        text.tag_add("block", f"{start} linestart", f"{end} lineend")
        text.see(f"{start} linestart")
    text.xview_moveto(0)
    text.config(state="disabled")

    def save():
        name, ext = os.path.splitext(os.path.basename(file_path))
        new_file_path = filedialog.asksaveasfilename(
            parent=win, initialdir=os.path.dirname(file_path), initialfile=f"{name}{ext or '.txt'}",
            defaultextension=ext or ".txt", filetypes=FILETYPES)
        if not new_file_path:
            return
        try:
            with open(new_file_path, "w", encoding="latin-1", newline="") as new_file:
                new_file.writelines(new_lines)
        except OSError as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}", parent=win)
            return
        app.status_var.set(f"Saved: {os.path.basename(new_file_path)}")
        win.destroy()

    ttk.Button(buttons, text="Save G-code", style="Accent.TButton", command=save, width=16).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=win.destroy, width=12).pack(side="right", padx=(0, 8))

    win.transient(app.root)
    win.lift()
    win.focus_force()


# Main window
#-----------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.options = load_machine_options()

        root.title("Perimeter Generator")
        root.resizable(False, False)
        set_icon(root)

        frame = ttk.Frame(root, padding=24)
        frame.pack(expand=True, fill="both")

        # Header
        head = ttk.Frame(frame)
        head.pack(fill="x", pady=(0, 20))
        try:
            self.logo = tk.PhotoImage(file=resource_path("logo.png")).subsample(10, 10)
            ttk.Label(head, image=self.logo).pack(side="left", padx=(0, 14))
        except tk.TclError:
            pass
        titles = ttk.Frame(head)
        titles.pack(side="left", fill="x")
        ttk.Label(titles, text="Perimeter Generator", font=ui_font("title")).pack(anchor="w")
        ttk.Label(titles, text="Plasma dry run for Centroid Acorn", foreground=C_MUTED).pack(anchor="w")

        # Settings card
        card = ttk.Frame(frame, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Dry run feed rate").grid(row=0, column=0, columnspan=2, sticky="w")
        vcmd = root.register(validate_input)
        self.feed_var = tk.StringVar(value=self.options.get("last_feed") or "150")
        ttk.Entry(card, textvariable=self.feed_var, validate="key", validatecommand=(vcmd, "%P"),
                  width=12).grid(row=1, column=0, sticky="ew", pady=(6, 14))
        self.unit_var = tk.StringVar(value=self.options["feed_rate"])
        unit = ttk.Combobox(card, textvariable=self.unit_var, values=FEED_UNITS, state="readonly", width=10)
        unit.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 14))
        unit.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        ttk.Label(card, text="G-code units (if the file has no G20 / G21)").grid(row=2, column=0, columnspan=2, sticky="w")
        label_for = {v: k for k, v in UNIT_CHOICES.items()}
        self.file_units_var = tk.StringVar(value=label_for[self.options["file_units"]])
        fu = ttk.Combobox(card, textvariable=self.file_units_var, values=list(UNIT_CHOICES), state="readonly")
        fu.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        fu.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        # Main action
        ttk.Button(frame, text="Open G-code file...", style="Accent.TButton",
                   command=self.select_file).pack(fill="x", pady=(20, 10), ipady=6)

        self.status_var = tk.StringVar(value="Select a SheetCam G-code file to add the perimeter dry run.")
        ttk.Label(frame, textvariable=self.status_var, foreground=C_MUTED, wraplength=360,
                  justify="center", anchor="center").pack(fill="x")

        root.bind("<Return>", lambda e: self.select_file())

    def _save_settings(self):
        self.options["feed_rate"] = self.unit_var.get()
        self.options["file_units"] = UNIT_CHOICES[self.file_units_var.get()]
        save_machine_options(self.options)

    def select_file(self):
        self._save_settings()
        file_path = filedialog.askopenfilename(initialdir=self.options.get("last_dir") or None, filetypes=FILETYPES)
        if file_path:
            self.status_var.set(f"Opened: {os.path.basename(file_path)}")
            preview_and_save(file_path, self)


def validate_input(new_value):
    if new_value in ("", "."):
        return True
    try:
        float(new_value)
        return True
    except ValueError:
        return False


#------------------------------------------------------------------
def main():
    if sys.platform == "win32":
        try:  # sharp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    if sv_ttk:
        sv_ttk.set_theme("dark")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
