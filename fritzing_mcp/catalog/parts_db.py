"""SQLite parts database catalog queries and connector lookups."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from ..config import config
from ..models import ConnectorInfo, PartMetadata


class PartsDatabase:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path:
            self.db_path = db_path
        elif config.parts_dir and (config.parts_dir / "parts.db").is_file():
            self.db_path = config.parts_dir / "parts.db"
        else:
            self.db_path = None

    def _get_connection(self) -> sqlite3.Connection:
        if not self.db_path or not self.db_path.is_file():
            raise FileNotFoundError(f"Parts database not found at {self.db_path}")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def search_parts(self, query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Search parts by title, family, moduleID, or tags (max 50)."""
        limit = max(1, min(limit, 50))
        wildcard = f"%{query}%"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    """
                    SELECT id, moduleID, title, family, description, spice
                    FROM parts
                    WHERE (title LIKE ? OR family LIKE ? OR moduleID LIKE ?) AND family LIKE ?
                    LIMIT ?
                    """,
                    (wildcard, wildcard, wildcard, f"%{category}%", limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, moduleID, title, family, description, spice
                    FROM parts
                    WHERE title LIKE ? OR family LIKE ? OR moduleID LIKE ?
                    LIMIT ?
                    """,
                    (wildcard, wildcard, wildcard, limit),
                )

            results = []
            for row in cursor.fetchall():
                results.append({
                    "module_id": row["moduleID"],
                    "title": row["title"],
                    "family": row["family"],
                    "description": row["description"][:120] if row["description"] else None,
                    "has_spice": bool(row["spice"]),
                })
            return results

    def get_part_metadata(self, module_id: str) -> Optional[PartMetadata]:
        """Fetch complete metadata, connectors, and properties for a part."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM parts WHERE moduleID = ? LIMIT 1", (module_id,))
            p_row = cursor.fetchone()
            if not p_row:
                return None

            part_id = p_row["id"]

            # Connectors
            cursor.execute(
                "SELECT connectorid, name, type, description FROM connectors WHERE part_id = ?",
                (part_id,),
            )
            connectors = [
                ConnectorInfo(
                    connector_id=c["connectorid"],
                    name=c["name"] or c["connectorid"],
                    connector_type=str(c["type"]) if c["type"] is not None else "male",
                    description=c["description"],
                )
                for c in cursor.fetchall()
            ]

            # Properties
            cursor.execute("SELECT name, value FROM properties WHERE part_id = ?", (part_id,))
            properties = {row["name"]: row["value"] for row in cursor.fetchall()}

            # Tags
            cursor.execute("SELECT tag FROM tags WHERE part_id = ?", (part_id,))
            tags = [row["tag"] for row in cursor.fetchall() if row["tag"]]

            return PartMetadata(
                module_id=p_row["moduleID"],
                title=p_row["title"],
                family=p_row["family"],
                author=p_row["author"],
                description=p_row["description"],
                version=p_row["version"],
                properties=properties,
                tags=tags,
                connectors=connectors,
                has_spice=bool(p_row["spice"]),
            )

    def get_part_connectors(self, module_id: str) -> List[ConnectorInfo]:
        """Fetch normalized connector table for a part."""
        meta = self.get_part_metadata(module_id)
        if not meta:
            raise KeyError(f"Part '{module_id}' not found.")
        return meta.connectors


parts_db = PartsDatabase()
