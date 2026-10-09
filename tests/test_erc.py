from fritzing_mcp.circuit.manifest import CircuitManifest
from fritzing_mcp.circuit.verification import validate_circuit
from fritzing_mcp.models import PlacedPart, WireInfo

def test_erc_clean_circuit():
    p_res = PlacedPart(instance_id="res_1", module_id="ResistorModuleID", title="220 Resistor", x=10, y=10)
    p_led = PlacedPart(instance_id="led_1", module_id="LEDModuleID", title="Red LED", x=20, y=10)
    p_pwr = PlacedPart(instance_id="pwr_1", module_id="PowerModuleID", title="5V Power", x=0, y=0)

    # Wire 5V -> Resistor -> LED anode -> LED cathode -> GND
    w1 = WireInfo(wire_id="w1", from_instance="pwr_1", from_connector="VCC", to_instance="res_1", to_connector="pin1")
    w2 = WireInfo(wire_id="w2", from_instance="res_1", from_connector="pin2", to_instance="led_1", to_connector="anode")
    w3 = WireInfo(wire_id="w3", from_instance="led_1", from_connector="cathode", to_instance="pwr_1", to_connector="GND")

    manifest = CircuitManifest(project_id="test_proj", title="Test Clean", parts=[p_res, p_led, p_pwr], wires=[w1, w2, w3])
    report = validate_circuit(manifest)
    errors = [d for d in report.diagnostics if d.severity in ("CRITICAL_ERROR", "ERROR")]
    assert len(errors) == 0

def test_erc_short_circuit_detection():
    p_pwr = PlacedPart(instance_id="pwr_1", module_id="PowerModuleID", title="Power Supply", x=0, y=0)
    # Wire VCC directly to GND
    w_short = WireInfo(wire_id="w_short", from_instance="pwr_1", from_connector="VCC", to_instance="pwr_1", to_connector="GND")

    manifest = CircuitManifest(project_id="test_short", title="Short Circuit", parts=[p_pwr], wires=[w_short])
    report = validate_circuit(manifest)
    critical = [d for d in report.diagnostics if d.severity == "CRITICAL_ERROR"]
    assert len(critical) > 0
    assert any("short" in c.message.lower() for c in critical)

def test_erc_missing_led_resistor():
    p_led = PlacedPart(instance_id="led_1", module_id="LEDModuleID", title="Red LED", x=10, y=10)
    p_pwr = PlacedPart(instance_id="pwr_1", module_id="PowerModuleID", title="5V Supply", x=0, y=0)
    # Wire 5V directly to LED anode and GND to cathode
    w1 = WireInfo(wire_id="w1", from_instance="pwr_1", from_connector="VCC", to_instance="led_1", to_connector="anode")
    w2 = WireInfo(wire_id="w2", from_instance="pwr_1", from_connector="GND", to_instance="led_1", to_connector="cathode")

    manifest = CircuitManifest(project_id="test_led", title="LED without resistor", parts=[p_led, p_pwr], wires=[w1, w2])
    report = validate_circuit(manifest)
    errors = [d for d in report.diagnostics if d.severity == "ERROR"]
    assert any("resistor" in d.message.lower() for d in errors)
