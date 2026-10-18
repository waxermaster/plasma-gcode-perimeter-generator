"""G-code parsing and perimeter generation (no GUI, so it can be tested anywhere)."""
import math
import re

BLOCK_START = "; --- PERIMETER DRY RUN START ---"
BLOCK_END = "; --- PERIMETER DRY RUN END ---"
PAUSE_LINE = 'M225 #100 "Cycle Start to continue, or Cancel to adjust the starting point."'

FEED_UNITS = ["inch/min", "ft/min", "mm/sec", "mm/min", "m/min", "m/sec"]

# Feed unit -> (base unit "inch" or "mm", factor to convert to base-unit per minute)
_FEED_TO_PER_MIN = {
    "inch/min": ("inch", 1.0),
    "ft/min": ("inch", 12.0),
    "mm/sec": ("mm", 60.0),
    "mm/min": ("mm", 1.0),
    "m/min": ("mm", 1000.0),
    "m/sec": ("mm", 60000.0),
}

# G codes whose X/Y words are not a tool position in the work coordinates
# (dwell, offsets, home/reference returns, machine coords, coordinate-system set).
_NON_MOTION_G = {4, 10, 28, 30, 52, 53, 92}

_WORD_RE = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_PAREN_COMMENT_RE = re.compile(r"\([^)]*\)")


class GcodeError(Exception):
    pass


def _strip_comment(line):
    line = _PAREN_COMMENT_RE.sub(" ", line)
    return line.split(";", 1)[0].upper()


def _words(line):
    return [(m.group(1), float(m.group(2))) for m in _WORD_RE.finditer(_strip_comment(line))]


def _arc_points(sx, sy, ex, ey, cx, cy, clockwise):
    """Start, end and every axis extreme (0/90/180/270 deg) the arc passes through."""
    r = math.hypot(sx - cx, sy - cy)
    pts = [(sx, sy), (ex, ey)]
    if r == 0:
        return pts
    a_start = math.atan2(sy - cy, sx - cx)
    a_end = math.atan2(ey - cy, ex - cx)
    # Sweep measured counter-clockwise from start to end.
    if clockwise:
        a_start, a_end = a_end, a_start
    sweep = (a_end - a_start) % (2 * math.pi)
    if sweep < 1e-9:  # start == end -> full circle
        sweep = 2 * math.pi
    for k in range(4):
        ang = k * math.pi / 2
        if (ang - a_start) % (2 * math.pi) <= sweep + 1e-9:
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _arc_polyline(sx, sy, ex, ey, cx, cy, clockwise):
    """Points along an arc, for drawing the preview."""
    r = math.hypot(sx - cx, sy - cy)
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    sweep = (a0 - a1) % (2 * math.pi) if clockwise else (a1 - a0) % (2 * math.pi)
    if sweep < 1e-9:
        sweep = 2 * math.pi
    steps = max(2, int(sweep / (math.pi / 36)))
    sign = -1 if clockwise else 1
    return [(cx + r * math.cos(a0 + sign * sweep * k / steps),
             cy + r * math.sin(a0 + sign * sweep * k / steps)) for k in range(steps + 1)]


def _find_block(lines):
    """Return (start, end) indexes (end exclusive) of a previously inserted block, or None."""
    for i, line in enumerate(lines):
        if line.strip() == BLOCK_START:
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == BLOCK_END:
                    return i, j + 1
            return i, i + 1
    # Block written by the old version of this tool: 4 G1 lines followed by the M225 prompt.
    for i, line in enumerate(lines):
        if line.strip().startswith("M225") and "Cycle Start to continue" in line:
            start = i
            while start > 0 and start > i - 4 and lines[start - 1].strip().startswith("G1 "):
                start -= 1
            return start, i + 1
    return None


def parse_gcode(lines):
    """Return info about the cut area of a program.

    Only cutting moves (G1/G2/G3) count, so rapids to home/park positions do not
    inflate the perimeter. Arcs include their real extents, not just endpoints.
    """
    block = _find_block(lines)
    absolute = True
    motion = None
    units = None
    used_incremental = False
    x = y = 0.0
    min_x = min_y = math.inf
    cuts, rapids = [], []
    max_x = max_y = -math.inf

    for idx, line in enumerate(lines):
        if block and block[0] <= idx < block[1]:
            continue
        words = _words(line)
        if not words:
            continue
        g_codes = [v for k, v in words if k == "G"]
        skip_xy = False
        for g in g_codes:
            gi = int(round(g)) if abs(g - round(g)) < 1e-6 else None
            if gi in (0, 1, 2, 3):
                motion = gi
            elif gi == 90:
                absolute = True
            elif gi == 91:
                absolute = False
                used_incremental = True
            elif gi == 20 and units is None:
                units = "inch"
            elif gi == 21 and units is None:
                units = "mm"
            elif gi in _NON_MOTION_G:
                skip_xy = True
        if skip_xy:
            continue

        vals = {k: v for k, v in words if k in "XYIJR"}
        if "X" not in vals and "Y" not in vals and motion not in (2, 3):
            continue
        if motion in (2, 3) and not any(k in vals for k in "XYIJR"):
            continue

        nx = vals.get("X", 0.0 if not absolute else x)
        ny = vals.get("Y", 0.0 if not absolute else y)
        if not absolute:
            nx += x
            ny += y

        if motion == 1:
            pts = [(x, y), (nx, ny)]
            cuts.append(pts)
        elif motion in (2, 3):
            if "I" in vals or "J" in vals:
                cx, cy = x + vals.get("I", 0.0), y + vals.get("J", 0.0)
                pts = _arc_points(x, y, nx, ny, cx, cy, clockwise=(motion == 2))
                cuts.append(_arc_polyline(x, y, nx, ny, cx, cy, clockwise=(motion == 2)))
            else:
                pts = [(x, y), (nx, ny)]  # R-format: endpoints only
                cuts.append(pts)
        else:
            pts = []
            rapids.append([(x, y), (nx, ny)])

        for px, py in pts:
            min_x, max_x = min(min_x, px), max(max_x, px)
            min_y, max_y = min(min_y, py), max(max_y, py)
        x, y = nx, ny

    if min_x == math.inf:
        raise GcodeError("No cutting moves (G1/G2/G3 with X/Y) were found in this file.")

    return {
        "min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y,
        "units": units, "incremental": used_incremental, "block": block,
        "cuts": cuts, "rapids": rapids,
    }


def convert_feed(value, feed_unit, file_units):
    """Convert a feed in feed_unit to file_units per minute ("inch" or "mm")."""
    base, factor = _FEED_TO_PER_MIN[feed_unit]
    per_min = value * factor
    if base == file_units:
        return per_min
    return per_min * 25.4 if file_units == "mm" else per_min / 25.4


def _fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def perimeter_path(info):
    """Closed rectangle around the cut area, starting at the corner closest to 0,0, then back to 0,0."""
    lx, hx, ly, hy = info["min_x"], info["max_x"], info["min_y"], info["max_y"]
    corners = [(lx, ly), (hx, ly), (hx, hy), (lx, hy)]
    start = min(range(4), key=lambda k: math.hypot(*corners[k]))
    ordered = corners[start:] + corners[:start]
    # Always travel along X first from the start corner (same feel as the original tool).
    if ordered[1][1] != ordered[0][1]:
        ordered = [ordered[0]] + ordered[1:][::-1]
    return ordered + [ordered[0], (0.0, 0.0)]


def build_block(info, feed, newline="\n"):
    path = perimeter_path(info)
    f = _fmt(feed)
    out = [BLOCK_START, "G90"]
    for i, (px, py) in enumerate(path):
        out.append(f"G1 X{_fmt(px)} Y{_fmt(py)}" + (f" F{f}" if i == 0 else ""))
    out.append(PAUSE_LINE)
    out.append(BLOCK_END)
    return [l + newline for l in out]


def _has_word(line, letter, number):
    return any(k == letter and v == number for k, v in _words(line))


def find_insert_index(lines):
    """Before the first M65 (original behaviour), else the first torch on (M3), else the first cut move."""
    for code, num in (("M", 65), ("M", 3)):
        for i, line in enumerate(lines):
            if _has_word(line, code, num):
                return i, f"before first M{num}"
    for i, line in enumerate(lines):
        if any(k == "G" and v in (1, 2, 3) for k, v in _words(line)):
            return i, "before first cutting move"
    return len(lines), "at end of file"


def process(lines, feed, feed_unit, default_units=None):
    """Return (new_lines, info, notes). Replaces a previously inserted block if there is one."""
    info = parse_gcode(lines)
    notes = []
    file_units = info["units"] or default_units or _FEED_TO_PER_MIN[feed_unit][0]
    if info["units"] is None:
        notes.append(f"No G20/G21 found in file, assuming {file_units}.")
    if info["incremental"]:
        notes.append("File uses G91 (incremental). Check the result carefully.")

    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    work = list(lines)
    if info["block"]:
        del work[info["block"][0]:info["block"][1]]
        notes.append("Existing perimeter block replaced.")

    f_value = convert_feed(feed, feed_unit, file_units)
    idx, where = find_insert_index(work)
    if idx == len(work) and work and not work[-1].endswith(("\n", "\r")):
        work[-1] += newline
    work[idx:idx] = build_block(info, f_value, newline)
    notes.append(f"Perimeter inserted {where} (line {idx + 1}).")
    info["file_units"] = file_units
    info["feed_out"] = f_value
    return work, info, notes
