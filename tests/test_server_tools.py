import pytest
from fritzing_mcp.server import server

REQUIRED_TOOLS = [
    "fritzing_status",
    "fritzing_search_parts",
    "fritzing_get_part",
    "fritzing_get_part_connectors",
    "fritzing_create_project",
    "fritzing_get_project",
    "fritzing_place_part",
    "fritzing_move_part",
    "fritzing_wire",
    "fritzing_validate_project",
    "fritzing_render",
    "fritzing_visual_report",
    "fritzing_save_project",
    "fritzing_export",
    "fritzing_create_part",
    "fritzing_validate_part",
    "fritzing_list_windows",
    "fritzing_select_window",
    "fritzing_release_window",
    "fritzing_switch_view",
    "fritzing_screenshot",
    "fritzing_remove_part",
    "fritzing_modify_part",
    "fritzing_delete_wire",
    "fritzing_run_simulation",
    "fritzing_get_simulation_results",
    "fritzing_set_code",
    "fritzing_compile_code",
    "fritzing_simulate_code",
    "fritzing_read_serial",
    "fritzing_write_serial",
    "fritzing_stop_simulation",
]

def test_all_tools_registered():
    tools = server._tool_manager.list_tools()
    tool_names = {t.name for t in tools}
    for req in REQUIRED_TOOLS:
        assert req in tool_names, f"Tool {req} is missing from MCP server"

def test_status_tool_direct():
    tool = server._tool_manager.get_tool("fritzing_status")
    assert tool is not None
    # Call the tool function directly
    res = tool.fn()
    assert "status" in res
    assert "version" in res
    assert "policy" in res

def test_search_parts_tool():
    tool = server._tool_manager.get_tool("fritzing_search_parts")
    assert tool is not None
    res = tool.fn(query="resistor", limit=5)
    assert isinstance(res, list)
    assert len(res) > 0

def test_validation_tool():
    tool = server._tool_manager.get_tool("fritzing_validate_project")
    assert tool is not None
    res = tool.fn()
    assert "status" in res
    assert "diagnostics" in res
