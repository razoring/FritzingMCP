"""Arduino CLI compilation and extensible firmware MCU co-simulation engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Dict, List, Optional

from ..config import config


def compile_sketch(
    code: str,
    fqbn: str = "arduino:avr:uno",
    build_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compile Arduino sketch code using local arduino-cli binary."""
    if not config.arduino_cli_exe or not config.arduino_cli_exe.is_file():
        raise FileNotFoundError("arduino-cli executable not found on system.")

    work_dir = build_dir or Path(tempfile.mkdtemp(prefix="arduino_sketch_"))
    sketch_dir = work_dir / "sketch"
    sketch_dir.mkdir(parents=True, exist_ok=True)
    sketch_file = sketch_dir / "sketch.ino"
    sketch_file.write_text(code, encoding="utf-8")

    cmd = [
        str(config.arduino_cli_exe),
        "compile",
        "--fqbn",
        fqbn,
        str(sketch_dir),
        "--output-dir",
        str(work_dir / "build"),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    success = (proc.returncode == 0)

    # Parse flash and RAM footprint
    flash_bytes = None
    ram_bytes = None
    if success:
        m_flash = re.search(r"Sketch uses (\d+) bytes", proc.stdout)
        if m_flash:
            flash_bytes = int(m_flash.group(1))
        m_ram = re.search(r"Global variables use (\d+) bytes", proc.stdout)
        if m_ram:
            ram_bytes = int(m_ram.group(1))

    return {
        "success": success,
        "fqbn": fqbn,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "flash_bytes": flash_bytes,
        "ram_bytes": ram_bytes,
        "build_dir": str(work_dir / "build"),
    }


class McuEmulatorDriver(ABC):
    """Abstract base class for microcontroller emulation drivers."""

    @abstractmethod
    def load_firmware(self, binary_path: Path) -> None: ...

    @abstractmethod
    def step_cycles(self, cycles: int) -> None: ...

    @abstractmethod
    def get_pin_voltage(self, pin_name: str) -> float: ...

    @abstractmethod
    def set_pin_voltage(self, pin_name: str, voltage: float) -> None: ...

    @abstractmethod
    def read_serial_buffer(self) -> str: ...

    @abstractmethod
    def write_serial_buffer(self, data: str) -> None: ...


class SimulatedArduinoSession:
    """Lightweight cycle-accurate state machine simulator for Arduino logic & virtual UART."""

    def __init__(self, code: str, fqbn: str = "arduino:avr:uno") -> None:
        self.code = code
        self.fqbn = fqbn
        self.is_running = False
        self.serial_buffer_out: str = ""
        self.serial_buffer_in: str = ""
        self.pin_voltages: Dict[str, float] = {}
        self.pin_modes: Dict[str, str] = {} # OUTPUT or INPUT
        self._init_pins()

    def _init_pins(self) -> None:
        # Standard digital and analog pins
        for i in range(14):
            self.pin_voltages[f"D{i}"] = 0.0
            self.pin_voltages[f"pin{i}"] = 0.0
            self.pin_modes[f"D{i}"] = "INPUT"
        for i in range(6):
            self.pin_voltages[f"A{i}"] = 0.0
            self.pin_modes[f"A{i}"] = "INPUT"
        self.pin_voltages["VCC"] = 5.0
        self.pin_voltages["GND"] = 0.0

    def step(self, duration_ms: float = 1000.0) -> None:
        """Step execution time budget and interpret basic pin states & serial prints."""
        self.is_running = True
        
        # Parse basic Serial.print strings from setup / loop
        for match in re.finditer(r'Serial\.print(?:ln)?\s*\(\s*"([^"]+)"\s*\)', self.code):
            self.serial_buffer_out += match.group(1) + "\n"

        # Parse basic digitalWrite(pin, HIGH/LOW)
        for match in re.finditer(r"digitalWrite\s*\(\s*(\d+|[A-Z0-9_]+)\s*,\s*(HIGH|LOW)\s*\)", self.code):
            pin = match.group(1)
            state = match.group(2)
            pin_key = f"D{pin}" if pin.isdigit() else pin
            self.pin_voltages[pin_key] = 5.0 if state == "HIGH" else 0.0
            self.pin_voltages[f"pin{pin}"] = 5.0 if state == "HIGH" else 0.0

    def read_serial(self, clear: bool = True) -> str:
        out = self.serial_buffer_out
        if clear:
            self.serial_buffer_out = ""
        return out

    def write_serial(self, data: str) -> None:
        self.serial_buffer_in += data

    def stop(self) -> None:
        self.is_running = False
