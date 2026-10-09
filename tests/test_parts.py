import pytest
from fritzing_mcp.catalog.parts_db import PartsDatabase
from fritzing_mcp.config import config

def test_parts_db_search():
    if not config.parts_dir or not (config.parts_dir / "parts.db").is_file():
        pytest.skip("parts.db not found on host")
    db = PartsDatabase()
    res = db.search_parts("resistor", limit=10)
    assert len(res) > 0
    assert any("resistor" in r["title"].lower() or "resistor" in (r.get("description") or "").lower() for r in res)

def test_parts_db_get_part():
    if not config.parts_dir or not (config.parts_dir / "parts.db").is_file():
        pytest.skip("parts.db not found on host")
    db = PartsDatabase()
    res = db.search_parts("LED", limit=5)
    assert len(res) > 0
    module_id = res[0]["module_id"]
    detail = db.get_part_metadata(module_id)
    assert detail is not None
    assert detail.module_id == module_id
    assert len(detail.connectors) > 0

def test_parts_db_connectors():
    if not config.parts_dir or not (config.parts_dir / "parts.db").is_file():
        pytest.skip("parts.db not found on host")
    db = PartsDatabase()
    res = db.search_parts("Arduino Uno", limit=5)
    if not res:
        pytest.skip("Arduino Uno part not indexed")
    conns = db.get_part_connectors(res[0]["module_id"])
    assert len(conns) > 0
    assert any(c.name for c in conns)
