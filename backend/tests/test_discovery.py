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
    assert summary["hostname"] == "rabbitmq-kali"
    assert summary["os"]["name"] == "Kali GNU/Linux"
    assert summary["os"]["version"] == "2026.3"
    assert summary["metrics"]["cpu_physical_cores"] == 10
    assert summary["metrics"]["cpu_logical_cores"] == 16
    assert summary["metrics"]["memory_total_bytes"] == 16481103872

    # Ensure physical disk vs child partitions separation (never summing partitions into physical disk total!)
    stg = normalized["sections"]["hardware"]["storage"]
    assert len(stg["physical_disks"]) == 1
    assert len(stg["partitions"]) == 3
    assert stg["physical_disks"][0]["name"] == "/dev/nvme0n1"
    assert stg["total_physical_bytes"] == 1000215216 * 512

    # Build CMIR and validate
    cmir, graph, validation = build_discovery_cmir_and_graph(normalized)
    assert validation["valid"] is True
    assert len(validation["errors"]) == 0
    assert graph["root_node_id"] == "host-rabbitmq-kali"


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

    # Sizing reflects 10C/16T Intel Core i7-1255U and 15.35 GiB RAM -> c6i.2xlarge (with right-sized option t3.xlarge)
    assert replatform_tf["sizing"]["instance_type"] == "c6i.2xlarge"
    assert replatform_tf["sizing"]["right_sized_alternative"] == "t3.xlarge"
    assert replatform_tf["cmir_nodes_translated"] >= 20

    # Replatform includes VPC, EC2, NVMe EBS gp3, RDS PostgreSQL, and Amazon MQ for RabbitMQ
    main_replatform = replatform_tf["files"]["main.tf"]
    assert 'resource "aws_vpc" "rabbitmq_kali_vpc"' in main_replatform
    assert 'resource "aws_instance" "rabbitmq_kali"' in main_replatform
    assert 'resource "aws_ebs_volume" "rabbitmq_kali_disk_nvme0n1"' in main_replatform
    assert 'resource "aws_db_instance" "rabbitmq_kali_postgres"' in main_replatform
    assert 'resource "aws_mq_broker" "rabbitmq_kali_rabbitmq"' in main_replatform

    # Rehost keeps everything on EC2 + EBS without creating separate RDS/MQ
    main_rehost = rehost_tf["files"]["main.tf"]
    assert 'resource "aws_instance" "rabbitmq_kali"' in main_rehost
    assert 'resource "aws_ebs_volume" "rabbitmq_kali_disk_nvme0n1"' in main_rehost
    assert 'resource "aws_db_instance"' not in main_rehost
    assert 'resource "aws_mq_broker"' not in main_rehost


def test_collector_script_and_live_device_endpoint():
    script_res = client.get("/api/v1/discovery/collector-script")
    assert script_res.status_code == 200
    assert "collect_osquery_inventory" in script_res.text
    assert "launch_local_ui" in script_res.text

    import shutil
    if shutil.which("osqueryi"):
        live_res = client.post("/api/v1/discovery/collect-device?persist_json=false")
        assert live_res.status_code == 200
        live_data = live_res.json()
        assert live_data["cmir_validation"]["valid"] is True
        assert live_data["hostname"]
        assert "terraform" in live_data



