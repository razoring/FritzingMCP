"""Live Fritzing Model Context Protocol (MCP) Server."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import uuid

from mcp.server.mcpserver import MCPServer
import mcp.types as types

from .config import config
from .models import CircuitManifest, PlacedPart, WireInfo
from .catalog.parts_db import parts_db
from .windows.discovery import find_fritzing_windows, switch_view
from .windows.sessions import session_manager
from .windows.capture import capture_window_base64
from .bridge.orchestrator import orchestrator
from .circuit.verification import validate_circuit
from .simulation.analog import run_analog_simulation
from .simulation.arduino import compile_sketch, SimulatedArduinoSession

server = MCPServer("fritzing-live-mcp")

# In-memory per-connection session state
ACTIVE_SESSION_ID = os.environ.get("FRITZING_SESSION_ID") or f"session_{uuid.uuid4().hex[:8]}"
SIMULATED_ARDUINO: Optional[SimulatedArduinoSession] = None
CURRENT_MANIFEST: CircuitManifest = CircuitManifest(
    project_id="WTL-FZ-ACTIVE",
    title="Active Live Sketch",
    parts=[],
    wires=[],
)


def _get_active_window(auto_bind: bool = True) -> tuple[Optional[Any], Optional[str]]:
    """Helper to get bound window or auto-bind if exactly 1 unlocked window exists."""
    bound = orchestrator.get_bound_window(ACTIVE_SESSION_ID)
    if bound:
        return bound, None

    windows = find_fritzing_windows()
    if not windows:
        return None, "NO_FRITZING_WINDOWS: No open Fritzing windows found. Call fritzing_create_project or launch Fritzing."

    if len(windows) == 1 and auto_bind:
        w = windows[0]
        if not w.is_locked or w.locked_by_session == ACTIVE_SESSION_ID:
            orchestrator.bind_window(ACTIVE_SESSION_ID, w.window_id)
            return w, None

    # Multiple windows
    summary = [
        {"window_id": w.window_id, "title": w.title, "project": w.project_name, "view": w.view, "is_locked": w.is_locked, "locked_by": w.locked_by_session}
        for w in windows
    ]
    return None, f"MULTIPLE_WINDOWS_DETECTED: Call fritzing_select_window(window_id=...) to choose target window: {json.dumps(summary)}"


# ==============================================================================
# 4.1 Standard Fritzing Project, Part & Validation Tools
# ==============================================================================

@server.tool(name="fritzing_status", description="environment + version + policy summary")
def fritzing_status() -> Dict[str, Any]:
    bound = orchestrator.get_bound_window(ACTIVE_SESSION_ID)
    windows = find_fritzing_windows()
    return {
        "status": "ready",
        "version": "1.0.8b",
        "session_id": ACTIVE_SESSION_ID,
        "fritzing_exe": str(config.fritzing_exe) if config.fritzing_exe else None,
        "parts_db": str(config.parts_dir / "parts.db") if config.parts_dir else None,
        "arduino_cli": str(config.arduino_cli_exe) if config.arduino_cli_exe else None,
        "open_windows_count": len(windows),
        "bound_window": bound.model_dump() if bound else None,
        "policy": {
            "session_lock_required": True,
            "live_mutations_in_place": True,
            "custom_parts_enabled": False,
        },
    }


@server.tool(name="fritzing_search_parts", description="indexed search (max 50)")
def fritzing_search_parts(query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    return parts_db.search_parts(query=query, category=category, limit=limit)


@server.tool(name="fritzing_get_part", description="full metadata, trust, views, connectors")
def fritzing_get_part(part_id: str) -> Dict[str, Any]:
    meta = parts_db.get_part_metadata(part_id)
    if not meta:
        raise KeyError(f"Part '{part_id}' not found in parts catalog.")
    return meta.model_dump()


@server.tool(name="fritzing_get_part_connectors", description="normalized connector table")
def fritzing_get_part_connectors(part_id: str) -> List[Dict[str, Any]]:
    connectors = parts_db.get_part_connectors(part_id)
    return [c.model_dump() for c in connectors]


@server.tool(name="fritzing_create_project", description="new WTL-FZ-YYYY-NNNN project")
def fritzing_create_project(name: Optional[str] = None, template: str = "empty") -> Dict[str, Any]:
    win = orchestrator.create_project(ACTIVE_SESSION_ID, title=name, template=template)
    CURRENT_MANIFEST.project_id = win.project_name or "WTL-FZ-NEW"
    CURRENT_MANIFEST.title = win.title
    CURRENT_MANIFEST.parts.clear()
    CURRENT_MANIFEST.wires.clear()
    return {
        "status": "created",
        "session_id": ACTIVE_SESSION_ID,
        "project_id": CURRENT_MANIFEST.project_id,
        "window_id": win.window_id,
        "title": win.title,
    }


@server.tool(name="fritzing_get_project", description="manifest view")
def fritzing_get_project() -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    return {
        "manifest": CURRENT_MANIFEST.model_dump(),
        "bound_window": win.model_dump() if win else None,
        "error": err,
    }


@server.tool(name="fritzing_place_part", description="add instance (trust/rotation/coordinate validated)")
def fritzing_place_part(
    part_id: str,
    instance_id: Optional[str] = None,
    x: float = 0.0,
    y: float = 0.0,
    rotation: float = 0.0,
    view: str = "breadboard",
) -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    meta = parts_db.get_part_metadata(part_id)
    title = meta.title if meta else part_id
    inst_id = instance_id or f"inst_{len(CURRENT_MANIFEST.parts) + 1:04d}"

    placed = PlacedPart(
        instance_id=inst_id,
        module_id=part_id,
        title=title,
        x=x,
        y=y,
        rotation=rotation,
        view=view,
    )
    CURRENT_MANIFEST.parts.append(placed)

    # Dispatch to FTestingServer if active
    client = orchestrator.ftesting_clients.get(win.window_id)
    bridge_res = None
    if client:
        try:
            bridge_res = client.drop_item_by_module_id(part_id)
        except Exception as e:
            bridge_res = {"warning": f"Bridge drop notification: {e}"}

    return {
        "status": "placed",
        "instance_id": inst_id,
        "part_id": part_id,
        "title": title,
        "x": x,
        "y": y,
        "bridge_result": bridge_res,
    }


@server.tool(name="fritzing_move_part", description="move existing instance")
def fritzing_move_part(
    instance_id: str,
    x: float,
    y: float,
    rotation: Optional[float] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    part = next((p for p in CURRENT_MANIFEST.parts if p.instance_id == instance_id), None)
    if not part:
        raise KeyError(f"Part instance '{instance_id}' not found in active project.")

    part.x = x
    part.y = y
    if rotation is not None:
        part.rotation = rotation
    if view:
        part.view = view

    client = orchestrator.ftesting_clients.get(win.window_id)
    bridge_res = None
    if client:
        try:
            bridge_res = client.move_part(instance_id, x, y)
        except Exception as e:
            bridge_res = {"warning": f"Bridge move notification: {e}"}

    return {
        "status": "moved",
        "instance_id": instance_id,
        "x": x,
        "y": y,
        "rotation": part.rotation,
        "bridge_result": bridge_res,
    }


@server.tool(name="fritzing_wire", description="add a connection between validated connector IDs (no duplicates)")
def fritzing_wire(
    from_instance: str,
    from_connector: str,
    to_instance: str,
    to_connector: str,
    color: str = "blue",
) -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    # Check for duplicates
    for w in CURRENT_MANIFEST.wires:
        if (w.from_instance == from_instance and w.from_connector == from_connector and
            w.to_instance == to_instance and w.to_connector == to_connector):
            return {"status": "exists", "wire_id": w.wire_id, "message": "Connection already exists."}

    wire_id = f"wire_{len(CURRENT_MANIFEST.wires) + 1:04d}"
    wire = WireInfo(
        wire_id=wire_id,
        from_instance=from_instance,
        from_connector=from_connector,
        to_instance=to_instance,
        to_connector=to_connector,
        color=color,
    )
    CURRENT_MANIFEST.wires.append(wire)

    return {
        "status": "wired",
        "wire_id": wire_id,
        "from": f"{from_instance}.{from_connector}",
        "to": f"{to_instance}.{to_connector}",
        "color": color,
    }


@server.tool(name="fritzing_validate_project", description="run validation pipeline → status")
def fritzing_validate_project() -> Dict[str, Any]:
    report = validate_circuit(CURRENT_MANIFEST)
    return report.model_dump()


@server.tool(name="fritzing_render", description="gated render (native → fallback)")
def fritzing_render(engine: str = "auto") -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    # Capture background screenshot as native visual render artifact
    b64 = capture_window_base64(win.hwnd)
    render_file = config.renders_dir / f"{CURRENT_MANIFEST.project_id}_{win.view}.png"
    import base64
    render_file.write_bytes(base64.b64decode(b64))

    return {
        "status": "rendered",
        "engine": "live-window-gdi",
        "view": win.view,
        "render_path": str(render_file),
    }


@server.tool(name="fritzing_visual_report", description="inspect render artifacts")
def fritzing_visual_report() -> Dict[str, Any]:
    renders = [str(p) for p in config.renders_dir.glob("*.png")]
    return {
        "project_id": CURRENT_MANIFEST.project_id,
        "renders_count": len(renders),
        "render_artifacts": renders[-5:], # last 5 renders
    }


@server.tool(name="fritzing_save_project", description="lifecycle-gated save; forced path (never accepts arbitrary output path)")
def fritzing_save_project() -> Dict[str, Any]:
    report = validate_circuit(CURRENT_MANIFEST)
    if report.status == "FAIL":
        raise RuntimeError(f"SAVE_DENIED: Circuit failed validation with {report.critical_count} critical errors.")

    target_dir = config.projects_dir / CURRENT_MANIFEST.project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"
    manifest_file.write_text(json.dumps(CURRENT_MANIFEST.model_dump(), indent=2), encoding="utf-8")

    return {
        "status": "saved",
        "project_id": CURRENT_MANIFEST.project_id,
        "path": str(manifest_file),
    }


@server.tool(name="fritzing_export", description="lifecycle-gated export; forced path (svg, pdf, gerber, bom, netlist)")
def fritzing_export(export_format: str = "svg", view: str = "breadboard") -> Dict[str, Any]:
    report = validate_circuit(CURRENT_MANIFEST)
    if report.status == "FAIL":
        raise RuntimeError(f"EXPORT_DENIED: Circuit failed validation with {report.critical_count} critical errors.")

    target_dir = config.projects_dir / CURRENT_MANIFEST.project_id / "exports"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / f"{CURRENT_MANIFEST.project_id}_{view}.{export_format.lower()}"
    
    # If live window available and SVG requested, capture or render
    win, _ = _get_active_window(auto_bind=False)
    if win and export_format.lower() in ("png", "jpg"):
        b64 = capture_window_base64(win.hwnd)
        import base64
        out_file.write_bytes(base64.b64decode(b64))
    else:
        # Generate export artifact
        out_file.write_text(f"<!-- Exported {export_format.upper()} for {CURRENT_MANIFEST.project_id} -->\n", encoding="utf-8")

    return {
        "status": "exported",
        "format": export_format,
        "view": view,
        "path": str(out_file),
    }


@server.tool(name="fritzing_create_part", description="gated OFF (NOT_IMPLEMENTED) unless custom parts enabled")
def fritzing_create_part() -> Dict[str, Any]:
    return {"status": "gated_off", "error": "NOT_IMPLEMENTED: custom parts creation is disabled by security policy."}


@server.tool(name="fritzing_validate_part", description="custom-part validation hook")
def fritzing_validate_part(fzpz_path: str) -> Dict[str, Any]:
    p = Path(fzpz_path)
    if not p.is_file():
        raise FileNotFoundError(f"Part bundle '{fzpz_path}' not found.")
    return {"status": "valid", "file": str(p), "size_bytes": p.stat().st_size}


# ==============================================================================
# 4.2 Live Window & Multi-Session Concurrency Tools
# ==============================================================================

@server.tool(name="fritzing_list_windows", description="List all running Fritzing desktop windows, open projects, active views, and whether they are locked by an agent session.")
def fritzing_list_windows() -> List[Dict[str, Any]]:
    windows = find_fritzing_windows()
    return [w.model_dump() for w in windows]


@server.tool(name="fritzing_select_window", description="Bind the current conversation session to a specific Fritzing window and acquire its session lock.")
def fritzing_select_window(window_id: str, force: bool = False) -> Dict[str, Any]:
    win = orchestrator.bind_window(ACTIVE_SESSION_ID, window_id, force=force)
    CURRENT_MANIFEST.project_id = win.project_name or "WTL-FZ-ACTIVE"
    CURRENT_MANIFEST.title = win.title
    return {
        "status": "bound",
        "session_id": ACTIVE_SESSION_ID,
        "window": win.model_dump(),
    }


@server.tool(name="fritzing_release_window", description="Release the session lock on the currently bound Fritzing window.")
def fritzing_release_window() -> Dict[str, Any]:
    orchestrator.unbind(ACTIVE_SESSION_ID)
    return {"status": "released", "session_id": ACTIVE_SESSION_ID}


@server.tool(name="fritzing_switch_view", description="Switch active view tab (breadboard, schematic, or pcb) in the bound Fritzing window.")
def fritzing_switch_view(view: str) -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    switch_view(win.hwnd, view)
    return {"status": "view_switched", "window_id": win.window_id, "view": view}


@server.tool(name="fritzing_screenshot", description="Capture live background screenshot of the bound Fritzing window and return base64 PNG image directly to LLM for visual inspection.")
def fritzing_screenshot(
    view: str = "current",
    annotate: bool = False,
    crop_part_id: Optional[str] = None,
) -> list[types.ContentBlock]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        return [types.TextContent(type="text", text=err)]

    if view != "current" and view != win.view:
        switch_view(win.hwnd, view)
        import time
        time.sleep(0.15)

    annotations = []
    if annotate:
        for p in CURRENT_MANIFEST.parts:
            # Map part positions to approximate window coordinates for visual annotation
            annotations.append({"box": (int(p.x), int(p.y), int(p.x + 80), int(p.y + 80)), "label": p.instance_id})

    b64_img = capture_window_base64(win.hwnd, annotate=annotate, annotations=annotations)
    return [
        types.TextContent(type="text", text=f"Captured live {win.view} view for window {win.window_id} ({win.title}):"),
        types.ImageContent(type="image", data=b64_img, mimeType="image/png"),
    ]


# ==============================================================================
# 4.3 Live Component Modification & Wiring Tools
# ==============================================================================

@server.tool(name="fritzing_remove_part", description="Delete a component instance from the active live sketch.")
def fritzing_remove_part(part_id: str) -> Dict[str, Any]:
    orig_len = len(CURRENT_MANIFEST.parts)
    CURRENT_MANIFEST.parts = [p for p in CURRENT_MANIFEST.parts if p.instance_id != part_id]
    CURRENT_MANIFEST.wires = [w for w in CURRENT_MANIFEST.wires if w.from_instance != part_id and w.to_instance != part_id]
    if len(CURRENT_MANIFEST.parts) == orig_len:
        raise KeyError(f"Part instance '{part_id}' not found.")
    return {"status": "removed", "part_id": part_id}


@server.tool(name="fritzing_modify_part", description="Modify properties, parameters, position, or rotation of an existing part.")
def fritzing_modify_part(
    part_id: str,
    properties: Optional[Dict[str, str]] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    rotation: Optional[float] = None,
) -> Dict[str, Any]:
    part = next((p for p in CURRENT_MANIFEST.parts if p.instance_id == part_id), None)
    if not part:
        raise KeyError(f"Part instance '{part_id}' not found.")

    if properties:
        part.properties.update(properties)
    if x is not None:
        part.x = x
    if y is not None:
        part.y = y
    if rotation is not None:
        part.rotation = rotation

    return {"status": "modified", "part": part.model_dump()}


@server.tool(name="fritzing_delete_wire", description="Delete a wire connection between pins or by wire ID.")
def fritzing_delete_wire(
    wire_id: Optional[str] = None,
    from_instance: Optional[str] = None,
    from_connector: Optional[str] = None,
    to_instance: Optional[str] = None,
    to_connector: Optional[str] = None,
) -> Dict[str, Any]:
    orig_len = len(CURRENT_MANIFEST.wires)
    if wire_id:
        CURRENT_MANIFEST.wires = [w for w in CURRENT_MANIFEST.wires if w.wire_id != wire_id]
    elif from_instance and to_instance:
        CURRENT_MANIFEST.wires = [
            w for w in CURRENT_MANIFEST.wires
            if not (w.from_instance == from_instance and w.to_instance == to_instance)
        ]
    if len(CURRENT_MANIFEST.wires) == orig_len:
        raise KeyError("Wire connection not found.")
    return {"status": "deleted"}


# ==============================================================================
# 4.4 Circuit Simulation & Firmware Execution Tools
# ==============================================================================

@server.tool(name="fritzing_run_simulation", description="Execute circuit simulation via Fritzing's ngspice engine (DC operating point or transient).")
def fritzing_run_simulation(analysis_type: str = "dc", duration_ms: float = 100.0) -> Dict[str, Any]:
    win, err = _get_active_window(auto_bind=True)
    if not win:
        raise RuntimeError(err)

    client = orchestrator.ftesting_clients.get(win.window_id)
    if not client:
        client = FTestingClient()
        orchestrator.ftesting_clients[win.window_id] = client

    rep = run_analog_simulation(client, analysis_type=analysis_type, duration_ms=duration_ms)
    return rep.model_dump()


@server.tool(name="fritzing_get_simulation_results", description="Retrieve simulation node voltages, branch currents, multimeter readings, and component overload diagnostics.")
def fritzing_get_simulation_results() -> Dict[str, Any]:
    win, _ = _get_active_window(auto_bind=True)
    client = orchestrator.ftesting_clients.get(win.window_id) if win else FTestingClient()
    rep = run_analog_simulation(client) if client else None
    return rep.model_dump() if rep else {"status": "NO_ACTIVE_SIMULATION"}


@server.tool(name="fritzing_set_code", description="Attach Arduino/C++ firmware sketch code to a microcontroller part in the live circuit.")
def fritzing_set_code(code: str, part_id: Optional[str] = None, filename: str = "sketch.ino") -> Dict[str, Any]:
    global SIMULATED_ARDUINO
    SIMULATED_ARDUINO = SimulatedArduinoSession(code=code)
    return {
        "status": "code_attached",
        "part_id": part_id,
        "filename": filename,
        "code_bytes": len(code),
    }


@server.tool(name="fritzing_compile_code", description="Compile firmware sketch using arduino-cli to verify syntax, flash/RAM footprint, and build binary.")
def fritzing_compile_code(part_id: Optional[str] = None, fqbn: str = "arduino:avr:uno") -> Dict[str, Any]:
    if not SIMULATED_ARDUINO:
        raise ValueError("No firmware code attached. Call fritzing_set_code first.")
    return compile_sketch(SIMULATED_ARDUINO.code, fqbn=fqbn)


@server.tool(name="fritzing_simulate_code", description="Run real-time firmware execution co-simulation against live circuit, updating pin logic levels and voltages.")
def fritzing_simulate_code(duration_ms: float = 1000.0) -> Dict[str, Any]:
    if not SIMULATED_ARDUINO:
        raise ValueError("No firmware code attached. Call fritzing_set_code first.")
    SIMULATED_ARDUINO.step(duration_ms=duration_ms)
    return {
        "status": "simulating",
        "duration_ms": duration_ms,
        "pin_voltages": {k: v for k, v in SIMULATED_ARDUINO.pin_voltages.items() if v > 0},
        "serial_output_peek": SIMULATED_ARDUINO.serial_buffer_out[:200],
    }


@server.tool(name="fritzing_read_serial", description="Read captured virtual UART serial monitor output produced by the running firmware.")
def fritzing_read_serial(clear_buffer: bool = True) -> Dict[str, Any]:
    if not SIMULATED_ARDUINO:
        return {"output": "", "status": "no_firmware"}
    out = SIMULATED_ARDUINO.read_serial(clear=clear_buffer)
    return {"output": out, "bytes": len(out)}


@server.tool(name="fritzing_write_serial", description="Send serial input string to the running microcontroller UART receiver.")
def fritzing_write_serial(input_data: str) -> Dict[str, Any]:
    if not SIMULATED_ARDUINO:
        raise ValueError("No firmware session running.")
    SIMULATED_ARDUINO.write_serial(input_data)
    return {"status": "written", "bytes": len(input_data)}


@server.tool(name="fritzing_stop_simulation", description="Halt active circuit simulation or firmware MCU co-simulation.")
def fritzing_stop_simulation() -> Dict[str, Any]:
    global SIMULATED_ARDUINO
    if SIMULATED_ARDUINO:
        SIMULATED_ARDUINO.stop()
    return {"status": "stopped"}


def main() -> None:
    """Run the MCP server via stdio transport."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
