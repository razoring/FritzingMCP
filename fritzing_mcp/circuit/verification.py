"""Multi-tier Electrical Rule Check (ERC) and Design Rule Check (DRC) engine."""

from __future__ import annotations

from typing import List, Optional, Set
from ..models import CircuitManifest, DiagnosticItem, ValidationReport


def _build_nets(manifest: CircuitManifest) -> List[Set[tuple[str, str]]]:
    """Union-Find algorithm to cluster connected (instance_id, connector_id) pairs into nets."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(item: tuple[str, str]) -> tuple[str, str]:
        if item not in parent:
            parent[item] = item
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for wire in manifest.wires:
        p1 = (wire.from_instance, wire.from_connector)
        p2 = (wire.to_instance, wire.to_connector)
        union(p1, p2)

    nets_map: dict[tuple[str, str], Set[tuple[str, str]]] = {}
    for node in parent:
        root = find(node)
        if root not in nets_map:
            nets_map[root] = set()
        nets_map[root].add(node)

    return list(nets_map.values())


def validate_circuit(
    manifest: CircuitManifest,
    checks: Optional[List[str]] = None
) -> ValidationReport:
    """Run ERC & DRC diagnostics on circuit graph."""
    diagnostics: List[DiagnosticItem] = []
    nets = _build_nets(manifest)

    # 1. VCC-GND Short Detection
    for net in nets:
        has_vcc = False
        has_gnd = False
        vcc_nodes = []
        gnd_nodes = []

        for inst, conn in net:
            conn_lower = conn.lower()
            if any(k in conn_lower for k in ["vcc", "5v", "3v3", "3.3v", "vin", "power"]):
                has_vcc = True
                vcc_nodes.append(f"{inst}.{conn}")
            if any(k in conn_lower for k in ["gnd", "ground"]):
                has_gnd = True
                gnd_nodes.append(f"{inst}.{conn}")

        if has_vcc and has_gnd:
            diagnostics.append(
                DiagnosticItem(
                    category="power_shorts",
                    severity="CRITICAL_ERROR",
                    message=f"Direct short between supply rail ({', '.join(vcc_nodes)}) and ground ({', '.join(gnd_nodes)})!",
                    affected_parts=[n.split(".")[0] for n in vcc_nodes + gnd_nodes],
                    advice="Remove direct shorting wire immediately before powering or simulating.",
                )
            )

    # 2. LED Missing Series Current-Limiting Resistor
    for part in manifest.parts:
        if "led" in part.module_id.lower() or "led" in part.title.lower():
            # Check if part is connected to a resistor
            led_inst = part.instance_id
            connected_resistor = False
            for wire in manifest.wires:
                other_inst = wire.to_instance if wire.from_instance == led_inst else (
                    wire.from_instance if wire.to_instance == led_inst else None
                )
                if other_inst:
                    other_part = next((p for p in manifest.parts if p.instance_id == other_inst), None)
                    if other_part and ("resistor" in other_part.module_id.lower() or "resistor" in other_part.title.lower()):
                        connected_resistor = True
                        break

            if not connected_resistor and len([w for w in manifest.wires if w.from_instance == led_inst or w.to_instance == led_inst]) >= 2:
                diagnostics.append(
                    DiagnosticItem(
                        category="missing_resistors",
                        severity="ERROR",
                        message=f"LED '{part.title}' ({led_inst}) has no series current-limiting resistor.",
                        affected_parts=[led_inst],
                        advice="Add a 220Ω - 1kΩ current-limiting resistor in series with the LED to prevent burnout.",
                    )
                )

    # 3. Orphaned / Unconnected Components
    wired_parts = set()
    for wire in manifest.wires:
        wired_parts.add(wire.from_instance)
        wired_parts.add(wire.to_instance)

    for part in manifest.parts:
        if part.instance_id not in wired_parts:
            diagnostics.append(
                DiagnosticItem(
                    category="floating_pins",
                    severity="INFO",
                    message=f"Component '{part.title}' ({part.instance_id}) is completely unconnected.",
                    affected_parts=[part.instance_id],
                    advice="Connect component pins or delete unused part.",
                )
            )

    # Calculate status counts
    crit_count = sum(1 for d in diagnostics if d.severity == "CRITICAL_ERROR")
    err_count = sum(1 for d in diagnostics if d.severity == "ERROR")
    warn_count = sum(1 for d in diagnostics if d.severity == "WARNING")

    if crit_count > 0 or err_count > 0:
        status = "FAIL"
    elif warn_count > 0:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    return ValidationReport(
        status=status,
        diagnostics=diagnostics,
        critical_count=crit_count,
        error_count=err_count,
        warning_count=warn_count,
    )
