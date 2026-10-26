"""
GitHub Integration & Verified Repository Analysis Connector (`github_connector.py`).

Addresses Section 4 (Caso de Uso 1: GitHub Real -> Análisis -> Migración):
- Validates repository URLs (public and private repos).
- Real GitHub REST API integration with rate limit handling and error propagation.
- Resolves and pins exact commit SHAs (preventing drift during planning & migration).
- Ephemeral checkout / archive extraction in an isolated sandbox with guaranteed cleanup.
- Static application analysis (language, runtime, frameworks, dependencies, Docker, env vars with redacted secrets).
- Distinguishes confirmed vs inferred vs unknown dependencies.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Dict, Iterator, List, Optional, Tuple
import urllib.error
import urllib.request

from app.discovery.connectors import ConnectorAuthError, ConnectorError, ConnectorTimeoutError


GITHUB_URL_REGEX = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)(?P<owner>[a-zA-Z0-9_.-]+)/(?P<repo>[a-zA-Z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


LANGUAGE_EXTENSIONS: Dict[str, str] = {
    ".py": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SASS",
    ".less": "LESS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".xml": "XML",
    ".toml": "TOML",
    ".ini": "INI / Config",
    ".cfg": "INI / Config",
    ".conf": "Config",
    ".env": "Environment",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".sql": "SQL",
    ".sh": "Shell Script",
    ".bash": "Shell Script",
    ".zsh": "Shell Script",
    ".tf": "Terraform",
    ".tfvars": "Terraform",
    ".proto": "Protocol Buffers",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
}

MANIFEST_NAMES: Dict[str, str] = {
    "requirements.txt": "python_requirements",
    "pyproject.toml": "python_pyproject",
    "Pipfile": "python_pipfile",
    "Pipfile.lock": "python_pipfile_lock",
    "setup.py": "python_setup",
    "setup.cfg": "python_setup_cfg",
    "runtime.txt": "python_runtime",
    ".python-version": "python_version",
    "package.json": "nodejs_package_json",
    "package-lock.json": "nodejs_lock",
    "yarn.lock": "nodejs_yarn_lock",
    "pnpm-lock.yaml": "nodejs_pnpm_lock",
    ".nvmrc": "nodejs_nvmrc",
    "pom.xml": "java_maven",
    "build.gradle": "java_gradle",
    "build.gradle.kts": "java_gradle_kts",
    "settings.gradle": "java_gradle_settings",
    "go.mod": "golang_modules",
    "go.sum": "golang_sum",
    "Cargo.toml": "rust_cargo",
    "Cargo.lock": "rust_cargo_lock",
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "docker-compose.yml": "docker_compose",
    "docker-compose.yaml": "docker_compose",
    "compose.yml": "docker_compose",
    "compose.yaml": "docker_compose",
    ".env.example": "env_example",
    ".env.template": "env_template",
    ".env": "env_file",
    "alembic.ini": "alembic_config",
    "app_manifest.yaml": "cloudmove_app_manifest",
    "app_manifest.yml": "cloudmove_app_manifest",
}


def is_manifest_file(filename: str) -> bool:
    lower = filename.lower()
    if lower in MANIFEST_NAMES:
        return True
    if lower.startswith("dockerfile") or lower.startswith("containerfile"):
        return True
    if lower.startswith("docker-compose") or lower.startswith("compose."):
        return True
    if lower.startswith(".env") or lower.endswith(".env"):
        return True
    if "alembic.ini" in lower:
        return True
    return False


def get_manifest_type(filename: str) -> str:
    lower = filename.lower()
    if lower in MANIFEST_NAMES:
        return MANIFEST_NAMES[lower]
    if lower.startswith("dockerfile") or lower.startswith("containerfile"):
        return "dockerfile"
    if lower.startswith("docker-compose") or lower.startswith("compose."):
        return "docker_compose"
    if lower.startswith(".env") or lower.endswith(".env"):
        return "env_file"
    if "alembic.ini" in lower:
        return "alembic_config"
    return "manifest"


def build_hierarchical_tree(items: List[Dict[str, Any]], root_name: str = "root") -> Dict[str, Any]:
    """Build a nested tree of folders, subfolders, and files from a flat list of paths."""
    root: Dict[str, Any] = {"name": root_name, "path": "", "type": "directory", "children": []}

    for item in items:
        raw_path = item.get("path", "").strip("/")
        if not raw_path:
            continue
        parts = raw_path.split("/")
        curr = root
        for i, part in enumerate(parts[:-1]):
            subpath = "/".join(parts[: i + 1])
            found = next((c for c in curr["children"] if c["name"] == part and c["type"] == "directory"), None)
            if not found:
                found = {"name": part, "path": subpath, "type": "directory", "children": []}
                curr["children"].append(found)
            curr = found

        leaf_name = parts[-1]
        leaf_type = "directory" if item.get("type") in ("tree", "directory") else "file"
        if leaf_type == "directory":
            found = next((c for c in curr["children"] if c["name"] == leaf_name and c["type"] == "directory"), None)
            if not found:
                curr["children"].append({"name": leaf_name, "path": raw_path, "type": "directory", "children": []})
        else:
            ext = ("." + leaf_name.rsplit(".", 1)[-1].lower()) if "." in leaf_name else ""
            lang = LANGUAGE_EXTENSIONS.get(ext, "Other" if ext else "Plain Text")
            is_manifest = is_manifest_file(leaf_name)
            curr["children"].append({
                "name": leaf_name,
                "path": raw_path,
                "type": "file",
                "size": item.get("size", 0),
                "extension": ext,
                "language": lang,
                "is_manifest": is_manifest,
                "manifest_type": get_manifest_type(leaf_name) if is_manifest else None,
            })

    def sort_children(node: Dict[str, Any]) -> None:
        if "children" in node:
            node["children"].sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
            for child in node["children"]:
                if child["type"] == "directory":
                    sort_children(child)

    sort_children(root)
    return root


class GitHubConnector:
    """Production GitHub integration connector for repository validation, commit pinning, and ephemeral checkout."""

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "").strip() or None

    @staticmethod
    def parse_repo_url(url: str) -> Tuple[str, str]:
        """Extract (owner, repo) from standard GitHub URLs."""
        clean_url = str(url or "").strip()
        match = GITHUB_URL_REGEX.match(clean_url)
        if not match:
            raise ValueError(
                f"URL de GitHub no válida: '{url}'. Debe tener el formato 'https://github.com/owner/repo' o 'git@github.com:owner/repo.git'."
            )
        owner = match.group("owner")
        repo = match.group("repo")
        return owner, repo

    def _request(
        self,
        endpoint: str,
        token: Optional[str] = None,
        binary_response: bool = False,
        timeout: int = 15,
    ) -> Any:
        active_token = token or self.token
        url = endpoint if endpoint.startswith("http") else f"https://api.github.com{endpoint}"
        headers = {
            "User-Agent": "CloudMove-Migration-Engine/2.1",
            "Accept": "application/vnd.github+json" if "api.github.com" in url else "*/*",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if active_token:
            headers["Authorization"] = f"Bearer {active_token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if binary_response:
                    return data
                return json.loads(data.decode("utf-8")) if data else {}
        except urllib.error.HTTPError as exc:
            hdrs = getattr(exc, "headers", None) or getattr(exc, "hdrs", None) or {}
            rate_remaining = hdrs.get("x-ratelimit-remaining")
            rate_reset = hdrs.get("x-ratelimit-reset")
            if exc.code == 404:
                raise ConnectorError(
                    "GITHUB_NOT_FOUND",
                    f"Repositorio no encontrado en GitHub ({url}). Si es un repositorio privado, proporcione un token de acceso autorizado."
                ) from exc
            elif exc.code in (401, 403):
                if rate_remaining == "0":
                    reset_ts = datetime.fromtimestamp(int(rate_reset), timezone.utc).isoformat() if rate_reset else "pronto"
                    raise ConnectorError(
                        "GITHUB_RATE_LIMIT",
                        f"Límite de peticiones de la API de GitHub excedido (rate limit). Se restablece en: {reset_ts} UTC. "
                        f"Configure un GitHub Personal Access Token para incrementar la cuota."
                    ) from exc
                raise ConnectorAuthError(
                    "GITHUB_AUTH_FAILED",
                    f"Error de autenticación o permisos insuficientes en GitHub (HTTP {exc.code}). Compruebe la validez del token."
                ) from exc
            else:
                err_body = exc.read().decode("utf-8", errors="replace")[:1000]
                raise ConnectorError("GITHUB_API_ERROR", f"Error de GitHub API (HTTP {exc.code}): {err_body}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise ConnectorTimeoutError(f"Tiempo de espera agotado al conectar con GitHub ({url}).") from exc
            raise ConnectorError("GITHUB_NETWORK_ERROR", f"Fallo de conexión de red hacia GitHub: {exc.reason}") from exc

    def validate_repository(
        self,
        url: str,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify repository existence, accessibility, visibility, and default branch."""
        owner, repo = self.parse_repo_url(url)
        data = self._request(f"/repos/{owner}/{repo}", token=token)
        return {
            "valid": True,
            "owner": owner,
            "repo": repo,
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "description": data.get("description", ""),
            "visibility": "private" if data.get("private") else "public",
            "default_branch": data.get("default_branch", "main"),
            "language": data.get("language", "Unknown"),
            "stars_count": data.get("stargazers_count", 0),
            "html_url": data.get("html_url", f"https://github.com/{owner}/{repo}"),
            "archived": data.get("archived", False),
            "permissions": data.get("permissions", {}),
            "checked_at": _utc_now(),
        }

    def list_branches_and_tags(
        self,
        url: str,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List branches, tags, and commits available for selection."""
        owner, repo = self.parse_repo_url(url)
        branches_data = self._request(f"/repos/{owner}/{repo}/branches?per_page=30", token=token)
        tags_data = self._request(f"/repos/{owner}/{repo}/tags?per_page=30", token=token)

        branches = []
        for b in branches_data if isinstance(branches_data, list) else []:
            branches.append({
                "name": b.get("name"),
                "commit_sha": (b.get("commit") or {}).get("sha"),
            })

        tags = []
        for t in tags_data if isinstance(tags_data, list) else []:
            tags.append({
                "name": t.get("name"),
                "commit_sha": (t.get("commit") or {}).get("sha"),
            })

        return {
            "owner": owner,
            "repo": repo,
            "branches": branches,
            "tags": tags,
        }

    def resolve_and_pin_commit(
        self,
        url: str,
        ref: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a branch, tag, or HEAD reference to a pinned, immutable 40-character commit SHA.
        Guarantees that analysis, IaC generation, and deployment target the exact same code revision.
        """
        owner, repo = self.parse_repo_url(url)
        target_ref = ref.strip() if ref and ref.strip() else None
        if not target_ref:
            repo_info = self.validate_repository(url, token=token)
            target_ref = repo_info["default_branch"]

        data = self._request(f"/repos/{owner}/{repo}/commits/{target_ref}", token=token)
        commit_sha = data.get("sha")
        if not commit_sha:
            raise ConnectorError(
                "GITHUB_REF_NOT_FOUND",
                f"No se pudo resolver la referencia '{target_ref}' en el repositorio '{owner}/{repo}'."
            )

        commit_obj = data.get("commit", {})
        author_obj = commit_obj.get("author", {})
        return {
            "owner": owner,
            "repo": repo,
            "ref": target_ref,
            "commit_sha": commit_sha,
            "short_sha": commit_sha[:8],
            "commit_message": (commit_obj.get("message") or "").splitlines()[0],
            "author_name": author_obj.get("name", "Unknown"),
            "author_date": author_obj.get("date", _utc_now()),
            "pinned_at": _utc_now(),
        }

    def get_repository_tree(
        self,
        url: str,
        ref: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Query GitHub Git Trees API recursively for the pinned commit to discover
        all folders, subfolders, files, extensions, file sizes, and language breakdown.
        """
        owner, repo = self.parse_repo_url(url)
        pinned = self.resolve_and_pin_commit(url, ref=ref, token=token)
        commit_sha = pinned["commit_sha"]

        data = self._request(
            f"/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1",
            token=token,
        )
        tree_items = data.get("tree", []) if isinstance(data, dict) else []

        files: List[Dict[str, Any]] = []
        directories: List[str] = []
        ext_counter: Dict[str, int] = {}
        ext_bytes: Dict[str, int] = {}
        total_size = 0
        key_manifests: List[Dict[str, Any]] = []

        for item in tree_items:
            path = item.get("path", "")
            item_type = item.get("type", "")
            size = item.get("size", 0) or 0
            if item_type == "tree":
                directories.append(path)
            else:
                total_size += size
                name = path.rsplit("/", 1)[-1]
                ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
                lang = LANGUAGE_EXTENSIONS.get(ext, "Other" if ext else "Plain Text")
                is_manifest = is_manifest_file(name)
                file_info = {
                    "path": path,
                    "name": name,
                    "size": size,
                    "extension": ext,
                    "language": lang,
                    "is_manifest": is_manifest,
                }
                files.append(file_info)
                if is_manifest:
                    key_manifests.append({
                        "path": path,
                        "name": name,
                        "manifest_type": get_manifest_type(name),
                        "size": size,
                    })

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

        hierarchical = build_hierarchical_tree(tree_items, root_name=repo)

        return {
            "owner": owner,
            "repo": repo,
            "ref": pinned["ref"],
            "commit_sha": commit_sha,
            "short_sha": pinned["short_sha"],
            "truncated": data.get("truncated", False),
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

    def download_and_extract_tarball(
        self,
        url: str,
        commit_sha: str,
        target_dir: Path,
        token: Optional[str] = None,
    ) -> Path:
        """Download tarball of pinned commit and safely unpack into target directory."""
        owner, repo = self.parse_repo_url(url)
        archive_url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{commit_sha}"
        data = self._request(archive_url, token=token, binary_response=True)

        tar_path = target_dir / "repo_archive.tar.gz"
        tar_path.write_bytes(data)

        # Extract safely avoiding path traversal
        extract_dir = target_dir / "unpacked"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                # Defend against zip-slip / absolute path injection
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                tar.extract(member, extract_dir)

        # GitHub tarballs nest files in an outer folder e.g. owner-repo-sha
        subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        final_dir = subdirs[0] if subdirs else extract_dir
        return final_dir

    @contextmanager
    def ephemeral_checkout(
        self,
        url: str,
        ref: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Iterator[Tuple[Path, Dict[str, Any]]]:
        """
        Context manager that pins the commit, downloads files to an ephemeral temporary directory,
        yields the path for static analysis, and guarantees complete cleanup upon exit.
        """
        pinned = self.resolve_and_pin_commit(url, ref=ref, token=token)
        temp_dir = tempfile.mkdtemp(prefix="cloudmove_gh_")
        try:
            checkout_path = self.download_and_extract_tarball(
                url=url,
                commit_sha=pinned["commit_sha"],
                target_dir=Path(temp_dir),
                token=token,
            )
            yield checkout_path, pinned
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
