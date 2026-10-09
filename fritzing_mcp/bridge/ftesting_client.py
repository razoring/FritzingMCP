"""HTTP client for Fritzing's native embedded FTestingServer (port 17999)."""

from __future__ import annotations

import json
import socket
import urllib.parse
from typing import Any, Dict, List, Optional

from ..config import config


class FTestingClient:
    def __init__(self, host: str = "::1", port: Optional[int] = None) -> None:
        self.host = host
        self.port = port or config.default_testing_port

    def _send_request(self, method: str, path: str, timeout: float = 3.0) -> Dict[str, Any]:
        """Send raw HTTP request to dual-stack IPv6/IPv4 FTestingServer."""
        # Try IPv6 first, fall back to IPv4
        sock = None
        for res in socket.getaddrinfo(self.host, self.port, socket.AF_UNSPEC, socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            try:
                sock = socket.socket(af, socktype, proto)
                sock.settimeout(timeout)
                sock.connect(sa)
                break
            except Exception:
                if sock:
                    sock.close()
                sock = None

        if not sock:
            raise ConnectionError(f"Cannot connect to FTestingServer at {self.host}:{self.port}")

        try:
            req = f"{method} {path} HTTP/1.0\r\nHost: [{self.host}]:{self.port}\r\nConnection: close\r\n\r\n"
            sock.sendall(req.encode("utf-8"))

            resp_bytes = b""
            while True:
                try:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    resp_bytes += chunk
                except Exception:
                    break
        finally:
            sock.close()

        resp_text = resp_bytes.decode("utf-8", errors="replace")
        if "\r\n\r\n" in resp_text:
            header_str, body_str = resp_text.split("\r\n\r\n", 1)
        else:
            header_str, body_str = resp_text, ""

        lines = header_str.splitlines()
        status_line = lines[0] if lines else ""
        status_code = 0
        if len(status_line.split()) >= 2:
            try:
                status_code = int(status_line.split()[1])
            except ValueError:
                pass

        if status_code >= 400:
            return {"ok": False, "status_code": status_code, "error": body_str.strip() or status_line}

        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            return {"ok": True, "raw_body": body_str}

    def read_probe(self, probe_name: str) -> Dict[str, Any]:
        """Read data from an active FProbe."""
        path = f"/read/{probe_name}"
        return self._send_request("GET", path)

    def write_probe(self, probe_name: str, command: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON command operation to an active FProbe."""
        json_str = json.dumps(command)
        encoded = urllib.parse.quote(json_str)
        path = f"/write/{probe_name}/{encoded}"
        return self._send_request("GET", path)

    # --- High-level probe convenience operations ---

    def get_wires(self) -> Dict[str, Any]:
        """Fetch all wires in the active sketch."""
        return self.write_probe("WireProbe", {"cmd": "getWires"})

    def get_connections(self) -> Dict[str, Any]:
        """Fetch all connector connections in the active sketch."""
        return self.write_probe("WireProbe", {"cmd": "getConnections"})

    def move_part(self, part_id: str, x: float, y: float) -> Dict[str, Any]:
        """Move component instance on active canvas."""
        return self.write_probe("PartProbe", {"cmd": "movePart", "part": part_id, "x": x, "y": y})

    def get_part_position(self, part_id: str) -> Dict[str, Any]:
        """Get scene coordinates of component instance."""
        return self.write_probe("PartProbe", {"cmd": "getPosition", "part": part_id})

    def delete_wire(self, wire_id: str) -> Dict[str, Any]:
        """Delete wire from active sketch."""
        return self.write_probe("WireProbe", {"cmd": "deleteWire", "wireId": wire_id})

    def drop_item_by_module_id(self, module_id: str) -> Dict[str, Any]:
        """Place part onto active canvas by moduleID."""
        return self.write_probe("DropByModuleID", {"cmd": "putItemByModuleID", "moduleID": module_id})

    def start_simulator(self) -> Dict[str, Any]:
        """Start ngspice circuit simulation."""
        return self.write_probe("StartSimulator", {"cmd": "startSimulator"})

    def stop_simulator(self) -> Dict[str, Any]:
        """Stop ngspice circuit simulation."""
        return self.write_probe("StartSimulator", {"cmd": "stopSimulation"})

    def get_current_sketch_xml(self) -> Dict[str, Any]:
        """Get memory dump of current sketch XML."""
        return self.read_probe("CurrentSketchXml")
