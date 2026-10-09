"""Circuit project manifest handling and XML synchronization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

from ..models import CircuitManifest, PlacedPart, WireInfo


def parse_fz_file(fz_path: Path) -> CircuitManifest:
    """Parse a .fz Fritzing XML file into a CircuitManifest."""
    tree = ET.parse(fz_path)
    root = tree.getroot()

    project_id = root.get("moduleId", fz_path.stem)
    title_el = root.find("title")
    title = title_el.text if title_el is not None and title_el.text else project_id

    parts: List[PlacedPart] = []
    wires: List[WireInfo] = []

    # Parse instances from views
    inst_elements = root.findall(".//instances/instance")
    seen_instances = set()

    for inst in inst_elements:
        inst_id = inst.get("instanceId") or inst.get("moduleId")
        if not inst_id or inst_id in seen_instances:
            continue
        seen_instances.add(inst_id)

        mod_id = inst.get("moduleId", "")
        title_val = inst.findtext("title") or inst_id
        
        # Position from breadboardView or schematicView
        x, y = 0.0, 0.0
        geom = inst.find(".//geometry")
        if geom is not None:
            x = float(geom.get("x", 0.0))
            y = float(geom.get("y", 0.0))

        parts.append(
            PlacedPart(
                instance_id=inst_id,
                module_id=mod_id,
                title=title_val,
                x=x,
                y=y,
                view="breadboard",
            )
        )

    # Parse wires from connections
    wire_id_idx = 1
    for conn in root.findall(".//connections/connection"):
        from_node = conn.find("from")
        to_node = conn.find("to")
        if from_node is not None and to_node is not None:
            wires.append(
                WireInfo(
                    wire_id=f"wire_{wire_id_idx:04d}",
                    from_instance=from_node.get("instanceId", ""),
                    from_connector=from_node.get("connectorId", ""),
                    to_instance=to_node.get("instanceId", ""),
                    to_connector=to_node.get("connectorId", ""),
                )
            )
            wire_id_idx += 1

    return CircuitManifest(
        project_id=project_id,
        title=title,
        file_path=str(fz_path),
        parts=parts,
        wires=wires,
    )
