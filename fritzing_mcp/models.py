"""Data models for Fritzing Live MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class WindowInfo(BaseModel):
    window_id: str = Field(description="Unique window ID (e.g. '0x001205FA' or HWND integer)")
    hwnd: int
    pid: int
    title: str
    project_name: Optional[str] = None
    file_path: Optional[str] = None
    view: Literal["breadboard", "schematic", "pcb", "welcome", "unknown"] = "breadboard"
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    is_locked: bool = False
    locked_by_session: Optional[str] = None
    lease_expires_in_sec: Optional[float] = None


class LockEntry(BaseModel):
    window_id: str
    session_id: str
    pid: int
    acquired_at: float
    expires_at: float


class ConnectorInfo(BaseModel):
    connector_id: str
    name: str
    connector_type: str = "male"
    pin_number: Optional[str] = None
    description: Optional[str] = None


class PartMetadata(BaseModel):
    module_id: str
    title: str
    version: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    family: Optional[str] = None
    variant: Optional[str] = None
    properties: Dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    connectors: List[ConnectorInfo] = Field(default_factory=list)
    has_spice: bool = False


class WireInfo(BaseModel):
    wire_id: str
    from_instance: str
    from_connector: str
    to_instance: str
    to_connector: str
    color: str = "blue"
    view: str = "breadboard"


class PlacedPart(BaseModel):
    instance_id: str
    module_id: str
    title: str
    x: float
    y: float
    rotation: float = 0
    view: str = "breadboard"
    properties: Dict[str, str] = Field(default_factory=dict)


class CircuitManifest(BaseModel):
    project_id: str
    title: str
    file_path: Optional[str] = None
    parts: List[PlacedPart] = Field(default_factory=list)
    wires: List[WireInfo] = Field(default_factory=list)


class DiagnosticItem(BaseModel):
    category: str
    severity: Literal["CRITICAL_ERROR", "ERROR", "WARNING", "INFO"]
    message: str
    affected_parts: List[str] = Field(default_factory=list)
    affected_wires: List[str] = Field(default_factory=list)
    advice: Optional[str] = None


class ValidationReport(BaseModel):
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    diagnostics: List[DiagnosticItem] = Field(default_factory=list)
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0


class SimulationNodeVoltage(BaseModel):
    node_name: str
    voltage: float
    unit: str = "V"


class SimulationReport(BaseModel):
    status: Literal["SUCCESS", "CONVERGENCE_ERROR", "TIMEOUT", "NO_CIRCUIT"]
    analysis_type: str
    elapsed_ms: float
    node_voltages: List[SimulationNodeVoltage] = Field(default_factory=list)
    branch_currents: Dict[str, float] = Field(default_factory=dict)
    multimeter_readings: Dict[str, str] = Field(default_factory=dict)
    overloaded_parts: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    raw_output: Optional[str] = None
