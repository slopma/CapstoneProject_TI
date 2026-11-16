"""
Use Case 1 (`app_source`) Application & GitHub Migration Endpoints (`/api/v1/migration`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.api.routers.migration_helpers import validate_target_provider
from app.api.routers.migration_schemas import (
    AppInspectRequest,
    GitHubValidateRequest,
    UpdateArchitectureDecisionsRequest,
)
from app.discovery.connectors import ConnectorError
from app.migration.app_migrator import (
    build_application_cmir,
    evaluate_app_migration_viability,
    inspect_application_source,
)
from app.migration.orchestrator import migration_orchestrator

router = APIRouter()


@router.post("/github/validate")
def validate_github_repository(request: GitHubValidateRequest):
    """Validate a GitHub repository URL and return branches, tags, and file tree."""
    from app.discovery.github_connector import GitHubConnector

    try:
        gh = GitHubConnector(token=request.github_token)
        repo_info = gh.validate_repository(request.github_url, token=request.github_token)
        refs = gh.list_branches_and_tags(request.github_url, token=request.github_token)
        default_branch = repo_info.get("default_branch", "main")
        tree_info = None
        try:
            tree_info = gh.get_repository_tree(request.github_url, ref=default_branch, token=request.github_token)
        except Exception:
            tree_info = None

        return {
            "status": "valid",
            "repository": repo_info,
            "branches": refs.get("branches", []),
            "tags": refs.get("tags", []),
            "default_branch": default_branch,
            "tree": tree_info,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/use-case-1/inspect")
def inspect_use_case_1_application(request: Optional[AppInspectRequest] = None):
    """Inspect a GitHub/local application, classify dependencies, and build CMIR v2.1."""
    req = request or AppInspectRequest()
    target = validate_target_provider(req.target_provider)
    try:
        app_disc = inspect_application_source(
            source_path=req.source_path,
            inline_files=req.inline_files,
            runtime_metadata=req.runtime_metadata,
            app_name_override=req.app_name,
            github_url=req.github_url,
            github_ref=req.github_ref,
            github_token=req.github_token,
        )
        cmir_obj = build_application_cmir(
            app_disc,
            target_provider=target,
            deployment_mode=req.deployment_mode,
            user_decisions=req.user_decisions,
        )
        viability = evaluate_app_migration_viability(
            app_disc,
            cmir_obj,
            target_provider=target,
            deployment_mode=req.deployment_mode,
        )
        return {
            "use_case": "app_source",
            "target_provider": target,
            "application": app_disc,
            "transformation_catalog": app_disc.get("transformation_catalog"),
            "cmir": cmir_obj.model_dump(),
            "viability": viability,
        }
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc


@router.post("/jobs/{migration_id}/decisions")
def update_job_architecture_decisions(migration_id: str, request: UpdateArchitectureDecisionsRequest):
    """Update user transformation choices and regenerate CMIR + Terraform HCL bundle."""
    try:
        return migration_orchestrator.update_architecture_decisions(
            migration_id=migration_id,
            user_decisions=request.user_decisions,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/use-case-1/migrate")
def orchestrate_use_case_1_migration(request: Optional[AppInspectRequest] = None):
    """Create and plan a 12-stage guided application migration job in the orchestrator."""
    req = request or AppInspectRequest()
    target = validate_target_provider(req.target_provider)
    try:
        app_name = req.app_name or (
            req.github_url.rstrip("/").split("/")[-1]
            if req.github_url
            else (Path(req.source_path).name if req.source_path else "app")
        )
        return migration_orchestrator.create_migration(
            name=f"App Migration: {app_name} -> {target.upper()}",
            use_case="app_source",
            target_provider=target,
            source_config={
                "source_path": req.source_path,
                "inline_files": req.inline_files,
                "runtime_metadata": req.runtime_metadata,
                "app_name": app_name,
                "deployment_mode": req.deployment_mode,
                "github_url": req.github_url,
                "github_ref": req.github_ref,
                "github_token": "[REDACTED]" if req.github_token else None,
                "user_decisions": req.user_decisions,
            },
            transient_secrets={"github_token": req.github_token} if req.github_token else None,
            auto_assess_and_plan=True,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        status = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
        raise HTTPException(status_code=status, detail=exc.message) from exc
