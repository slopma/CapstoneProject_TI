"""
Security & isolation helpers for public AWS web deployment (`backend/app/core/security.py`).

Provides:
- DNS-resolving SSRF protection blocking AWS EC2 IMDSv1/v2 (`169.254.169.254`, `fd00:ec2::254`),
  loopback, link-local, RFC1918/private Docker/VPC networks, CGNAT, and multicast ranges.
- HTTP opener blocking open-redirect SSRF bypasses while remaining mockable in tests.
- Strict identifier validation against path traversal (`..`, `/`, `\\`, null bytes).
- Dynamic AWS control-plane self-identification (IMDSv2 + env configuration) so hardcoded
  instance IDs, VPCs, or domains are unnecessary.
"""

from __future__ import annotations

from functools import lru_cache
import ipaddress
import os
import re
import socket
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.parse
import urllib.request


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
_EC2_IMDS_V6 = ipaddress.ip_address("fd00:ec2::254")
_BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata",
    "100.100.100.200",
    "fd00:ec2::254",
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
}

_ORIGINAL_URLOPEN = urllib.request.urlopen


class SSRFBlockedError(ValueError):
    """Raised when an outbound URL/host violates anti-SSRF policy."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"Redirección HTTP bloqueada por política anti-SSRF ({code} -> {newurl})",
            headers,
            fp,
        )


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def validate_safe_id(value: str, label: str = "identificador") -> str:
    """Validate an identifier used in filesystem paths against path traversal."""
    clean = str(value or "").strip()
    if (
        not clean
        or clean in (".", "..")
        or ".." in clean
        or "/" in clean
        or "\\" in clean
        or "\x00" in clean
        or not _SAFE_ID_RE.match(clean)
    ):
        raise ValueError(f"{label} inválido o inseguro: '{clean[:64]}'")
    return clean


def _is_disallowed_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool) -> Optional[str]:
    if ip_obj == _EC2_IMDS_V6 or ip_obj.is_link_local:
        return "Rango link-local / AWS Instance Metadata bloqueado por política anti-SSRF."
    if ip_obj.is_loopback:
        return "Dirección loopback no permitida por política anti-SSRF."
    if ip_obj.is_multicast or ip_obj.is_unspecified or ip_obj.is_reserved:
        return "Dirección IP reservada, multicast o no especificada no permitida."
    if not allow_private:
        if ip_obj.is_private:
            return "Rango IP privado (RFC1918 / ULA / VPC interna) no permitido."
        if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in _CGNAT_NET:
            return "Rango CGNAT (100.64.0.0/10) no permitido para sondas externas."
    return None


def validate_public_target_host(host: str, allow_private: bool = False) -> str:
    """
    Validate a target hostname or IP string against SSRF, resolving DNS names and
    checking all returned IPv4/IPv6 addresses before any outbound socket/HTTP call.
    """
    raw = str(host or "").strip()
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:raw.index("]")]
    else:
        raw = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]

    clean_host = raw.strip().rstrip(".")
    lower = clean_host.lower()

    if not clean_host or len(clean_host) > 253:
        raise SSRFBlockedError("Dirección IP o hostname inválido.")
    if lower in _BLOCKED_METADATA_HOSTS or lower.endswith(".local") or lower.endswith(".localhost"):
        raise SSRFBlockedError("Host local o endpoint de metadata cloud no permitido.")

    # Literal IP address check
    try:
        ip_obj = ipaddress.ip_address(clean_host)
        reason = _is_disallowed_ip(ip_obj, allow_private=allow_private)
        if reason:
            raise SSRFBlockedError(reason)
        return clean_host
    except ValueError:
        pass

    if not _HOSTNAME_RE.match(clean_host):
        raise SSRFBlockedError("Caracteres no válidos en el hostname destino.")
    if not allow_private and (lower.endswith(".internal") or "." not in lower):
        raise SSRFBlockedError("Dominios internos (.internal / single-label) no permitidos.")

    # Resolve hostname via DNS and inspect every returned IP to stop DNS rebinding / nip.io bypasses
    try:
        addr_infos = socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        if allow_private:
            # Allow offline private connector hostnames (e.g., mocked unit tests) after literal checks
            return clean_host
        raise SSRFBlockedError(f"No se pudo resolver DNS para '{clean_host}': {exc}") from exc

    resolved_ips: List[str] = []
    for info in addr_infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = str(sockaddr[0]).split("%")[0]
        resolved_ips.append(ip_str)
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        reason = _is_disallowed_ip(ip_obj, allow_private=allow_private)
        if reason:
            raise SSRFBlockedError(f"{reason} (DNS '{clean_host}' -> {ip_str})")

    if not resolved_ips and not allow_private:
        raise SSRFBlockedError(f"El hostname '{clean_host}' no devolvió direcciones IP válidas.")

    return clean_host


def validate_public_url(url: str, allow_private: bool = False) -> urllib.parse.ParseResult:
    """Validate URL scheme (`http`/`https`), absence of embedded credentials, and target host."""
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFBlockedError(f"Esquema URL '{parsed.scheme}' no permitido; solo http/https.")
    if parsed.username or parsed.password:
        raise SSRFBlockedError("Las URLs con credenciales embebidas no están permitidas.")
    if not parsed.hostname:
        raise SSRFBlockedError("La URL no contiene un hostname válido.")
    validate_public_target_host(parsed.hostname, allow_private=allow_private)
    return parsed


def open_url_no_redirects(req: urllib.request.Request, timeout: float = 8.0):
    """
    Open HTTP(S) request blocking HTTP redirects to prevent SSRF bypasses.
    Falls back to `urllib.request.urlopen` when monkeypatched inside unit tests.
    """
    if urllib.request.urlopen is not _ORIGINAL_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)
    return _NO_REDIRECT_OPENER.open(req, timeout=timeout)


def _csv_env_set(var_name: str) -> Set[str]:
    raw = os.getenv(var_name, "")
    return {x.strip() for x in raw.split(",") if x.strip()}


@lru_cache(maxsize=1)
def get_control_plane_metadata() -> Dict[str, Any]:
    """
    Identify the CloudMove control-plane host dynamically (via AWS EC2 IMDSv2 when running on EC2
    plus optional `CLOUDMOVE_*` environment variables) so it stays hidden/protected in multi-user
    AWS Academy audits without hardcoding account-specific IDs in source code.
    """
    protected_instance_ids: Set[str] = _csv_env_set("CLOUDMOVE_PROTECTED_INSTANCE_IDS")
    protected_vpc_ids: Set[str] = _csv_env_set("CLOUDMOVE_PROTECTED_VPC_IDS")
    protected_ips: Set[str] = _csv_env_set("CLOUDMOVE_CONTROL_PLANE_IPS")
    protected_hosts: Set[str] = {"cloudmove-server", "localhost", "127.0.0.1"} | {
        h.lower() for h in _csv_env_set("CLOUDMOVE_CONTROL_PLANE_HOSTS")
    }

    public_api_url = os.getenv("CLOUDMOVE_API_URL", "").strip().rstrip("/")
    if public_api_url:
        try:
            parsed = urllib.parse.urlparse(public_api_url)
            if parsed.hostname:
                protected_hosts.add(parsed.hostname.lower())
        except Exception:
            pass

    self_instance_id = ""
    self_public_ip = ""
    self_private_ip = ""

    # Only probe IMDSv2 if explicitly opted in or not disabled (short 0.25s timeout; zero impact off-EC2)
    if os.getenv("CLOUDMOVE_ENABLE_IMDS_SELF_DISCOVERY", "true").lower() == "true" and not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            tok_req = urllib.request.Request(
                "http://169.254.169.254/latest/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
                method="PUT",
            )
            with _ORIGINAL_URLOPEN(tok_req, timeout=0.25) as resp:
                token = resp.read().decode("utf-8").strip()
            if token:
                hdrs = {"X-aws-ec2-metadata-token": token}
                for key, target_attr in (
                    ("instance-id", "iid"),
                    ("public-ipv4", "pub"),
                    ("local-ipv4", "priv"),
                ):
                    try:
                        mreq = urllib.request.Request(
                            f"http://169.254.169.254/latest/meta-data/{key}",
                            headers=hdrs,
                        )
                        with _ORIGINAL_URLOPEN(mreq, timeout=0.25) as mresp:
                            val = mresp.read().decode("utf-8").strip()
                            if target_attr == "iid" and val:
                                self_instance_id = val
                                protected_instance_ids.add(val)
                            elif target_attr == "pub" and val:
                                self_public_ip = val
                                protected_ips.add(val)
                            elif target_attr == "priv" and val:
                                self_private_ip = val
                                protected_ips.add(val)
                    except Exception:
                        pass
        except Exception:
            pass

    return {
        "protected_instance_ids": protected_instance_ids,
        "protected_vpc_ids": protected_vpc_ids,
        "protected_ips": protected_ips,
        "protected_hosts": protected_hosts,
        "self_instance_id": self_instance_id,
        "self_public_ip": self_public_ip,
        "self_private_ip": self_private_ip,
        "public_api_url": public_api_url,
    }


def is_control_plane_agent(agent: Dict[str, Any]) -> bool:
    """Return True if an agent record belongs to the CloudMove server container/host itself."""
    meta = get_control_plane_metadata()
    hostname = str(agent.get("hostname") or "").strip().lower()
    ip_addr = str(agent.get("ip_address") or "").strip()
    if hostname in meta["protected_hosts"]:
        return True
    if re.fullmatch(r"[0-9a-f]{12}", hostname):  # Docker container ID hostname
        return True
    if ip_addr and ip_addr in meta["protected_ips"]:
        return True
    return False
