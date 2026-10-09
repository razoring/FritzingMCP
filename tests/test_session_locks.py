import time
from fritzing_mcp.windows.sessions import SessionManager

def test_session_lock_acquire_and_release(tmp_path):
    mgr = SessionManager()
    mgr.locks_path = tmp_path / "locks.json"
    
    # Acquire lock for window "win_12345"
    ok = mgr.acquire_lock("win_12345", "agent_1")
    assert ok is True

    # Verify agent_1 holds it
    info = mgr.get_lock_info("win_12345")
    assert info["is_locked"] is True
    assert info["locked_by"] == "agent_1"

    # Agent 2 trying to acquire should fail
    ok2 = mgr.acquire_lock("win_12345", "agent_2")
    assert ok2 is False

    # Release lock
    ok3 = mgr.release_lock("win_12345", "agent_1")
    assert ok3 is True

    # Now agent 2 can acquire
    ok4 = mgr.acquire_lock("win_12345", "agent_2")
    assert ok4 is True
    mgr.release_lock("win_12345", "agent_2")

def test_session_lock_expiration(tmp_path):
    mgr = SessionManager()
    mgr.locks_path = tmp_path / "locks.json"
    mgr.lease_timeout = 1 # 1s lease
    
    ok = mgr.acquire_lock("win_short", "agent_short")
    assert ok is True

    # Sleep past lease
    time.sleep(1.2)

    # Next agent can acquire expired lock
    ok2 = mgr.acquire_lock("win_short", "agent_new")
    assert ok2 is True
    mgr.release_lock("win_short", "agent_new")
