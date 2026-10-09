"""Live bridge orchestrator managing window attachment, launching, and session routing."""

from __future__ import annotations

from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional
import uuid

from ..config import config
from ..models import WindowInfo
from ..windows.discovery import find_fritzing_windows, switch_view
from ..windows.sessions import session_manager
from .ftesting_client import FTestingClient


class LiveOrchestrator:
    def __init__(self) -> None:
        self.session_windows: Dict[str, str] = {} # session_id -> window_id
        self.ftesting_clients: Dict[str, FTestingClient] = {} # window_id -> client

    def get_bound_window(self, session_id: str) -> Optional[WindowInfo]:
        """Get WindowInfo currently bound to session_id, or None."""
        wid = self.session_windows.get(session_id)
        if not wid:
            return None
        windows = find_fritzing_windows()
        for w in windows:
            if w.window_id == wid:
                # Renew lease on access
                session_manager.renew_lock(wid, session_id)
                return w
        # If window no longer exists, unbind
        self.unbind(session_id)
        return None

    def bind_window(self, session_id: str, window_id: str, force: bool = False) -> WindowInfo:
        """Bind session to window and acquire lock."""
        windows = find_fritzing_windows()
        target = next((w for w in windows if w.window_id == window_id), None)
        if not target:
            raise ValueError(f"Fritzing window '{window_id}' not found.")

        ok = session_manager.acquire_lock(window_id, session_id, pid=target.pid, force=force)
        if not ok:
            lock_info = session_manager.get_lock_info(window_id)
            raise PermissionError(
                f"Window {window_id} ({target.title}) is locked by session '{lock_info['locked_by']}'."
            )

        self.session_windows[session_id] = window_id
        return target

    def unbind(self, session_id: str) -> None:
        """Release session lock and unbind."""
        wid = self.session_windows.pop(session_id, None)
        if wid:
            session_manager.release_lock(wid, session_id)

    def launch_fritzing(self, project_path: Optional[str] = None) -> WindowInfo:
        """Launch Fritzing with -ftesting enabled and return the new WindowInfo."""
        if not config.fritzing_exe or not config.fritzing_exe.is_file():
            raise FileNotFoundError("Fritzing executable not found on system.")

        args = [str(config.fritzing_exe), "-ftesting"]
        if project_path:
            args.append(str(Path(project_path).resolve()))

        # Spawn detached process
        proc = subprocess.Popen(
            args,
            cwd=str(config.fritzing_dir or Path.cwd()),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

        # Wait for window to appear
        for _ in range(40): # up to 8s
            time.sleep(0.2)
            windows = find_fritzing_windows()
            for w in windows:
                if w.pid == proc.pid:
                    return w

        # Fallback to any active window
        windows = find_fritzing_windows()
        if windows:
            return windows[-1]
        raise TimeoutError("Fritzing launched but window did not appear within 8s.")

    def create_project(self, session_id: str, title: Optional[str] = None, template: str = "empty") -> WindowInfo:
        """Create a new project, launch in a new Fritzing window, and bind session lock."""
        project_name = title or f"WTL-FZ-{time.strftime('%Y')}-{uuid.uuid4().hex[:4].upper()}"
        pdir = config.projects_dir / project_name
        pdir.mkdir(parents=True, exist_ok=True)

        fz_path = pdir / f"{project_name}.fz"
        if not fz_path.exists():
            # Create minimal valid Fritzing XML sketch
            xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<module fritzingVersion="1.0.8" moduleId="{project_name}">
    <title>{project_name}</title>
    <views>
        <breadboardView><instances></instances></breadboardView>
        <schematicView><instances></instances></schematicView>
        <pcbView><instances></instances></pcbView>
    </views>
</module>
"""
            fz_path.write_text(xml_content, encoding="utf-8")

        win = self.launch_fritzing(str(fz_path))
        self.bind_window(session_id, win.window_id, force=True)
        return win


orchestrator = LiveOrchestrator()
