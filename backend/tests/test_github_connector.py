"""
Unit and Integration Tests for GitHub Connector & Use Case 1 Integration (`test_github_connector.py`).

Covers Section 4 (Caso de Uso 1: GitHub Real -> Análisis -> Migración):
1. GitHub URL parsing and validation (public and private formats).
2. Rate limit handling, 404 handling, and credential verification.
3. Commit pinning to an immutable 40-character SHA.
4. Ephemeral sandbox checkout and guaranteed cleanup.
5. Integration with inspect_application_source and CMIR v2.1 evidence items.
6. Endpoint validation `/api/v1/migration/github/validate` and orchestrator planning.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import tempfile
import urllib.error
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.discovery.github_connector import GitHubConnector
from app.discovery.connectors import ConnectorAuthError, ConnectorError
from app.migration.app_migrator import (
    inspect_application_source,
    build_application_cmir,
    evaluate_app_migration_viability,
)


client = TestClient(app)


def test_github_url_parsing():
    valid_cases = [
        ("https://github.com/fastapi/fastapi", ("fastapi", "fastapi")),
        ("https://github.com/pallets/flask.git", ("pallets", "flask")),
        ("https://github.com/psf/requests/", ("psf", "requests")),
        ("git@github.com:django/django.git", ("django", "django")),
    ]
    for url, expected in valid_cases:
        owner, repo = GitHubConnector.parse_repo_url(url)
        assert (owner, repo) == expected

    invalid_cases = [
        "https://gitlab.com/owner/repo",
        "https://bitbucket.org/owner/repo",
        "ftp://github.com/owner/repo",
        "just-a-string",
    ]
    for bad_url in invalid_cases:
        with pytest.raises(ValueError):
            GitHubConnector.parse_repo_url(bad_url)


def test_github_validate_repository_and_rate_limits():
    connector = GitHubConnector()

    # 1. Successful repository validation mock
    mock_repo_payload = {
        "full_name": "acme-corp/billing-service",
        "description": "Enterprise Billing API",
        "private": False,
        "default_branch": "main",
        "language": "Python",
        "stargazers_count": 42,
        "html_url": "https://github.com/acme-corp/billing-service",
        "archived": False,
    }
    with patch.object(connector, "_request", return_value=mock_repo_payload):
        res = connector.validate_repository("https://github.com/acme-corp/billing-service")
        assert res["valid"] is True
        assert res["owner"] == "acme-corp"
        assert res["repo"] == "billing-service"
        assert res["default_branch"] == "main"
        assert res["visibility"] == "public"

    # 2. Rate limit exceeded mock
    mock_http_err = urllib.error.HTTPError(
        url="https://api.github.com/repos/test/rate-limited",
        code=403,
        msg="rate limit exceeded",
        hdrs={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1730000000"},
        fp=io.BytesIO(b'{"message": "API rate limit exceeded"}'),
    )
    with patch("app.discovery.github_connector.urllib.request.urlopen", side_effect=mock_http_err):
        with pytest.raises(ConnectorError) as exc_info:
            connector.validate_repository("https://github.com/test/rate-limited")
        assert "rate limit" in str(exc_info.value).lower()

    # 3. Repository not found (404) mock
    mock_404_err = urllib.error.HTTPError(
        url="https://api.github.com/repos/nonexistent/repo",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=io.BytesIO(b'{"message": "Not Found"}'),
    )
    with patch("app.discovery.github_connector.urllib.request.urlopen", side_effect=mock_404_err):
        with pytest.raises(ConnectorError) as exc_info:
            connector.validate_repository("https://github.com/nonexistent/repo")
        assert "no encontrado" in str(exc_info.value).lower()


def test_github_commit_pinning_and_ephemeral_checkout():
    connector = GitHubConnector()

    mock_commit_payload = {
        "sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        "commit": {
            "message": "feat: add payment gateway webhook support",
            "author": {
                "name": "Jane CloudArchitect",
                "date": "2026-10-25T12:00:00Z",
            },
        },
    }
    with patch.object(connector, "_request", return_value=mock_commit_payload):
        pinned = connector.resolve_and_pin_commit("https://github.com/acme/billing", ref="main")
        assert pinned["commit_sha"] == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
        assert pinned["short_sha"] == "a1b2c3d4"
        assert pinned["author_name"] == "Jane CloudArchitect"

    # Create in-memory mock tarball containing requirements.txt and Dockerfile
    tar_bytes_io = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes_io, mode="w:gz") as tar:
        # File 1: requirements.txt
        req_content = b"fastapi==0.115.0\nuvicorn==0.30.0\npsycopg2-binary==2.9.9\nredis==5.0.8\n"
        ti1 = tarfile.TarInfo(name="acme-billing-a1b2c3d/requirements.txt")
        ti1.size = len(req_content)
        tar.addfile(ti1, io.BytesIO(req_content))

        # File 2: Dockerfile
        df_content = b"FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nCMD [\"uvicorn\", \"app.main:app\", \"--port\", \"8080\"]\n"
        ti2 = tarfile.TarInfo(name="acme-billing-a1b2c3d/Dockerfile")
        ti2.size = len(df_content)
        tar.addfile(ti2, io.BytesIO(df_content))

        # File 3: .env.example with secret to test redacting
        env_content = b"DATABASE_URL=postgres://user:supersecretpass@db.local:5432/billing\nAPI_KEY=live_sk_123456\nPORT=8080\n"
        ti3 = tarfile.TarInfo(name="acme-billing-a1b2c3d/.env.example")
        ti3.size = len(env_content)
        tar.addfile(ti3, io.BytesIO(env_content))

    tar_bytes = tar_bytes_io.getvalue()

    def mock_request_side_effect(endpoint, token=None, binary_response=False, timeout=15):
        if binary_response:
            return tar_bytes
        if "commits" in endpoint:
            return mock_commit_payload
        return {"default_branch": "main", "private": False}

    with patch.object(connector, "_request", side_effect=mock_request_side_effect):
        temp_seen_dir = None
        with connector.ephemeral_checkout("https://github.com/acme/billing", ref="main") as (checkout_path, meta):
            temp_seen_dir = checkout_path.parent
            assert checkout_path.is_dir()
            assert (checkout_path / "requirements.txt").is_file()
            assert (checkout_path / "Dockerfile").is_file()
            assert meta["commit_sha"] == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

            # Run inspection directly on checked-out repository
            disc = inspect_application_source(
                source_path=str(checkout_path),
                app_name_override="acme-billing",
            )
            assert disc["language"] == "Python"
            assert disc["has_dockerfile"] is True
            # Verify secrets are redacted
            env_vars = {v["name"]: v for v in disc["environment_variables"]}
            assert env_vars["API_KEY"]["is_secret"] is True
            assert env_vars["API_KEY"]["redacted_value"] == "[REDACTED_SECRET]"
            assert "supersecretpass" not in str(env_vars["DATABASE_URL"]["redacted_value"])

            # Verify CMIR construction
            cmir = build_application_cmir(disc, target_provider="aws")
            assert cmir.version == "2.1"
            assert len(cmir.resources) >= 2

        # Verify sandbox directory was completely cleaned up upon context exit
        assert not temp_seen_dir.exists()


def test_github_api_endpoints_integration():
    # Test /api/v1/migration/github/validate with mock
    mock_validate_payload = {
        "full_name": "octocat/Hello-World",
        "description": "My first repo",
        "private": False,
        "default_branch": "master",
        "language": "C",
        "stargazers_count": 2500,
        "html_url": "https://github.com/octocat/Hello-World",
    }
    mock_branches = [{"name": "master", "commit": {"sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"}}]

    with patch("app.discovery.github_connector.GitHubConnector.validate_repository", return_value=mock_validate_payload), \
         patch("app.discovery.github_connector.GitHubConnector.list_branches_and_tags", return_value={"branches": mock_branches, "tags": []}):
        resp = client.post("/api/v1/migration/github/validate", json={"github_url": "https://github.com/octocat/Hello-World"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "valid"
        assert data["default_branch"] == "master"
        assert len(data["branches"]) == 1


def test_github_tarball_headers_prevent_415_unsupported_media():
    """Verify GitHub API requests for tarball archives do not send application/x-gzip in Accept."""
    connector = GitHubConnector()
    captured_requests = []

    def mock_urlopen(req, timeout=15):
        captured_requests.append(req)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"fake-gzip-data"
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("app.discovery.github_connector.urllib.request.urlopen", side_effect=mock_urlopen):
        connector._request("https://api.github.com/repos/octocat/Hello-World/tarball/master", binary_response=True)

    assert len(captured_requests) == 1
    req = captured_requests[0]
    # Critical verification: GitHub API requires application/vnd.github+json and forbids application/x-gzip
    assert req.headers.get("Accept") == "application/vnd.github+json"
    assert req.headers.get("Accept") != "application/x-gzip"
    assert req.headers.get("X-github-api-version") == "2022-11-28"


def test_connector_error_in_jobs_endpoint_returns_json_and_cors():
    """Verify that a ConnectorError during job creation returns a clean JSON response instead of unhandled 500."""
    with patch("app.migration.orchestrator.migration_orchestrator.create_migration", side_effect=ConnectorError("GITHUB_API_ERROR", "Error de GitHub simulado")):
        resp = client.post(
            "/api/v1/migration/jobs",
            json={
                "name": "Test Fail",
                "use_case": "app_source",
                "target_provider": "aws",
                "source_config": {"github_url": "https://github.com/test/repo"},
            },
        )
        assert resp.status_code in (400, 502)
        assert "Error de GitHub simulado" in resp.json().get("detail", "")


def test_github_get_repository_tree_and_subfolders():
    """Verify recursive repository tree analysis: folders, subfolders, files, extensions and languages."""
    connector = GitHubConnector()
    mock_tree_payload = {
        "sha": "c1d2e3f4",
        "tree": [
            {"path": "src", "type": "tree"},
            {"path": "src/controllers", "type": "tree"},
            {"path": "src/controllers/payment.py", "type": "blob", "size": 1500},
            {"path": "src/main.py", "type": "blob", "size": 2200},
            {"path": "frontend", "type": "tree"},
            {"path": "frontend/package.json", "type": "blob", "size": 450},
            {"path": "frontend/src/App.tsx", "type": "blob", "size": 3100},
            {"path": "Dockerfile", "type": "blob", "size": 520},
            {"path": "requirements.txt", "type": "blob", "size": 120},
        ],
        "truncated": False,
    }

    with patch.object(connector, "resolve_and_pin_commit", return_value={"commit_sha": "c1d2e3f4", "short_sha": "c1d2e3f4", "ref": "main"}), \
         patch.object(connector, "_request", return_value=mock_tree_payload):
        tree_res = connector.get_repository_tree("https://github.com/acme/complex-app", ref="main")

        assert tree_res["commit_sha"] == "c1d2e3f4"
        assert tree_res["summary"]["total_files"] == 6
        assert tree_res["summary"]["total_directories"] == 3
        assert "src" in tree_res["directories"]
        assert "src/controllers" in tree_res["directories"]
        assert "frontend" in tree_res["directories"]

        # Check languages detected
        lang_names = [l["language"] for l in tree_res["summary"]["languages"]]
        assert "Python" in lang_names
        assert "TypeScript (React)" in lang_names

        # Check hierarchical tree
        root = tree_res["hierarchical_tree"]
        assert root["type"] == "directory"
        child_names = [c["name"] for c in root["children"]]
        assert "src" in child_names
        assert "frontend" in child_names
        assert "Dockerfile" in child_names
        assert "requirements.txt" in child_names

        # Check subfolder nesting
        src_node = next(c for c in root["children"] if c["name"] == "src")
        assert src_node["type"] == "directory"
        src_children = [c["name"] for c in src_node["children"]]
        assert "controllers" in src_children
        assert "main.py" in src_children

        ctrl_node = next(c for c in src_node["children"] if c["name"] == "controllers")
        assert ctrl_node["children"][0]["name"] == "payment.py"
        assert ctrl_node["children"][0]["type"] == "file"
        assert ctrl_node["children"][0]["language"] == "Python"


