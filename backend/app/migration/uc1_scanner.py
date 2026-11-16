"""
Static Application & Database Backup Scanner for CloudMove Use Case 1 (`app_source`).

Strictly read-only static discovery across Python, Node.js, Java, Go, Docker/Compose,
runtime metadata, GitHub archives, and PostgreSQL/PostGIS dumps without touching
CMIR, dependency graphs, or Terraform adapters.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import zlib
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.text_utils import slugify as _slug, utc_now_iso as _utc_now
from app.discovery.connectors import SecretRedactor
from app.discovery.github_connector import (
    LANGUAGE_EXTENSIONS,
    MANIFEST_NAMES,
    build_hierarchical_tree,
    get_manifest_type,
    is_manifest_file,
)

DEFAULT_INLINE_APP: Dict[str, str] = {
    "app_manifest.yaml": (
        "name: app\n"
        "version: '1.0.0'\n"
        "description: 'CloudMove Generic Microservice'\n"
        "runtime: 'python:3.11'\n"
        "entrypoint: 'uvicorn app.main:app --host 0.0.0.0 --port 8080'\n"
    ),
    "requirements.txt": "fastapi==0.110.0\nuvicorn==0.27.0\nboto3==1.34.0\npsycopg2-binary==2.9.9\nredis==5.0.1\n",
    "docker-compose.yml": (
        "version: '3.8'\n"
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    ports:\n"
        "      - '8080:8080'\n"
        "    environment:\n"
        "      - DB_PASS=${DB_PASSWORD}\n"
        "      - STRIPE_SECRET_KEY=${STRIPE_API_KEY}\n"
        "      - JWT_SECRET=${JWT_SIGNING_SECRET}\n"
        "      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/appdb\n"
        "      - REDIS_URL=redis://redis:6379/0\n"
        "      - APP_BUCKET=app-storage-bucket\n"
        "      - EXTERNAL_API_URL=https://api.external-service.com/v1\n"
        "  postgres:\n"
        "    image: postgres:15\n"
        "  redis:\n"
        "    image: redis:7\n"
    ),
    "main.py": (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'healthy'}\n"
    ),
}

SECRET_KEY_PATTERNS = re.compile(
    r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH_KEY|CLIENT_SECRET|DB_PASS|ANON_KEY|SERVICE_ROLE_KEY|SUPABASE_KEY|_KEY$)",
    re.IGNORECASE,
)
JWT_VALUE_PATTERN = re.compile(r"^eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+$")
URL_CREDENTIAL_PATTERN = re.compile(r"([a-zA-Z0-9+.-]+://[^:/\s]+:)([^@\s]+)(@)")


def _sanitize_app_name(candidate: Optional[str], fallback: str = "discovered-application") -> str:
    """
    Prevent accidental API tokens / GitHub PATs (e.g. `ghp_...`, `github_pat_...`)
    from being used as the workload or application name.
    """
    val = str(candidate or "").strip()
    if not val:
        return fallback
    low = val.lower()
    if low.startswith(("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_", "glpat-")) or SECRET_KEY_PATTERNS.search(val):
        return fallback
    if len(val) >= 32 and re.match(r"^[a-zA-Z0-9_]+$", val) and any(c.isdigit() for c in val) and any(c.isupper() for c in val):
        return fallback
    return val


def redact_env_value(key: str, raw_value: str) -> Dict[str, Any]:
    """
    Preserve the environment variable name and structural classification while
    redacting any credential, password, token, private key, JWT, or connection URI password.
    Never stores raw `.env` secret values in CMIR or discovery outputs.
    """
    val = str(raw_value or "").strip().strip('"').strip("'")
    is_secret = bool(SECRET_KEY_PATTERNS.search(key)) or bool(JWT_VALUE_PATTERN.match(val))
    contains_inline_cred = bool(URL_CREDENTIAL_PATTERN.search(val))
    contains_pem = "PRIVATE KEY" in val.upper()

    if is_secret or contains_pem:
        safe_val = "[REDACTED_SECRET]"
        redacted = True
    elif contains_inline_cred:
        safe_val = URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED_SECRET]\3", val)
        redacted = True
    else:
        redacted_res = SecretRedactor.redact_text(val)
        safe_val = redacted_res[0] if isinstance(redacted_res, tuple) else str(redacted_res)
        redacted = safe_val != val

    return {
        "name": key,
        "redacted_value": safe_val,
        "is_secret": is_secret or redacted,
        "value_stored": False if (is_secret or redacted) else True,
    }


def inspect_application_source(
    source_path: Optional[str] = None,
    inline_files: Optional[Dict[str, str]] = None,
    runtime_metadata: Optional[Dict[str, Any]] = None,
    app_name_override: Optional[str] = None,
    github_url: Optional[str] = None,
    github_ref: Optional[str] = None,
    github_token: Optional[str] = None,
    catalog_builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Perform static evidence-based analysis (without executing source code) across Python,
    Node.js, Java (Maven/Gradle), Go, Dockerfile/Compose, authorized runtime process descriptors,
    or verified GitHub repositories (public or private with token).
    """
    if github_url:
        from app.discovery.github_connector import GitHubConnector
        gh = GitHubConnector(token=github_token)
        with gh.ephemeral_checkout(github_url, ref=github_ref, token=github_token) as (checkout_path, pinned):
            git_meta = {
                "repository_url": github_url,
                "owner": pinned["owner"],
                "repo": pinned["repo"],
                "ref": pinned["ref"],
                "commit_sha": pinned["commit_sha"],
                "short_sha": pinned["short_sha"],
                "commit_message": pinned["commit_message"],
                "author_name": pinned["author_name"],
                "author_date": pinned["author_date"],
                "pinned_at": pinned["pinned_at"],
            }
            return _analyze_source_payload(
                target_dir=checkout_path,
                inline_files=None,
                runtime_metadata=runtime_metadata,
                app_name_override=_sanitize_app_name(app_name_override, fallback=pinned["repo"]),
                git_meta=git_meta,
                catalog_builder=catalog_builder,
            )

    if not source_path and not inline_files:
        inline_files = DEFAULT_INLINE_APP

    target_dir = None
    if source_path:
        target_dir = Path(source_path).expanduser().resolve()
        if not target_dir.exists():
            raise FileNotFoundError(f"La ruta de origen especificada no existe: {source_path}")

    fallback_name = target_dir.name if target_dir else "discovered-application"
    return _analyze_source_payload(
        target_dir=target_dir,
        inline_files=inline_files,
        runtime_metadata=runtime_metadata,
        app_name_override=_sanitize_app_name(app_name_override, fallback=fallback_name) if app_name_override else None,
        git_meta=None,
        catalog_builder=catalog_builder,
    )


def scan_local_filesystem_tree(target_dir: Path) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Recursively inspect an unpacked repository or local directory.
    Discovers all folders, subfolders, files, extensions, and sizes.
    Builds the hierarchical tree and reads key manifest files across all subdirectories.
    """
    ignore_dirs = {
        ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        "node_modules", ".idea", ".vscode", "dist", "build", ".next",
        "target", "bin", "obj", ".pytest_cache", ".mypy_cache"
    }

    tree_items: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    directories: List[str] = []
    ext_counter: Dict[str, int] = {}
    ext_bytes: Dict[str, int] = {}
    total_size = 0
    key_manifests: List[Dict[str, Any]] = []
    manifests_content: Dict[str, str] = {}

    for root, dirnames, filenames in os.walk(target_dir):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".git")]

        rel_root = os.path.relpath(root, target_dir)
        if rel_root != ".":
            norm_rel_root = rel_root.replace("\\", "/")
            directories.append(norm_rel_root)
            tree_items.append({"path": norm_rel_root, "type": "tree"})

        for f in filenames:
            fpath = Path(root) / f
            rel_file = os.path.relpath(fpath, target_dir).replace("\\", "/")
            try:
                size = fpath.stat().st_size
            except Exception:
                size = 0
            total_size += size

            ext = ("." + f.rsplit(".", 1)[-1].lower()) if "." in f else ""
            lang = LANGUAGE_EXTENSIONS.get(ext, "Other" if ext else "Plain Text")
            is_manifest = is_manifest_file(f)

            tree_items.append({
                "path": rel_file,
                "type": "blob",
                "size": size,
            })
            file_item = {
                "path": rel_file,
                "name": f,
                "size": size,
                "extension": ext,
                "language": lang,
                "is_manifest": is_manifest,
            }
            files.append(file_item)

            if is_manifest:
                m_type = get_manifest_type(f)
                key_manifests.append({
                    "path": rel_file,
                    "name": f,
                    "manifest_type": m_type,
                    "size": size,
                })
                # Read text content safely (up to 1MB), skipping binary database dumps
                if m_type != "database_backup" and ext not in (".dump", ".pgdump", ".backup", ".bak", ".sqlite", ".sqlite3"):
                    try:
                        if size <= 1_048_576:
                            content = fpath.read_text(encoding="utf-8", errors="replace")
                            manifests_content[rel_file] = content
                            if f not in manifests_content:
                                manifests_content[f] = content
                    except Exception:
                        pass

            ext_key = lang if lang != "Other" else (ext.upper() if ext else "Other")
            ext_counter[ext_key] = ext_counter.get(ext_key, 0) + 1
            ext_bytes[ext_key] = ext_bytes.get(ext_key, 0) + size

    languages = []
    for lang_name, count in sorted(ext_counter.items(), key=lambda x: x[1], reverse=True):
        b = ext_bytes.get(lang_name, 0)
        pct = round((count / len(files)) * 100, 1) if files else 0.0
        pct_bytes = round((b / total_size) * 100, 1) if total_size > 0 else 0.0
        languages.append({
            "language": lang_name,
            "file_count": count,
            "bytes": b,
            "percentage_files": pct,
            "percentage_bytes": pct_bytes,
        })

    hierarchical = build_hierarchical_tree(tree_items, root_name=target_dir.name)

    tree_result = {
        "summary": {
            "total_files": len(files),
            "total_directories": len(directories),
            "total_size_bytes": total_size,
            "languages": languages,
            "key_manifests_count": len(key_manifests),
        },
        "directories": sorted(directories),
        "files_sample": files[:250],
        "key_manifests": key_manifests,
        "hierarchical_tree": hierarchical,
    }
    return tree_result, manifests_content


_COMPOSE_INTERP_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?|-|\?)([^}]*))?\}")


def _parse_env_defaults(
    target_dir: Optional[Path],
    files_map: Dict[str, str],
) -> Dict[str, str]:
    """Read `.env.example` and `.env` manifests in precedence order to resolve Compose variables."""
    defaults: Dict[str, str] = {}
    candidates: List[Tuple[int, str, str]] = []
    for k, content in files_map.items():
        base = k.rsplit("/", 1)[-1]
        if base in (".env.example", ".env", ".env.local.example"):
            depth = k.count("/")
            # Lower rank processed first; root `.env` overrides `.env.example` and nested files.
            priority = (2 if base == ".env" else 1) - (depth * 10)
            candidates.append((priority, k, content))

    if target_dir and target_dir.exists():
        for fname, prio in ((".env.example", 1), (".env", 2)):
            fpath = target_dir / fname
            if fpath.is_file():
                try:
                    candidates.append((prio + 5, fname, fpath.read_text(encoding="utf-8", errors="replace")))
                except Exception:
                    pass

    for _, _, text in sorted(candidates, key=lambda item: item[0]):
        for raw_line in text.splitlines():
            s = raw_line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, val = s.split("=", 1)
            key = key.strip()
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                continue
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            defaults[key] = val
    return defaults


def _resolve_compose_interpolations(text: str, env_defaults: Dict[str, str]) -> str:
    """Resolve Docker Compose `${VAR}`, `${VAR:-default}`, and `${VAR:?msg}` placeholders."""
    if not text or "${" not in text:
        return text

    def _sub(match: re.Match[str]) -> str:
        var_name = match.group(1)
        op = match.group(2)
        fallback = match.group(3) or ""
        if var_name in env_defaults and env_defaults[var_name] != "":
            return env_defaults[var_name]
        if op in (":-", "-") and fallback:
            return fallback
        if var_name in env_defaults:
            return env_defaults[var_name]
        return match.group(0)

    resolved = text
    for _ in range(3):
        updated = _COMPOSE_INTERP_RE.sub(_sub, resolved)
        if updated == resolved:
            break
        resolved = updated
    return resolved


def _extract_compose_service_ports(
    sblock: str,
    env_defaults: Dict[str, str],
) -> Tuple[List[int], List[int]]:
    """Extract resolved `(host_ports, container_ports)` from a Compose service block."""
    resolved_block = _resolve_compose_interpolations(sblock, env_defaults)
    host_ports: List[int] = []
    container_ports: List[int] = []

    for m in re.finditer(
        r'^\s*-\s*["\']?(?:[0-9.]+:)?(\d{2,5}):(\d{2,5})(?:/[a-zA-Z]+)?["\']?\s*(?:#.*)?$',
        resolved_block,
        re.MULTILINE,
    ):
        hp, cp = int(m.group(1)), int(m.group(2))
        if hp not in host_ports:
            host_ports.append(hp)
        if cp not in container_ports:
            container_ports.append(cp)

    if not container_ports:
        ports_sec = re.search(r"^\s+ports:\s*\n((?:\s+-.*\n?)+)", resolved_block, re.MULTILINE)
        if ports_sec:
            for m in re.finditer(r'-\s*["\']?(\d{2,5})(?:/[a-zA-Z]+)?["\']?\s*$', ports_sec.group(1), re.MULTILINE):
                p = int(m.group(1))
                if p not in container_ports:
                    container_ports.append(p)
    return host_ports, container_ports


def _extract_compose_depends_on(sblock: str) -> List[str]:
    """Parse both list-style and condition-dict `depends_on` declarations."""
    deps: List[str] = []
    dep_sec = re.search(r"^(\s+)depends_on:\s*\n((?:\1[ \t]+.*\n?)+)", sblock, re.MULTILINE)
    if not dep_sec:
        return deps
    base_indent = len(dep_sec.group(1))
    for raw_line in dep_sec.group(2).splitlines():
        list_m = re.match(r"^\s*-\s*([a-zA-Z0-9_.-]+)\s*$", raw_line)
        if list_m:
            if list_m.group(1) not in deps:
                deps.append(list_m.group(1))
            continue
        dict_m = re.match(r"^(\s+)([a-zA-Z0-9_.-]+):\s*(?:#.*)?$", raw_line)
        if dict_m and len(dict_m.group(1)) <= base_indent + 4:
            if dict_m.group(2) not in deps:
                deps.append(dict_m.group(2))
    return deps


def _infer_service_endpoints(
    components: List[Dict[str, Any]],
    ports: List[int],
    health_endpoints: List[str],
) -> Dict[str, Any]:
    """Derive primary frontend port, backend port, and healthcheck path from discovered topology."""
    non_db_ports = [p for p in ports if isinstance(p, int) and p not in (22, 5432, 3306, 6379, 27017, 5672)]

    fe_comp = next((c for c in components if c.get("tier") == "frontend"), None)
    be_comp = next((c for c in components if c.get("tier") == "backend"), None)

    fe_port: Optional[int] = None
    if fe_comp:
        fe_candidates = fe_comp.get("host_ports") or fe_comp.get("container_ports") or []
        if fe_candidates:
            fe_port = int(fe_candidates[0])
    if fe_port is None:
        for preferred in (3000, 8080, 80, 5173, 4200):
            if preferred in non_db_ports:
                fe_port = preferred
                break
    if fe_port is None and non_db_ports:
        fe_port = int(non_db_ports[0])

    be_port: Optional[int] = None
    if be_comp:
        be_candidates = be_comp.get("host_ports") or be_comp.get("container_ports") or []
        if be_candidates:
            be_port = int(be_candidates[0])
    if be_port is None:
        for preferred in (8000, 5001, 5000, 8080, 4000):
            if preferred in non_db_ports and preferred != fe_port:
                be_port = preferred
                break
    if be_port is None:
        other_ports = [p for p in non_db_ports if p != fe_port]
        be_port = int(other_ports[0]) if other_ports else (fe_port if fe_port is not None else 8000)

    return {
        "frontend_port": int(fe_port if fe_port is not None else 3000),
        "backend_port": int(be_port if be_port is not None else 8000),
        "health_endpoint": (health_endpoints or ["/health"])[0],
    }


def discover_app_components_and_code(
    target_dir: Optional[Path],
    files_map: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Deeply inspect repository tree, subfolders, manifests (including all docker-compose*.yml),
    Python files (FastAPI/Flask routers, endpoints, ORM, migrations), TypeScript/JavaScript
    files (React Vite, Next.js, API calls, Supabase SDK), and detect multi-service topology.
    """
    components: List[Dict[str, Any]] = []
    deep_insights: Dict[str, Any] = {
        "architecture_pattern": "single_tier",
        "has_docker_compose": False,
        "compose_file": None,
        "supabase_detected": False,
        "supabase_details": {},
        "alembic_detected": False,
        "internal_service_links": [],
        "discovered_endpoints": [],
        "discovered_api_calls": [],
    }

    # 1. Identify compose files
    compose_keys = [k for k in files_map.keys() if "compose" in k.lower() and (k.endswith(".yml") or k.endswith(".yaml"))]
    if not compose_keys and target_dir and target_dir.exists():
        found = list(target_dir.glob("docker-compose*.yml")) + list(target_dir.glob("docker-compose*.yaml")) + list(target_dir.glob("compose*.yml"))
        if found:
            rel = str(found[0].relative_to(target_dir)).replace("\\", "/")
            compose_keys = [rel]
            try:
                files_map[rel] = found[0].read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

    env_defaults = _parse_env_defaults(target_dir, files_map)

    if compose_keys:
        deep_insights["has_docker_compose"] = True
        deep_insights["compose_file"] = compose_keys[0]
        compose_text = files_map[compose_keys[0]]

        in_services = False
        current_svc = None
        service_blocks: Dict[str, List[str]] = {}
        for line in compose_text.splitlines():
            sline = line.rstrip()
            if sline.strip().startswith("services:"):
                in_services = True
                continue
            if in_services:
                m = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", sline)
                if m:
                    current_svc = m.group(1)
                    service_blocks[current_svc] = []
                elif current_svc:
                    if re.match(r"^[^\s]", sline):
                        in_services = False
                        current_svc = None
                    else:
                        service_blocks[current_svc].append(sline)

        compose_services_meta: List[Dict[str, Any]] = []
        for sname, slines in service_blocks.items():
            sblock = "\n".join(slines)
            ctx_m = re.search(r"^\s+context:\s*([^\s#]+)", sblock, re.MULTILINE)
            inline_build_m = re.search(r"^\s+build:\s*([^\s#{\n]+)", sblock, re.MULTILINE)
            has_build_dir = bool(re.search(r"^\s+build:\s*(?:$|\S)", sblock, re.MULTILINE))
            df_m = re.search(r"dockerfile:\s*([^\s#]+)", sblock)
            img_m = re.search(r"^\s+image:\s*([^\s#]+)", sblock, re.MULTILINE)
            resolved_img = _resolve_compose_interpolations(img_m.group(1), env_defaults) if img_m else None

            h_ports, c_ports = _extract_compose_service_ports(sblock, env_defaults)
            deps = _extract_compose_depends_on(sblock)

            raw_ctx = ctx_m.group(1) if ctx_m else (inline_build_m.group(1) if inline_build_m else None)
            ctx_clean = (
                raw_ctx.lstrip("./").strip("/") if raw_ctx and raw_ctx != "." else (
                    "." if raw_ctx == "." else (sname if has_build_dir else None)
                )
            )
            if ctx_clean is not None and not ctx_clean:
                ctx_clean = "."

            # Only treat services with a build context (or an actual local build directory)
            # as source components; prebuilt image infrastructure services (postgres, bootstrap, redis)
            # do not have `./<service>` build directories in the repository.
            local_dir_exists = bool(
                target_dir
                and (target_dir / (ctx_clean or sname)).is_dir()
                and any(
                    ((target_dir / (ctx_clean or sname)) / mf).exists()
                    for mf in ("Dockerfile", "package.json", "requirements.txt", "pyproject.toml", "pom.xml", "go.mod")
                )
            )
            files_prefix = f"{(ctx_clean or sname).rstrip('/')}/"
            in_files_map = ctx_clean == "." or any(k.startswith(files_prefix) for k in files_map)
            is_buildable = bool(has_build_dir or local_dir_exists or (raw_ctx and in_files_map))

            tier = "service"
            sname_lower = sname.lower()
            img_lower = (resolved_img or "").lower()
            if any(w in sname_lower for w in ("back", "api", "server", "srv", "backend")):
                tier = "backend"
            elif any(w in sname_lower for w in ("front", "ui", "web", "client", "frontend")):
                tier = "frontend"
            elif any(w in sname_lower or w in img_lower for w in ("postgres", "mysql", "mariadb", "mongo")) or sname_lower == "db":
                tier = "database"
            elif any(w in sname_lower for w in ("bootstrap", "init", "seed", "migrate")):
                tier = "init"
            elif any(w in sname_lower or w in img_lower for w in ("redis", "rabbit", "kafka", "memcached")):
                tier = "cache"

            compose_services_meta.append({
                "name": sname,
                "tier": tier,
                "has_build": is_buildable,
                "image": resolved_img,
                "host_ports": h_ports,
                "container_ports": c_ports,
                "depends_on": deps,
            })

            if not is_buildable:
                continue

            components.append({
                "name": sname,
                "tier": tier,
                "has_build": True,
                "image": resolved_img,
                "context_path": ctx_clean or ".",
                "dockerfile": df_m.group(1) if df_m else "Dockerfile",
                "container_ports": c_ports,
                "host_ports": h_ports,
                "depends_on": deps,
                "start_command": None,
                "runtime": "unknown",
                "language": "unknown",
                "framework": "unknown",
                "endpoints": [],
                "api_calls": [],
                "env_vars": {},
                "uses_supabase": False,
                "alembic_enabled": False,
            })

        deep_insights["compose_services"] = compose_services_meta
        deep_insights["compose_has_own_db"] = any(
            s["tier"] == "database" for s in compose_services_meta
        )

    # 2. If no compose, detect standard subdirectories
    if not components and target_dir and target_dir.exists():
        subdirs = [d for d in target_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "node_modules", "venv"))]
        for sub in subdirs:
            has_df = (sub / "Dockerfile").exists()
            has_py = (sub / "requirements.txt").exists() or (sub / "pyproject.toml").exists()
            has_node = (sub / "package.json").exists()
            if has_df or has_py or has_node:
                sname = sub.name
                tier = "backend" if any(w in sname.lower() for w in ("back", "api", "srv")) else ("frontend" if any(w in sname.lower() for w in ("front", "client", "ui", "web")) else "component")
                components.append({
                    "name": sname,
                    "tier": tier,
                    "has_build": True,
                    "context_path": sname,
                    "dockerfile": "Dockerfile" if has_df else None,
                    "container_ports": [8000] if tier == "backend" else ([80] if tier == "frontend" else [8080]),
                    "host_ports": [],
                    "depends_on": ["backend"] if tier == "frontend" and any(c.get("tier") == "backend" for c in components) else [],
                    "start_command": None,
                    "runtime": "unknown",
                    "language": "unknown",
                    "framework": "unknown",
                    "endpoints": [],
                    "api_calls": [],
                    "env_vars": {},
                    "uses_supabase": False,
                    "alembic_enabled": False,
                })

    # 3. Deep scan each component's directory & code
    for comp in components:
        ctx_rel = comp.get("context_path") or "."
        comp_dir = (target_dir if ctx_rel == "." else (target_dir / ctx_rel)) if target_dir else None

        df_content = None
        if comp_dir and (comp_dir / (comp.get("dockerfile") or "Dockerfile")).exists():
            df_content = (comp_dir / (comp.get("dockerfile") or "Dockerfile")).read_text(encoding="utf-8", errors="replace")
        elif ctx_rel == ".":
            df_content = files_map.get(comp.get("dockerfile") or "Dockerfile")
        else:
            df_key = f"{ctx_rel}/{comp.get('dockerfile') or 'Dockerfile'}".lstrip("/")
            df_content = files_map.get(df_key)

        if df_content:
            for line in df_content.splitlines():
                s = line.strip()
                if s.upper().startswith("FROM "):
                    from_img = s.split(None, 1)[1].strip().split()[0]
                    comp["runtime"] = _resolve_compose_interpolations(from_img, env_defaults)
                elif s.upper().startswith("EXPOSE "):
                    for tok in s.split()[1:]:
                        port_str = _resolve_compose_interpolations(tok.split("/")[0], env_defaults)
                        if port_str.isdigit():
                            p_num = int(port_str)
                            if p_num not in comp["container_ports"]:
                                comp["container_ports"].append(p_num)
                elif s.upper().startswith("CMD ") or s.upper().startswith("ENTRYPOINT "):
                    comp["start_command"] = s.split(None, 1)[1].strip()

        py_manifest = None
        if comp_dir and (comp_dir / "requirements.txt").exists():
            py_manifest = (comp_dir / "requirements.txt").read_text(encoding="utf-8", errors="replace")
        elif ctx_rel == ".":
            py_manifest = files_map.get("requirements.txt")
        else:
            py_manifest = files_map.get(f"{ctx_rel}/requirements.txt")

        if py_manifest:
            comp["language"] = "Python"
            if comp["runtime"] == "unknown":
                comp["runtime"] = "python:3.11"
            if "fastapi" in py_manifest.lower():
                comp["framework"] = "FastAPI"
            elif "flask" in py_manifest.lower():
                comp["framework"] = "Flask"
            elif "django" in py_manifest.lower():
                comp["framework"] = "Django"
            if "supabase" in py_manifest.lower():
                comp["uses_supabase"] = True
                deep_insights["supabase_detected"] = True

        pkg_content = None
        if comp_dir and (comp_dir / "package.json").exists():
            pkg_content = (comp_dir / "package.json").read_text(encoding="utf-8", errors="replace")
        elif ctx_rel == ".":
            pkg_content = files_map.get("package.json")
        else:
            pkg_content = files_map.get(f"{ctx_rel}/package.json")

        if pkg_content:
            try:
                pkg_data = json.loads(pkg_content)
                deps = {**(pkg_data.get("dependencies") or {}), **(pkg_data.get("devDependencies") or {})}
                comp["language"] = "TypeScript/React" if any("react" in k for k in deps) or (comp_dir and any(p.suffix in (".ts", ".tsx") for p in comp_dir.rglob("*"))) else "JavaScript/Node.js"
                if "vite" in deps:
                    comp["framework"] = "React (Vite SPA)" if "react" in deps else "Vite SPA"
                elif "next" in deps:
                    comp["framework"] = "Next.js"
                elif "express" in deps:
                    comp["framework"] = "Express"
                if "@supabase/supabase-js" in deps:
                    comp["uses_supabase"] = True
                    deep_insights["supabase_detected"] = True
            except Exception:
                pass

        if comp_dir and comp_dir.exists():
            py_files = [p for p in comp_dir.rglob("*.py") if "__pycache__" not in str(p) and ".venv" not in str(p)]
            for pf in py_files:
                txt = pf.read_text(encoding="utf-8", errors="ignore")
                if "FastAPI(" in txt:
                    comp["framework"] = "FastAPI"
                if "create_client" in txt and "supabase" in txt.lower():
                    comp["uses_supabase"] = True
                    deep_insights["supabase_detected"] = True
                for m in re.finditer(r"prefix=[\"']([^\"']+)[\"']", txt):
                    pref = m.group(1)
                    if pref not in comp["endpoints"]:
                        comp["endpoints"].append(f"ROUTER {pref}")
                        deep_insights["discovered_endpoints"].append(f"ROUTER {pref}")
                for m in re.finditer(r"@(app|router)\.(get|post|put|delete|patch)\([\"']([^\"']+)[\"']", txt):
                    ep = f"{m.group(2).upper()} {m.group(3)}"
                    if ep not in comp["endpoints"]:
                        comp["endpoints"].append(ep)
                        deep_insights["discovered_endpoints"].append(ep)

            ts_files = [p for p in comp_dir.rglob("*") if p.suffix in (".ts", ".tsx", ".js", ".jsx") and "node_modules" not in str(p)]
            for tf in ts_files:
                txt = tf.read_text(encoding="utf-8", errors="ignore")
                if "createClient" in txt and "supabase" in txt.lower():
                    comp["uses_supabase"] = True
                    deep_insights["supabase_detected"] = True
                for m in re.finditer(r"fetch\((?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')", txt):
                    url = m.group(1) or m.group(2) or m.group(3)
                    if url and url not in comp["api_calls"]:
                        comp["api_calls"].append(url)
                        deep_insights["discovered_api_calls"].append(url)

    # 4. Check for Alembic migrations
    alembic_found = False
    if target_dir:
        alembic_found = (target_dir / "alembic.ini").exists() or (target_dir / "backend" / "alembic.ini").exists()
    if not alembic_found:
        alembic_found = any("alembic.ini" in k for k in files_map)
    deep_insights["alembic_detected"] = alembic_found

    # 5. Check for Supabase project reference
    for k, v in files_map.items():
        if "supabase" in v.lower():
            m_url = re.search(r"https://([a-zA-Z0-9_-]+)\.supabase\.co", v)
            if m_url:
                deep_insights["supabase_detected"] = True
                deep_insights["supabase_details"] = {
                    "project_ref": m_url.group(1),
                    "endpoint": m_url.group(0),
                }
                break

    # 6. Map Inter-Service Linkages
    if len(components) > 1:
        deep_insights["architecture_pattern"] = "multi_tier_decoupled"
        frontend_comp = next((c for c in components if c["tier"] == "frontend"), None)
        backend_comp = next((c for c in components if c["tier"] == "backend"), None)
        if frontend_comp and backend_comp:
            has_api_link = any("VITE_API_URL" in call or "API_URL" in call or "/api" in call for call in frontend_comp["api_calls"])
            depends_on_be = backend_comp["name"] in (frontend_comp.get("depends_on") or [])
            if has_api_link or depends_on_be:
                be_port = (backend_comp.get("host_ports") or backend_comp.get("container_ports") or [8000])[0]
                deep_insights["internal_service_links"].append({
                    "source": frontend_comp["name"],
                    "target": backend_comp["name"],
                    "protocol": "HTTP/REST",
                    "port": be_port,
                    "env_variable": "VITE_API_URL",
                    "description": f"El frontend ({frontend_comp['name']}) se comunica con la API backend ({backend_comp['name']}) en el puerto {be_port}.",
                })

    return components, deep_insights


def _extract_sql_from_pgdmp(dump_path: Path) -> str:
    """
    Convert a PostgreSQL custom dump (`PGDMP`) file into plain SQL text for static schema & data inspection.
    Uses `pg_restore -f -` when available, with a pure-Python binary/gzip fallback if `pg_restore` is absent.
    """
    try:
        proc = subprocess.run(
            ["pg_restore", "-f", "-", str(dump_path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=25,
        )
        if proc.stdout and ("CREATE TABLE" in proc.stdout or "PostgreSQL database dump" in proc.stdout):
            return proc.stdout
    except Exception:
        pass

    # Pure-Python fallback: extract ASCII TOC headers and decompress embedded gzip/zlib streams
    try:
        raw = dump_path.read_bytes()
        extracted_chunks: List[str] = [raw.decode("utf-8", errors="ignore")]
        for m in re.finditer(b"\x1f\x8b\x08", raw):
            start = m.start()
            try:
                decomp = zlib.decompress(raw[start:], 16 + zlib.MAX_WBITS)
                extracted_chunks.append(decomp.decode("utf-8", errors="replace"))
            except Exception:
                pass
        return "\n".join(extracted_chunks)
    except Exception:
        return ""


def _parse_sql_dump_text(
    sql_text: str,
    rel_path: str,
    size_bytes: int,
    dump_format: str = "PostgreSQL SQL Dump",
) -> Dict[str, Any]:
    """
    Parse SQL dump text (from `pg_restore -f -` or `.sql` files) to extract:
    - Database engine & version
    - Schemas (`public`, `auth`, `storage`, `extensions`, etc.)
    - Extensions (`postgis`, `pgcrypto`, `uuid-ossp`, etc.)
    - Custom SQL / RPC functions (`public.*`)
    - Tables, columns, exact row counts (`COPY ... FROM stdin` & `INSERT INTO`), and redacted sample rows
    - Database roles referenced
    """
    ver_m = re.search(r"Dumped from database version ([0-9.]+)", sql_text)
    db_version = ver_m.group(1) if ver_m else "16"

    schemas_set = {
        s for s in re.findall(r"CREATE SCHEMA (?:IF NOT EXISTS\s+)?\"?([a-zA-Z0-9_]+)\"?", sql_text, re.IGNORECASE)
        if s.upper() not in ("IF", "NOT", "EXISTS")
    }
    extensions_set = {
        e for e in re.findall(r"CREATE EXTENSION (?:IF NOT EXISTS\s+)?\"?([a-zA-Z0-9_-]+)\"?", sql_text, re.IGNORECASE)
        if e.upper() not in ("IF", "NOT", "EXISTS")
    }
    roles_set = set(re.findall(r"OWNER TO \"?([a-zA-Z0-9_]+)\"?;", sql_text))

    # Extract functions (focusing on public and custom RPCs)
    functions_list: List[Dict[str, str]] = []
    seen_funcs = set()
    for fm in re.finditer(
        r"CREATE (?:OR REPLACE )?FUNCTION\s+([a-zA-Z0-9_.\"]+)\(([^)]*)\)\s+RETURNS\s+([^\n\r{;]+)",
        sql_text,
    ):
        raw_fn = fm.group(1).replace('"', "")
        args = " ".join(fm.group(2).split())
        ret_type = " ".join(fm.group(3).split()).rstrip("AS").strip()
        schema_name = raw_fn.split(".")[0] if "." in raw_fn else "public"
        fn_name = raw_fn.split(".")[-1]
        schemas_set.add(schema_name)
        sig = f"{schema_name}.{fn_name}({args})"
        if sig not in seen_funcs and schema_name in ("public", "auth", "storage"):
            seen_funcs.add(sig)
            functions_list.append({
                "schema": schema_name,
                "name": fn_name,
                "arguments": args,
                "returns": ret_type,
                "signature": sig,
            })

    # Extract tables and their columns
    tables_map: Dict[str, Dict[str, Any]] = {}
    for tm in re.finditer(
        r"^CREATE TABLE (?:IF NOT EXISTS )?([a-zA-Z0-9_.\"]+)\s*\(\s*(.*?)\r?\n\);",
        sql_text,
        re.MULTILINE | re.DOTALL,
    ):
        raw_tbl = tm.group(1).replace('"', "")
        body = tm.group(2)
        t_schema = raw_tbl.split(".")[0] if "." in raw_tbl else "public"
        t_name = raw_tbl.split(".")[-1]
        full_name = f"{t_schema}.{t_name}"
        schemas_set.add(t_schema)

        cols: List[Dict[str, str]] = []
        for line in body.splitlines():
            s = line.strip().rstrip(",")
            if not s or s.upper().startswith(("CONSTRAINT ", "PRIMARY KEY", "FOREIGN KEY", "UNIQUE ", "CHECK ")):
                continue
            parts = s.split(None, 1)
            if len(parts) == 2:
                c_name = parts[0].strip('"')
                c_type = re.split(r"\s+(?:NOT NULL|DEFAULT|PRIMARY KEY|REFERENCES|NULL|CONSTRAINT|GENERATED)", parts[1], flags=re.IGNORECASE)[0].strip()
                cols.append({"name": c_name, "type": c_type})

        tables_map[full_name] = {
            "schema": t_schema,
            "name": t_name,
            "full_name": full_name,
            "columns": cols,
            "row_count": 0,
            "sample_rows": [],
        }

    # Parse COPY <table_name> (<cols>) FROM stdin; ... \. blocks for exact row counts and sample data
    has_copy_blocks = False
    for cm in re.finditer(
        r"^COPY\s+([a-zA-Z0-9_.\"]+)\s*(?:\(([^)]*)\))?\s+FROM stdin;\r?\n(.*?)^\\\.",
        sql_text,
        re.MULTILINE | re.DOTALL,
    ):
        has_copy_blocks = True
        raw_tbl = cm.group(1).replace('"', "")
        col_header = cm.group(2) or ""
        data_block = cm.group(3)
        t_schema = raw_tbl.split(".")[0] if "." in raw_tbl else "public"
        t_name = raw_tbl.split(".")[-1]
        full_name = f"{t_schema}.{t_name}"
        schemas_set.add(t_schema)

        lines = [ln for ln in data_block.splitlines() if ln != "" and ln != "\\."]
        row_count = len(lines)

        if full_name not in tables_map:
            if full_name == "public.spatial_ref_sys" and row_count == 0:
                continue
            tables_map[full_name] = {
                "schema": t_schema,
                "name": t_name,
                "full_name": full_name,
                "columns": [{"name": c.strip().strip('"'), "type": "unknown"} for c in col_header.split(",") if c.strip()],
                "row_count": 0,
                "sample_rows": [],
            }
        tables_map[full_name]["row_count"] += row_count

        # Capture up to 2 sample rows for public tables (redacting any sensitive columns)
        if t_schema == "public" and lines and len(tables_map[full_name]["sample_rows"]) < 2:
            col_names = [c.strip().strip('"') for c in col_header.split(",") if c.strip()]
            for sample_ln in lines[:2]:
                vals = sample_ln.split("\t")
                row_preview: Dict[str, str] = {}
                for idx_c, val in enumerate(vals[:8]):
                    cname = col_names[idx_c] if idx_c < len(col_names) else f"col_{idx_c}"
                    if SECRET_KEY_PATTERNS.search(cname) or "hash" in cname.lower():
                        row_preview[cname] = "[REDACTED]"
                    else:
                        row_preview[cname] = (val[:75] + "...") if len(val) > 75 else val
                tables_map[full_name]["sample_rows"].append(row_preview)

    # Also count INSERT INTO statements if the SQL dump uses INSERTs instead of COPY
    if not has_copy_blocks:
        for im in re.finditer(r"^INSERT INTO\s+([a-zA-Z0-9_.\"]+)\s+", sql_text, re.IGNORECASE | re.MULTILINE):
            raw_tbl = im.group(1).replace('"', "")
            t_schema = raw_tbl.split(".")[0] if "." in raw_tbl else "public"
            t_name = raw_tbl.split(".")[-1]
            full_name = f"{t_schema}.{t_name}"
            if full_name in tables_map:
                tables_map[full_name]["row_count"] += 1

    public_tables = [t for t in tables_map.values() if t["schema"] == "public"]
    public_tables.sort(key=lambda x: (-x["row_count"], x["name"]))
    all_tables = sorted(tables_map.values(), key=lambda x: (x["schema"] != "public", -x["row_count"], x["full_name"]))

    public_row_total = sum(t["row_count"] for t in public_tables)
    all_row_total = sum(t["row_count"] for t in all_tables)

    schema_row_totals: Dict[str, int] = {}
    for t in all_tables:
        schema_row_totals[t["schema"]] = schema_row_totals.get(t["schema"], 0) + t["row_count"]

    requires_postgis = "postgis" in {e.lower() for e in extensions_set} or "geometry(" in sql_text.lower()
    requires_supabase_compat = bool(
        {"auth", "storage", "supabase_migrations"} & schemas_set
        or {"supabase_admin", "anon", "authenticated", "service_role"} & roles_set
    )

    return {
        "path": rel_path,
        "name": Path(rel_path).name,
        "size_bytes": size_bytes,
        "format": dump_format,
        "engine": "PostgreSQL + PostGIS (Supabase Compatible)" if requires_postgis else "PostgreSQL",
        "dumped_from_version": db_version,
        "requires_postgis": requires_postgis,
        "requires_supabase_compat": requires_supabase_compat,
        "schemas": sorted(schemas_set),
        "extensions": sorted(extensions_set),
        "roles_referenced": sorted(roles_set),
        "public_functions": [f for f in functions_list if f["schema"] == "public"],
        "public_tables_count": len(public_tables),
        "total_tables_count": len(all_tables),
        "public_rows_count": public_row_total,
        "total_rows_count": all_row_total,
        "schema_row_totals": schema_row_totals,
        "public_tables": public_tables,
        "non_empty_tables": [
            {"table": t["full_name"], "rows": t["row_count"], "columns": [c["name"] for c in t["columns"][:8]]}
            for t in all_tables
            if t["row_count"] > 0
        ],
    }


def discover_database_backups_and_seeds(
    target_dir: Optional[Path],
    files_map: Dict[str, str],
) -> Dict[str, Any]:
    """
    Scan the repository for database backups (`.dump`, `.pgdump`, `.backup`, `.bak`, `.sql`, `PGDMP` binaries),
    JSON data seed exports (`*output.json`, `feed.json`, `*seed*.json`), database loader scripts
    (`import_*.py`, `upload_*.py`), and ER schema diagrams (`modelo.dot`).
    Extracts exact schemas, extensions (e.g. PostGIS), RPC functions, tables, and row counts
    so CloudMove can recreate the database and restore all its data in AWS.
    """
    backups: List[Dict[str, Any]] = []
    seed_files: List[Dict[str, Any]] = []
    importer_scripts: List[Dict[str, Any]] = []
    er_diagram_files: List[Dict[str, Any]] = []

    ignore_dirs = {
        ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        "node_modules", ".idea", ".vscode", "dist", "build", ".next",
        "target", "bin", "obj", ".pytest_cache", ".mypy_cache",
    }
    ignore_json_names = {
        "package.json", "package-lock.json", "tsconfig.json", "tsconfig.app.json",
        "tsconfig.node.json", "components.json", "vercel.json", "manifest.json",
    }

    if target_dir and target_dir.exists():
        for root, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".git")]
            for fname in sorted(filenames):
                fpath = Path(root) / fname
                rel_path = os.path.relpath(fpath, target_dir).replace("\\", "/")
                low_name = fname.lower()
                try:
                    fsize = fpath.stat().st_size
                except Exception:
                    fsize = 0

                # 1. Check for PostgreSQL custom dump (PGDMP) or SQL dump files
                is_dump_ext = low_name.endswith((".dump", ".pgdump", ".backup", ".bak"))
                is_sql_ext = low_name.endswith(".sql")
                magic_header = b""
                if fsize >= 5 and (is_dump_ext or "backup" in low_name or "dump" in low_name):
                    try:
                        with open(fpath, "rb") as bf:
                            magic_header = bf.read(16)
                    except Exception:
                        magic_header = b""

                if magic_header.startswith(b"PGDMP") or is_dump_ext:
                    sql_text = _extract_sql_from_pgdmp(fpath)
                    if sql_text:
                        parsed_bkp = _parse_sql_dump_text(
                            sql_text=sql_text,
                            rel_path=rel_path,
                            size_bytes=fsize,
                            dump_format="PostgreSQL Custom Binary Dump (PGDMP)",
                        )
                        backups.append(parsed_bkp)
                    else:
                        backups.append({
                            "path": rel_path,
                            "name": fname,
                            "size_bytes": fsize,
                            "format": "PostgreSQL Custom Binary Dump (PGDMP)",
                            "engine": "PostgreSQL",
                            "dumped_from_version": "16",
                            "requires_postgis": False,
                            "requires_supabase_compat": "supabase" in low_name,
                            "schemas": ["public"],
                            "extensions": [],
                            "roles_referenced": [],
                            "public_functions": [],
                            "public_tables_count": 0,
                            "total_tables_count": 0,
                            "public_rows_count": 0,
                            "total_rows_count": 0,
                            "schema_row_totals": {},
                            "public_tables": [],
                            "non_empty_tables": [],
                        })
                    continue

                if is_sql_ext and fsize <= 25 * 1024 * 1024:
                    try:
                        sql_text = fpath.read_text(encoding="utf-8", errors="replace")
                        if any(kw in sql_text.upper() for kw in ("CREATE TABLE", "INSERT INTO", "COPY ", "POSTGRESQL DATABASE DUMP")):
                            parsed_bkp = _parse_sql_dump_text(
                                sql_text=sql_text,
                                rel_path=rel_path,
                                size_bytes=fsize,
                                dump_format="Plain SQL Dump (.sql)",
                            )
                            backups.append(parsed_bkp)
                    except Exception:
                        pass
                    continue

                # 2. Check for ER diagram / schema graph files (e.g. modelo.dot)
                if low_name.endswith(".dot") and fsize <= 1_048_576:
                    try:
                        dot_txt = fpath.read_text(encoding="utf-8", errors="replace")
                        entities = re.findall(r'^\s*([a-zA-Z0-9_]+)\s*\[label=', dot_txt, re.MULTILINE)
                        er_diagram_files.append({
                            "path": rel_path,
                            "name": fname,
                            "size_bytes": fsize,
                            "entities_modeled": entities[:30],
                        })
                    except Exception:
                        pass
                    continue

                # 3. Check for JSON seed / data export files
                if low_name.endswith(".json") and low_name not in ignore_json_names and not low_name.startswith("tsconfig"):
                    if 20 <= fsize <= 10 * 1024 * 1024:
                        try:
                            raw_json = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
                            seed_entry = None
                            if isinstance(raw_json, dict):
                                if raw_json.get("type") == "FeatureCollection" and isinstance(raw_json.get("features"), list):
                                    feats = raw_json["features"]
                                    props_keys = list((feats[0].get("properties") or {}).keys()) if feats and isinstance(feats[0], dict) else []
                                    seed_entry = {
                                        "path": rel_path,
                                        "name": fname,
                                        "size_bytes": fsize,
                                        "format": "GeoJSON FeatureCollection",
                                        "record_count": len(feats),
                                        "sample_fields": props_keys[:10],
                                    }
                                elif isinstance(raw_json.get("feeds"), list):
                                    feeds = raw_json["feeds"]
                                    seed_entry = {
                                        "path": rel_path,
                                        "name": fname,
                                        "size_bytes": fsize,
                                        "format": "IoT Sensor Feed Export (JSON)",
                                        "record_count": len(feeds),
                                        "sample_fields": list(feeds[0].keys())[:10] if feeds and isinstance(feeds[0], dict) else [],
                                    }
                                else:
                                    for list_key in ("data", "records", "items", "rows", "arboles", "cultivos", "lotes", "users"):
                                        if isinstance(raw_json.get(list_key), list):
                                            arr = raw_json[list_key]
                                            seed_entry = {
                                                "path": rel_path,
                                                "name": fname,
                                                "size_bytes": fsize,
                                                "format": f"JSON Data Object ({list_key})",
                                                "record_count": len(arr),
                                                "sample_fields": list(arr[0].keys())[:10] if arr and isinstance(arr[0], dict) else [],
                                            }
                                            break
                            elif isinstance(raw_json, list) and len(raw_json) > 0 and isinstance(raw_json[0], dict):
                                seed_entry = {
                                    "path": rel_path,
                                    "name": fname,
                                    "size_bytes": fsize,
                                    "format": "JSON Record Array",
                                    "record_count": len(raw_json),
                                    "sample_fields": list(raw_json[0].keys())[:10],
                                }
                            if seed_entry:
                                seed_files.append(seed_entry)
                        except Exception:
                            pass

                # 4. Check for Python DB seed / import scripts (e.g. import_lotes_supabase.py, upload_cultivos.py)
                if low_name.endswith(".py") and (
                    any(p in low_name for p in ("import_", "upload_", "seed", "restore", "migrate"))
                    or "/db/" in f"/{rel_path.lower()}/"
                ):
                    if fsize <= 512 * 1024:
                        try:
                            py_txt = fpath.read_text(encoding="utf-8", errors="replace")
                            rpc_calls = re.findall(r'\.rpc\(\s*["\']([^"\']+)["\']', py_txt)
                            table_ops = re.findall(r'\.table\(\s*["\']([^"\']+)["\']\)\.(?:insert|upsert)', py_txt)
                            json_refs = re.findall(r'["\']([a-zA-Z0-9_./-]+\.json)["\']', py_txt)
                            if rpc_calls or table_ops:
                                importer_scripts.append({
                                    "path": rel_path,
                                    "name": fname,
                                    "target_tables": sorted(set(table_ops)),
                                    "rpc_functions_called": sorted(set(rpc_calls)),
                                    "seed_files_referenced": sorted(set(json_refs)),
                                })
                        except Exception:
                            pass

    # Also check inline_files if target_dir was not provided
    if not target_dir and files_map:
        for k, v in files_map.items():
            if k.lower().endswith((".sql", ".dump")) and any(w in v.upper() for w in ("CREATE TABLE", "COPY ", "INSERT INTO")):
                backups.append(
                    _parse_sql_dump_text(
                        sql_text=v,
                        rel_path=k,
                        size_bytes=len(v.encode("utf-8")),
                        dump_format="Inline SQL Backup",
                    )
                )

    primary_bkp = backups[0] if backups else None
    return {
        "has_backups": len(backups) > 0,
        "has_seed_files": len(seed_files) > 0,
        "primary_backup_file": primary_bkp["path"] if primary_bkp else None,
        "primary_backup_format": primary_bkp["format"] if primary_bkp else None,
        "primary_backup_engine": primary_bkp["engine"] if primary_bkp else None,
        "requires_postgis": any(b.get("requires_postgis") for b in backups),
        "requires_supabase_compat": any(b.get("requires_supabase_compat") for b in backups),
        "total_backup_files": len(backups),
        "total_seed_files": len(seed_files),
        "total_public_tables": primary_bkp["public_tables_count"] if primary_bkp else 0,
        "total_tables_all_schemas": primary_bkp["total_tables_count"] if primary_bkp else 0,
        "total_public_rows": primary_bkp["public_rows_count"] if primary_bkp else 0,
        "total_rows_all_schemas": primary_bkp["total_rows_count"] if primary_bkp else 0,
        "backups": backups,
        "seed_files": seed_files,
        "importer_scripts": importer_scripts,
        "er_diagram_files": er_diagram_files,
    }


def _analyze_source_payload(
    target_dir: Optional[Path],
    inline_files: Optional[Dict[str, str]] = None,
    runtime_metadata: Optional[Dict[str, Any]] = None,
    app_name_override: Optional[str] = None,
    git_meta: Optional[Dict[str, Any]] = None,
    catalog_builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    now = _utc_now()
    files_map: Dict[str, str] = {}
    resolved_dir: Optional[Path] = None
    tree_result: Optional[Dict[str, Any]] = None

    if inline_files:
        files_map.update(inline_files)
    elif target_dir:
        if not target_dir.exists() or not target_dir.is_dir():
            raise ValueError(f"El directorio de la aplicación '{target_dir}' no existe o no es accesible.")
        resolved_dir = target_dir
        tree_result, scanned_manifests = scan_local_filesystem_tree(target_dir)
        files_map.update(scanned_manifests)

    discovered_components, deep_insights = discover_app_components_and_code(resolved_dir, files_map)
    db_backups_info = discover_database_backups_and_seeds(resolved_dir, files_map)
    deep_insights["database_backups"] = db_backups_info

    fallback_app_name = (git_meta or {}).get("repo") or (resolved_dir.name if resolved_dir else "discovered-application")
    app_name = _sanitize_app_name(app_name_override, fallback=fallback_app_name)
    language = "unknown"
    framework = "unknown"
    runtime = "linux-process"
    runtime_constraints = ">=current"
    start_commands: List[str] = []
    ports: List[int] = []
    health_endpoints: List[str] = []
    volume_paths: List[str] = []
    env_vars: Dict[str, Dict[str, Any]] = {}
    packages_detected: List[str] = []
    dependencies: List[Dict[str, Any]] = []
    assumptions: List[str] = []

    # 1. Parse app_manifest.yaml if present
    if "app_manifest.yaml" in files_map:
        raw_manifest = files_map["app_manifest.yaml"]
        for line in raw_manifest.splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, v = line.split(":", 1)
                k = k.strip().lower()
                v = v.strip().strip('"').strip("'")
                if k == "name" and v and not app_name_override:
                    app_name = v
                elif k == "runtime" and v:
                    runtime = v
                    if "python" in v.lower():
                        language = "Python"
                    elif "node" in v.lower():
                        language = "JavaScript/Node.js"
                    elif "java" in v.lower() or "jdk" in v.lower():
                        language = "Java"
                    elif "go" in v.lower():
                        language = "Go"
                elif k == "entrypoint" and v:
                    start_commands.append(v)
                elif k in ("healthcheck", "health_endpoint") and v:
                    if v not in health_endpoints:
                        health_endpoints.append(v)

    # 2a. Python (`requirements.txt`, `pyproject.toml`, `runtime.txt`)
    if "requirements.txt" in files_map:
        language = "Python"
        if runtime == "linux-process":
            runtime = "python:3.11"
            runtime_constraints = ">=3.10,<4.0"
        for line in files_map["requirements.txt"].splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            pkg_name = re.split(r"[=<>!\[]", clean)[0].strip().lower()
            packages_detected.append(clean)
            if pkg_name in ("fastapi", "flask", "django", "tornado", "aiohttp"):
                framework = "FastAPI" if pkg_name == "fastapi" else pkg_name.capitalize()

    if "pyproject.toml" in files_map:
        language = "Python"
        pyproj = files_map["pyproject.toml"]
        m_py = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', pyproj)
        if m_py:
            runtime_constraints = m_py.group(1)
        m_name = re.search(r'name\s*=\s*["\']([^"\']+)["\']', pyproj)
        if m_name and not app_name_override and app_name == "discovered-application":
            app_name = m_name.group(1)
        for dep_m in re.finditer(r'["\']([a-zA-Z0-9_-]+(?:[><=~!]+[0-9a-zA-Z.*]+)+)["\']', pyproj):
            packages_detected.append(dep_m.group(1))
            if "fastapi" in dep_m.group(1).lower():
                framework = "FastAPI"
            elif "django" in dep_m.group(1).lower():
                framework = "Django"

    # 2b. Node.js (`package.json`, `.nvmrc`)
    if "package.json" in files_map:
        try:
            pkg_json = json.loads(files_map["package.json"])
            language = "JavaScript/Node.js"
            if runtime == "linux-process":
                runtime = "node:20"
            engines = pkg_json.get("engines") or {}
            if engines.get("node"):
                runtime_constraints = str(engines["node"])
            if not app_name_override and pkg_json.get("name"):
                app_name = pkg_json["name"]
            scripts = pkg_json.get("scripts") or {}
            if scripts.get("start"):
                start_commands.append(f"npm start ({scripts['start']})")
            deps = {**(pkg_json.get("dependencies") or {}), **(pkg_json.get("devDependencies") or {})}
            for d_name, d_ver in deps.items():
                packages_detected.append(f"{d_name}@{d_ver}")
                if d_name in ("express", "next", "nestjs", "@nestjs/core", "fastify"):
                    framework = "NestJS" if "nestjs" in d_name else d_name.capitalize()
        except Exception:
            pass

    # 2c. Java (`pom.xml`, `build.gradle`, `build.gradle.kts`)
    if "pom.xml" in files_map:
        pom = files_map["pom.xml"]
        language = "Java"
        java_ver_m = re.search(r"<java\.version>([^<]+)</java\.version>", pom) or re.search(
            r"<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>", pom
        )
        java_ver = java_ver_m.group(1).strip() if java_ver_m else "17"
        runtime = f"openjdk:{java_ver}"
        runtime_constraints = f">={java_ver}"
        art_m = re.search(r"<artifactId>([^<]+)</artifactId>", pom)
        if art_m and not app_name_override and app_name == "discovered-application":
            app_name = art_m.group(1).strip()
        if "spring-boot" in pom.lower():
            framework = "Spring Boot"
            if "/actuator/health" not in health_endpoints:
                health_endpoints.append("/actuator/health")
        elif "quarkus" in pom.lower():
            framework = "Quarkus"
            if "/q/health" not in health_endpoints:
                health_endpoints.append("/q/health")
        for dep_m in re.finditer(r"<artifactId>([^<]+)</artifactId>", pom):
            packages_detected.append(dep_m.group(1).strip())
        if not start_commands:
            start_commands.append(f"java -jar target/{_slug(app_name)}.jar")

    for gradle_file in ("build.gradle", "build.gradle.kts"):
        if gradle_file in files_map:
            gtxt = files_map[gradle_file]
            language = "Java"
            runtime = "openjdk:17"
            runtime_constraints = ">=17"
            if "org.springframework.boot" in gtxt:
                framework = "Spring Boot"
                if "/actuator/health" not in health_endpoints:
                    health_endpoints.append("/actuator/health")
            for dep_m in re.finditer(r"""(?:implementation|runtimeOnly)\s*\(?["']([^"']+)["']\)?""", gtxt):
                packages_detected.append(dep_m.group(1))
            if not start_commands:
                start_commands.append(f"java -jar build/libs/{_slug(app_name)}.jar")

    # 2d. Go (`go.mod`)
    if "go.mod" in files_map:
        gomod = files_map["go.mod"]
        language = "Go"
        go_ver_m = re.search(r"^go\s+([0-9.]+)", gomod, re.MULTILINE)
        go_ver = go_ver_m.group(1) if go_ver_m else "1.22"
        runtime = f"golang:{go_ver}"
        runtime_constraints = f">={go_ver}"
        mod_m = re.search(r"^module\s+([^\s]+)", gomod, re.MULTILINE)
        if mod_m and not app_name_override and app_name == "discovered-application":
            app_name = mod_m.group(1).rsplit("/", 1)[-1]
        for req_m in re.finditer(r"^\s*([a-zA-Z0-9_./-]+)\s+v([0-9.a-zA-Z+-]+)", gomod, re.MULTILINE):
            mod_pkg = f"{req_m.group(1)}@v{req_m.group(2)}"
            packages_detected.append(mod_pkg)
            if "gin-gonic/gin" in mod_pkg:
                framework = "Gin"
            elif "gofiber/fiber" in mod_pkg:
                framework = "Fiber"
            elif "labstack/echo" in mod_pkg:
                framework = "Echo"
        if not start_commands:
            start_commands.append(f"./bin/{_slug(app_name)}")

    # 3. Parse Dockerfile
    if "Dockerfile" in files_map:
        df_text = files_map["Dockerfile"]
        for line in df_text.splitlines():
            s = line.strip()
            if s.upper().startswith("FROM "):
                base_img = s.split(None, 1)[1].strip()
                runtime = base_img
                if "python" in base_img.lower() and language == "unknown":
                    language = "Python"
                elif "node" in base_img.lower() and language == "unknown":
                    language = "JavaScript/Node.js"
                elif "golang" in base_img.lower() and language == "unknown":
                    language = "Go"
                elif ("openjdk" in base_img.lower() or "temurin" in base_img.lower()) and language == "unknown":
                    language = "Java"
            elif s.upper().startswith("EXPOSE "):
                for tok in s.split()[1:]:
                    port_str = tok.split("/")[0]
                    if port_str.isdigit():
                        p = int(port_str)
                        if p not in ports:
                            ports.append(p)
            elif s.upper().startswith("VOLUME "):
                paths_found = re.findall(r'["\'](/[^"\']+)["\']', s)
                for vp in paths_found:
                    if vp not in volume_paths:
                        volume_paths.append(vp)
            elif s.upper().startswith("HEALTHCHECK "):
                url_m = re.search(r"https?://[^/\s]+(/[^\s\"']+)", s)
                if url_m and url_m.group(1) not in health_endpoints:
                    health_endpoints.append(url_m.group(1))
            elif s.upper().startswith("CMD ") or s.upper().startswith("ENTRYPOINT "):
                cmd_val = s.split(None, 1)[1].strip()
                if cmd_val not in start_commands:
                    start_commands.append(cmd_val)

    # 4. Parse .env.example / .env (strictly redacting secret values!)
    for env_file in (".env.example", ".env"):
        if env_file in files_map:
            for line in files_map[env_file].splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                env_vars[k] = redact_env_value(k, v)

    # 5. Parse docker-compose files for services, ports, volumes, healthcheck, env vars & confirmed dependencies
    env_defaults = _parse_env_defaults(resolved_dir, files_map)
    compose_services: List[str] = []
    compose_text_parts = [v for k, v in files_map.items() if ("compose" in k.lower() or "docker-compose" in k.lower()) and (k.endswith(".yml") or k.endswith(".yaml"))]
    compose_text = "\n".join(compose_text_parts) if compose_text_parts else (files_map.get("docker-compose.yml") or files_map.get("docker-compose.yaml") or files_map.get("compose.yaml") or "")
    if compose_text:
        resolved_compose_text = _resolve_compose_interpolations(compose_text, env_defaults)
        for m in re.finditer(r'-\s*["\']?(?:[0-9.]+:)?(\d{2,5}):(\d{2,5})(?:/[a-zA-Z]+)?["\']?', resolved_compose_text):
            host_p = int(m.group(1))
            cont_p = int(m.group(2))
            if host_p not in (5432, 3306, 6379, 27017, 5672):
                if host_p not in ports:
                    ports.append(host_p)
                if cont_p not in ports:
                    ports.append(cont_p)
        for m in re.finditer(r"-\s*([A-Z0-9_]+)=(.+)", compose_text):
            k, v = m.group(1).strip(), m.group(2).strip()
            env_vars[k] = redact_env_value(k, v)
        for m in re.finditer(r"-\s*(/[a-zA-Z0-9_./-]+):(/[a-zA-Z0-9_./-]+)", compose_text):
            vp = m.group(1)
            if vp not in volume_paths:
                volume_paths.append(vp)
        for svc_match in re.finditer(r"^  ([a-zA-Z0-9_-]+):\s*$", compose_text, re.MULTILINE):
            svc_name = svc_match.group(1)
            compose_services.append(svc_name)
        for hc_m in re.finditer(r"https?://[A-Za-z0-9._:${}-]+(/[^,\s\"']*)", resolved_compose_text):
            cand_path = hc_m.group(1)
            if cand_path and not cand_path.startswith("//") and "$" not in cand_path and cand_path not in health_endpoints:
                health_endpoints.append(cand_path)
        for hc_m in re.finditer(r"https?://[A-Za-z0-9._:${}-]+(/[A-Za-z0-9._/-]*)", compose_text):
            cand_path = hc_m.group(1)
            if cand_path and not cand_path.startswith("//") and cand_path not in health_endpoints:
                health_endpoints.append(cand_path)

    # Incorporate discovered multi-tier components into ports, commands, and architecture definition
    if discovered_components:
        for c in discovered_components:
            for hp in c.get("host_ports", []):
                if hp not in ports:
                    ports.append(hp)
            for cp in c.get("container_ports", []):
                if cp not in ports:
                    ports.append(cp)
            if c.get("start_command") and c["start_command"] not in start_commands:
                start_commands.append(c["start_command"])

        if len(discovered_components) > 1:
            backend_c = next((c for c in discovered_components if c["tier"] == "backend"), None)
            frontend_c = next((c for c in discovered_components if c["tier"] == "frontend"), None)
            if backend_c and frontend_c:
                language = f"{backend_c['language']} ({backend_c['name']}) + {frontend_c['language']} ({frontend_c['name']})"
                framework = f"{backend_c['framework']} (Backend API) + {frontend_c['framework']} (Frontend)"
                runtime = f"Multi-Tier Container ({backend_c['runtime']} & {frontend_c['runtime']})"
                runtime_constraints = ">=Containerized Runtime"

    # 6. Incorporate authorized runtime process metadata (`runtime_metadata`)
    rt = runtime_metadata or {}
    for port_list_key in ("ports", "listening_ports"):
        if rt.get(port_list_key):
            for p in rt[port_list_key]:
                if int(p) not in ports:
                    ports.append(int(p))
    for cmd_key in ("start_command", "process_cmdline"):
        if rt.get(cmd_key) and rt[cmd_key] not in start_commands:
            start_commands.append(rt[cmd_key])
    if rt.get("health_endpoint") and rt["health_endpoint"] not in health_endpoints:
        health_endpoints.append(rt["health_endpoint"])
    for path_list_key in ("persistent_paths", "local_state_paths"):
        if rt.get(path_list_key):
            for vp in rt[path_list_key]:
                if vp not in volume_paths:
                    volume_paths.append(vp)

    if not ports:
        ports = [8080]
    if not health_endpoints:
        health_endpoints = ["/health"]
        assumptions.append("No se declaró endpoint explícito en HEALTHCHECK; se asume `/health` sobre el puerto principal.")

    # 7. Identify & Classify Dependencies (`confirmed`/`observed`, `inferred`, `unknown`)
    pkg_blob = " ".join(packages_detected).lower()
    env_keys = set(env_vars.keys())

    # PostgreSQL & Managed BaaS check
    has_pg_compose = any("postgres" in s.lower() or "db" in s.lower() for s in compose_services) or "postgres:" in compose_text.lower()
    has_pg_pkg = any(x in pkg_blob for x in ("psycopg", "sqlalchemy", "pg", "asyncpg", "postgresql", "pgx", "gorm.io/driver/postgres"))
    has_pg_env = "DATABASE_URL" in env_keys or "POSTGRES_HOST" in env_keys or "SPRING_DATASOURCE_URL" in env_keys

    has_supabase = deep_insights.get("supabase_detected", False)
    has_db_backup = bool(db_backups_info.get("has_backups"))
    primary_bkp = (db_backups_info.get("backups") or [None])[0]
    bkp_evidence_list: List[Dict[str, Any]] = []
    if primary_bkp:
        non_empty_preview = ", ".join(
            f"{t['table']} ({t['rows']} filas)" for t in (primary_bkp.get("non_empty_tables") or [])[:10]
        )
        fn_preview = ", ".join(f["name"] for f in (primary_bkp.get("public_functions") or [])[:6])
        ext_preview = ", ".join(primary_bkp.get("extensions") or [])
        seed_preview = ", ".join(
            f"{s['path']} ({s['record_count']} registros)" for s in (db_backups_info.get("seed_files") or [])[:5]
        )
        bkp_detail = (
            f"Backup de base de datos detectado en `{primary_bkp['path']}` ({primary_bkp['format']}, "
            f"PostgreSQL {primary_bkp.get('dumped_from_version', '16')}, {primary_bkp['size_bytes']} bytes). "
            f"Contiene {primary_bkp['public_tables_count']} tablas públicas ({primary_bkp['public_rows_count']} filas de dominio) "
            f"y {primary_bkp['total_tables_count']} tablas totales ({primary_bkp['total_rows_count']} filas totales en esquemas "
            f"{', '.join(primary_bkp.get('schemas', []))}). "
            + (f"Tablas con datos: {non_empty_preview}. " if non_empty_preview else "")
            + (f"Extensiones requeridas: {ext_preview}. " if ext_preview else "")
            + (f"Funciones RPC/SQL: {fn_preview}. " if fn_preview else "")
            + (f"Archivos semilla JSON adicionales: {seed_preview}." if seed_preview else "")
        )
        bkp_evidence_list.append({
            "source": f"Backup de Base de Datos ({primary_bkp['path']})" + (f" + {len(db_backups_info.get('seed_files', []))} semillas JSON" if db_backups_info.get("seed_files") else ""),
            "observed_at": now,
            "epistemic_state": "observed",
            "confidence": 1.0,
            "detail": bkp_detail,
        })

    if has_supabase:
        sb_details = deep_insights.get("supabase_details", {})
        supabase_endpoint = sb_details.get("endpoint") or (env_vars.get("VITE_SUPABASE_URL", {}).get("redacted_value") if "VITE_SUPABASE_URL" in env_vars else None) or "https://supabase.co"
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-supabase-baas",
            "name": f"{_slug(app_name)}-supabase-baas",
            "type": "database_instance",
            "engine": "supabase_postgresql",
            "port": 5432,
            "relationship_type": "reads_and_writes",
            "classification": "confirmed",
            "epistemic_state": "observed",
            "confidence": 0.99,
            "requires_data_migration": True if has_db_backup else False,
            "is_external_baas": True,
            "has_backup_file": has_db_backup,
            "backup_file": db_backups_info.get("primary_backup_file"),
            "requires_postgis": bool(db_backups_info.get("requires_postgis")),
            "evidence": [
                {
                    "source": "SDK Supabase (@supabase/supabase-js, supabase-py) + endpoint verificado",
                    "observed_at": now,
                    "epistemic_state": "observed",
                    "confidence": 0.99,
                    "detail": (
                        f"Backend-as-a-Service (BaaS) Supabase detectado en {supabase_endpoint} (PostgreSQL + PostGIS + Auth). "
                        + (
                            f"Se identificó el volcado completo `{db_backups_info.get('primary_backup_file')}` en el repositorio para recrear la base de datos y restaurar todos sus datos automáticamente en AWS."
                            if has_db_backup
                            else "Provee base de datos relacional y autenticación en la nube sin requerir aprovisionar una instancia IaaS vacía."
                        )
                    ),
                },
                *bkp_evidence_list,
            ],
        })
    elif has_pg_compose or (has_pg_pkg and has_pg_env) or has_db_backup:
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-postgresql",
            "name": "billing-postgres" if "billing-postgres" in compose_services else f"{_slug(app_name)}-postgresql",
            "type": "database_instance",
            "engine": "postgres",
            "port": 5432,
            "relationship_type": "reads_from",
            "classification": "confirmed",
            "epistemic_state": "observed",
            "confidence": 0.99 if has_db_backup else 0.98,
            "requires_data_migration": True,
            "has_backup_file": has_db_backup,
            "backup_file": db_backups_info.get("primary_backup_file"),
            "requires_postgis": bool(db_backups_info.get("requires_postgis")),
            "evidence": [
                {
                    "source": "docker-compose.yml / manifest + driver + variable de conexión",
                    "observed_at": now,
                    "epistemic_state": "observed",
                    "confidence": 0.98,
                    "detail": "Dependencia PostgreSQL confirmada por declaración de servicio, driver de base de datos y/o archivo de backup en el repositorio.",
                },
                *bkp_evidence_list,
            ],
        })
    elif has_pg_pkg:
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-postgresql-inferred",
            "name": f"{_slug(app_name)}-postgresql",
            "type": "database_instance",
            "engine": "postgres",
            "port": 5432,
            "relationship_type": "inferred_relation",
            "classification": "inferred",
            "epistemic_state": "inferred",
            "confidence": 0.65,
            "requires_data_migration": True,
            "evidence": [
                {
                    "source": "manifiesto de paquetes",
                    "observed_at": now,
                    "epistemic_state": "inferred",
                    "confidence": 0.65,
                    "detail": "Driver PostgreSQL presente en dependencias de paquetes pero sin endpoint de conexión confirmado.",
                }
            ],
        })

    # Internal Service Mesh Links (e.g. Frontend to Backend)
    for link in deep_insights.get("internal_service_links", []):
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-mesh-{_slug(link['source'])}-to-{_slug(link['target'])}",
            "name": f"service-mesh-{link['source']}-to-{link['target']}",
            "type": "service_mesh_link",
            "engine": "http_rest",
            "port": link.get("port", 8000),
            "relationship_type": "consumes_api",
            "classification": "confirmed",
            "epistemic_state": "observed",
            "confidence": 0.98,
            "requires_data_migration": False,
            "evidence": [
                {
                    "source": "docker-compose / llamadas fetch() en frontend y prefijos de router FastAPI",
                    "observed_at": now,
                    "epistemic_state": "observed",
                    "confidence": 0.98,
                    "detail": link.get("description", "Comunicación interna verificada entre servicios."),
                }
            ],
        })

    # Redis cache check
    has_redis_compose = any("redis" in s.lower() for s in compose_services) or "redis:" in compose_text.lower()
    has_redis_pkg = "redis" in pkg_blob or "ioredis" in pkg_blob or "go-redis" in pkg_blob
    has_redis_env = "REDIS_URL" in env_keys or "REDIS_HOST" in env_keys
    if has_redis_compose or (has_redis_pkg and has_redis_env):
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-redis",
            "name": "billing-redis" if "billing-redis" in compose_services else f"{_slug(app_name)}-redis",
            "type": "cache",
            "engine": "redis",
            "port": 6379,
            "relationship_type": "connects_to",
            "classification": "confirmed",
            "epistemic_state": "observed",
            "confidence": 0.96,
            "evidence": [
                {
                    "source": "docker-compose.yml + manifiesto de dependencias",
                    "observed_at": now,
                    "epistemic_state": "observed",
                    "confidence": 0.96,
                    "detail": "Caché Redis confirmada en manifiesto de servicios, librería cliente y variable REDIS_URL.",
                }
            ],
        })

    # RabbitMQ / Celery / AMQP message broker check
    has_mq_compose = any("rabbit" in s.lower() or "mq" in s.lower() for s in compose_services)
    has_mq_pkg = "celery" in pkg_blob or "pika" in pkg_blob or "amqplib" in pkg_blob or "amqp" in pkg_blob
    has_mq_env = "RABBITMQ_URL" in env_keys or "BROKER_URL" in env_keys
    if has_mq_compose or has_mq_pkg or has_mq_env:
        is_confirmed = bool(has_mq_compose and has_mq_env)
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-rabbitmq",
            "name": "billing-rabbitmq" if "billing-rabbitmq" in compose_services else f"{_slug(app_name)}-mq",
            "type": "queue",
            "engine": "rabbitmq",
            "port": 5672,
            "relationship_type": "connects_to" if is_confirmed else "inferred_relation",
            "classification": "confirmed" if is_confirmed else "inferred",
            "epistemic_state": "observed" if is_confirmed else "inferred",
            "confidence": 0.92 if is_confirmed else 0.70,
            "evidence": [
                {
                    "source": "docker-compose.yml + dependencias AMQP/Celery",
                    "observed_at": now,
                    "epistemic_state": "observed" if is_confirmed else "inferred",
                    "confidence": 0.92 if is_confirmed else 0.70,
                    "detail": "Cola de mensajería AMQP/RabbitMQ detectada para tareas asíncronas.",
                }
            ],
        })

    # Object storage / Bucket check
    has_bucket_env = any("BUCKET" in k.upper() for k in env_keys)
    has_storage_sdk = "boto3" in pkg_blob or "storage" in pkg_blob or "aws-sdk" in pkg_blob
    if has_bucket_env or has_storage_sdk:
        dependencies.append({
            "id": f"dep-{_slug(app_name)}-object-storage",
            "name": f"{_slug(app_name)}-invoices-bucket",
            "type": "storage",
            "engine": "s3_compatible",
            "port": 443,
            "relationship_type": "inferred_relation",
            "classification": "inferred",
            "epistemic_state": "inferred",
            "confidence": 0.78,
            "evidence": [
                {
                    "source": "SDK de almacenamiento + variable BUCKET",
                    "observed_at": now,
                    "epistemic_state": "inferred",
                    "confidence": 0.78,
                    "detail": "Dependencia de almacenamiento de objetos inferida por SDK cloud y variable de bucket.",
                }
            ],
        })

    # External APIs (unknown internal/external reachability from cloud VPC)
    internal_env_keys = {link.get("env_variable", "") for link in deep_insights.get("internal_service_links", [])}
    for k, v_info in env_vars.items():
        if k in internal_env_keys or "SUPABASE" in k.upper():
            continue
        if "API_URL" in k.upper() or "WEBHOOK" in k.upper():
            dependencies.append({
                "id": f"dep-{_slug(app_name)}-ext-{_slug(k)}",
                "name": f"external-endpoint-{_slug(k)}",
                "type": "network_connection",
                "engine": "https",
                "port": 443,
                "relationship_type": "communicates_with",
                "classification": "unknown",
                "epistemic_state": "unknown",
                "confidence": 0.50,
                "evidence": [
                    {
                        "source": f".env ({k})",
                        "observed_at": now,
                        "epistemic_state": "unknown",
                        "confidence": 0.50,
                        "detail": f"Endpoint externo referenciado en '{k}' ({v_info['redacted_value']}); se desconoce si requiere VPN/DirectConnect desde la nube.",
                    }
                ],
            })

    confirmed_deps = [d for d in dependencies if d["classification"] == "confirmed"]
    inferred_deps = [d for d in dependencies if d["classification"] == "inferred"]
    unknown_deps = [d for d in dependencies if d["classification"] == "unknown"]

    network_and_identity_reqs = {
        "ingress_tcp_ports": sorted(ports),
        "egress_required_ports": sorted(list({d.get("port", 443) for d in dependencies if d.get("port")})),
        "secrets_manager_keys": [v["name"] for v in env_vars.values() if v["is_secret"]],
        "least_privilege_iam_actions": [
            "secretsmanager:GetSecretValue / secretmanager.versions.access",
            "s3:GetObject,s3:PutObject / storage.objects.create,storage.objects.get",
            "logs:CreateLogStream,logs:PutLogEvents / logging.logEntries.create",
        ],
    }

    service_endpoints = _infer_service_endpoints(discovered_components, ports, health_endpoints)
    primary_fe = service_endpoints.get("frontend_port")
    ordered_ports = (
        [primary_fe] + sorted(p for p in ports if p != primary_fe)
        if primary_fe in ports
        else sorted(ports)
    )

    out = {
        "app_id": f"app-{_slug(app_name)}",
        "app_name": app_name,
        "source_path": str(resolved_dir) if resolved_dir else "inline_manifests",
        "discovered_at": now,
        "static_analysis_only": True,
        "arbitrary_code_executed": False,
        "files_inspected": sorted(list(files_map.keys())),
        "language": language,
        "framework": framework,
        "runtime": runtime,
        "runtime_constraints": runtime_constraints,
        "has_dockerfile": "Dockerfile" in files_map,
        "start_commands": start_commands or ["uvicorn app.main:app --host 0.0.0.0 --port 8080"],
        "exposed_ports": ordered_ports,
        "health_endpoints": health_endpoints,
        "service_endpoints": service_endpoints,
        "persistent_volumes": volume_paths,
        "environment_variables": list(env_vars.values()),
        "secrets_redacted_count": sum(1 for v in env_vars.values() if v["is_secret"]),
        "packages_count": len(packages_detected),
        "packages_sample": packages_detected[:30],
        "network_and_identity_requirements": network_and_identity_reqs,
        "assumptions": assumptions,
        "dependencies": dependencies,
        "dependency_summary": {
            "total": len(dependencies),
            "confirmed_count": len(confirmed_deps),
            "inferred_count": len(inferred_deps),
            "unknown_count": len(unknown_deps),
            "confirmed": [d["id"] for d in confirmed_deps],
            "inferred": [d["id"] for d in inferred_deps],
            "unknown": [d["id"] for d in unknown_deps],
        },
        "components": discovered_components,
        "deep_insights": deep_insights,
        "database_backups": db_backups_info,
    }
    from app.migration.external_services import detect_external_services
    out["external_services"] = detect_external_services(out)

    if deep_insights.get("alembic_detected"):
        out["database_migrations"] = {
            "tool": "Alembic",
            "config_file": "alembic.ini",
            "automated": True,
            "detail": "Control de versiones y migraciones de esquema de base de datos detectado vía Alembic (SQLAlchemy).",
        }
    if tree_result:
        out["repository_tree"] = tree_result["hierarchical_tree"]
        out["tree_summary"] = tree_result["summary"]
        out["directory_inventory"] = tree_result["directories"]
        out["file_inventory"] = tree_result["files_sample"]
        out["key_manifests"] = tree_result["key_manifests"]
        if out.get("language") == "unknown" and tree_result["summary"]["languages"]:
            out["language"] = tree_result["summary"]["languages"][0]["language"]
    elif inline_files:
        items = [{"path": k, "type": "blob", "size": len(v)} for k, v in inline_files.items()]
        out["repository_tree"] = build_hierarchical_tree(items, root_name=app_name)
        out["tree_summary"] = {
            "total_files": len(items),
            "total_directories": 0,
            "total_size_bytes": sum(len(v) for v in inline_files.values()),
            "languages": [],
            "key_manifests_count": len(items),
        }
        out["directory_inventory"] = []
        out["file_inventory"] = [{"path": k, "name": k, "size": len(v)} for k, v in inline_files.items()]
        out["key_manifests"] = [{"path": k, "name": k, "manifest_type": MANIFEST_NAMES.get(k, "manifest"), "size": len(v)} for k, v in inline_files.items()]

    if git_meta:
        out["git_metadata"] = git_meta
    if callable(catalog_builder):
        out["transformation_catalog"] = catalog_builder(
            out, target_provider="aws", deployment_mode="vm_rehost", user_decisions=None
        )
    return out


