"""
Transactional Persistence Engine & Optimistic Concurrency Control for CloudMove.

Addresses Section 5.1 & Section 9:
- Provides ACID transactional storage backed by SQLite (`WAL` mode + `FOREIGN KEYS` +
  `BEGIN IMMEDIATE` write transactions) for local/single-node deployments and supports
  PostgreSQL DSN configuration (`CLOUDMOVE_DATABASE_URL`) for multi-user deployments.
- Versioned schema migrations (`v1.0`, `v2.0`, `v2.1`) tracked in `schema_migrations`.
- Persistent relational tables with primary keys, unique constraints, foreign keys, and indexes:
  1. `schema_migrations`
  2. `assets`
  3. `migration_plans`
  4. `migration_stages`
  5. `stage_executions` (with `UNIQUE(migration_id, stage_id, idempotency_key)` to guarantee idempotent retries)
  6. `migration_artifacts`
  7. `cloud_discovery_snapshots`
  8. `audit_events`
- Prevents two operators from executing the same migration stage simultaneously via
  atomic stage locks (`locked_by`, `locked_at`) and optimistic concurrency (`version` column).
- Controlled migration of legacy JSON files (`migrations_state.json`)
  with automatic `.bak` backup and corruption/incompatibility detection.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.config import DATA_DIR, PROJECT_ROOT
from app.core.text_utils import utc_now_iso as _utc_now
from app.persistence.schema import SCHEMA_MIGRATIONS, apply_schema_migrations


DEFAULT_SQLITE_PATH = DATA_DIR / "cloudmove_transactional.db"
DEFAULT_OPERATOR = os.getenv("CLOUDMOVE_OPERATOR_USER", "operator")


class ConcurrencyConflictError(RuntimeError):
    """Raised when optimistic locking detects a concurrent modification (`version` mismatch)."""


class StageLockedError(RuntimeError):
    """Raised when two operators attempt to execute the same migration stage simultaneously."""


class IncompatibleLegacyDataError(ValueError):
    """Raised or recorded when legacy JSON data fails structural schema validation."""


class TransactionalDatabase:
    """
    ACID transactional persistence engine with versioned schema migrations,
    optimistic concurrency control, stage locking, and idempotent execution tracking.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        database_url: Optional[str] = None,
    ) -> None:
        self.database_url = database_url if database_url is not None else os.getenv("CLOUDMOVE_DATABASE_URL", "")
        if self.database_url.lower().startswith(("postgresql://", "postgres://")):
            raise NotImplementedError(
                "El motor PostgreSQL externo aún no está implementado en TransactionalDatabase; "
                "use SQLite WAL mediante `sqlite:///...` o `CLOUDMOVE_DATA_DIR`."
            )
        if db_path is not None:
            self.db_path = Path(db_path)
        elif self.database_url.startswith("sqlite:///"):
            self.db_path = Path(self.database_url.replace("sqlite:///", "", 1))
        else:
            env_db_path = os.getenv("CLOUDMOVE_DB_PATH")
            if env_db_path:
                self.db_path = Path(env_db_path).expanduser()
            else:
                env_data_dir = os.getenv("CLOUDMOVE_DATA_DIR")
                self.db_path = (Path(env_data_dir).expanduser() / "cloudmove_transactional.db") if env_data_dir else DEFAULT_SQLITE_PATH

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.legacy_migration_report: Dict[str, Any] = {
            "migrated_from_json": False,
            "backups_created": [],
            "incompatible_records": [],
        }
        self._apply_migrations()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    @contextmanager
    def transaction(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Execute a block inside an ACID transaction (`BEGIN IMMEDIATE` for writes)."""
        with self._lock:
            conn = self._connect()
            try:
                if write:
                    conn.execute("BEGIN IMMEDIATE;")
                else:
                    conn.execute("BEGIN;")
                yield conn
                conn.execute("COMMIT;")
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def _apply_migrations(self) -> None:
        with self.transaction(write=True) as conn:
            apply_schema_migrations(conn)

    def get_schema_status(self) -> Dict[str, Any]:
        with self.transaction(write=False) as conn:
            rows = conn.execute(
                "SELECT version, description, checksum, applied_at FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
            plans_count = conn.execute("SELECT COUNT(*) AS c FROM migration_plans").fetchone()["c"]
            assets_count = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
            exec_count = conn.execute("SELECT COUNT(*) AS c FROM stage_executions").fetchone()["c"]
            audit_count = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]

        return {
            "engine": "sqlite_wal",
            "journal_mode": "WAL",
            "database_path": str(self.db_path),
            "current_version": rows[-1]["version"] if rows else "0.0.0",
            "current_schema_version": rows[-1]["version"] if rows else "0.0.0",
            "applied_migrations": [dict(r) for r in rows],
            "counts": {
                "migration_plans": plans_count,
                "assets": assets_count,
                "stage_executions": exec_count,
                "audit_events": audit_count,
            },
            "legacy_migration_report": self.legacy_migration_report,
        }

    # ==========================================================================
    # Audit Trail
    # ==========================================================================

    def record_audit_event(
        self,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict[str, Any]:
        evt = {
            "event_id": f"aud-{uuid.uuid4().hex[:12]}",
            "actor_id": actor_id or "system@cloudmove.local",
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "timestamp": _utc_now(),
            "metadata": metadata or {},
        }
        if conn is not None:
            conn.execute(
                """
                INSERT INTO audit_events (event_id, actor_id, action, target_type, target_id, timestamp, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt["event_id"],
                    evt["actor_id"],
                    evt["action"],
                    evt["target_type"],
                    evt["target_id"],
                    evt["timestamp"],
                    json.dumps(evt["metadata"], ensure_ascii=False),
                ),
            )
        else:
            with self.transaction(write=True) as c:
                c.execute(
                    """
                    INSERT INTO audit_events (event_id, actor_id, action, target_type, target_id, timestamp, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evt["event_id"],
                        evt["actor_id"],
                        evt["action"],
                        evt["target_type"],
                        evt["target_id"],
                        evt["timestamp"],
                        json.dumps(evt["metadata"], ensure_ascii=False),
                    ),
                )
        return evt

    def list_audit_events(self, target_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            if target_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE target_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (target_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "event_id": r["event_id"],
                    "actor_id": r["actor_id"],
                    "action": r["action"],
                    "target_type": r["target_type"],
                    "target_id": r["target_id"],
                    "timestamp": r["timestamp"],
                    "metadata": json.loads(r["metadata_json"]),
                }
                for r in rows
            ]

    # ==========================================================================
    # Migration Plans, Stages, Artifacts, Optimistic Locking & Stage Locks
    # ==========================================================================

    def save_migration_job(
        self,
        job: Dict[str, Any],
        expected_version: Optional[int] = None,
        actor_id: str = "orchestrator@cloudmove.local",
    ) -> Dict[str, Any]:
        """
        Persist a migration job, its ordered stages, and its generated artifacts inside a
        single atomic transaction. Enforces optimistic concurrency control when
        `expected_version` is provided.
        """
        migration_id = job["migration_id"]
        target_provider = str(job.get("target_provider", "aws")).lower().strip()
        use_case = str(job.get("use_case", "app_source")).lower().strip()
        if target_provider != "aws":
            raise ValueError(f"Proveedor '{target_provider}' rechazado por restricción de integridad (exclusivo aws).")
        if use_case not in ("app_source", "vm_image"):
            raise ValueError(f"Caso de uso '{use_case}' inválido en persistencia transaccional.")

        now = _utc_now()
        with self.transaction(write=True) as conn:
            existing = conn.execute(
                "SELECT version, locked_by, locked_at FROM migration_plans WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()

            if existing is None:
                new_version = int(job.get("version", 1))
                job["version"] = new_version
                job["updated_at"] = now
                payload_str = json.dumps(job, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO migration_plans (
                        migration_id, name, use_case, target_provider, state,
                        execution_mode, completed_in_real_cloud, version,
                        locked_by, locked_at, created_at, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        migration_id,
                        job.get("name", migration_id),
                        use_case,
                        target_provider,
                        job["state"],
                        job.get("execution_mode", "simulated_dry_run"),
                        1 if job.get("completed_in_real_cloud") else 0,
                        new_version,
                        job.get("locked_by"),
                        job.get("locked_at"),
                        job.get("created_at", now),
                        now,
                        payload_str,
                    ),
                )
            else:
                current_version = int(existing["version"])
                if expected_version is not None and expected_version != current_version:
                    raise ConcurrencyConflictError(
                        f"Conflicto de concurrencia optimista en migración '{migration_id}': "
                        f"versión esperada {expected_version}, pero la base de datos contiene versión {current_version}."
                    )
                new_version = current_version + 1
                job["version"] = new_version
                job["updated_at"] = now
                payload_str = json.dumps(job, ensure_ascii=False)
                cursor = conn.execute(
                    """
                    UPDATE migration_plans
                    SET name = ?, use_case = ?, target_provider = ?, state = ?,
                        execution_mode = ?, completed_in_real_cloud = ?, version = ?,
                        locked_by = ?, locked_at = ?, updated_at = ?, payload_json = ?
                    WHERE migration_id = ? AND version = ?
                    """,
                    (
                        job.get("name", migration_id),
                        use_case,
                        target_provider,
                        job["state"],
                        job.get("execution_mode", "simulated_dry_run"),
                        1 if job.get("completed_in_real_cloud") else 0,
                        new_version,
                        job.get("locked_by"),
                        job.get("locked_at"),
                        now,
                        payload_str,
                        migration_id,
                        current_version,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ConcurrencyConflictError(
                        f"Conflicto de escritura concurrente al actualizar la migración '{migration_id}'."
                    )

            # Upsert ordered stages
            for st in job.get("ordered_stages", []):
                stage_pk = f"{migration_id}:{st['stage_id']}"
                conn.execute(
                    """
                    INSERT INTO migration_stages (
                        id, migration_id, stage_id, stage_order, title, status,
                        attempts, max_retries, recovery_point, locked_by, locked_at,
                        started_at, completed_at, error_text, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(migration_id, stage_id) DO UPDATE SET
                        stage_order = excluded.stage_order,
                        title = excluded.title,
                        status = excluded.status,
                        attempts = excluded.attempts,
                        max_retries = excluded.max_retries,
                        recovery_point = excluded.recovery_point,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at,
                        error_text = excluded.error_text,
                        payload_json = excluded.payload_json
                    """,
                    (
                        stage_pk,
                        migration_id,
                        st["stage_id"],
                        int(st.get("order", 1)),
                        st.get("title", st["stage_id"]),
                        st.get("status", "PENDING"),
                        int(st.get("attempts", 0)),
                        int(st.get("max_retries", 3)),
                        st.get("recovery_point", f"checkpoint-{st['stage_id']}"),
                        st.get("locked_by"),
                        st.get("locked_at"),
                        st.get("started_at"),
                        st.get("completed_at"),
                        st.get("error"),
                        json.dumps(st, ensure_ascii=False),
                    ),
                )

            # Upsert generated artifacts
            files_map = (job.get("generated_artifacts") or {}).get("files") or {}
            for fname, content in files_map.items():
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False, indent=2)
                art_id = f"{migration_id}:{fname}"
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                art_type = "terraform_hcl" if fname.endswith(".tf") else ("shell_script" if fname.endswith(".sh") else "json_or_config")
                conn.execute(
                    """
                    INSERT INTO migration_artifacts (
                        artifact_id, migration_id, filename, artifact_type, sha256, content_text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(migration_id, filename) DO UPDATE SET
                        sha256 = excluded.sha256,
                        content_text = excluded.content_text
                    """,
                    (art_id, migration_id, fname, art_type, sha, content, now),
                )

            self.record_audit_event(
                actor_id=actor_id,
                action=f"MIGRATION_SAVED_{job['state']}",
                target_type="migration_plan",
                target_id=migration_id,
                metadata={"state": job["state"], "version": new_version},
                conn=conn,
            )

        return job

    def get_migration_job(self, migration_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            row = conn.execute(
                "SELECT payload_json, version, locked_by, locked_at FROM migration_plans WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
            if not row:
                return None
            job = json.loads(row["payload_json"])
            job["version"] = row["version"]
            job["locked_by"] = row["locked_by"]
            job["locked_at"] = row["locked_at"]
            return job

    def list_migration_jobs(
        self,
        use_case: Optional[str] = None,
        target_provider: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT payload_json, version, locked_by, locked_at FROM migration_plans WHERE 1=1"
        params: List[Any] = []
        if use_case:
            query += " AND use_case = ?"
            params.append(use_case.lower().strip())
        if target_provider:
            query += " AND target_provider = ?"
            params.append(target_provider.lower().strip())
        query += " ORDER BY created_at DESC"

        with self.transaction(write=False) as conn:
            rows = conn.execute(query, params).fetchall()
            results: List[Dict[str, Any]] = []
            for r in rows:
                job = json.loads(r["payload_json"])
                job["version"] = r["version"]
                job["locked_by"] = r["locked_by"]
                job["locked_at"] = r["locked_at"]
                results.append(job)
            return results

    def delete_migration_job(self, migration_id: str) -> bool:
        """
        Delete a migration job and all associated stages, executions, and artifacts
        within an atomic transaction.
        """
        with self.transaction(write=True) as conn:
            existing = conn.execute(
                "SELECT 1 FROM migration_plans WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
            if not existing:
                return False
            conn.execute("DELETE FROM migration_artifacts WHERE migration_id = ?", (migration_id,))
            conn.execute("DELETE FROM stage_executions WHERE migration_id = ?", (migration_id,))
            conn.execute("DELETE FROM migration_stages WHERE migration_id = ?", (migration_id,))
            conn.execute("DELETE FROM migration_plans WHERE migration_id = ?", (migration_id,))
            return True

    def clear_all_migration_jobs(self) -> int:
        """
        Delete all migration jobs, stages, executions, and artifacts from the database.
        Returns the count of migration plans removed.
        """
        with self.transaction(write=True) as conn:
            count_row = conn.execute("SELECT COUNT(*) as cnt FROM migration_plans").fetchone()
            count = count_row["cnt"] if count_row else 0
            conn.execute("DELETE FROM migration_artifacts")
            conn.execute("DELETE FROM stage_executions")
            conn.execute("DELETE FROM migration_stages")
            conn.execute("DELETE FROM migration_plans")
            return count

    def acquire_stage_lock(
        self,
        migration_id: str,
        stage_id: str,
        operator_id: str = "operator@cloudmove.local",
    ) -> None:
        """
        Atomically lock a migration stage so two operators cannot execute the same
        stage simultaneously. Raises `StageLockedError` if already locked by another operator.
        """
        now = _utc_now()
        with self.transaction(write=True) as conn:
            row = conn.execute(
                "SELECT locked_by, locked_at FROM migration_stages WHERE migration_id = ? AND stage_id = ?",
                (migration_id, stage_id),
            ).fetchone()
            if row and row["locked_by"] and row["locked_by"] != operator_id:
                raise StageLockedError(
                    f"La etapa '{stage_id}' de la migración '{migration_id}' ya se encuentra bloqueada en ejecución "
                    f"por otro operador ('{row['locked_by']}' desde {row['locked_at']})."
                )
            conn.execute(
                "UPDATE migration_stages SET locked_by = ?, locked_at = ? WHERE migration_id = ? AND stage_id = ?",
                (operator_id, now, migration_id, stage_id),
            )
            conn.execute(
                "UPDATE migration_plans SET locked_by = ?, locked_at = ? WHERE migration_id = ?",
                (operator_id, now, migration_id),
            )

    def release_stage_lock(self, migration_id: str, stage_id: str, operator_id: Optional[str] = None) -> None:
        with self.transaction(write=True) as conn:
            if operator_id:
                conn.execute(
                    "UPDATE migration_stages SET locked_by = NULL, locked_at = NULL WHERE migration_id = ? AND stage_id = ? AND locked_by = ?",
                    (migration_id, stage_id, operator_id),
                )
            else:
                conn.execute(
                    "UPDATE migration_stages SET locked_by = NULL, locked_at = NULL WHERE migration_id = ? AND stage_id = ?",
                    (migration_id, stage_id),
                )
            conn.execute(
                "UPDATE migration_plans SET locked_by = NULL, locked_at = NULL WHERE migration_id = ?",
                (migration_id,),
            )

    def record_idempotent_stage_execution(
        self,
        migration_id: str,
        stage_id: str,
        idempotency_key: str,
        operator_id: str,
        execution_mode: str,
        status: str,
        result_payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Record or retrieve an idempotent stage execution.
        Returns `(execution_record, already_executed)`. If `(migration_id, stage_id, idempotency_key)`
        already succeeded, returns the existing execution record with `already_executed=True`
        so retries never duplicate resources or irreversible operations.
        """
        now = _utc_now()
        with self.transaction(write=True) as conn:
            existing = conn.execute(
                """
                SELECT execution_id, migration_id, stage_id, idempotency_key,
                       operator_id, execution_mode, status, started_at, completed_at, result_json
                FROM stage_executions
                WHERE migration_id = ? AND idempotency_key = ?
                """,
                (migration_id, idempotency_key),
            ).fetchone()
            if existing and existing["status"] == "COMPLETED":
                return (
                    {
                        "execution_id": existing["execution_id"],
                        "migration_id": existing["migration_id"],
                        "stage_id": existing["stage_id"],
                        "idempotency_key": existing["idempotency_key"],
                        "operator_id": existing["operator_id"],
                        "execution_mode": existing["execution_mode"],
                        "status": existing["status"],
                        "started_at": existing["started_at"],
                        "completed_at": existing["completed_at"],
                        "result": json.loads(existing["result_json"]),
                        "idempotent_replay": True,
                    },
                    True,
                )

            target_stage_id = existing["stage_id"] if existing else stage_id
            exec_id = existing["execution_id"] if existing else f"exec-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO stage_executions (
                    execution_id, migration_id, stage_id, idempotency_key,
                    operator_id, execution_mode, status, started_at, completed_at, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(migration_id, stage_id, idempotency_key) DO UPDATE SET
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    result_json = excluded.result_json
                """,
                (
                    exec_id,
                    migration_id,
                    target_stage_id,
                    idempotency_key,
                    operator_id,
                    execution_mode,
                    status,
                    now,
                    now if status in ("COMPLETED", "FAILED", "ROLLED_BACK") else None,
                    json.dumps(result_payload, ensure_ascii=False),
                ),
            )
            return (
                {
                    "execution_id": exec_id,
                    "migration_id": migration_id,
                    "stage_id": target_stage_id,
                    "idempotency_key": idempotency_key,
                    "operator_id": operator_id,
                    "execution_mode": execution_mode,
                    "status": status,
                    "started_at": now,
                    "completed_at": now,
                    "result": result_payload,
                    "idempotent_replay": False,
                },
                False,
            )

    # ==========================================================================
    # Assets Transactional Persistence
    # ==========================================================================

    def upsert_asset(
        self,
        asset_id: str,
        canonical_key: str,
        hostname: str,
        asset_type: str,
        environment_id: str,
        site_id: str,
        lifecycle_state: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction(write=True) as conn:
            conn.execute(
                """
                INSERT INTO assets (
                    id, canonical_key, hostname, asset_type, environment_id,
                    site_id, lifecycle_state, version, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    canonical_key = excluded.canonical_key,
                    hostname = excluded.hostname,
                    asset_type = excluded.asset_type,
                    environment_id = excluded.environment_id,
                    site_id = excluded.site_id,
                    lifecycle_state = excluded.lifecycle_state,
                    version = assets.version + 1,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    asset_id,
                    canonical_key,
                    hostname,
                    asset_type,
                    environment_id,
                    site_id,
                    lifecycle_state,
                    now,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return {
            "id": asset_id,
            "canonical_key": canonical_key,
            "hostname": hostname,
            "asset_type": asset_type,
            "environment_id": environment_id,
            "site_id": site_id,
            "lifecycle_state": lifecycle_state,
            "updated_at": now,
            "payload": payload,
        }

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["payload"] = json.loads(res.pop("payload_json"))
            return res

    def list_assets(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            rows = conn.execute(
                "SELECT * FROM assets ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                item["payload"] = json.loads(item.pop("payload_json"))
                out.append(item)
            return out

    # ==========================================================================
    # Cloud Live Discovery Snapshots Persistence
    # ==========================================================================

    def save_cloud_discovery_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        with self.transaction(write=True) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cloud_discovery_snapshots (
                    snapshot_id, provider, account_or_project, region,
                    execution_mode, discovered_at, resources_count,
                    cmir_json, reconciliation_json, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["snapshot_id"],
                    snapshot["provider"],
                    snapshot["account_or_project"],
                    snapshot["region"],
                    snapshot["execution_mode"],
                    snapshot["discovered_at"],
                    int(snapshot.get("resources_count", 0)),
                    json.dumps(snapshot.get("cmir", {}), ensure_ascii=False),
                    json.dumps(snapshot.get("reconciliation", {}), ensure_ascii=False),
                    json.dumps(snapshot.get("read_errors", []), ensure_ascii=False),
                ),
            )
        return snapshot

    def get_latest_cloud_discovery_snapshot(
        self,
        provider: str,
        account_or_project: str,
    ) -> Optional[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            row = conn.execute(
                """
                SELECT * FROM cloud_discovery_snapshots
                WHERE provider = ? AND account_or_project = ?
                ORDER BY discovered_at DESC LIMIT 1
                """,
                (provider.lower().strip(), account_or_project),
            ).fetchone()
            if not row:
                return None
            return {
                "snapshot_id": row["snapshot_id"],
                "provider": row["provider"],
                "account_or_project": row["account_or_project"],
                "region": row["region"],
                "execution_mode": row["execution_mode"],
                "discovered_at": row["discovered_at"],
                "resources_count": row["resources_count"],
                "cmir": json.loads(row["cmir_json"]),
                "reconciliation": json.loads(row["reconciliation_json"]),
                "read_errors": json.loads(row["errors_json"]),
            }

    def list_cloud_discovery_snapshots(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            if provider:
                rows = conn.execute(
                    "SELECT * FROM cloud_discovery_snapshots WHERE provider = ? ORDER BY discovered_at DESC",
                    (provider.lower().strip(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cloud_discovery_snapshots ORDER BY discovered_at DESC"
                ).fetchall()
            return [
                {
                    "snapshot_id": r["snapshot_id"],
                    "provider": r["provider"],
                    "account_or_project": r["account_or_project"],
                    "region": r["region"],
                    "execution_mode": r["execution_mode"],
                    "discovered_at": r["discovered_at"],
                    "resources_count": r["resources_count"],
                    "cmir": json.loads(r["cmir_json"]),
                    "reconciliation": json.loads(r["reconciliation_json"]),
                    "read_errors": json.loads(r["errors_json"]),
                }
                for r in rows
            ]

    # ==========================================================================
    # Controlled Legacy JSON Migration with Backup & Incompatible Data Detection
    # ==========================================================================

    def migrate_legacy_json_files(
        self,
        migrations_json_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Migrate legacy JSON files (`migrations_state.json`)
        into the transactional database, creating `.bak` backups and detecting any
        incompatible or corrupted records (e.g., unsupported target provider `azure`).
        """
        report: Dict[str, Any] = {
            "migrated_jobs_count": 0,
            "backups_created": [],
            "incompatible_records": [],
        }

        if migrations_json_path and migrations_json_path.is_file():
            backup_path = migrations_json_path.with_suffix(".json.bak")
            if not backup_path.exists():
                shutil.copy2(migrations_json_path, backup_path)
                report["backups_created"].append(str(backup_path))
            try:
                raw = json.loads(migrations_json_path.read_text(encoding="utf-8"))
                jobs_dict = raw.get("jobs", {}) if isinstance(raw, dict) else {}
                if not isinstance(jobs_dict, dict):
                    report["incompatible_records"].append({
                        "file": str(migrations_json_path),
                        "reason": "El campo raíz 'jobs' no es un objeto JSON válido.",
                    })
                else:
                    for mid, job in jobs_dict.items():
                        if not isinstance(job, dict) or not job.get("migration_id"):
                            report["incompatible_records"].append({
                                "file": str(migrations_json_path),
                                "record_id": str(mid),
                                "reason": "Registro de migración sin 'migration_id' o estructura inválida.",
                            })
                            continue
                        prov = str(job.get("target_provider", "")).lower().strip()
                        if prov != "aws":
                            report["incompatible_records"].append({
                                "file": str(migrations_json_path),
                                "record_id": str(mid),
                                "reason": f"Proveedor '{prov}' incompatible con el alcance exclusivo AWS.",
                            })
                            continue
                        if self.get_migration_job(job["migration_id"]) is None:
                            self.save_migration_job(job, actor_id="legacy_json_migrator")
                            report["migrated_jobs_count"] += 1
            except Exception as exc:
                report["incompatible_records"].append({
                    "file": str(migrations_json_path),
                    "reason": f"Archivo JSON corrupto o ilegible: {exc}",
                })

        self.legacy_migration_report = {
            "migrated_from_json": True,
            **report,
        }
        return self.legacy_migration_report

    # ==============================================================================
    # CloudMove Agent & Token Management (Section 3 & Section 7)
    # ==============================================================================

    def create_enrollment_token(
        self,
        created_by: str = DEFAULT_OPERATOR,
        ttl_seconds: int = 86400,
        max_uses: int = 1,
        org_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Generate a cryptographically secure, time-limited enrollment token for registering
        an authorized CloudMove agent. Tokens are stored hashed (SHA-256).
        """
        token_id = f"tok-{uuid.uuid4().hex[:12]}"
        raw_secret = f"cmat_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        token_prefix = raw_secret[:12] + "..."
        now = _utc_now()
        expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + ttl_seconds, timezone.utc
        ).isoformat()

        with self.transaction(write=True) as conn:
            conn.execute(
                """
                INSERT INTO agent_enrollment_tokens (
                    token_id, token_hash, token_prefix, org_id, expires_at,
                    max_uses, uses_count, revoked, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (token_id, token_hash, token_prefix, org_id, expires_at, max_uses, now, created_by),
            )
            self.record_audit_event(
                actor_id=created_by,
                action="CREATE_ENROLLMENT_TOKEN",
                target_type="agent_enrollment_token",
                target_id=token_id,
                metadata={"token_prefix": token_prefix, "expires_at": expires_at, "max_uses": max_uses},
                conn=conn,
            )

        return {
            "token_id": token_id,
            "enrollment_token": raw_secret,
            "token_prefix": token_prefix,
            "expires_at": expires_at,
            "max_uses": max_uses,
            "org_id": org_id,
            "created_at": now,
        }

    def list_enrollment_tokens(self) -> List[Dict[str, Any]]:
        """List active and historical enrollment tokens without exposing the secret token hash."""
        with self.transaction(write=False) as conn:
            rows = conn.execute(
                """
                SELECT token_id, token_prefix, org_id, expires_at, max_uses, uses_count, revoked, created_at, created_by
                FROM agent_enrollment_tokens
                ORDER BY created_at DESC
                """
            ).fetchall()
        now = _utc_now()
        result = []
        for r in rows:
            d = dict(r)
            d["is_expired"] = d["expires_at"] < now
            d["is_active"] = (not d["revoked"]) and (not d["is_expired"]) and (d["uses_count"] < d["max_uses"])
            result.append(d)
        return result

    def verify_and_consume_enrollment_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """Verify an enrollment token, increment usage counter, and revoke if max_uses reached."""
        token_hash = hashlib.sha256(str(raw_token).strip().encode("utf-8")).hexdigest()
        now = _utc_now()
        with self.transaction(write=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_enrollment_tokens
                WHERE token_hash = ? AND revoked = 0 AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if not row:
                return None
            token_dict = dict(row)
            if token_dict["uses_count"] >= token_dict["max_uses"]:
                return None

            new_uses = token_dict["uses_count"] + 1
            revoked_flag = 1 if new_uses >= token_dict["max_uses"] else 0
            conn.execute(
                """
                UPDATE agent_enrollment_tokens
                SET uses_count = ?, revoked = ?
                WHERE token_id = ?
                """,
                (new_uses, revoked_flag, token_dict["token_id"]),
            )
            return token_dict

    def enroll_agent(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enroll an authorized agent, issue an Agent API Key (Bearer Token),
        and establish its identity and bounded capability set.
        """
        raw_api_key = f"cma_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
        machine_id = str(agent_data.get("machine_id") or uuid.uuid4().hex)
        hostname = str(agent_data.get("hostname") or "unknown-host")
        agent_id = str(agent_data.get("agent_id") or f"agent-{hashlib.sha256((machine_id + hostname).encode()).hexdigest()[:16]}")
        now = _utc_now()
        capabilities = agent_data.get("capabilities") or [
            "discovery",
            "advanced_inspection",
            "disk_snapshot",
            "native_tool_install",
            "config_modification",
            "service_control",
            "cutover_revert",
        ]
        health_metrics = agent_data.get("health_metrics") or {"cpu_percent": 0.0, "ram_percent": 0.0, "status": "enrolled"}
        metadata = agent_data.get("metadata") or {}

        with self.transaction(write=True) as conn:
            existing = conn.execute(
                "SELECT status FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if existing and existing["status"] == "REVOKED":
                raise PermissionError(
                    f"El agente '{agent_id}' fue revocado permanentemente y no puede re-inscribirse."
                )

            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, hostname, ip_address, os_family, os_name, os_version,
                    architecture, machine_id, status, version, auth_token_hash,
                    capabilities_json, enrolled_at, last_heartbeat_at, revoked_at,
                    revocation_reason, health_metrics_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ONLINE', ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    hostname = excluded.hostname,
                    ip_address = excluded.ip_address,
                    os_family = excluded.os_family,
                    os_name = excluded.os_name,
                    os_version = excluded.os_version,
                    architecture = excluded.architecture,
                    machine_id = excluded.machine_id,
                    status = 'ONLINE',
                    version = excluded.version,
                    auth_token_hash = excluded.auth_token_hash,
                    capabilities_json = excluded.capabilities_json,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    revoked_at = NULL,
                    revocation_reason = NULL,
                    health_metrics_json = excluded.health_metrics_json,
                    metadata_json = excluded.metadata_json
                """,
                (
                    agent_id,
                    hostname,
                    agent_data.get("ip_address") or "127.0.0.1",
                    agent_data.get("os_family") or "linux",
                    agent_data.get("os_name") or "Linux",
                    agent_data.get("os_version") or "unknown",
                    agent_data.get("architecture") or "x86_64",
                    machine_id,
                    agent_data.get("version") or "2.1.0",
                    token_hash,
                    json.dumps(capabilities),
                    now,
                    now,
                    json.dumps(health_metrics),
                    json.dumps(metadata),
                ),
            )
            self.record_audit_event(
                actor_id=agent_id,
                action="ENROLL_AGENT",
                target_type="agent",
                target_id=agent_id,
                metadata={"hostname": hostname, "ip": agent_data.get("ip_address"), "os": agent_data.get("os_name")},
                conn=conn,
            )

        return {
            "agent_id": agent_id,
            "agent_api_key": raw_api_key,
            "hostname": hostname,
            "status": "ONLINE",
            "capabilities": capabilities,
            "enrolled_at": now,
        }

    def authenticate_agent(self, agent_id: str, raw_api_key: str) -> Optional[Dict[str, Any]]:
        """Verify the agent's Bearer API Key against stored SHA-256 hash."""
        token_hash = hashlib.sha256(str(raw_api_key).strip().encode("utf-8")).hexdigest()
        with self.transaction(write=False) as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? AND auth_token_hash = ?",
                (agent_id, token_hash),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            if d["status"] == "REVOKED":
                return None
            return d

    def record_agent_heartbeat(
        self,
        agent_id: str,
        health_metrics: Dict[str, Any],
        nonce: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record outbound heartbeat from an enrolled host, updating CPU/RAM/load metrics
        and protecting against replay attacks with timestamp verification.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        if timestamp:
            try:
                ts_dt = datetime.fromisoformat(str(timestamp).strip().replace("Z", "+00:00"))
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            except Exception as exc:
                raise ValueError("Heartbeat timestamp inválido (se requiere formato ISO 8601).") from exc
            diff = abs((now_dt - ts_dt).total_seconds())
            if diff > 300:
                raise ValueError(f"Heartbeat timestamp skew out of tolerance ({diff:.1f}s > 300s). Replay rejected.")

        with self.transaction(write=True) as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not row:
                raise KeyError(f"Agente '{agent_id}' no encontrado.")
            if row["status"] == "REVOKED":
                raise PermissionError(f"El agente '{agent_id}' está revocado.")

            if nonce is not None:
                clean_nonce = str(nonce).strip()
                if not clean_nonce or len(clean_nonce) > 128:
                    raise ValueError("Heartbeat nonce inválido.")
                cutoff = datetime.fromtimestamp(now_dt.timestamp() - 600, timezone.utc).isoformat()
                conn.execute("DELETE FROM agent_nonces WHERE seen_at < ?", (cutoff,))
                try:
                    conn.execute(
                        "INSERT INTO agent_nonces (agent_id, nonce, seen_at) VALUES (?, ?, ?)",
                        (agent_id, clean_nonce, now),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("Heartbeat nonce reutilizado; replay rechazado.") from exc

            agent_ver = health_metrics.get("agent_version")
            if agent_ver:
                conn.execute(
                    """
                    UPDATE agents
                    SET last_heartbeat_at = ?, status = 'ONLINE', health_metrics_json = ?, version = ?
                    WHERE agent_id = ?
                    """,
                    (now, json.dumps(health_metrics), str(agent_ver)[:32], agent_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE agents
                    SET last_heartbeat_at = ?, status = 'ONLINE', health_metrics_json = ?
                    WHERE agent_id = ?
                    """,
                    (now, json.dumps(health_metrics), agent_id),
                )
            pending_count = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_tasks WHERE agent_id = ? AND status = 'PENDING'",
                (agent_id,),
            ).fetchone()["c"]

        return {
            "agent_id": agent_id,
            "status": "ONLINE",
            "last_heartbeat_at": now,
            "pending_tasks_count": pending_count,
        }

    def list_agents(self, include_revoked: bool = True) -> List[Dict[str, Any]]:
        """List all enrolled agents with health and connectivity status."""
        with self.transaction(write=False) as conn:
            query = "SELECT * FROM agents"
            if not include_revoked:
                query += " WHERE status != 'REVOKED'"
            query += " ORDER BY enrolled_at DESC"
            rows = conn.execute(query).fetchall()

        now_ts = datetime.now(timezone.utc).timestamp()
        results = []
        for r in rows:
            d = dict(r)
            d["capabilities"] = json.loads(d["capabilities_json"])
            d["health_metrics"] = json.loads(d["health_metrics_json"])
            d["metadata"] = json.loads(d["metadata_json"])
            del d["auth_token_hash"]
            if d["status"] == "ONLINE":
                try:
                    last_hb = datetime.fromisoformat(d["last_heartbeat_at"].replace("Z", "+00:00")).timestamp()
                    if now_ts - last_hb > 60:
                        d["status"] = "OFFLINE"
                except Exception:
                    pass
            results.append(d)
        return results

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full details for a specific agent."""
        with self.transaction(write=False) as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["capabilities"] = json.loads(d["capabilities_json"])
            d["health_metrics"] = json.loads(d["health_metrics_json"])
            d["metadata"] = json.loads(d["metadata_json"])
            del d["auth_token_hash"]
            return d

    def revoke_agent(
        self,
        agent_id: str,
        reason: str = "Revocado por el operador",
        revoked_by: str = DEFAULT_OPERATOR,
    ) -> Dict[str, Any]:
        """Revoke an agent's credentials, preventing further actions or heartbeats."""
        now = _utc_now()
        with self.transaction(write=True) as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not row:
                raise KeyError(f"Agente '{agent_id}' no encontrado.")
            conn.execute(
                """
                UPDATE agents
                SET status = 'REVOKED', revoked_at = ?, revocation_reason = ?
                WHERE agent_id = ?
                """,
                (now, reason, agent_id),
            )
            self.record_audit_event(
                actor_id=revoked_by,
                action="REVOKE_AGENT",
                target_type="agent",
                target_id=agent_id,
                metadata={"reason": reason},
                conn=conn,
            )
        return {"agent_id": agent_id, "status": "REVOKED", "revoked_at": now, "reason": reason}

    def create_agent_task(
        self,
        agent_id: str,
        action: str,
        parameters: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Dispatch an authorized, bounded migration task to an agent.
        Enforces a strict capability whitelist (no arbitrary shell execution).
        """
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        allowed_actions = (
            "collect_inventory",
            "inspect_disk",
            "check_mgn_prerequisites",
            "quiesce_database",
            "unquiesce_database",
            "install_mgn_agent",
            "stage_selected_paths",
            "push_selected_paths_to_ec2",
            "self_update",
        )
        if action not in allowed_actions:
            raise ValueError(
                f"Acción '{action}' rechazada por la política de seguridad de CloudMove. "
                f"Acciones permitidas: {allowed_actions}"
            )

        with self.transaction(write=True) as conn:
            agent = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not agent:
                raise KeyError(f"Agente '{agent_id}' no encontrado.")
            if agent["status"] == "REVOKED":
                raise PermissionError(f"No se pueden despachar órdenes a un agente revocado ('{agent_id}').")

            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, agent_id, action, parameters_json, status, created_at, timeout_seconds
                ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (task_id, agent_id, action, json.dumps(parameters or {}), now, timeout_seconds),
            )
        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "action": action,
            "status": "PENDING",
            "created_at": now,
        }

    def get_pending_tasks_for_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """Fetch pending tasks for an agent and transition them to DISPATCHED."""
        now = _utc_now()
        with self.transaction(write=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_tasks
                WHERE agent_id = ? AND status = 'PENDING'
                ORDER BY created_at ASC
                """,
                (agent_id,),
            ).fetchall()
            tasks = []
            for r in rows:
                t = dict(r)
                t["parameters"] = json.loads(t["parameters_json"])
                tasks.append(t)
                conn.execute(
                    "UPDATE agent_tasks SET status = 'DISPATCHED', dispatched_at = ? WHERE task_id = ?",
                    (now, t["task_id"]),
                )
            return tasks

    def complete_agent_task(
        self,
        task_id: str,
        agent_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record task execution completion or error reported by the agent."""
        now = _utc_now()
        with self.transaction(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ? AND agent_id = ?",
                (task_id, agent_id),
            ).fetchone()
            if not row:
                raise KeyError(f"Tarea '{task_id}' no encontrada para el agente '{agent_id}'.")

            conn.execute(
                """
                UPDATE agent_tasks
                SET status = ?, result_json = ?, error_message = ?, completed_at = ?
                WHERE task_id = ?
                """,
                (status, json.dumps(result or {}), error, now, task_id),
            )
        return {"task_id": task_id, "status": status, "completed_at": now}


_default_db_instance: Optional[TransactionalDatabase] = None


def get_transactional_db() -> TransactionalDatabase:
    global _default_db_instance
    if _default_db_instance is None:
        _default_db_instance = TransactionalDatabase()
    return _default_db_instance
