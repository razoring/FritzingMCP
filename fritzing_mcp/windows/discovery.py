"""Win32 Fritzing window discovery and title parsing."""

from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Iterator, List, Optional

from ..models import WindowInfo
from .sessions import session_manager

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

DESKTOP_ALL = 0x01FF


@contextlib.contextmanager
def default_desktop_context() -> Iterator[int | None]:
    """Ensure calling thread has access to the interactive desktop (WinSta0\\default)."""
    current_tid = kernel32.GetCurrentThreadId()
    orig_desk = user32.GetThreadDesktop(current_tid)
    target_desk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
    if target_desk:
        user32.SetThreadDesktop(target_desk)
    try:
        yield target_desk
    finally:
        if orig_desk and orig_desk != target_desk:
            user32.SetThreadDesktop(orig_desk)
        if target_desk:
            user32.CloseDesktop(target_desk)


def _parse_view_from_title(title: str) -> str:
    title_lower = title.lower()
    if "breadboard view" in title_lower:
        return "breadboard"
    if "schematic view" in title_lower:
        return "schematic"
    if "pcb view" in title_lower:
        return "pcb"
    if "welcome" in title_lower:
        return "welcome"
    return "breadboard"


def _parse_file_from_title(title: str) -> Optional[str]:
    parts = [p.strip() for p in title.split(" - ")]
    if len(parts) >= 2 and "fritzing" in parts[1].lower():
        return parts[0]
    if len(parts) >= 3 and "fritzing" in parts[2].lower():
        return parts[0]
    return None


def find_fritzing_windows() -> List[WindowInfo]:
    """Find all running, visible top-level Fritzing windows on interactive desktop."""
    windows: List[WindowInfo] = []

    with default_desktop_context() as hdesk:
        if not hdesk:
            return windows

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            hproc = kernel32.OpenProcess(0x1000, False, pid.value)
            if not hproc:
                return True

            namebuf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            is_fritzing = False
            if kernel32.QueryFullProcessImageNameW(hproc, 0, namebuf, ctypes.byref(size)):
                if "fritzing.exe" in namebuf.value.lower():
                    is_fritzing = True
            kernel32.CloseHandle(hproc)

            if is_fritzing:
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()

                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top

                # Ignore invisible utility or splash windows
                if w > 200 and h > 200:
                    wid = f"0x{hwnd:08X}"
                    lock_info = session_manager.get_lock_info(wid)
                    
                    file_path = _parse_file_from_title(title)
                    project_name = Path(file_path).name if file_path else (title if title else "Untitled")
                    view = _parse_view_from_title(title)
                    
                    windows.append(
                        WindowInfo(
                            window_id=wid,
                            hwnd=hwnd,
                            pid=pid.value,
                            title=title,
                            project_name=project_name,
                            file_path=file_path,
                            view=view,
                            rect=(rect.left, rect.top, w, h),
                            is_locked=lock_info["is_locked"],
                            locked_by_session=lock_info["locked_by"],
                            lease_expires_in_sec=lock_info["lease_expires_in_sec"],
                        )
                    )
            return True

        user32.EnumDesktopWindows(hdesk, WNDENUMPROC(enum_cb), 0)

    return windows


def switch_view(hwnd: int, view: str) -> bool:
    """Switch active view tab on Fritzing window purely in background without touching cursor."""
    view_map = {
        "welcome": 0x31,    # Ctrl+1
        "breadboard": 0x32, # Ctrl+2
        "schematic": 0x33,  # Ctrl+3
        "pcb": 0x34,        # Ctrl+4
    }
    view_key = view.lower().strip()
    if view_key not in view_map:
        raise ValueError(f"Invalid view '{view}'. Choose from: {list(view_map.keys())}")

    vk_code = view_map[view_key]
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    VK_CONTROL = 0x11

    with default_desktop_context():
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0x001D0001)
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, 0x00020001)
        user32.PostMessageW(hwnd, WM_KEYUP, vk_code, 0xC0020001)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_CONTROL, 0xC01D0001)
    return True
