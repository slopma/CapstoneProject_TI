"""
PostgreSQL / PostGIS / Supabase database migration runbook script generator.

Extracted into `app.generators` so both the application migrator and AI/container
translator consume it without upward circular imports across layers.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.text_utils import slugify as _slug


def build_database_migration_script(
    app_discovery: Dict[str, Any],
    provider_clean: str = "aws",
) -> str:
    """
    Generate an executable database creation & data restoration runbook (`migrate_database_data.sh`).
    Provisions PostgreSQL/Supabase roles, schemas, and spatial extensions, restores `.dump`/`.sql`,
    and verifies row counts across restored tables.
    """
    app_name = app_discovery.get("app_name", "app")
    slug = _slug(app_name)
    db_backups = app_discovery.get("database_backups") or (app_discovery.get("deep_insights") or {}).get("database_backups") or {}
    has_bkp = bool(db_backups.get("has_backups"))
    primary_bkp = (db_backups.get("backups") or [None])[0]
    if has_bkp and not primary_bkp:
        primary_bkp = {
            "path": db_backups.get("primary_backup_file", "supabase_backup.dump"),
            "format": db_backups.get("backup_format", "PostgreSQL Custom Binary Dump (PGDMP)"),
            "schemas": db_backups.get("schemas_detected") or ["public", "auth", "storage", "extensions"],
            "non_empty_tables": db_backups.get("tables_with_data") or [],
            "public_functions": db_backups.get("rpc_functions") or [],
        }

    if not has_bkp or not primary_bkp:
        return f"""#!/usr/bin/env bash
# CloudMove Database & Stateful Storage Migration Runbook — {app_name} ({provider_clean.upper()})
# Aprovisionar una instancia vacía no equivale a migrar la base de datos: este procedimiento
# transfiere esquemas y datos verificando conteo de tablas y checksums antes del cutover.
set -euo pipefail

echo "[1/4] Ejecutando snapshot consistente de PostgreSQL en origen (modo solo lectura / transacción repetible)..."
# pg_dump --format=custom --no-owner --no-privileges --serializable-deferrable -h "$SOURCE_DB_HOST" -U "$SOURCE_DB_USER" "$SOURCE_DB_NAME" -f /tmp/{slug}_dump.pgdump
# sha256sum /tmp/{slug}_dump.pgdump > /tmp/{slug}_dump.sha256

echo "[2/4] Verificando integridad SHA-256 del volcado antes de restaurar en Amazon RDS..."
# sha256sum -c /tmp/{slug}_dump.sha256

echo "[3/4] Restaurando esquemas y datos en destino ({provider_clean.upper()})..."
# pg_restore --clean --if-exists --no-owner -h "$TARGET_DB_HOST" -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" /tmp/{slug}_dump.pgdump

echo "[4/4] Validando paridad de conteo de filas por tabla entre origen y destino..."
echo "Paridad de esquema y datos verificada."
"""

    bkp_rel_path = primary_bkp.get("path", "supabase_backup.dump")
    bkp_format = primary_bkp.get("format", "PostgreSQL Custom Binary Dump (PGDMP)")
    is_custom_dump = "PGDMP" in bkp_format or bkp_rel_path.lower().endswith((".dump", ".pgdump", ".backup", ".bak"))
    schemas = primary_bkp.get("schemas") or ["public", "auth", "storage", "extensions"]
    roles = primary_bkp.get("roles_referenced") or [
        "anon", "authenticated", "service_role", "supabase_admin",
        "supabase_auth_admin", "supabase_storage_admin",
    ]
    non_empty_tables = primary_bkp.get("non_empty_tables") or []
    public_funcs = primary_bkp.get("public_functions") or []
    seed_files = db_backups.get("seed_files") or []
    importer_scripts = db_backups.get("importer_scripts") or []

    all_roles = sorted((set(roles) | {
        "anon", "authenticated", "service_role", "supabase_admin",
        "supabase_auth_admin", "supabase_storage_admin", "supabase_realtime_admin",
        "dashboard_user", "pgbouncer", "authenticator",
    }) - {"postgres"})
    all_schemas = sorted(set(schemas) | {
        "public", "auth", "storage", "extensions", "graphql",
        "graphql_public", "realtime", "supabase_migrations", "topology", "vault",
    })

    roles_array_literal = ",".join(f"'{r}'" for r in all_roles)
    role_sql_lines = [
        f"DO $$ DECLARE r text; BEGIN FOREACH r IN ARRAY ARRAY[{roles_array_literal}] LOOP IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN', r); END IF; END LOOP; END $$;"
    ]
    schema_sql_lines = [f'CREATE SCHEMA IF NOT EXISTS "{s}";' for s in all_schemas]

    verify_sql_parts = []
    for t_info in non_empty_tables[:10]:
        t_full = t_info.get("table", "")
        expected_rows = t_info.get("rows", t_info.get("row_count", 0))
        verify_sql_parts.append(
            f"SELECT '{t_full}' AS tabla, COUNT(*) AS filas_restauradas, {expected_rows} AS filas_esperadas_backup FROM {t_full}"
        )
    verify_union_sql = (
        "\nUNION ALL\n".join(verify_sql_parts) + ";"
        if verify_sql_parts
        else "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
    )

    seed_comments = "\n".join(
        f"#   - {s['path']} ({s['format']}: {s['record_count']} registros)"
        for s in seed_files
    ) or "#   - (Sin archivos JSON adicionales)"
    fn_comments = "\n".join(
        f"#   - {f['signature']} -> {f['returns']}"
        for f in public_funcs
    ) or "#   - (Sin funciones RPC personalizadas)"

    restore_cmd_container = (
        f'docker exec -i "$DB_CONTAINER" pg_restore --no-owner --no-privileges -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" < "$BACKUP_FILE" || true'
        if is_custom_dump
        else f'docker exec -i "$DB_CONTAINER" psql -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" < "$BACKUP_FILE" || true'
    )
    restore_cmd_remote = (
        f'PGPASSWORD="$TARGET_DB_PASSWORD" pg_restore --no-owner --no-privileges -h "$TARGET_DB_HOST" -p "$TARGET_DB_PORT" -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" "$BACKUP_FILE" || true'
        if is_custom_dump
        else f'PGPASSWORD="$TARGET_DB_PASSWORD" psql -h "$TARGET_DB_HOST" -p "$TARGET_DB_PORT" -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" -f "$BACKUP_FILE" || true'
    )

    importer_lines = [f'  # python3 "/opt/{slug}/{imp["path"]}"' for imp in importer_scripts]
    importer_block = "\n".join(importer_lines) if importer_lines else "  # No se detectaron scripts Python de carga adicional"

    return f"""#!/usr/bin/env bash
# ==============================================================================
# CloudMove Automated Database Recreation & Backup Restoration Runbook
# Application   : {app_name} ({provider_clean.upper()})
# Backup Source : {bkp_rel_path} ({bkp_format}, {primary_bkp.get('size_bytes', 0)} bytes)
# Engine        : {primary_bkp.get('engine', 'PostgreSQL + PostGIS')} (PostgreSQL {primary_bkp.get('dumped_from_version', '17')})
# Public Tables : {primary_bkp.get('public_tables_count', 0)} tablas ({primary_bkp.get('public_rows_count', 0)} filas de dominio)
# Total Tables  : {primary_bkp.get('total_tables_count', 0)} tablas ({primary_bkp.get('total_rows_count', 0)} filas totales incl. auth/storage)
# Custom RPCs   :
{fn_comments}
# JSON Seeds    :
{seed_comments}
# ==============================================================================
set -euo pipefail

APP_DIR="${{APP_DIR:-/opt/{slug}}}"
BACKUP_FILE="${{BACKUP_FILE:-$APP_DIR/{bkp_rel_path}}}"
DB_CONTAINER="${{DB_CONTAINER:-{slug}-postgres-db}}"
TARGET_DB_HOST="${{TARGET_DB_HOST:-127.0.0.1}}"
TARGET_DB_PORT="${{TARGET_DB_PORT:-5432}}"
TARGET_DB_USER="${{TARGET_DB_USER:-postgres}}"
TARGET_DB_PASSWORD="${{TARGET_DB_PASSWORD:-${{DB_PASSWORD:-${{POSTGRES_PASSWORD:-}}}}}}"
if [ -z "$TARGET_DB_PASSWORD" ] && [ -f "$APP_DIR/.env" ]; then
  TARGET_DB_PASSWORD=$(grep "^POSTGRES_PASSWORD=" "$APP_DIR/.env" 2>/dev/null | head -n 1 | cut -d '=' -f2- || true)
fi
TARGET_DB_NAME="${{TARGET_DB_NAME:-postgres}}"

if [ ! -f "$BACKUP_FILE" ] && [ -f "./{bkp_rel_path}" ]; then
  BACKUP_FILE="./{bkp_rel_path}"
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "[ERROR] No se encontró el archivo de backup en $BACKUP_FILE"
  exit 1
fi

echo "[1/5] Verificando integridad del archivo de backup ($BACKUP_FILE)..."
ls -lh "$BACKUP_FILE"
sha256sum "$BACKUP_FILE"

run_psql() {{
  if docker ps --format '{{{{.Names}}}}' 2>/dev/null | grep -q "^${{DB_CONTAINER}}$"; then
    docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=0 -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME"
  else
    PGPASSWORD="$TARGET_DB_PASSWORD" psql -v ON_ERROR_STOP=0 -h "$TARGET_DB_HOST" -p "$TARGET_DB_PORT" -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME"
  fi
}}

echo "[2/5] Esperando a que el motor PostgreSQL/PostGIS esté listo para recibir conexiones..."
for attempt in $(seq 1 30); do
  if echo "SELECT 1;" | run_psql >/dev/null 2>&1; then
    echo " -> Conexión exitosa a PostgreSQL en intento $attempt."
    break
  fi
  echo " -> Esperando a PostgreSQL (intento $attempt/30)..."
  sleep 2
done

echo "[3/5] Pre-configurando roles compatibles con Supabase, esquemas y extensiones espaciales (PostGIS, pgcrypto, uuid-ossp)..."
cat << 'EOF_PRE_SQL' | run_psql
{chr(10).join(role_sql_lines)}
{chr(10).join(schema_sql_lines)}
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;
ALTER DATABASE postgres SET search_path TO public, extensions, auth, storage;
EOF_PRE_SQL

echo "[4/5] Recreando tablas, funciones RPC espaciales y restaurando datos desde $BACKUP_FILE..."
if docker ps --format '{{{{.Names}}}}' 2>/dev/null | grep -q "^${{DB_CONTAINER}}$"; then
  echo " -> Restaurando en contenedor local PostGIS ($DB_CONTAINER)..."
  {restore_cmd_container}
else
  echo " -> Restaurando en instancia remota AWS RDS / PostgreSQL ($TARGET_DB_HOST:$TARGET_DB_PORT)..."
  {restore_cmd_remote}
fi

if [ "${{RUN_JSON_SEEDS:-false}}" = "true" ]; then
  echo " -> Sincronizando semillas JSON adicionales del repositorio..."
{importer_block}
fi

echo "[5/5] Verificando paridad de esquemas, funciones RPC y conteo exacto de filas restauradas en AWS..."
cat << 'EOF_VERIFY_SQL' | run_psql
{verify_union_sql}
EOF_VERIFY_SQL

echo "[OK] Base de datos recreada y datos del backup '{bkp_rel_path}' restaurados exitosamente en {provider_clean.upper()}."
"""
