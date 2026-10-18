import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from perimeter_core import FEED_UNITS, GcodeError, perimeter_path, process

BG = "#444444"
APP_NAME = "GcodePerimeterGenerator"


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
    return options


def save_machine_options(options):
    try:
        with open(config_path(), "w") as f:
            json.dump(options, f, indent=2)
    except OSError as e:
        messagebox.showerror("Error", f"Could not save options:\n{e}")


# Preview and save
#-----------------------------------------------------------------------
def draw_preview(canvas, info):
    """Cut paths in grey/blue, perimeter dry run in orange, 0,0 as a red cross."""
    canvas.delete("all")
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 20 or h < 20:
        return
    path = perimeter_path(info)
    xs = [p[0] for p in path] + [0.0]
    ys = [p[1] for p in path] + [0.0]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    margin = 30
    scale = min((w - 2 * margin) / ((max_x - min_x) or 1), (h - 2 * margin) / ((max_y - min_y) or 1))
    ox = (w - (max_x - min_x) * scale) / 2
    oy = (h - (max_y - min_y) * scale) / 2

    def pt(x, y):
        return ox + (x - min_x) * scale, h - (oy + (y - min_y) * scale)

    def flat(points):
        return [c for p in points for c in pt(*p)]

    for seg in info["rapids"]:
        canvas.create_line(*flat(seg), fill="#555555", dash=(2, 4))
    for seg in info["cuts"]:
        canvas.create_line(*flat(seg), fill="#4fc3f7", width=2)
    canvas.create_line(*flat(path), fill="#ff9800", width=2, dash=(8, 4), arrow="last", arrowshape=(12, 14, 5))
    sx, sy = pt(*path[0])
    canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, outline="#ff9800", width=2)
    zx, zy = pt(0, 0)
    canvas.create_line(zx - 8, zy, zx + 8, zy, fill="#ef5350", width=2)
    canvas.create_line(zx, zy - 8, zx, zy + 8, fill="#ef5350", width=2)
    canvas.create_text(zx + 6, zy + 4, text="X0 Y0", fill="#ef5350", anchor="nw")
    canvas.create_text(10, 10, anchor="nw", fill="white", justify="left",
                       text="Blue: cut\nOrange: perimeter dry run\nRed: X0 Y0")


def preview_and_save(file_path, feed_rate_entry, root, options):
    try:
        feed = float(feed_rate_entry.get())
        if feed <= 0:
            raise ValueError
    except ValueError:
        messagebox.showerror("Error", "Invalid feed rate value. Please enter a number greater than 0.")
        return

    try:
        with open(file_path, "r", encoding="latin-1", newline="") as f:
            lines = f.readlines()
        default_units = None if options["file_units"] == "auto" else options["file_units"]
        new_lines, info, notes = process(lines, feed, options["feed_rate"], default_units)
    except (OSError, GcodeError) as e:
        messagebox.showerror("Error", str(e))
        return

    options["last_feed"] = feed_rate_entry.get()
    options["last_dir"] = os.path.dirname(file_path)
    save_machine_options(options)

    u = info["file_units"]
    summary = (
        f"X: {info['min_x']:.4f} to {info['max_x']:.4f}    "
        f"Y: {info['min_y']:.4f} to {info['max_y']:.4f}    ({u})\n"
        f"Size: {info['max_x'] - info['min_x']:.4f} x {info['max_y'] - info['min_y']:.4f} {u}    "
        f"Feed: {info['feed_out']:.2f} {u}/min\n" + "\n".join(notes)
    )

    preview_window = tk.Toplevel(root)
    preview_window.title(f"Preview - {os.path.basename(file_path)}")
    preview_window.geometry("1100x700")
    preview_window.minsize(700, 450)
    set_icon(preview_window)
    preview_window.configure(bg=BG)

    tk.Label(preview_window, text=summary, justify="left", anchor="w",
             bg=BG, fg="white", font=("Consolas", 10)).pack(fill="x", padx=5, pady=5)

    buttons = tk.Frame(preview_window, bg=BG)
    buttons.pack(side="bottom", fill="x")

    panes = tk.PanedWindow(preview_window, orient="horizontal", bg=BG, sashwidth=6)
    panes.pack(expand=True, fill="both", padx=5)

    canvas = tk.Canvas(panes, bg="#1e1e1e", highlightthickness=0)
    panes.add(canvas, minsize=300, width=600)
    canvas.bind("<Configure>", lambda e: draw_preview(canvas, info))

    text_frame = tk.Frame(panes)
    panes.add(text_frame, minsize=250)
    yscroll = tk.Scrollbar(text_frame)
    yscroll.pack(side="right", fill="y")
    xscroll = tk.Scrollbar(text_frame, orient="horizontal")
    xscroll.pack(side="bottom", fill="x")
    preview_text_widget = tk.Text(text_frame, wrap="none", yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    preview_text_widget.pack(expand=True, fill="both")
    yscroll.config(command=preview_text_widget.yview)
    xscroll.config(command=preview_text_widget.xview)
    preview_text_widget.insert("1.0", "".join(new_lines).replace("\r\n", "\n"))
    preview_text_widget.tag_configure("block", background="#ffe9a8")
    start = preview_text_widget.search("PERIMETER DRY RUN START", "1.0")
    end = preview_text_widget.search("PERIMETER DRY RUN END", "1.0")
    if start and end:
        preview_text_widget.tag_add("block", f"{start} linestart", f"{end} lineend")
        preview_text_widget.see(f"{start} linestart")
    preview_text_widget.xview_moveto(0)
    preview_text_widget.config(state="disabled")

    # Bring the preview in front of the main window
    preview_window.transient(root)
    preview_window.lift()
    preview_window.focus_force()

    def save():
        name, ext = os.path.splitext(os.path.basename(file_path))
        new_file_path = filedialog.asksaveasfilename(
            parent=preview_window,
            initialdir=os.path.dirname(file_path),
            initialfile=f"{name}{ext or '.txt'}",
            defaultextension=ext or ".txt",
            filetypes=[("G-code files", "*.txt *.nc *.tap *.ngc *.cnc"), ("All files", "*.*")],
        )
        if not new_file_path:
            return
        try:
            with open(new_file_path, "w", encoding="latin-1", newline="") as new_file:
                new_file.writelines(new_lines)
        except OSError as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}", parent=preview_window)
            return
        messagebox.showinfo("Success", "Perimeter added and file saved successfully.", parent=preview_window)
        preview_window.destroy()

    tk.Button(buttons, text="Save", width=10, command=save).pack(side="left", padx=5, pady=5)
    tk.Button(buttons, text="Cancel", width=10, command=preview_window.destroy).pack(side="right", padx=5, pady=5)


def select_file(feed_rate_entry, root, options):
    file_path = filedialog.askopenfilename(
        initialdir=options.get("last_dir") or None,
        filetypes=[("G-code files", "*.txt *.nc *.tap *.ngc *.cnc"), ("All files", "*.*")],
    )
    if file_path:
        preview_and_save(file_path, feed_rate_entry, root, options)


def validate_input(new_value):
    if new_value == "":
        return True
    try:
        float(new_value)
        return True
    except ValueError:
        return new_value == "."


# Machine options window
#-----------------------------------------------------------------------
def open_machine_option_setting(root, feed_rate_label, options):
    win = tk.Toplevel(root)
    win.title("Machine Option Setting")
    win.configure(bg=root.cget("bg"))
    win.resizable(False, False)
    set_icon(win)
    win.transient(root)
    win.grab_set()

    feed_rate_var = tk.StringVar(value=options["feed_rate"])
    frame = ttk.LabelFrame(win, text="Feed Rate Unit")
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    for i, option in enumerate(FEED_UNITS):
        ttk.Radiobutton(frame, text=option, variable=feed_rate_var, value=option).grid(
            row=i, column=0, padx=5, pady=2, sticky="w")

    units_var = tk.StringVar(value=options["file_units"])
    frame2 = ttk.LabelFrame(win, text="G-code Units")
    frame2.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
    for i, (value, text) in enumerate([("auto", "Auto (G20/G21)"), ("inch", "Inch"), ("mm", "mm")]):
        ttk.Radiobutton(frame2, text=text, variable=units_var, value=value).grid(
            row=i, column=0, padx=5, pady=2, sticky="w")
    ttk.Label(frame2, text="Used only if the file\nhas no G20 / G21.", justify="left").grid(
        row=3, column=0, padx=5, pady=(8, 2), sticky="w")

    win.columnconfigure(0, weight=1)
    win.columnconfigure(1, weight=1)

    def save():
        options["feed_rate"] = feed_rate_var.get()
        options["file_units"] = units_var.get()
        save_machine_options(options)
        feed_rate_label.config(text=f"Enter feed rate in {options['feed_rate']}:")
        win.destroy()

    tk.Button(win, text="Save", command=save).grid(row=1, column=0, columnspan=2, pady=10, padx=100, sticky="ew")


#------------------------------------------------------------------
def main():
    if sys.platform == "win32":
        try:  # sharp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    root.title("G-code Perimeter Generator")
    root.geometry("400x430")
    set_icon(root)
    root.configure(bg=BG)

    options = load_machine_options()
    first_run = not os.path.exists(config_path())

    try:
        logo_image = tk.PhotoImage(file=resource_path("logo.png")).subsample(7, 7)
        logo_label = tk.Label(root, image=logo_image, bg=BG)
        logo_label.image = logo_image
        logo_label.pack(pady=10)
    except tk.TclError:
        pass

    tk.Label(root, text="G-code Perimeter Generator", font=("Helvetica", 16), bg=BG, fg="white").pack(padx=20, pady=20)

    feed_rate_label = tk.Label(root, text=f"Enter feed rate in {options['feed_rate']}:",
                               font=("Helvetica", 11), bg=BG, fg="white")
    feed_rate_label.pack(padx=20, pady=(20, 5))

    validate_cmd = root.register(validate_input)
    feed_rate_entry = tk.Entry(root, validate="key", validatecommand=(validate_cmd, "%P"))
    feed_rate_entry.insert(0, options.get("last_feed") or "150")
    feed_rate_entry.pack(padx=20, pady=(0, 20))

    tk.Button(root, text="Select File", command=lambda: select_file(feed_rate_entry, root, options)).pack(padx=20, pady=(0, 20))
    tk.Button(root, text="Machine Option",
              command=lambda: open_machine_option_setting(root, feed_rate_label, options)).pack(padx=20, pady=(0, 20))

    if first_run:
        root.after(100, lambda: open_machine_option_setting(root, feed_rate_label, options))

    root.mainloop()


if __name__ == "__main__":
    main()
