# PixelTV – YouTube Pixel-Screen Sample

A MicroStation Python sample that builds a TV set whose picture area is a
grid of filled polygon elements ("pixels") and can play YouTube videos frame
by frame directly inside the DGN model.

---

## How it works

| Layer | Technology |
|---|---|
| TV bezel & stand | `ShapeHandler.CreateShapeElement` polygon elements |
| Pixel grid | N × M filled square polygon elements, one per screen pixel |
| Colour mapping | `DgnColorMap.FindClosestMatch` maps each RGB pixel to the nearest DGN palette entry |
| Video frames | `yt-dlp` resolves a YouTube URL → direct stream; `OpenCV` reads frames |
| Animation loop | `PyQt5.QTimer` drives frame updates while keeping MicroStation's input loop alive via `PyCadInputQueue.PythonMainLoop()` |
| Element update | `ElementPropertiesSetter.SetFillColor` + `EditElementHandle.ReplaceInModel` per pixel |

---

## Requirements

**Core** (always required – already part of MicroStation's Python distribution):
```
MSPyBentley  MSPyBentleyGeom  MSPyECObjects
MSPyDgnPlatform  MSPyDgnView  MSPyMstnPlatform
PyQt5
```

**YouTube streaming** (optional – install before using the *Play YouTube* button):
```
pip install yt-dlp opencv-python numpy
```

`numpy` is also needed for the built-in test patterns.

---

## Quick start

Open a DGN file in MicroStation, then run from the Python console:

```python
# Simplest: build a TV and open the control panel
exec(open(r"C:\...\MSPythonSamples\PixelTV\PixelTV.py").read())
tv = PixelTVScreen()
```

The control panel lets you:
* Display a built-in **test pattern** (rainbow / gradient / SMPTE bars) – no
  external dependencies needed.
* Enter a **YouTube URL** and click **Play YouTube** to stream the video onto
  the pixel grid.

### Programmatic use

```python
from PixelTV import create_tv_screen, show_test_pattern, stream_youtube

# Build the TV at a specific position
pixel_refs = create_tv_screen(base_x=5000, base_y=2000)

# Show a test pattern (requires numpy)
show_test_pattern(pixel_refs, pattern='smpte')

# Build + stream in one call
tv = PixelTVScreen(base_x=0, base_y=0, autoshow=True)
```

---

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `base_x`, `base_y` | `0`, `0` | TV origin in master units |
| `pixel_cols` | `32` | Horizontal pixel count |
| `pixel_rows` | `18` | Vertical pixel count (16:9 with 32 cols) |
| `pixel_size` | `50.0` | Side length of each pixel polygon (master units) |
| `pixel_gap` | `2.0` | Gap between adjacent pixels (master units) |
| `bezel_margin` | `80.0` | Bezel thickness around the pixel grid (master units) |

---

## Performance notes

Each video frame requires replacing `pixel_cols × pixel_rows` elements in
the DGN model (576 replacements for the default 32 × 18 grid).  Expect
roughly **1–3 frames per second** depending on hardware.  Use the FPS slider
in the control panel to match the actual render throughput.

For a smoother result, reduce the grid size (e.g. `pixel_cols=16, pixel_rows=9`).

---

## File layout

```
MSPythonSamples/PixelTV/
    PixelTV.py      ← main script (all logic in one file)
    README.md       ← this file
```
