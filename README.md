# plasma-G-code-perimeter-generator
CNC plasma G-code perimeter generator

This little tool opens a plasma G-code file, finds the real extents of the cut (arcs included) and inserts a dry run at the start of the program: it traces a rectangle around the part at the feed you choose, comes back to X0 Y0, then pauses until you press **Cycle Start** (or Cancel to adjust the starting point).

Made for the SheetCam post processor **Centroid Acorn Plasma THC.scpost**. The block is inserted before the first `M65`. If there is no `M65`, it goes before the first `M3`, or else before the first cut move.

## Usage
1. Run `g-code_perimeter_generator.exe`. From source: `pip install -r requirements.txt` then `python g-code_perimeter_generator.py`.
2. Type the dry run feed and choose its unit. The tool converts it to the units of the file (G20 = inch, G21 = mm).
3. Click **Open G-code file...**, check the preview (drawing of the part + the inserted block highlighted) and click **Save G-code**.

To change the feed later, open the saved file again with a new feed. The old perimeter block is replaced. The rest of the program is never changed.

Settings are saved in `%APPDATA%\GcodePerimeterGenerator\machine_option.json`.

## Download / build
- Every push builds the exe with GitHub Actions (tab **Actions** > latest run > artifact). Pushing a tag such as `v2.0` attaches the exe to a GitHub release.
- To build it yourself on Windows: install Python 3 from python.org, then double-click `build.bat`. The exe goes into `dist\`.
- Tests: `python -m unittest discover -s tests`
- Sample files for trying the app (not for real cutting): `examples/`

If your plasma uses another controller, tell me which SheetCam post processor you use (waxer.master@gmail.com).
