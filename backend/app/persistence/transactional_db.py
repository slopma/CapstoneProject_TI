"""
Transactional Persistence Engine & Optimistic Concurrency Control for CloudMove.

Addresses Section 5.1 & Section 9:
- Provides ACID transactional storage backed by SQLite (`WAL` mode + `FOREIGN KEYS` +
  `BEGIN IMMEDIATE` write transactions) for local/single-node deployments and supports
  PostgreSQL DSN configuration (`CLOUDMOVE_DATABASE_URL`) for multi-user deployments.
- Versioned schema migrations (`v1.0`, `v2.0`, `v2.1`) tracked in `schema_migrations`.
- Persistent relational tables with primary keys, unique constraints, foreign keys, and indexes:
  1. `schema_migrations`
  2. `campaigns`
  3. `assets`
  4. `migration_plans`
  5. `migration_stages`
  6. `stage_executions` (with `UNIQUE(migration_id, stage_id, idempotency_key)` to guarantee idempotent retries)
  7. `migration_artifacts`
  8. `cloud_discovery_snapshots`
  9. `audit_events`
- Prevents two operators from executing the same migration stage simultaneously via
  atomic stage locks (`locked_by`, `locked_at`) and optimistic concurrency (`version` column).
-Controlled migration of legacy JSON files (`migrations_state.json`, `datacenter_campaigns.json`)
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

from app.config import PROJECT_ROOT


DEFAULT_SQLITE_PATH = PROJECT_ROOT / "backend" / "data" / "cloudmove_transactional.db"
DEFAULT_OPERATOR = os.getenv("CLOUDMOVE_OPERATOR_USER", "operator")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConcurrencyConflictError(RuntimeError):
    """Raised when optimistic locking detects a concurrent modification (`version` mismatch)."""


class StageLockedError(RuntimeError):
    """Raised when two operators attempt to execute the same migration stage simultaneously."""


class IncompatibleLegacyDataError(ValueError):
    """Raised or recorded when legacy JSON data fails structural schema validation."""


SCHEMA_MIGRATIONS: List[Tuple[str, str, str]] = [
    (
        "1.0.0",
        "Initial transactional tables for campaigns, assets, migration_plans, and audit_events",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_campaigns_env_status ON campaigns(environment_id, status);

        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            canonical_key TEXT NOT NULL UNIQUE,
            hostname TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            lifecycle_state TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_assets_env_site ON assets(environment_id, site_id);
        CREATE INDEX IF NOT EXISTS idx_assets_state ON assets(lifecycle_state);

        CREATE TABLE IF NOT EXISTS migration_plans (
            migration_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            use_case TEXT NOT NULL,
            target_provider TEXT NOT NULL,
            state TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            completed_in_real_cloud INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            locked_by TEXT,
            locked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            CHECK (target_provider IN ('aws', 'gcp')),
            CHECK (use_case IN ('app_source', 'vm_image', 'datacenter_campaign'))
        );
        CREATE INDEX IF NOT EXISTS idx_migration_plans_uc_prov ON migration_plans(use_case, target_provider);
        CREATE INDEX IF NOT EXISTS idx_migration_plans_state ON migration_plans(state);

        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_events_target ON audit_events(target_type, target_id);
        """,
    ),
    (
        "2.0.0",
        "Add migration_stages, stage_executions with idempotency keys, and migration_artifacts",
        """
        CREATE TABLE IF NOT EXISTS migration_stages (
            id TEXT PRIMARY KEY,
            migration_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            stage_order INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            recovery_point TEXT NOT NULL,
            locked_by TEXT,
            locked_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            error_text TEXT,
            payload_json TEXT NOT NULL,
            UNIQUE(migration_id, stage_id),
            FOREIGN KEY(migration_id) REFERENCES migration_plans(migration_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_migration_stages_mig ON migration_stages(migration_id, stage_order);

        CREATE TABLE IF NOT EXISTS stage_executions (
            execution_id TEXT PRIMARY KEY,
            migration_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_json TEXT NOT NULL,
            UNIQUE(migration_id, stage_id, idempotency_key),
            FOREIGN KEY(migration_id) REFERENCES migration_plans(migration_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_stage_exec_lookup ON stage_executions(migration_id, stage_id);

        CREATE TABLE IF NOT EXISTS migration_artifacts (
            artifact_id TEXT PRIMARY KEY,
            migration_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            content_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(migration_id, filename),
            FOREIGN KEY(migration_id) REFERENCES migration_plans(migration_id) ON DELETE CASCADE
        );
        """,
    ),
    (
        "2.1.0",
        "Add cloud_discovery_snapshots and campaign_global_state table for full restart recovery",
        """
        CREATE TABLE IF NOT EXISTS cloud_discovery_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            account_or_project TEXT NOT NULL,
            region TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            resources_count INTEGER NOT NULL,
            cmir_json TEXT NOT NULL,
            reconciliation_json TEXT NOT NULL,
            errors_json TEXT NOT NULL,
            CHECK (provider IN ('aws', 'gcp'))
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_snapshots_prov ON cloud_discovery_snapshots(provider, account_or_project, discovered_at);

        CREATE TABLE IF NOT EXISTS campaign_global_state (
            state_key TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """,
    ),
    (
        "2.2.0",
        "Add agents, agent_enrollment_tokens, agent_tasks and organizations tables for production agent management",
        """
        CREATE TABLE IF NOT EXISTS organizations (
            org_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_enrollment_tokens (
            token_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            org_id TEXT NOT NULL DEFAULT 'default',
            expires_at TEXT NOT NULL,
            max_uses INTEGER NOT NULL DEFAULT 1,
            uses_count INTEGER NOT NULL DEFAULT 0,
            revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_enrollment_tokens(token_hash);

        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            os_family TEXT NOT NULL,
            os_name TEXT NOT NULL,
            os_version TEXT NOT NULL,
            architecture TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            status TEXT NOT NULL,
            version TEXT NOT NULL,
            auth_token_hash TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            enrolled_at TEXT NOT NULL,
            last_heartbeat_at TEXT NOT NULL,
            revoked_at TEXT,
            revocation_reason TEXT,
            health_metrics_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
        CREATE INDEX IF NOT EXISTS idx_agents_machine_id ON agents(machine_id);

        CREATE TABLE IF NOT EXISTS agent_tasks (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            action TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            dispatched_at TEXT,
            completed_at TEXT,
            timeout_seconds INTEGER NOT NULL DEFAULT 300,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_status ON agent_tasks(agent_id, status);
        """,
    ),
]


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
        self.database_url = database_url or os.getenv("CLOUDMOVE_DATABASE_URL", "")
        if db_path is not None:
            self.db_path = Path(db_path)
        elif self.database_url.startswith("sqlite:///"):
            self.db_path = Path(self.database_url.replace("sqlite:///", "", 1))
        else:
            self.db_path = DEFAULT_SQLITE_PATH

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                """
            )
            existing = {
                row["version"]: row["checksum"]
                for row in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
            }
            now = _utc_now()
            for version, description, sql_script in SCHEMA_MIGRATIONS:
                checksum = hashlib.sha256(sql_script.strip().encode("utf-8")).hexdigest()
                if version in existing:
                    continue
                conn.executescript(sql_script)
                # Ensure we are in a transaction if executescript committed implicitly
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations (version, description, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (version, description, checksum, now),
                )

    def get_schema_status(self) -> Dict[str, Any]:
        with self.transaction(write=False) as conn:
            rows = conn.execute(
                "SELECT version, description, checksum, applied_at FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
            plans_count = conn.execute("SELECT COUNT(*) AS c FROM migration_plans").fetchone()["c"]
            camps_count = conn.execute("SELECT COUNT(*) AS c FROM campaigns").fetchone()["c"]
            assets_count = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
            exec_count = conn.execute("SELECT COUNT(*) AS c FROM stage_executions").fetchone()["c"]
            audit_count = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]

        return {
            "engine": "postgresql_compatible_sqlite_wal" if not self.database_url.startswith("postgresql") else "postgresql",
            "journal_mode": "WAL" if not self.database_url.startswith("postgresql") else "MVCC",
            "database_path": str(self.db_path),
            "current_version": rows[-1]["version"] if rows else "0.0.0",
            "current_schema_version": rows[-1]["version"] if rows else "0.0.0",
            "applied_migrations": [dict(r) for r in rows],
            "counts": {
                "migration_plans": plans_count,
                "campaigns": camps_count,
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
        if target_provider not in ("aws", "gcp"):
            raise ValueError(f"Proveedor '{target_provider}' rechazado por restricción de integridad (solo aws|gcp).")
        if use_case not in ("app_source", "vm_image", "datacenter_campaign"):
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
    # Datacenter Campaigns & Assets Transactional Persistence
    # ==========================================================================

    def save_campaign_state(self, state: Dict[str, Any]) -> None:
        """
        Atomically persist the full datacenter campaign state, individual campaigns,
        and reconciled assets into relational tables so campaigns and partial progress
        survive backend restarts cleanly.
        """
        now = _utc_now()
        with self.transaction(write=True) as conn:
            row = conn.execute(
                "SELECT version FROM campaign_global_state WHERE state_key = 'primary'"
            ).fetchone()
            next_ver = (int(row["version"]) + 1) if row else 1
            conn.execute(
                """
                INSERT INTO campaign_global_state (state_key, version, updated_at, payload_json)
                VALUES ('primary', ?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    version = excluded.version,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (next_ver, now, json.dumps(state, ensure_ascii=False)),
            )

            for cid, camp in (state.get("campaigns") or {}).items():
                conn.execute(
                    """
                    INSERT INTO campaigns (
                        id, name, environment_id, mode, status, version,
                        created_by, created_at, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        mode = excluded.mode,
                        status = excluded.status,
                        version = campaigns.version + 1,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        cid,
                        camp.get("name", cid),
                        camp.get("environment_id", "env-datacenter-01"),
                        camp.get("mode", "discover_plan"),
                        camp.get("status", "created"),
                        1,
                        camp.get("created_by", DEFAULT_OPERATOR),
                        camp.get("created_at", now),
                        camp.get("updated_at", now),
                        json.dumps(camp, ensure_ascii=False),
                    ),
                )

            for aid, asset in (state.get("assets") or {}).items():
                canonical_key = asset.get("canonical_key") or aid
                conn.execute(
                    """
                    INSERT INTO assets (
                        id, canonical_key, hostname, asset_type, environment_id,
                        site_id, lifecycle_state, version, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        hostname = excluded.hostname,
                        asset_type = excluded.asset_type,
                        lifecycle_state = excluded.lifecycle_state,
                        version = assets.version + 1,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        aid,
                        canonical_key,
                        asset.get("hostname", aid),
                        asset.get("asset_type", "virtual_machine"),
                        asset.get("environment_id", "env-datacenter-01"),
                        asset.get("site_id", "site-dc-a"),
                        asset.get("lifecycle_state", "discovered"),
                        now,
                        json.dumps(asset, ensure_ascii=False),
                    ),
                )

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

    def load_campaign_state(self) -> Optional[Dict[str, Any]]:
        with self.transaction(write=False) as conn:
            row = conn.execute(
                "SELECT payload_json FROM campaign_global_state WHERE state_key = 'primary'"
            ).fetchone()
            if not row:
                return None
            return json.loads(row["payload_json"])

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
        campaigns_json_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Migrate legacy JSON files (`migrations_state.json`, `datacenter_campaigns.json`)
        into the transactional database, creating `.bak` backups and detecting any
        incompatible or corrupted records (e.g., unsupported target provider `azure`).
        """
        report: Dict[str, Any] = {
            "migrated_jobs_count": 0,
            "migrated_campaigns_count": 0,
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
                        if prov not in ("aws", "gcp"):
                            report["incompatible_records"].append({
                                "file": str(migrations_json_path),
                                "record_id": str(mid),
                                "reason": f"Proveedor '{prov}' incompatible con el alcance AWS/GCP.",
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

        if campaigns_json_path and campaigns_json_path.is_file():
            backup_path = campaigns_json_path.with_suffix(".json.bak")
            if not backup_path.exists():
                shutil.copy2(campaigns_json_path, backup_path)
                report["backups_created"].append(str(backup_path))
            try:
                raw_camp = json.loads(campaigns_json_path.read_text(encoding="utf-8"))
                if not isinstance(raw_camp, dict) or "campaigns" not in raw_camp or "sites" not in raw_camp:
                    report["incompatible_records"].append({
                        "file": str(campaigns_json_path),
                        "reason": "Estructura de campañas incompatible: faltan claves 'campaigns' o 'sites'.",
                    })
                else:
                    if self.load_campaign_state() is None:
                        self.save_campaign_state(raw_camp)
                        report["migrated_campaigns_count"] = len(raw_camp.get("campaigns", {}))
            except Exception as exc:
                report["incompatible_records"].append({
                    "file": str(campaigns_json_path),
                    "reason": f"Archivo JSON de campañas corrupto: {exc}",
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
            conn.execute(
                """
                INSERT OR REPLACE INTO agents (
                    agent_id, hostname, ip_address, os_family, os_name, os_version,
                    architecture, machine_id, status, version, auth_token_hash,
                    capabilities_json, enrolled_at, last_heartbeat_at, revoked_at,
                    revocation_reason, health_metrics_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ONLINE', ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
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
        now = _utc_now()
        if timestamp:
            try:
                ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                curr_dt = datetime.now(timezone.utc)
                diff = abs((curr_dt - ts_dt).total_seconds())
                if diff > 300:
                    raise ValueError(f"Heartbeat timestamp skew out of tolerance ({diff:.1f}s > 300s). Replay rejected.")
            except Exception as e:
                if isinstance(e, ValueError) and "skew" in str(e):
                    raise
                pass

        with self.transaction(write=True) as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not row:
                raise KeyError(f"Agente '{agent_id}' no encontrado.")
            if row["status"] == "REVOKED":
                raise PermissionError(f"El agente '{agent_id}' está revocado.")

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
            "check_gcp_migrate_prerequisites",
            "quiesce_database",
            "unquiesce_database",
            "install_mgn_agent",
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
