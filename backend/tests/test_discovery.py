import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.cmir.validator import validate_cmir
from app.discovery.models import DataState, OpenAudITCollectorAdapter
from app.discovery.osquery_parser import OsqueryDiscoveryParser, parse_int_strict, format_bytes
from app.discovery.cmir_bridge import build_discovery_cmir_and_graph
from app.discovery.storage import DEFAULT_OSQUERY_JSON_PATH, DiscoverySessionStore

client = TestClient(app)


def _minimal_valid_inventory(**overrides):
    base = {
        "schema_version": "cloudmove.discovery.v1",
        "source": {
            "tool": "osquery",
            "tool_version": "osqueryi version 5.23.1",
            "collector": "synthetic_test_collector.py",
            "collector_host": "srv-synth-01",
        },
        "collected_at": "2026-10-19T18:00:00+00:00",
        "asset": {
            "hostname": "srv-synth-01",
            "uuid": "00000000-1111-2222-3333-444444444444",
            "hardware_vendor": "Dell Inc.",
            "hardware_model": "PowerEdge R650",
            "cpu_type": "x86_64",
            "cpu_logical_cores": "32",
            "cpu_physical_cores": "16",
            "physical_memory_bytes": "68719476736",
            "os": {
                "name": "Debian GNU/Linux",
                "version": "12",
                "codename": "bookworm",
                "arch": "x86_64",
                "platform": "debian",
                "platform_like": "debian",
            },
            "platform": {
                "firmware_type": "uefi",
                "vendor": "Dell Inc.",
                "version": "1.12.0",
            },
            "system_info": {
                "computer_name": "srv-synth-01",
                "hostname": "srv-synth-01",
                "cpu_brand": "Intel(R) Xeon(R) Gold 6326",
            },
        },
        "hardware": {
            "cpu_info": [
                {
                    "model": "Intel(R) Xeon(R) Gold 6326",
                    "manufacturer": "Intel",
                    "number_of_cores": "16",
                    "logical_processors": "32",
                    "max_clock_speed": "3500",
                    "current_clock_speed": "2900",
                }
            ],
            "memory_info": [
                {
                    "memory_total": "68719476736",
                    "memory_available": "34359738368",
                    "memory_free": "17179869184",
                    "cached": "17179869184",
                    "buffers": "1073741824",
                    "swap_total": "0",
                    "swap_free": "0",
                }
            ],
            "block_devices": [
                {
                    "name": "/dev/sda",
                    "parent": "",
                    "model": "PERC H755",
                    "size": "200000000",
                    "block_size": "512",
                    "type": "",
                },
                {
                    "name": "/dev/sda1",
                    "parent": "/dev/sda",
                    "model": "PERC H755",
                    "size": "190000000",
                    "block_size": "",
                    "type": "ext4",
                },
            ],
            "mounts": [
                {
                    "device": "/dev/sda1",
                    "path": "/",
                    "type": "ext4",
                    "blocks": "23750000",
                    "blocks_available": "15000000",
                    "blocks_free": "16000000",
                    "blocks_size": "4096",
                }
            ],
        },
        "network": {
            "interfaces": [
                {
                    "interface": "lo",
                    "address": "127.0.0.1",
                    "mask": "255.0.0.0",
                    "type": "unknown",
                },
                {
                    "interface": "eth0",
                    "address": "10.20.30.40",
                    "mask": "255.255.255.0",
                    "type": "unknown",
                },
                {
                    "interface": "eth0",
                    "address": "fe80::1234:5678%eth0",
                    "mask": "ffff:ffff:ffff:ffff::",
                    "type": "unknown",
                },
            ],
            "routes": [
                {
                    "destination": "0.0.0.0",
                    "gateway": "10.20.30.1",
                    "interface": "eth0",
                    "netmask": "0",
                    "type": "gateway",
                    "metric": "100",
                }
            ],
            "listening_ports": [
                {"address": "0.0.0.0", "port": "22", "protocol": "6", "pid": "500"},
            ],
            "process_open_sockets": [
                {
                    "pid": "500",
                    "fd": "3",
                    "family": "2",
                    "protocol": "6",
                    "local_address": "10.20.30.40",
                    "local_port": "22",
                    "remote_address": "10.20.30.99",
                    "remote_port": "51234",
                }
            ],
        },
        "software": {
            "deb_packages": [
                {
                    "name": "openssh-server",
                    "version": "1:9.2p1",
                    "arch": "amd64",
                    "section": "net",
                    "status": "install ok installed",
                    "size": "1800",
                }
            ],
            "systemd_units": [
                {
                    "id": "ssh.service",
                    "active_state": "active",
                    "sub_state": "running",
                    "load_state": "loaded",
                    "unit_file_state": "enabled",
                    "description": "OpenBSD Secure Shell server",
                }
            ],
            "kernel_modules": [
                {"name": "xt_conntrack", "size": "16384", "status": "Live", "used_by": "-"}
            ],
        },
        "runtime": {
            "processes": [
                {"pid": "500", "name": "sshd", "path": "/usr/sbin/sshd", "uid": "0"}
            ],
            "uptime": [
                {"days": "10", "hours": "4", "minutes": "30", "seconds": "12", "total_seconds": "880212"}
            ],
        },
        "collection": {
            "query_count": 16,
            "successful_query_count": 16,
            "errors": [],
        },
    }
    base.update(overrides)
    return base


# 1. Real osquery JSON inventory test
@pytest.mark.skipif(
    not DEFAULT_OSQUERY_JSON_PATH.is_file(),
    reason="Real osquery inventory file not present in environment",
)
def test_real_osquery_inventory_parsing_and_cmir():
    raw = json.loads(DEFAULT_OSQUERY_JSON_PATH.read_text(encoding="utf-8"))
    parser = OsqueryDiscoveryParser()
    normalized = parser.parse(raw)

    assert normalized["schema_version"] == "cloudmove.normalized.v1"
    summary = normalized["summary"]
    assert summary["hostname"] in ("rabbitmq-kali", "slopma")
    assert "Kali" in summary["os"]["name"]
    assert summary["metrics"]["cpu_physical_cores"] >= 1
    assert summary["metrics"]["cpu_logical_cores"] >= 1
    assert summary["metrics"]["memory_total_bytes"] > 0

    # Ensure physical disk vs child partitions separation (never summing partitions into physical disk total!)
    stg = normalized["sections"]["hardware"]["storage"]
    assert len(stg["physical_disks"]) >= 1
    assert len(stg["partitions"]) >= 1
    assert stg["physical_disks"][0]["name"].startswith("/dev/")
    assert stg["total_physical_bytes"] > 0

    # Build CMIR and validate
    cmir, graph, validation = build_discovery_cmir_and_graph(normalized)
    assert validation["valid"] is True
    assert len(validation["errors"]) == 0
    assert graph["root_node_id"] in (f"host-{summary['hostname']}", "host-rabbitmq-kali", "host-slopma")


# 2. Empty or malformed JSON
def test_empty_and_malformed_json_rejected():
    parser = OsqueryDiscoveryParser()
    assert len(parser.validate_payload({})) > 0
    assert len(parser.validate_payload([])) > 0
    assert len(parser.validate_payload("not-a-dict")) > 0

    with pytest.raises(ValueError):
        parser.parse({})


# 3. Unsupported schema version
def test_unsupported_schema_rejected():
    parser = OsqueryDiscoveryParser()
    bad = _minimal_valid_inventory(schema_version="unknown.schema.v99")
    errors = parser.validate_payload(bad)
    assert any("no soportado" in e for e in errors)
    with pytest.raises(ValueError, match="no soportado"):
        parser.parse(bad)


# 4. Missing optional fields & 6. Empty tables
def test_missing_optional_fields_and_empty_tables():
    parser = OsqueryDiscoveryParser()
    minimal = {
        "schema_version": "cloudmove.discovery.v1",
        "asset": {"hostname": "minimal-node"},
        "hardware": {},
        "network": {},
        "software": {},
        "runtime": {},
    }
    norm = parser.parse(minimal)
    assert norm["summary"]["hostname"] == "minimal-node"
    assert norm["summary"]["uuid"] is None
    assert norm["summary"]["metrics"]["cpu_physical_cores"] is None
    assert norm["summary"]["metrics"]["installed_packages_count"] == 0
    assert norm["summary"]["metrics"]["processes_count"] == 0
    assert len(norm["summary"]["collection_quality"]["missing_fields"]) >= 2


# 5. Numeric strings, zero vs null/empty preservation
def test_numeric_strings_and_zero_vs_null():
    val_zero, state_zero = parse_int_strict("0")
    assert val_zero == 0
    assert state_zero == DataState.OBSERVED
    assert format_bytes(val_zero) == "0 B"

    val_empty, state_empty = parse_int_strict("")
    assert val_empty is None
    assert state_empty == DataState.UNAVAILABLE
    assert format_bytes(val_empty) is None

    val_none, state_none = parse_int_strict(None)
    assert val_none is None
    assert state_none == DataState.UNAVAILABLE

    val_err, state_err = parse_int_strict("not_a_number")
    assert val_err is None
    assert state_err == DataState.ERROR


# 7. Collector query errors recorded
def test_collector_query_errors_recorded():
    parser = OsqueryDiscoveryParser()
    inv = _minimal_valid_inventory(
        collection={
            "query_count": 16,
            "successful_query_count": 14,
            "errors": [
                {"query": "deb_packages", "error": "timeout"},
                {"query": "systemd_units", "error": "permission denied"},
            ],
        }
    )
    norm = parser.parse(inv)
    error_issues = [i for i in norm["issues"] if i["code"] == "COLLECTOR_QUERY_ERROR"]
    assert len(error_issues) == 2
    assert norm["summary"]["collection_quality"]["error_count"] == 2


# 8 & 9. IPv4 and IPv6 interfaces, routes, and subnet mask derivation
def test_ipv4_ipv6_interfaces_and_routes():
    parser = OsqueryDiscoveryParser()
    inv = _minimal_valid_inventory()
    norm = parser.parse(inv)
    ifaces = norm["sections"]["network"]["interfaces"]
    eth_v4 = next(i for i in ifaces if i["interface"] == "eth0" and i["ip_version"] == "IPv4")
    eth_v6 = next(i for i in ifaces if i["interface"] == "eth0" and i["ip_version"] == "IPv6")

    assert eth_v4["subnet"] == "10.20.30.0/24"
    assert eth_v4["cidr"] == "10.20.30.40/24"
    assert eth_v6["subnet"] == "fe80::/64"
    assert norm["sections"]["network"]["default_gateways"] == ["10.20.30.1"]


# 10 & 11. Unmatched listener PIDs & incomplete sockets
def test_unmatched_listener_pids_and_incomplete_sockets():
    parser = OsqueryDiscoveryParser()
    inv = _minimal_valid_inventory()
    inv["network"]["listening_ports"].append(
        {"address": "0.0.0.0", "port": "8080", "protocol": "6", "pid": "99999"}
    )
    inv["network"]["process_open_sockets"].extend([
        {"pid": "500", "local_address": "0.0.0.0", "local_port": "22", "remote_address": "0.0.0.0", "remote_port": "0", "protocol": "6"},
        {"pid": "500", "local_address": "127.0.0.1", "local_port": "80", "remote_address": "127.0.0.1", "remote_port": "44111", "protocol": "6"},
        {"pid": "500", "local_address": "10.20.30.40", "local_port": "45000", "remote_address": "invalid_ip", "remote_port": "443", "protocol": "6"},
    ])

    norm = parser.parse(inv)
    codes = {i["code"] for i in norm["issues"]}
    assert "UNMATCHED_LISTENER_PIDS" in codes

    unmatched = next(l for l in norm["sections"]["network"]["listening_ports"] if l["port"] == 8080)
    assert unmatched["pid_matched"] is False

    sock_summary = norm["sections"]["network"]["socket_summary"]
    assert sock_summary["unconnected_or_incomplete_sockets"] == 2
    assert sock_summary["local_loopback_sockets"] == 1
    assert sock_summary["remote_connected_sockets"] == 1


# 12, 13 & 14. Large inventory aggregation, no invented DBs or confirmed dependencies
def test_large_inventory_graph_aggregation_and_no_invented_relations():
    parser = OsqueryDiscoveryParser()
    inv = _minimal_valid_inventory()
    # Generate 2,500 packages including postgresql/mariadb, and 400 background processes
    inv["software"]["deb_packages"] = [
        {
            "name": f"lib-synth-pkg-{i}",
            "version": "1.0.0",
            "arch": "amd64",
            "section": "libs",
            "status": "install ok installed",
            "size": "100",
        }
        for i in range(2500)
    ] + [
        {
            "name": "postgresql-18",
            "version": "18.6-3",
            "arch": "amd64",
            "section": "database",
            "status": "install ok installed",
            "size": "15000",
        }
    ]
    inv["runtime"]["processes"].extend([
        {"pid": str(1000 + i), "name": f"worker-{i}", "path": "/usr/bin/worker", "uid": "1000"}
        for i in range(400)
    ])

    norm = parser.parse(inv)
    assert norm["sections"]["software"]["package_count"] == 2501
    assert norm["sections"]["runtime"]["process_count"] == 401

    # Verify PostgreSQL package does NOT invent a running database instance
    db_ev = norm["sections"]["databases"]["detected_engine_evidence"]
    pg_ev = next(e for e in db_ev if e["engine_id"] == "postgresql")
    assert pg_ev["runtime_status"] == "packages_installed_only_not_running"
    assert "No recopilado" in pg_ev["catalog_metadata_status"]

    # Verify interactive graph stays compact (< 100 nodes even with 2,501 packages and 401 processes!)
    cmir, graph, validation = build_discovery_cmir_and_graph(norm)
    assert validation["valid"] is True
    assert len(graph["nodes"]) < 100

    # Verify remote endpoints use 'observed_connection' (never confirmed 'depends_on')
    remote_edges = [e for e in graph["edges"] if e["target"].startswith("peer-")]
    for edge in remote_edges:
        assert edge["type"] in ("contains", "observed_connection")
        assert edge["type"] != "depends_on"


# 15 & 16. Backend endpoints error handling + Export and Re-import of normalized inventory
def test_api_import_errors_and_export_reimport_cycle():
    # Invalid MIME type
    res_mime = client.post(
        "/api/v1/discovery/import",
        content=b"<html></html>",
        headers={"Content-Type": "text/html"},
    )
    assert res_mime.status_code == 415

    # Malformed JSON syntax
    res_bad_json = client.post(
        "/api/v1/discovery/import",
        content=b"{corrupted json",
        headers={"Content-Type": "application/json"},
    )
    assert res_bad_json.status_code == 400
    assert res_bad_json.json()["detail"]["code"] == "INVALID_JSON_SYNTAX"

    # Unsupported schema
    res_bad_schema = client.post(
        "/api/v1/discovery/import",
        json={"schema_version": "unsupported.v0", "asset": {"hostname": "x"}},
    )
    assert res_bad_schema.status_code == 422

    # Valid import
    valid_payload = _minimal_valid_inventory()
    res_ok = client.post("/api/v1/discovery/import", json=valid_payload)
    assert res_ok.status_code == 200
    session_data = res_ok.json()
    sid = session_data["session_id"]
    assert session_data["hostname"] == "srv-synth-01"

    # Query packages & processes endpoints
    res_pkgs = client.get(f"/api/v1/discovery/sessions/{sid}/packages?q=openssh")
    assert res_pkgs.status_code == 200
    assert res_pkgs.json()["total"] == 1

    res_procs = client.get(f"/api/v1/discovery/sessions/{sid}/processes?only_network=true")
    assert res_procs.status_code == 200
    assert res_procs.json()["total"] == 1

    # Export normalized JSON
    res_export = client.get(f"/api/v1/discovery/sessions/{sid}/export?format=json")
    assert res_export.status_code == 200
    exported_norm = res_export.json()
    assert exported_norm["schema_version"] == "cloudmove.normalized.v1"

    # Export Markdown report
    res_md = client.get(f"/api/v1/discovery/sessions/{sid}/export?format=md")
    assert res_md.status_code == 200
    assert "# CloudMove Discovery Report" in res_md.text

    # Re-import the exported normalized inventory JSON!
    res_reimport = client.post("/api/v1/discovery/import", json=exported_norm)
    assert res_reimport.status_code == 200
    reimported_data = res_reimport.json()
    assert reimported_data["reimported"] is True
    assert reimported_data["hostname"] == "srv-synth-01"
    assert reimported_data["cmir_validation"]["valid"] is True

    # Verify Open-AudIT collector adapter interface readiness
    open_audit = OpenAudITCollectorAdapter()
    assert open_audit.can_parse({"schema_version": "cloudmove.openaudit.v1"}) is True

    # Verify Terraform generation endpoint and inline bundle
    assert "terraform" in session_data
    assert "replatform" in session_data["terraform"]
    assert "rehost" in session_data["terraform"]
    tf_res = client.get(f"/api/v1/discovery/sessions/{sid}/terraform?strategy=replatform")
    assert tf_res.status_code == 200
    tf_payload = tf_res.json()
    assert "main.tf" in tf_payload["files"]
    assert "variables.tf" in tf_payload["files"]
    assert "provider.tf" in tf_payload["files"]
    assert "outputs.tf" in tf_payload["files"]
    assert len(tf_payload["traceability"]) >= 4


def test_real_osquery_to_aws_terraform_traceability():
    if not DEFAULT_OSQUERY_JSON_PATH.exists():
        pytest.skip("Real osquery inventory file not present")

    res = client.post("/api/v1/discovery/import-local")
    assert res.status_code == 200
    data = res.json()
    replatform_tf = data["terraform"]["replatform"]
    rehost_tf = data["terraform"]["rehost"]

    # Sizing dynamically checks instance_type and alternatives based on collected metrics
    assert replatform_tf["sizing"]["instance_type"] in ("c6i.2xlarge", "t3a.xlarge", "t3.xlarge")
    assert replatform_tf["sizing"]["right_sized_alternative"] in ("t3.xlarge", "t3a.medium", "t3.large")
    assert replatform_tf["cmir_nodes_translated"] >= 15

    # Replatform includes VPC, EC2, NVMe EBS gp3, and RDS PostgreSQL
    main_replatform = replatform_tf["files"]["main.tf"]
    assert 'resource "aws_vpc"' in main_replatform
    assert 'resource "aws_instance"' in main_replatform
    assert 'resource "aws_ebs_volume"' in main_replatform
    assert 'resource "aws_db_instance"' in main_replatform

    # Rehost keeps everything on EC2 + EBS without creating separate RDS/MQ
    main_rehost = rehost_tf["files"]["main.tf"]
    assert 'resource "aws_instance"' in main_rehost
    assert 'resource "aws_ebs_volume"' in main_rehost
    assert 'resource "aws_db_instance"' not in main_rehost


def test_collector_script_and_live_device_endpoint():
    script_res = client.get("/api/v1/discovery/collector-script")
    assert script_res.status_code == 200
    assert "collect_osquery_inventory" in script_res.text
    assert "launch_local_ui" in script_res.text

    catalog_res = client.get("/api/v1/discovery/osquery-catalog")
    assert catalog_res.status_code == 200
    cat = catalog_res.json()
    assert cat["available_web_assets_count"] >= 8
    assert cat["recommended_asset_for_pc"] is not None

    import shutil
    if shutil.which("osqueryi"):
        live_res = client.post("/api/v1/discovery/collect-device?persist_json=false")
        assert live_res.status_code == 200
        live_data = live_res.json()
        assert live_data["cmir_validation"]["valid"] is True
        assert live_data["hostname"]
        assert "terraform" in live_data
        assert live_data["agent_smoke_test"]["verified"] is True


def test_multi_os_installer_catalog_and_local_agent():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from cloudmove_agent.osquery_installer import (
        FALLBACK_RELEASE_ASSETS,
        _extract_archive_safely,
        fetch_available_release_assets,
        select_asset_for_current_pc,
    )
    from cloudmove_agent.app import app as agent_app
    import io
    import tarfile
    import tempfile

    # Verify tar.gz with internal absolute symlink ('usr/bin/osqueryi' -> '/opt/osquery/bin/osqueryd')
    # extracts cleanly under Python 3.12+ filter="data" by converting to a safe relative symlink
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "osquery-mock.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            payload = b"#!/bin/sh\necho 5.23.1\n"
            bin_info = tarfile.TarInfo(name="opt/osquery/bin/osqueryd")
            bin_info.size = len(payload)
            bin_info.mode = 0o755
            tf.addfile(bin_info, io.BytesIO(payload))

            sym_info = tarfile.TarInfo(name="usr/bin/osqueryi")
            sym_info.type = tarfile.SYMTYPE
            sym_info.linkname = "/opt/osquery/bin/osqueryd"
            tf.addfile(sym_info)

        extracted_dir = Path(tmp) / "extracted"
        _extract_archive_safely(tar_path, "tar.gz", extracted_dir)
        extracted_sym = extracted_dir / "usr/bin/osqueryi"
        assert extracted_sym.is_symlink()
        assert str(extracted_sym.readlink()) == "../../opt/osquery/bin/osqueryd"
        assert extracted_sym.resolve().is_file()

    assets, source = fetch_available_release_assets(timeout=5)
    assert len(assets) >= 8

    # Verify automatic selection across any PC (Linux x86_64/ARM64, Windows x86_64/ARM64, macOS ARM64/x86_64)
    linux_x64 = select_asset_for_current_pc(
        FALLBACK_RELEASE_ASSETS, {"os": "linux", "arch": "x86_64", "raw_system": "Linux", "raw_machine": "x86_64"}
    )
    assert linux_x64["name"].endswith(".linux_x86_64.tar.gz")
    assert linux_x64["portable"] is True
    assert linux_x64["sha256"]

    linux_arm = select_asset_for_current_pc(
        FALLBACK_RELEASE_ASSETS, {"os": "linux", "arch": "aarch64", "raw_system": "Linux", "raw_machine": "aarch64"}
    )
    assert linux_arm["name"].endswith(".linux_aarch64.tar.gz")

    win_x64 = select_asset_for_current_pc(
        FALLBACK_RELEASE_ASSETS, {"os": "windows", "arch": "x86_64", "raw_system": "Windows", "raw_machine": "AMD64"}
    )
    assert win_x64["name"].endswith(".windows_x86_64.zip")

    win_arm = select_asset_for_current_pc(
        FALLBACK_RELEASE_ASSETS, {"os": "windows", "arch": "aarch64", "raw_system": "Windows", "raw_machine": "ARM64"}
    )
    assert win_arm["name"].endswith(".windows_arm64.zip")

    mac_arm = select_asset_for_current_pc(
        FALLBACK_RELEASE_ASSETS, {"os": "darwin", "arch": "aarch64", "raw_system": "Darwin", "raw_machine": "arm64"}
    )
    assert "macos" in mac_arm["name"] and mac_arm["format"] == "tar.gz"

    # Test decoupled local agent FastAPI endpoints (/health, /catalog, /discover, /inventory)
    from cloudmove_agent.osquery_installer import _resolve_osquery_dirs, find_existing_osquery
    import stat

    if not find_existing_osquery():
        # In offline/sandboxed CI environments without preinstalled osqueryi, install a clean mock osqueryi binary
        _, bin_dir, bname = _resolve_osquery_dirs()
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_osquery = bin_dir / bname
        mock_osquery.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "args = ' '.join(sys.argv[1:])\n"
            "if '--version' in args:\n"
            "    print('osqueryi version 5.23.1')\n"
            "    sys.exit(0)\n"
            "if 'osquery_info' in args:\n"
            "    print(json.dumps([{'version': '5.23.1', 'build_platform': 'linux', 'build_distro': 'ubuntu'}]))\n"
            "elif 'system_info' in args:\n"
            "    print(json.dumps([{'hostname': 'test-agent-node', 'computer_name': 'test-agent-node', 'cpu_logical_cores': '4', 'cpu_physical_cores': '2', 'physical_memory': '8589934592', 'uuid': '00000000-0000-0000-0000-000000000001'}]))\n"
            "elif 'os_version' in args:\n"
            "    print(json.dumps([{'name': 'Ubuntu', 'version': '22.04', 'platform': 'ubuntu', 'arch': 'x86_64'}]))\n"
            "else:\n"
            "    print('[]')\n",
            encoding="utf-8",
        )
        mock_osquery.chmod(mock_osquery.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    agent_client = TestClient(agent_app)
    health_res = agent_client.get("/health")
    assert health_res.status_code == 200
    health_json = health_res.json()
    assert health_json["collector_exists"] is True
    assert health_json["recommended_asset_for_pc"] is not None

    disc_res = agent_client.post("/discover")
    assert disc_res.status_code == 200
    disc_json = disc_res.json()
    assert disc_json["status"] == "completed"
    assert disc_json["smoke_test"]["verified"] is True

    inv_res = agent_client.get("/inventory")
    assert inv_res.status_code == 200
    inv_doc = inv_res.json()
    assert inv_doc["schema_version"] == "cloudmove.discovery.v1"


def test_proxmox_connector_pagination_auth_timeout_and_ssrf():
    from app.discovery.connectors import (
        ConnectorAuthError,
        ConnectorTimeoutError,
        ProxmoxVEConnector,
        SecurityPolicyViolationError,
        validate_endpoint_against_ssrf,
    )

    # Anti-SSRF checks
    with pytest.raises(SecurityPolicyViolationError):
        validate_endpoint_against_ssrf("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SecurityPolicyViolationError):
        validate_endpoint_against_ssrf("file:///etc/passwd")

    # Partial config without transport -> test_connection returns ready_simulated, while _request_json raises ConnectorAuthError
    partial_conn = ProxmoxVEConnector(
        api_url="https://pve.internal:8006/api2/json",
        token_id="root@pam!tok",
        token_secret=None,
    )
    assert partial_conn.test_connection()["status"] == "ready_simulated"
    with pytest.raises(ConnectorAuthError):
        partial_conn.discover_infrastructure()

    # Mock transport for pagination, 401/403 and timeout
    def mock_transport(url: str, token_id: str, token_secret: str, timeout: int):
        if "unauthorized" in url:
            raise ConnectorAuthError("HTTP_401", "HTTP 401 Unauthorized")
        if "timeout" in url:
            raise ConnectorTimeoutError("Timeout connecting to Proxmox")
        if url.endswith("/version"):
            return {"data": {"version": "8.2-1", "release": "8.2"}}
        if url.endswith("/nodes"):
            return {"data": [{"node": "pve-01", "status": "online", "maxcpu": 16, "maxmem": 68719476736}]}
        if url.endswith("/cluster/resources"):
            return {
                "data": [
                    {"type": "qemu", "vmid": 101, "name": "vm-01", "node": "pve-01", "status": "running", "maxcpu": 4, "maxmem": 8589934592},
                    {"type": "qemu", "vmid": 102, "name": "vm-02", "node": "pve-01", "status": "running", "maxcpu": 8, "maxmem": 17179869184},
                    {"type": "storage", "storage": "ceph-nvme", "node": "pve-01", "plugintype": "rbd", "maxdisk": 1099511627776, "disk": 274877906944},
                ]
            }
        return {"data": {"ostype": "l26", "bios": "uefi"}}

    conn = ProxmoxVEConnector(
        api_url="https://pve.internal:8006/api2/json",
        token_id="cloudmove@pve!ro",
        token_secret="secret-val",
        http_transport=mock_transport,
    )
    assert conn.test_connection()["status"] == "connected"

    page1 = conn.discover_infrastructure(page=1, page_size=1)
    assert page1["total_vms"] == 2
    assert len(page1["virtual_machines"]) == 1
    assert page1["has_more"] is True

    # 401/403 Auth error propagation
    bad_auth_conn = ProxmoxVEConnector(
        api_url="https://unauthorized.internal:8006/api2/json",
        http_transport=mock_transport,
    )
    with pytest.raises(ConnectorAuthError):
        bad_auth_conn.discover_infrastructure()

    # Timeout propagation
    timeout_conn = ProxmoxVEConnector(
        api_url="https://timeout.internal:8006/api2/json",
        http_transport=mock_transport,
    )
    with pytest.raises(ConnectorTimeoutError):
        timeout_conn.discover_infrastructure()


def test_secret_redactor_and_architecture_scanner_security():
    from app.discovery.connectors import (
        ArchitectureFileScanner,
        SecretRedactor,
        SecurityPolicyViolationError,
    )

    raw_sample = """
    database_url = "postgresql://erp_admin:SuperSecret99!@10.0.2.42:5432/erp_prod"
    api_token = "tok_live_987654321abcdef"
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    -----BEGIN RSA PRIVATE KEY-----
    MIIEowIBAAKCAQEA0123456789abcdef
    -----END RSA PRIVATE KEY-----
    """
    redacted, refs = SecretRedactor.redact_text(raw_sample)
    assert "SuperSecret99!" not in redacted
    assert "tok_live_987654321abcdef" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "MIIEowIBAAKCAQEA0123456789abcdef" not in redacted
    assert len(refs) >= 3

    scanner = ArchitectureFileScanner()
    artifacts = scanner.scan_authorized_directories()
    assert len(artifacts) >= 2

    # Unauthorized directory / path traversal must raise SecurityPolicyViolationError
    with pytest.raises(SecurityPolicyViolationError):
        scanner.scan_file(Path("/etc/passwd"))






