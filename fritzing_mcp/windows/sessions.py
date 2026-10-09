"""Cross-process per-conversation session lock manager for Fritzing windows."""

from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import json
import os
import time
from typing import Dict, Iterator, Optional

from ..config import config
from ..models import LockEntry

kernel32 = ctypes.windll.kernel32
SYNCHRONIZE = 0x00100000
MUTEX_ALL_ACCESS = 0x001F0001
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000


@contextlib.contextmanager
def named_mutex(name: str = "Local\\FritzingMcpSessionLockMutex") -> Iterator[bool]:
    """Acquire a cross-process Windows Named Mutex to guard JSON lock registry reads/writes."""
    h_mutex = kernel32.CreateMutexW(None, False, name)
    if not h_mutex:
        yield False
        return
    
    wait_res = kernel32.WaitForSingleObject(h_mutex, 5000) # 5s timeout
    acquired = (wait_res == WAIT_OBJECT_0)
    try:
        yield acquired
    finally:
        if acquired:
            kernel32.ReleaseMutex(h_mutex)
        kernel32.CloseHandle(h_mutex)


class SessionManager:
    def __init__(self) -> None:
        self.locks_path = config.locks_file
        self.lease_timeout = config.lock_lease_timeout_sec

    def _read_locks_unlocked(self) -> Dict[str, dict]:
        if not self.locks_path.is_file():
            return {}
        try:
            with open(self.locks_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_locks_unlocked(self, data: Dict[str, dict]) -> None:
        self.locks_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.locks_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.locks_path)

    def _prune_expired_unlocked(self, locks: Dict[str, dict]) -> Dict[str, dict]:
        now = time.time()
        active = {}
        for wid, entry in locks.items():
            if entry.get("expires_at", 0) > now:
                active[wid] = entry
        return active

    def get_lock_info(self, window_id: str) -> dict:
        now = time.time()
        with named_mutex():
            locks = self._prune_expired_unlocked(self._read_locks_unlocked())
            entry = locks.get(window_id)
            if entry and entry.get("expires_at", 0) > now:
                return {
                    "is_locked": True,
                    "locked_by": entry.get("session_id"),
                    "lease_expires_in_sec": round(entry.get("expires_at", 0) - now, 1),
                }
            return {
                "is_locked": False,
                "locked_by": None,
                "lease_expires_in_sec": None,
            }

    def acquire_lock(self, window_id: str, session_id: str, pid: int = 0, force: bool = False) -> bool:
        now = time.time()
        with named_mutex() as ok:
            if not ok:
                return False
            locks = self._prune_expired_unlocked(self._read_locks_unlocked())
            current = locks.get(window_id)
            
            if current and current.get("session_id") != session_id:
                if not force and current.get("expires_at", 0) > now:
                    return False # Locked by active session
            
            # Grant lock
            locks[window_id] = {
                "window_id": window_id,
                "session_id": session_id,
                "pid": pid,
                "acquired_at": now,
                "expires_at": now + self.lease_timeout,
            }
            self._write_locks_unlocked(locks)
            return True

    def renew_lock(self, window_id: str, session_id: str) -> bool:
        now = time.time()
        with named_mutex() as ok:
            if not ok:
                return False
            locks = self._prune_expired_unlocked(self._read_locks_unlocked())
            current = locks.get(window_id)
            if current and current.get("session_id") == session_id:
                current["expires_at"] = now + self.lease_timeout
                self._write_locks_unlocked(locks)
                return True
            return False

    def release_lock(self, window_id: str, session_id: str) -> bool:
        with named_mutex() as ok:
            if not ok:
                return False
            locks = self._read_locks_unlocked()
            current = locks.get(window_id)
            if current and current.get("session_id") == session_id:
                del locks[window_id]
                self._write_locks_unlocked(locks)
                return True
            return False

    def release_all_for_session(self, session_id: str) -> int:
        count = 0
        with named_mutex() as ok:
            if not ok:
                return 0
            locks = self._read_locks_unlocked()
            to_del = [wid for wid, entry in locks.items() if entry.get("session_id") == session_id]
            for wid in to_del:
                del locks[wid]
                count += 1
            if count > 0:
                self._write_locks_unlocked(locks)
        return count


session_manager = SessionManager()
