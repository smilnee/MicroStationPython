# -*- coding: utf-8 -*-
'''
/*--------------------------------------------------------------------------------------+
| $Copyright: (c) 2024 Bentley Systems, Incorporated. All rights reserved. $
+--------------------------------------------------------------------------------------*/
'''

# PixelTV - A pixel TV screen that can display YouTube video frames in MicroStation
#
# Builds a TV screen whose picture area is a grid of filled square polygon elements
# ("pixels").  Each pixel's fill colour is mapped to the nearest entry in the active
# DGN colour table.  Video frames are obtained via yt-dlp + OpenCV so that any
# publicly-accessible YouTube URL can be used as a video source.
#
# Usage (MicroStation Python console):
#   exec(open(r"<path>\PixelTV.py").read())
#   tv = PixelTVScreen()          # build TV and open the control panel
#
# Alternatively, run the bottom __main__ block to create a TV and show a test pattern
# without any external dependencies.
#
# Optional third-party dependencies for YouTube streaming:
#   pip install yt-dlp opencv-python numpy

import math
import os
import sys

from MSPyBentley      import *
from MSPyBentleyGeom  import *
from MSPyECObjects    import *
from MSPyDgnPlatform  import *
from MSPyDgnView      import *
from MSPyMstnPlatform import *

# ---------------------------------------------------------------------------
# Default screen geometry (all values in master units)
# ---------------------------------------------------------------------------
PIXEL_COLS   = 32      # columns of pixels (horizontal)
PIXEL_ROWS   = 18      # rows of pixels    (vertical, 16:9 with PIXEL_COLS=32)
PIXEL_SIZE   = 50.0    # side length of each square pixel polygon
PIXEL_GAP    = 2.0     # gap between adjacent pixels
BEZEL_MARGIN = 80.0    # bezel thickness around the pixel area
STAND_HEIGHT = 120.0   # height of the TV stand pedestal
STAND_TOP_W  = 140.0   # stand width at the screen connection
STAND_BOT_W  = 240.0   # stand width at the floor
STAND_BASE_H = 12.0    # height of the flat stand base

# Palette indices used for structural parts (default DGN palette)
COLOR_BLACK  = 0        # screen background / default pixel colour
COLOR_BEZEL  = 248      # light-grey bezel / stand


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_rect_points(x0, y0, x1, y1):
    '''Return a closed DPoint3dArray rectangle (5 points).'''
    pts = DPoint3dArray()
    pts.append(DPoint3d(x0, y0, 0.0))
    pts.append(DPoint3d(x1, y0, 0.0))
    pts.append(DPoint3d(x1, y1, 0.0))
    pts.append(DPoint3d(x0, y1, 0.0))
    pts.append(DPoint3d(x0, y0, 0.0))
    return pts


def _add_shape(x0, y0, x1, y1, line_color, fill_color, line_weight, model_ref):
    '''Create a filled rectangle shape and add it to the model. Returns the element ref, or None.'''
    eeh = EditElementHandle()
    pts = _make_rect_points(x0, y0, x1, y1)
    status = ShapeHandler.CreateShapeElement(eeh, None, pts, model_ref.Is3d(), model_ref)
    if BentleyStatus.eSUCCESS != status:
        return None
    props = ElementPropertiesSetter()
    props.SetColor(line_color)
    props.SetFillColor(fill_color)
    props.SetWeight(line_weight)
    props.Apply(eeh)
    if BentleyStatus.eSUCCESS != eeh.AddToModel():
        return None
    return eeh.GetElementRef()


def _add_polygon(point_list, line_color, fill_color, line_weight, model_ref):
    '''Create a filled polygon from a list of (x, y) tuples and add it to the model.'''
    eeh = EditElementHandle()
    pts = DPoint3dArray()
    for x, y in point_list:
        pts.append(DPoint3d(x, y, 0.0))
    # ensure closure
    if (point_list[0][0] != point_list[-1][0] or point_list[0][1] != point_list[-1][1]):
        pts.append(DPoint3d(point_list[0][0], point_list[0][1], 0.0))
    status = ShapeHandler.CreateShapeElement(eeh, None, pts, model_ref.Is3d(), model_ref)
    if BentleyStatus.eSUCCESS != status:
        return None
    props = ElementPropertiesSetter()
    props.SetColor(line_color)
    props.SetFillColor(fill_color)
    props.SetWeight(line_weight)
    props.Apply(eeh)
    if BentleyStatus.eSUCCESS != eeh.AddToModel():
        return None
    return eeh.GetElementRef()


def _refresh_view():
    '''Trigger a full redraw of the selected viewport.'''
    vSet = IViewManager.GetActiveViewSet()
    if vSet is None:
        return
    vp = vSet.GetSelectedViewport()
    if vp is None:
        return
    info = IndexedViewSet.FullUpdateInfo()
    vSet.UpdateView(vp, DgnDrawMode.eDRAW_MODE_Normal, DrawPurpose.eUpdate, info)


# ---------------------------------------------------------------------------
# TV screen creation
# ---------------------------------------------------------------------------

def create_tv_screen(base_x=0.0, base_y=0.0,
                     pixel_cols=PIXEL_COLS, pixel_rows=PIXEL_ROWS,
                     pixel_size=PIXEL_SIZE, pixel_gap=PIXEL_GAP,
                     bezel_margin=BEZEL_MARGIN):
    '''
    Build a pixel TV screen at (base_x, base_y) and return the pixel element refs.

    The screen consists of:
      - A trapezoidal stand + flat base (structural polygons)
      - An outer bezel rectangle
      - A dark screen-background rectangle
      - A grid of pixel_cols × pixel_rows filled square polygons

    Parameters
    ----------
    base_x, base_y : float
        Bottom-left origin of the entire TV (including stand).
    pixel_cols, pixel_rows : int
        Number of pixel columns / rows in the display grid.
    pixel_size : float
        Side length of each square pixel polygon in master units.
    pixel_gap : float
        Gap between adjacent pixels in master units.
    bezel_margin : float
        Width of the bezel border around the pixel grid.

    Returns
    -------
    list of (ElementRef, DgnModel) tuples, one per pixel, in row-major order
    where index 0 is the top-left pixel (matching standard image row 0).
    Returns None if the model is unavailable.
    '''
    ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
    if ACTIVEMODEL is None:
        print('PixelTV: no active DGN model')
        return None

    dgnModel = ISessionMgr.ActiveDgnModel

    # Derived dimensions
    screen_w = pixel_cols * pixel_size + (pixel_cols - 1) * pixel_gap
    screen_h = pixel_rows * pixel_size + (pixel_rows - 1) * pixel_gap

    bezel_x0 = base_x
    bezel_y0 = base_y + STAND_HEIGHT
    bezel_x1 = bezel_x0 + screen_w + 2.0 * bezel_margin
    bezel_y1 = bezel_y0 + screen_h + 2.0 * bezel_margin

    bezel_cx = (bezel_x0 + bezel_x1) * 0.5

    # ---- Stand pedestal (trapezoid) ----
    stand_pts = [
        (bezel_cx - STAND_TOP_W * 0.5, bezel_y0),
        (bezel_cx + STAND_TOP_W * 0.5, bezel_y0),
        (bezel_cx + STAND_BOT_W * 0.5, base_y + STAND_BASE_H),
        (bezel_cx - STAND_BOT_W * 0.5, base_y + STAND_BASE_H),
    ]
    _add_polygon(stand_pts, COLOR_BEZEL, COLOR_BEZEL, 2, ACTIVEMODEL)

    # ---- Stand base (flat rectangle) ----
    _add_shape(bezel_cx - STAND_BOT_W * 0.5, base_y,
               bezel_cx + STAND_BOT_W * 0.5, base_y + STAND_BASE_H,
               COLOR_BEZEL, COLOR_BEZEL, 2, ACTIVEMODEL)

    # ---- Outer bezel ----
    _add_shape(bezel_x0, bezel_y0, bezel_x1, bezel_y1,
               COLOR_BEZEL, COLOR_BEZEL, 2, ACTIVEMODEL)

    # ---- Screen background ----
    inner_margin = bezel_margin * 0.5
    _add_shape(bezel_x0 + inner_margin, bezel_y0 + inner_margin,
               bezel_x1 - inner_margin, bezel_y1 - inner_margin,
               COLOR_BLACK, COLOR_BLACK, 1, ACTIVEMODEL)

    # ---- Pixel grid ----
    # Pixels are stored top-row first (row 0 = top of screen) to match image
    # coordinate conventions used by OpenCV / PIL.
    pixel_origin_x = bezel_x0 + bezel_margin
    pixel_origin_y = bezel_y0 + bezel_margin  # bottom edge of bottom pixel row

    pixel_refs = []
    for row in range(pixel_rows):
        # row 0 is the top row visually; map to the highest Y coordinate
        py0 = pixel_origin_y + (pixel_rows - 1 - row) * (pixel_size + pixel_gap)
        py1 = py0 + pixel_size
        for col in range(pixel_cols):
            px0 = pixel_origin_x + col * (pixel_size + pixel_gap)
            px1 = px0 + pixel_size
            ref = _add_shape(px0, py0, px1, py1,
                             COLOR_BLACK, COLOR_BLACK, 0, ACTIVEMODEL)
            if ref is not None:
                pixel_refs.append((ref, dgnModel))

    expected = pixel_cols * pixel_rows
    print(f'PixelTV: created {len(pixel_refs)}/{expected} pixels '
          f'({pixel_cols}×{pixel_rows})')
    _refresh_view()
    return pixel_refs


# ---------------------------------------------------------------------------
# Frame rendering
# ---------------------------------------------------------------------------

def _build_color_cache(color_map, step=16):
    '''
    Pre-compute a lookup table mapping (r//step, g//step, b//step) → palette index.
    This reduces calls to FindClosestMatch during frame updates.

    step=16 produces 16³ = 4096 entries (a reasonable balance between accuracy
    and initialisation time).  Any colour not found in the cache is resolved
    lazily via FindClosestMatch and stored for future use.
    '''
    cache = {}
    for r8 in range(0, 256, step):
        for g8 in range(0, 256, step):
            for b8 in range(0, 256, step):
                key = (r8 // step, g8 // step, b8 // step)
                cache[key] = color_map.FindClosestMatch(IntColorDef(r8, g8, b8))
    return cache, step


def update_pixels_from_frame(pixel_refs, frame_rgb, color_map=None, _cache_holder=None):
    '''
    Update every pixel polygon to reflect a new video frame.

    Parameters
    ----------
    pixel_refs : list of (ElementRef, DgnModel)
        Returned by create_tv_screen().
    frame_rgb : numpy.ndarray, shape (rows, cols, 3), dtype uint8
        Frame in RGB order, already resampled to the pixel grid dimensions.
    color_map : DgnColorMap or None
        Active colour map.  If None it is fetched automatically.
    _cache_holder : list or None
        Pass a mutable list [cache_dict, step] to reuse the colour cache across
        calls (avoids re-building each frame).
    '''
    if not pixel_refs:
        return

    if color_map is None:
        dgnFile = ISessionMgr.GetActiveDgnFile()
        if dgnFile is None:
            return
        color_map = DgnColorMap.GetForFile(dgnFile)
        if color_map is None:
            return

    # Build or reuse colour lookup cache
    if _cache_holder is not None and len(_cache_holder) == 2:
        cache, step = _cache_holder
    else:
        cache, step = _build_color_cache(color_map)
        if _cache_holder is not None:
            _cache_holder.clear()
            _cache_holder.append(cache)
            _cache_holder.append(step)

    rows, cols = frame_rgb.shape[:2]

    for idx, (elem_ref, model) in enumerate(pixel_refs):
        row = idx // cols
        col = idx % cols
        if row >= rows or col >= cols:
            continue
        r, g, b = frame_rgb[row, col].astype(int)
        key = (r // step, g // step, b // step)
        color_idx = cache.get(key)
        if color_idx is None:
            color_idx = color_map.FindClosestMatch(IntColorDef(r, g, b))
            cache[key] = color_idx

        eeh = EditElementHandle(elem_ref, model)
        props = ElementPropertiesSetter()
        props.SetColor(color_idx)
        props.SetFillColor(color_idx)
        props.Apply(eeh)
        eeh.ReplaceInModel(elem_ref)

    _refresh_view()


# ---------------------------------------------------------------------------
# Test pattern (no external dependencies)
# ---------------------------------------------------------------------------

def show_test_pattern(pixel_refs, pattern='rainbow',
                      pixel_cols=PIXEL_COLS, pixel_rows=PIXEL_ROWS):
    '''
    Display a built-in test pattern on the pixel TV (no yt-dlp/cv2 required).

    Parameters
    ----------
    pixel_refs : list
        Returned by create_tv_screen().
    pattern : str
        'rainbow'  – horizontal hue sweep
        'gradient' – diagonal brightness gradient
        'smpte'    – vertical SMPTE-style colour bars
    pixel_cols, pixel_rows : int
        Grid dimensions (must match those used in create_tv_screen()).
    '''
    try:
        import numpy as np
    except ImportError:
        print('PixelTV: numpy is required for test patterns. '
              'Install with: pip install numpy')
        return

    frame = np.zeros((pixel_rows, pixel_cols, 3), dtype='uint8')

    if pattern == 'rainbow':
        for col in range(pixel_cols):
            hue = col / pixel_cols          # 0.0 – 1.0
            r, g, b = _hsv_to_rgb(hue, 1.0, 1.0)
            frame[:, col] = [r, g, b]

    elif pattern == 'gradient':
        for row in range(pixel_rows):
            for col in range(pixel_cols):
                v = int(255 * (row + col) / (pixel_rows + pixel_cols - 2))
                frame[row, col] = [v, v, v]

    elif pattern == 'smpte':
        # Seven-bar SMPTE colour bars: white, yellow, cyan, green,
        # magenta, red, blue
        bars = [
            (192, 192, 192),  # 75 % white
            (192, 192,   0),  # 75 % yellow
            (  0, 192, 192),  # 75 % cyan
            (  0, 192,   0),  # 75 % green
            (192,   0, 192),  # 75 % magenta
            (192,   0,   0),  # 75 % red
            (  0,   0, 192),  # 75 % blue
        ]
        bar_w = max(1, pixel_cols // len(bars))
        for i, color in enumerate(bars):
            start = i * bar_w
            end = start + bar_w if i < len(bars) - 1 else pixel_cols
            frame[:, start:end] = color

    else:
        print(f'PixelTV: unknown pattern "{pattern}". '
              'Use "rainbow", "gradient", or "smpte".')
        return

    dgnFile = ISessionMgr.GetActiveDgnFile()
    color_map = DgnColorMap.GetForFile(dgnFile) if dgnFile else None
    if color_map is None:
        print('PixelTV: cannot obtain DGN colour map')
        return

    print(f'PixelTV: displaying test pattern "{pattern}"')
    update_pixels_from_frame(pixel_refs, frame, color_map)


def _hsv_to_rgb(h, s, v):
    '''Convert HSV (all 0-1) to RGB (0-255 integers).'''
    if s == 0.0:
        val = int(v * 255)
        return val, val, val
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0: r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    else:        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


# ---------------------------------------------------------------------------
# YouTube streaming (requires yt-dlp, opencv-python, numpy)
# ---------------------------------------------------------------------------

def _get_youtube_stream_url(youtube_url):
    '''
    Use yt-dlp to resolve a YouTube URL to a direct video stream URL.
    Returns the URL string or None on failure.
    '''
    try:
        import yt_dlp
    except ImportError:
        print('PixelTV: yt-dlp not found. Install with: pip install yt-dlp')
        return None

    ydl_opts = {
        'format': 'bestvideo[height<=360][ext=mp4]/bestvideo[height<=360]/best[height<=360]',
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            # Prefer a direct URL on the top-level info dict; fall back to
            # the last available format.
            if 'url' in info:
                return info['url']
            formats = info.get('formats', [])
            if formats:
                return formats[-1]['url']
    except Exception as exc:
        print(f'PixelTV: yt-dlp error – {exc}')
    return None


# ---------------------------------------------------------------------------
# PyQt5 control window
# ---------------------------------------------------------------------------

class PixelTVPlayer:
    '''
    A minimal PyQt5 control panel that streams a YouTube video onto a pixel TV
    screen in MicroStation at a user-selectable frame rate.

    Usage
    -----
    tv = PixelTVScreen()               # build TV, open control panel
    # OR if you already have pixel_refs:
    player = PixelTVPlayer(pixel_refs)
    player.show()
    '''

    def __init__(self, pixel_refs,
                 pixel_cols=PIXEL_COLS, pixel_rows=PIXEL_ROWS):
        self.pixel_refs  = pixel_refs
        self.pixel_cols  = pixel_cols
        self.pixel_rows  = pixel_rows
        self._cap        = None      # cv2.VideoCapture
        self._cache      = []        # [color_cache_dict, step]
        self._color_map  = None
        self._is_playing = False
        self._frame_timer   = None
        self._mstn_timer    = None
        self._window        = None
        self._app           = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        try:
            from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget,
                                         QVBoxLayout, QHBoxLayout, QLabel,
                                         QLineEdit, QPushButton, QSlider,
                                         QComboBox)
            from PyQt5.QtCore    import QTimer, Qt
        except ImportError:
            print('PixelTV: PyQt5 not found – control panel unavailable. '
                  'Call stream_youtube() directly instead.')
            return

        self._app = QApplication.instance() or QApplication(sys.argv)

        win = QMainWindow()
        win.setWindowTitle('PixelTV Player')
        win.setWindowFlags(Qt.WindowStaysOnTopHint)
        win.setGeometry(50, 50, 420, 180)
        self._window = win

        central = QWidget()
        win.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # URL row
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel('YouTube URL:'))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText('https://www.youtube.com/watch?v=...')
        url_row.addWidget(self._url_edit)
        layout.addLayout(url_row)

        # Pattern row (offline demo)
        pat_row = QHBoxLayout()
        pat_row.addWidget(QLabel('Test pattern:'))
        self._pattern_combo = QComboBox()
        self._pattern_combo.addItems(['rainbow', 'gradient', 'smpte'])
        pat_row.addWidget(self._pattern_combo)
        self._show_pattern_btn = QPushButton('Show pattern')
        self._show_pattern_btn.clicked.connect(self._on_show_pattern)
        pat_row.addWidget(self._show_pattern_btn)
        layout.addLayout(pat_row)

        # FPS row
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel('FPS:'))
        self._fps_slider = QSlider(Qt.Horizontal)
        self._fps_slider.setRange(1, 10)
        self._fps_slider.setValue(2)
        self._fps_slider.setTickInterval(1)
        self._fps_slider.setTickPosition(QSlider.TicksBelow)
        fps_row.addWidget(self._fps_slider)
        self._fps_label = QLabel('2')
        self._fps_slider.valueChanged.connect(
            lambda v: self._fps_label.setText(str(v)))
        fps_row.addWidget(self._fps_label)
        layout.addLayout(fps_row)

        # Play/Stop row
        btn_row = QHBoxLayout()
        self._play_btn = QPushButton('▶  Play YouTube')
        self._play_btn.clicked.connect(self._on_play)
        self._stop_btn = QPushButton('■  Stop')
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._stop_btn)
        layout.addLayout(btn_row)

        # Status label
        self._status_label = QLabel('Ready')
        layout.addWidget(self._status_label)

        # Keep MicroStation's input loop alive while the Qt window is open
        self._mstn_timer = QTimer()
        self._mstn_timer.timeout.connect(lambda: PyCadInputQueue.PythonMainLoop())
        self._mstn_timer.start(0)

        win.show()

    def show(self):
        if self._app is not None:
            self._app.exec()

    # ------------------------------------------------------------------
    def _on_show_pattern(self):
        pattern = self._pattern_combo.currentText()
        self._status_label.setText(f'Showing pattern: {pattern}')
        show_test_pattern(self.pixel_refs, pattern,
                          self.pixel_cols, self.pixel_rows)
        self._status_label.setText(f'Pattern "{pattern}" displayed')

    def _on_play(self):
        url = self._url_edit.text().strip()
        if not url:
            self._status_label.setText('Please enter a YouTube URL')
            return
        self._status_label.setText('Resolving stream URL…')
        self._app.processEvents()

        stream_url = _get_youtube_stream_url(url)
        if stream_url is None:
            self._status_label.setText('Failed to get stream URL (see console)')
            return

        try:
            import cv2
        except ImportError:
            self._status_label.setText(
                'opencv-python not found – install with: pip install opencv-python')
            return

        self._cap = cv2.VideoCapture(stream_url)
        if not self._cap.isOpened():
            self._status_label.setText('Could not open video stream')
            self._cap = None
            return

        dgnFile = ISessionMgr.GetActiveDgnFile()
        if dgnFile:
            self._color_map = DgnColorMap.GetForFile(dgnFile)

        self._is_playing = True
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText('Streaming…')

        from PyQt5.QtCore import QTimer
        fps = max(1, self._fps_slider.value())
        self._frame_timer = QTimer()
        self._frame_timer.timeout.connect(self._next_frame)
        self._frame_timer.start(int(1000.0 / fps))

    def _on_stop(self):
        self._is_playing = False
        if self._frame_timer:
            self._frame_timer.stop()
            self._frame_timer = None
        if self._cap:
            self._cap.release()
            self._cap = None
        self._play_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText('Stopped')

    def _next_frame(self):
        if not self._is_playing or self._cap is None:
            return
        try:
            import cv2
            import numpy as np
        except ImportError:
            self._on_stop()
            return

        ret, frame_bgr = self._cap.read()
        if not ret:
            # End of stream / video – restart from beginning
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame_bgr = self._cap.read()
            if not ret:
                self._on_stop()
                return

        # Convert BGR → RGB and resize to pixel grid
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_small = cv2.resize(frame_rgb, (self.pixel_cols, self.pixel_rows),
                                 interpolation=cv2.INTER_AREA)

        update_pixels_from_frame(self.pixel_refs, frame_small,
                                 self._color_map, self._cache)


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

class PixelTVScreen:
    '''
    One-stop convenience class: builds a pixel TV screen and opens the
    PyQt5 control panel.

    Parameters
    ----------
    base_x, base_y : float
        Bottom-left origin of the TV in the active model's master units.
    pixel_cols, pixel_rows : int
        Grid dimensions.
    pixel_size, pixel_gap, bezel_margin : float
        Pixel geometry in master units.
    autoshow : bool
        If True (default), enter the Qt event loop immediately.
        Set to False to call .show() manually later.
    '''

    def __init__(self, base_x=0.0, base_y=0.0,
                 pixel_cols=PIXEL_COLS, pixel_rows=PIXEL_ROWS,
                 pixel_size=PIXEL_SIZE, pixel_gap=PIXEL_GAP,
                 bezel_margin=BEZEL_MARGIN,
                 autoshow=True):
        self.pixel_cols = pixel_cols
        self.pixel_rows = pixel_rows
        self.pixel_refs = create_tv_screen(
            base_x, base_y, pixel_cols, pixel_rows,
            pixel_size, pixel_gap, bezel_margin)
        if self.pixel_refs is None:
            print('PixelTV: screen creation failed')
            return
        self.player = PixelTVPlayer(self.pixel_refs, pixel_cols, pixel_rows)
        if autoshow:
            self.player.show()

    def show_pattern(self, pattern='rainbow'):
        '''Display a test pattern without entering the Qt event loop.'''
        show_test_pattern(self.pixel_refs, pattern,
                          self.pixel_cols, self.pixel_rows)

    def show(self):
        '''Enter the Qt event loop (blocks until the control panel is closed).'''
        if self.player:
            self.player.show()


# ---------------------------------------------------------------------------
# Direct execution: build a TV and display a rainbow test pattern
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print('PixelTV: building TV screen…')
    pixel_refs = create_tv_screen()
    if pixel_refs:
        show_test_pattern(pixel_refs, 'rainbow')
        print('PixelTV: done. '
              'To stream YouTube, create PixelTVScreen() from the console.')
