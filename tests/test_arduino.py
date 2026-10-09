import pytest
from fritzing_mcp.simulation.arduino import SimulatedArduinoSession, compile_sketch
from fritzing_mcp.config import config

def test_arduino_simulated_session():
    sketch = '''
    void setup() {
      Serial.begin(9600);
      Serial.println("SYSTEM_INITIALIZED");
      pinMode(13, OUTPUT);
      digitalWrite(13, HIGH);
    }
    void loop() {}
    '''
    session = SimulatedArduinoSession(code=sketch)
    session.step(duration_ms=100.0)

    # Pin 13 should be 5.0V
    assert session.pin_voltages.get("D13") == 5.0 or session.pin_voltages.get("pin13") == 5.0

    # Serial buffer should contain initialization message
    serial_out = session.read_serial()
    assert "SYSTEM_INITIALIZED" in serial_out

def test_arduino_compile():
    if not config.arduino_cli_exe or not config.arduino_cli_exe.is_file():
        pytest.skip("arduino-cli not installed")
    
    sketch = '''
    void setup() {
      pinMode(13, OUTPUT);
      digitalWrite(13, HIGH);
    }
    void loop() {}
    '''
    # esp32 core is installed on this host
    result = compile_sketch(sketch, fqbn="esp32:esp32:esp32")
    assert result["success"] is True
    assert result["flash_bytes"] is not None
