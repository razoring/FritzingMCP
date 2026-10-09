"""Configuration and environment path discovery for Fritzing Live MCP."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Optional


def _find_fritzing_exe() -> Optional[Path]:
    override = os.environ.get("FRITZING_EXE")
    if override and Path(override).is_file():
        return Path(override)
    
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Fritzing" / "Fritzing.exe",
        Path("C:/Program Files/Fritzing/Fritzing.exe"),
        Path("C:/Program Files (x86)/Fritzing/Fritzing.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    
    which = shutil.which("Fritzing.exe") or shutil.which("fritzing")
    return Path(which) if which else None


def _find_arduino_cli() -> Optional[Path]:
    override = os.environ.get("ARDUINO_CLI_EXE")
    if override and Path(override).is_file():
        return Path(override)
    
    candidates = [
        Path("C:/Program Files/Arduino CLI/arduino-cli.exe"),
        Path("C:/Program Files (x86)/Arduino CLI/arduino-cli.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Arduino CLI" / "arduino-cli.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    
    which = shutil.which("arduino-cli.exe") or shutil.which("arduino-cli")
    return Path(which) if which else None


class Config:
    def __init__(self) -> None:
        self.fritzing_exe: Optional[Path] = _find_fritzing_exe()
        self.fritzing_dir: Optional[Path] = self.fritzing_exe.parent if self.fritzing_exe else None
        
        parts_override = os.environ.get("FRITZING_PARTS_DIR")
        if parts_override and Path(parts_override).is_dir():
            self.parts_dir: Optional[Path] = Path(parts_override)
        elif self.fritzing_dir and (self.fritzing_dir / "fritzing-parts").is_dir():
            self.parts_dir = self.fritzing_dir / "fritzing-parts"
        elif self.fritzing_dir and (self.fritzing_dir / "parts").is_dir():
            self.parts_dir = self.fritzing_dir / "parts"
        else:
            self.parts_dir = None
        
        self.arduino_cli_exe: Optional[Path] = _find_arduino_cli()
        
        app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        self.state_dir: Path = app_data / "FritzingMCP"
        self.projects_dir: Path = self.state_dir / "projects"
        self.renders_dir: Path = self.state_dir / "renders"
        self.locks_file: Path = self.state_dir / "session_locks.json"
        
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        
        self.default_testing_port: int = int(os.environ.get("FRITZING_TESTING_PORT", "17999"))
        self.lock_lease_timeout_sec: float = float(os.environ.get("FRITZING_LOCK_LEASE_SEC", "60.0"))


config = Config()
