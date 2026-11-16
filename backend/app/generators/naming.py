"""
Cloud provider and Terraform HCL identifier sanitization & validation helpers.

Ensures every derived resource name, database identifier, bucket name, launch template prefix,
and HCL block identifier complies strictly with AWS and Terraform naming rules
(for example, never starting RDS identifiers with digits such as repo name `2026-2`).
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List


def sanitize_hcl_id(raw: str, prefix: str = "cm", max_len: int = 64) -> str:
    """Return a valid Terraform HCL block identifier matching `^[a-zA-Z_][a-zA-Z0-9_-]*$`."""
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = prefix
    if not cleaned[0].isalpha():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:max_len].rstrip("_") or prefix


def sanitize_kebab_identifier(
    raw: str,
    prefix: str = "cm",
    max_len: int = 63,
    require_leading_letter: bool = True,
) -> str:
    """
    Normalize a cloud identifier (RDS identifier, ElastiCache cluster_id, Cloud SQL/Compute name,
    IAM/SG name, or Launch Template prefix) collapsing consecutive hyphens cleanly.
    """
    cleaned = re.sub(r"[^a-z0-9-]+", "-", str(raw or "").strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = prefix
    if require_leading_letter and not cleaned[0].isalpha():
        cleaned = f"{prefix}-{cleaned}"
    elif not cleaned[0].isalnum():
        cleaned = f"{prefix}-{cleaned}"
    truncated = cleaned[:max_len].rstrip("-")
    return truncated or prefix


def sanitize_bucket_name(raw: str, prefix: str = "cloudmove", max_len: int = 63) -> str:
    """
    Normalize an S3 / GCS bucket name strictly to lowercase `[a-z0-9-]` with valid boundaries
    and deterministic short entropy suffix to avoid cross-account collisions.
    """
    src = str(raw or "storage").strip().lower()
    digest = hashlib.sha1(src.encode("utf-8")).hexdigest()[:6]
    body = re.sub(r"[^a-z0-9-]+", "-", src)
    body = re.sub(r"-+", "-", body).strip("-")
    base = f"{prefix}-{body}" if body and not body.startswith(f"{prefix}-") else (body or prefix)
    head_max = max(8, max_len - len(digest) - 1)
    head = base[:head_max].rstrip("-")
    candidate = f"{head}-{digest}".strip("-")
    if len(candidate) < 3:
        candidate = f"{prefix}-{digest}"
    return candidate[:max_len].rstrip("-")


def validate_hcl_naming_constraints(tf_files: Dict[str, str]) -> List[str]:
    """
    Perform fast, offline provider-semantic checks across generated `.tf` files so invalid
    identifiers (e.g. RDS identifier starting with a digit, >32 char launch_template prefix,
    invalid S3/GCS bucket chars) are caught immediately during plan validation instead of deploy.
    """
    errors: List[str] = []
    block_re = re.compile(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')

    for fname, content in tf_files.items():
        if not fname.endswith(".tf"):
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            m = block_re.match(line.strip())
            if not m:
                continue
            r_type, r_id = m.group(1), m.group(2)
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", r_id):
                errors.append(
                    f"Identificador HCL inválido '{r_id}' en {r_type} ({fname}:{idx + 1}): debe iniciar con letra o '_'."
                )

            # Collect top-level attributes inside this resource block (simple brace depth tracker)
            depth = line.count("{") - line.count("}")
            body_lines: List[str] = []
            j = idx + 1
            while j < len(lines) and depth > 0:
                cur = lines[j]
                depth += cur.count("{") - cur.count("}")
                if depth >= 1:
                    body_lines.append(cur)
                j += 1
            body = "\n".join(body_lines)

            if r_type == "aws_db_instance":
                ident_m = re.search(r'^\s*identifier\s*=\s*"([^"]+)"', body, re.MULTILINE)
                if ident_m:
                    ident = ident_m.group(1)
                    if not re.match(r"^[a-z][a-z0-9-]{0,62}$", ident) or "--" in ident or ident.endswith("-"):
                        errors.append(
                            f"Identificador RDS inválido '{ident}' en {r_type}.{r_id} ({fname}): "
                            "AWS exige iniciar con letra minúscula [a-z], solo [a-z0-9-], sin '--' y máximo 63 caracteres."
                        )
            elif r_type == "aws_elasticache_cluster":
                cid_m = re.search(r'^\s*cluster_id\s*=\s*"([^"]+)"', body, re.MULTILINE)
                if cid_m:
                    cid = cid_m.group(1)
                    if not re.match(r"^[a-z][a-z0-9-]{0,49}$", cid) or "--" in cid or cid.endswith("-"):
                        errors.append(
                            f"Identificador ElastiCache inválido '{cid}' en {r_type}.{r_id} ({fname}): "
                            "debe iniciar con letra minúscula, solo [a-z0-9-] y máximo 50 caracteres."
                        )
            elif r_type == "aws_launch_template":
                np_m = re.search(r'^\s*name_prefix\s*=\s*"([^"]+)"', body, re.MULTILINE)
                if np_m and len(np_m.group(1)) > 32:
                    errors.append(
                        f"El prefijo name_prefix '{np_m.group(1)}' de {r_type}.{r_id} ({fname}) "
                        f"excede el límite de 32 caracteres de AWS EC2 ({len(np_m.group(1))})."
                    )
            elif r_type == "aws_s3_bucket":
                b_m = re.search(r'^\s*bucket\s*=\s*"([^"]+)"', body, re.MULTILINE)
                if b_m:
                    bname = b_m.group(1)
                    if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", bname) or "--" in bname:
                        errors.append(
                            f"Nombre de bucket inválido '{bname}' en {r_type}.{r_id} ({fname}): "
                            "debe usar solo [a-z0-9-], entre 3 y 63 caracteres."
                        )

    return errors
