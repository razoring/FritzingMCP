"""Analog ngspice simulation integration."""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from ..bridge.ftesting_client import FTestingClient
from ..models import SimulationNodeVoltage, SimulationReport


def run_analog_simulation(
    client: FTestingClient,
    analysis_type: str = "dc",
    duration_ms: float = 100.0,
) -> SimulationReport:
    """Trigger Fritzing's embedded ngspice simulator and retrieve node voltages."""
    start_t = time.time()
    res = client.start_simulator()
    elapsed = (time.time() - start_t) * 1000

    if not res.get("ok", True) and "error" in res:
        return SimulationReport(
            status="CONVERGENCE_ERROR",
            analysis_type=analysis_type,
            elapsed_ms=elapsed,
            errors=[str(res["error"])],
        )

    # In Fritzing ngspice, voltage vectors are extracted via FProbeStartSimulator
    # We parse node voltages if returned
    raw = res.get("voltageVector") or []
    node_voltages: List[SimulationNodeVoltage] = []
    if isinstance(raw, list):
        for i, v in enumerate(raw):
            node_voltages.append(SimulationNodeVoltage(node_name=f"net_{i}", voltage=float(v)))

    return SimulationReport(
        status="SUCCESS",
        analysis_type=analysis_type,
        elapsed_ms=elapsed,
        node_voltages=node_voltages,
    )
