from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import PROJECT_ROOT
from app.discovery.cmir_bridge import build_discovery_cmir_and_graph
from app.discovery.osquery_parser import OsqueryDiscoveryParser

DEFAULT_OSQUERY_JSON_PATH = PROJECT_ROOT / "docs" / "cloudmove-osquery-inventory.json"
SESSIONS_STORAGE_DIR = PROJECT_ROOT / "backend" / "data" / "discovery_sessions"


class DiscoverySessionStore:
    """In-memory and optional disk-backed repository for imported discovery sessions.

    Preserves each imported analysis with a unique session_id, never silently overwriting
    previous sessions, and caches the parsed result of the default local inventory file
    so the 2.3 MB JSON is not re-parsed unnecessarily on every request.
    """

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or SESSIONS_STORAGE_DIR
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._file_hash_to_session_id: Dict[str, str] = {}
        self._parser = OsqueryDiscoveryParser()

    def import_raw_inventory(
        self,
        raw_data: Dict[str, Any],
        filename: str = "uploaded-inventory.json",
        deduplicate_by_hash: bool = False,
        raw_bytes_digest: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate, parse, bridge to CMIR + Graph, and store a discovery session."""
        if deduplicate_by_hash and raw_bytes_digest and raw_bytes_digest in self._file_hash_to_session_id:
            existing_id = self._file_hash_to_session_id[raw_bytes_digest]
            if existing_id in self._sessions:
                return self._sessions[existing_id]

        normalized = self._parser.parse(raw_data)
        cmir, graph_payload, cmir_validation = build_discovery_cmir_and_graph(normalized)

        session_id = f"disc-{uuid.uuid4().hex[:10]}"
        imported_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        session_record = {
            "session_id": session_id,
            "filename": filename,
            "imported_at": imported_at,
            "hostname": normalized["summary"]["hostname"],
            "collected_at": normalized["source"].get("collected_at"),
            "schema_version": normalized.get("schema_version"),
            "source": normalized["source"],
            "normalized_inventory": normalized,
            "cmir": cmir.model_dump(),
            "graph": graph_payload,
            "cmir_validation": cmir_validation,
        }

        self._sessions[session_id] = session_record
        if raw_bytes_digest:
            self._file_hash_to_session_id[raw_bytes_digest] = session_id

        self._persist_session_metadata(session_record)
        return session_record

    def import_from_path(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"El archivo de inventario no existe en: {path}")
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if digest in self._file_hash_to_session_id:
            existing_id = self._file_hash_to_session_id[digest]
            if existing_id in self._sessions:
                return self._sessions[existing_id]

        try:
            raw_json = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"El archivo '{path.name}' no contiene JSON válido: {exc}") from exc

        return self.import_raw_inventory(
            raw_data=raw_json,
            filename=path.name,
            deduplicate_by_hash=True,
            raw_bytes_digest=digest,
        )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id in self._sessions:
            return self._sessions[session_id]
        # Check disk persistence fallback
        disk_path = self.storage_dir / f"{session_id}.json"
        if disk_path.is_file():
            try:
                loaded = json.loads(disk_path.read_text(encoding="utf-8"))
                self._sessions[session_id] = loaded
                return loaded
            except Exception:
                return None
        return None

    def get_latest_or_default(self) -> Optional[Dict[str, Any]]:
        if self._sessions:
            last_key = list(self._sessions.keys())[-1]
            return self._sessions[last_key]
        if DEFAULT_OSQUERY_JSON_PATH.is_file():
            return self.import_from_path(DEFAULT_OSQUERY_JSON_PATH)
        return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        items = []
        for sid, rec in reversed(list(self._sessions.items())):
            summary = rec["normalized_inventory"]["summary"]
            metrics = summary["metrics"]
            items.append({
                "session_id": sid,
                "filename": rec.get("filename"),
                "imported_at": rec.get("imported_at"),
                "hostname": rec.get("hostname"),
                "collected_at": rec.get("collected_at"),
                "os": f"{(summary.get('os') or {}).get('name') or 'Linux'} {(summary.get('os') or {}).get('version') or ''}".strip(),
                "packages_count": metrics.get("installed_packages_count", 0),
                "processes_count": metrics.get("processes_count", 0),
                "listening_ports_count": metrics.get("listening_ports_count", 0),
                "completeness_percent": summary["collection_quality"].get("completeness_percent", 0),
                "warnings_count": len(rec["normalized_inventory"].get("issues") or []),
            })
        return items

    def _persist_session_metadata(self, record: Dict[str, Any]) -> None:
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            out_file = self.storage_dir / f"{record['session_id']}.json"
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            out_file.chmod(0o600)
        except OSError:
            # Non-fatal if filesystem is read-only in test environments
            pass


discovery_store = DiscoverySessionStore()
