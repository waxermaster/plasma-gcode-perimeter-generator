import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from perimeter_core import (parse_gcode, process, convert_feed, GcodeError, BLOCK_START, BLOCK_END, PAUSE_LINE)

SAMPLE = """(Sheetcam style)
G20 G90 G40
M65
G0 X1 Y1
M3
G1 X5 Y1 F100
G1 Y4
X1
G1Y1
G0 Z1
M5
G0 X0 Y0
G28 X0 Y0
M30
""".splitlines(keepends=True)


def block(lines):
    s = [l.strip() for l in lines]
    return s[s.index(BLOCK_START):s.index(BLOCK_END) + 1]


class Core(unittest.TestCase):
    def test_bounds_ignore_rapids_and_g28(self):
        i = parse_gcode(SAMPLE)
        self.assertEqual((i["min_x"], i["max_x"], i["min_y"], i["max_y"]), (1, 5, 1, 4))
        self.assertEqual(i["units"], "inch")

    def test_arc_extents(self):
        # full circle centre (10,10) r=2 starting at (12,10)
        i = parse_gcode(["G21\n", "G0 X12 Y10\n", "G2 X12 Y10 I-2 J0\n"])
        self.assertAlmostEqual(i["min_x"], 8); self.assertAlmostEqual(i["max_x"], 12)
        self.assertAlmostEqual(i["min_y"], 8); self.assertAlmostEqual(i["max_y"], 12)
        # CCW quarter from (12,10) to (10,12): top-right only, no extra extremes
        i = parse_gcode(["G0 X12 Y10\n", "G3 X10 Y12 I-2 J0\n"])
        self.assertEqual((i["min_x"], i["max_x"], i["min_y"], i["max_y"]), (10, 12, 10, 12))
        # CW from (12,10) to (10,12) goes the long way: passes bottom and left
        i = parse_gcode(["G0 X12 Y10\n", "G2 X10 Y12 I-2 J0\n"])
        self.assertAlmostEqual(i["min_x"], 8); self.assertAlmostEqual(i["min_y"], 8)

    def test_line_numbers_comments_incremental(self):
        i = parse_gcode(["N10 G0 X2 Y2 (X99)\n", "N20 G1 X3 Y3 ; X-50\n", "G91\n", "G1 X1\n", "G90\n"])
        self.assertEqual((i["min_x"], i["max_x"], i["min_y"], i["max_y"]), (2, 4, 2, 3))
        self.assertTrue(i["incremental"])

    def test_no_moves(self):
        with self.assertRaises(GcodeError):
            parse_gcode(["G20\n", "M30\n"])

    def test_insert_rectangle_before_m65(self):
        out, info, notes = process(SAMPLE, 150, "inch/min")
        b = block(out)
        self.assertEqual(out[2].strip(), BLOCK_START)  # before M65
        self.assertEqual(b[1:-1], ["G90", "G1 X1 Y1 F150", "G1 X5 Y1", "G1 X5 Y4", "G1 X1 Y4",
                                   "G1 X1 Y1", "G1 X0 Y0", PAUSE_LINE])

    def test_negative_quadrant_starts_nearest_corner(self):
        out, *_ = process(["G20\n", "G1 X-1 Y-1\n", "G1 X-5 Y-4\n"], 150, "inch/min")
        b = block(out)
        self.assertEqual(b[2], "G1 X0 Y0 F150")  # (0,0) is a corner of the cut area here
        self.assertTrue(b[3].endswith("Y0"))      # X leg first
        self.assertEqual(b[-3], "G1 X0 Y0")

    def test_rerun_replaces_block_and_keeps_crlf(self):
        crlf = [l.replace("\n", "\r\n") for l in SAMPLE]
        out1, *_ = process(crlf, 150, "inch/min")
        out2, info, notes = process(out1, 200, "inch/min")
        self.assertEqual(sum(BLOCK_START in l for l in out2), 1)
        self.assertIn("G1 X1 Y1 F200", "".join(out2))
        self.assertTrue(all(l.endswith("\r\n") for l in out2))
        # Original cut lines untouched (old version rewrote every G1 F before M65)
        self.assertIn("G1 X5 Y1 F100\r\n", out2)

    def test_legacy_block_replaced(self):
        legacy = SAMPLE[:2] + ["G1 X5 F150\n", "G1 Y4 F150\n", "G1 X1 F150\n", "G1 Y1 F150\n",
                               'M225 #100 "Cycle Start to continue, or Cancel to adjust the starting point."\n'] + SAMPLE[2:]
        out, info, notes = process(legacy, 150, "inch/min")
        self.assertNotIn("G1 X5 F150\n", out)
        self.assertEqual(sum("M225" in l for l in out), 1)
        self.assertEqual((info["min_x"], info["max_x"]), (1, 5))

    def test_feed_conversion(self):
        self.assertAlmostEqual(convert_feed(10, "ft/min", "inch"), 120)
        self.assertAlmostEqual(convert_feed(100, "inch/min", "mm"), 2540)
        self.assertAlmostEqual(convert_feed(50, "mm/sec", "mm"), 3000)
        self.assertAlmostEqual(convert_feed(2540, "mm/min", "inch"), 100)
        out, info, notes = process(["G21\n", "G1 X10 Y10\n"], 10, "ft/min")
        self.assertAlmostEqual(info["feed_out"], 3048)

    def test_fallback_insert_without_m65(self):
        out, info, notes = process(["G20\n", "G0 X1 Y1\n", "M3\n", "G1 X2 Y2\n"], 100, "inch/min")
        self.assertEqual(out[2].strip(), BLOCK_START)
        self.assertTrue(any("M3" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
