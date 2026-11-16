"""Versioned SQLite relational schema definitions and migration runner."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import List, Tuple

from app.core.text_utils import utc_now_iso

SCHEMA_MIGRATIONS: List[Tuple[str, str, str]] = [
    (
        "1.0.0",
        "Initial transactional tables for assets, migration_plans, and audit_events",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

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
            CHECK (target_provider IN ('aws')),
            CHECK (use_case IN ('app_source', 'vm_image'))
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
        "Add cloud_discovery_snapshots table for full restart recovery",
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
            CHECK (provider IN ('aws'))
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_snapshots_prov ON cloud_discovery_snapshots(provider, account_or_project, discovered_at);
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
    (
        "2.3.0",
        "Add agent_nonces table for heartbeat replay protection",
        """
        CREATE TABLE IF NOT EXISTS agent_nonces (
            agent_id TEXT NOT NULL,
            nonce TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY (agent_id, nonce),
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_nonces_seen ON agent_nonces(seen_at);
        """,
    ),
]


def apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Create schema_migrations tracking table and apply pending SQLite DDL migrations."""
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
    now = utc_now_iso()
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
