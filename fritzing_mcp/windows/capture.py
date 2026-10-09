"""Background window screenshot capture and multimodal base64 encoding."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from .discovery import default_desktop_context

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def capture_window_image(hwnd: int) -> Image.Image:
    """Capture pixel-perfect screenshot of Fritzing window in background without stealing focus."""
    with default_desktop_context():
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        if w <= 0 or h <= 0:
            raise RuntimeError(f"Invalid window dimensions: {w}x{h}")

        hdc_win = user32.GetWindowDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        gdi32.SelectObject(hdc_mem, hbmp)

        # PrintWindow captures both visible and occluded areas of the window
        user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        buf = (ctypes.c_ubyte * (w * h * 4))()
        gdi32.GetDIBits(hdc_mem, hbmp, 0, h, ctypes.byref(buf), ctypes.byref(bmi), 0)

        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)

    img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
    return img.convert("RGB")


def capture_window_base64(
    hwnd: int,
    annotate: bool = False,
    crop_rect: Optional[Tuple[int, int, int, int]] = None,
    annotations: Optional[list] = None
) -> str:
    """Capture window and return base64 PNG data URL string."""
    img = capture_window_image(hwnd)

    if crop_rect:
        left, top, right, bottom = crop_rect
        left = max(0, min(left, img.width - 1))
        top = max(0, min(top, img.height - 1))
        right = max(left + 1, min(right, img.width))
        bottom = max(top + 1, min(bottom, img.height))
        img = img.crop((left, top, right, bottom))

    if annotate and annotations:
        draw = ImageDraw.Draw(img)
        for ann in annotations:
            # Draw bounding box and label
            box = ann.get("box")
            label = ann.get("label", "")
            if box:
                draw.rectangle(box, outline="lime", width=2)
                draw.text((box[0] + 4, box[1] + 4), label, fill="yellow")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    raw_bytes = buffer.getvalue()
    return base64.b64encode(raw_bytes).decode("ascii")
