"""Integration tests for Case 2 user-selected folder/file staging and EC2 validation."""

from __future__ import annotations

import base64
import gzip
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile
import threading

from fastapi.testclient import TestClient

from app.main import app
from app.migration.image_migrator import (
    build_vm_image_cmir,
    evaluate_vm_image_compatibility,
    generate_vm_image_migration_artifacts,
    inspect_vm_image,
)
from app.migration import uc2_staging


client = TestClient(app)


def test_browser_stage_upload_commit_and_token_download(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(uc2_staging, "get_staging_base_dir", lambda: tmp_path / "uc2_staged")

    init_resp = client.post(
        "/api/v1/migration/uc2-stage/init",
        json={"selected_paths": ["/home/lacastrilp/Descargas"]},
    )
    assert init_resp.status_code == 200, init_resp.text
    stage_id = init_resp.json()["stage_id"]

    pdf_bytes = b"%PDF-1.4\x00\x01binary-content"
    txt_bytes = b"Proyecto Final Redes\n"

    up_resp = client.post(
        f"/api/v1/migration/uc2-stage/{stage_id}/upload-files",
        json={
            "selected_paths": ["/home/lacastrilp/Descargas"],
            "files": [
                {
                    "rel_path": "home/lacastrilp/Descargas/docs/syllabus.pdf",
                    "content_b64": base64.b64encode(pdf_bytes).decode("ascii"),
                },
                {
                    "rel_path": "home/lacastrilp/Descargas/notas.txt",
                    "content_b64": base64.b64encode(txt_bytes).decode("ascii"),
                },
            ],
        },
    )
    assert up_resp.status_code == 200, up_resp.text

    commit_resp = client.post(
        f"/api/v1/migration/uc2-stage/{stage_id}/commit",
        json={"selected_paths": ["/home/lacastrilp/Descargas"]},
    )
    assert commit_resp.status_code == 200, commit_resp.text
    cdata = commit_resp.json()
    assert cdata["status"] == "READY"
    assert cdata["files_count"] == 2

    st_resp = client.get(
        "/api/v1/migration/uc2-stage/status",
        params={"stage_id": stage_id},
    )
    assert st_resp.status_code == 200
    assert st_resp.json()["ready"] is True

    # Download requires matching secret token
    meta_secret = uc2_staging.get_stage_metadata(stage_id, include_secrets=True)
    assert client.get(
        f"/api/v1/migration/uc2-stage/{stage_id}/bundle.tar.gz?token=wrong-token"
    ).status_code == 403

    dl_resp = client.get(
        f"/api/v1/migration/uc2-stage/{stage_id}/bundle.tar.gz?token={meta_secret['download_token']}"
    )
    assert dl_resp.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(dl_resp.content), mode="r:gz") as tf:
        names = set(tf.getnames())
        assert "home/lacastrilp/Descargas/docs/syllabus.pdf" in names
        assert "home/lacastrilp/Descargas/notas.txt" in names
        assert tf.extractfile("home/lacastrilp/Descargas/docs/syllabus.pdf").read() == pdf_bytes


def test_agent_v22_stage_selected_paths_and_install_upgrade(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(uc2_staging, "get_staging_base_dir", lambda: tmp_path / "uc2_staged")

    inst_sh = client.get("/api/v1/agents/install.sh").text
    assert "--upgrade" in inst_sh
    assert "2.2.0" in inst_sh

    # Enroll an agent and test chunked stage upload from CloudMoveAgentDaemon
    tok = client.post("/api/v1/agents/enrollment-tokens", json={"ttl_seconds": 300, "max_uses": 1}).json()["token"]
    enr = client.post(
        "/api/v1/agents/enroll",
        json={"enrollment_token": tok, "hostname": "test-kali-node", "version": "2.2.0"},
    ).json()
    agent_id = enr["agent_id"]
    api_key = enr["agent_api_key"]

    src_dir = tmp_path / "Descargas"
    (src_dir / "sub").mkdir(parents=True)
    (src_dir / "sub" / "informe.txt").write_text("hola aws", encoding="utf-8")
    (src_dir / ".env").write_text("SECRET=123", encoding="utf-8")
    (src_dir / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")

    from cloudmove_agent.agent_daemon import CloudMoveAgentDaemon

    daemon = CloudMoveAgentDaemon(server_url="http://testserver", agent_id=agent_id, api_key=api_key)

    def _client_http(method, path, payload=None, timeout=15, raw_bytes=None, content_type="application/json"):
        headers = daemon._build_auth_headers(content_type=content_type)
        if raw_bytes is not None:
            resp = client.request(method, path, content=raw_bytes, headers=headers)
        elif payload is not None:
            resp = client.request(method, path, json=payload, headers=headers)
        else:
            resp = client.request(method, path, headers=headers)
        assert resp.status_code < 300, resp.text
        return resp.json() if resp.content else {}

    daemon._http_request = _client_http

    stage_id = "uc2stg-agenttest01"
    res = daemon._task_stage_selected_paths({
        "stage_id": stage_id,
        "selected_paths": [str(src_dir)],
    })
    assert res["status"] == "success"
    assert res["included_files_count"] == 1
    assert res["skipped_files_count"] >= 2  # .env & id_rsa excluded

    meta = uc2_staging.get_stage_metadata(stage_id, include_secrets=True)
    assert meta["status"] == "READY"
    rel_paths = [f["path"] for f in meta["files"]]
    assert any(p.endswith("Descargas/sub/informe.txt") for p in rel_paths)
    assert not any(p.endswith(".env") or p.endswith("id_rsa") for p in rel_paths)


def test_uc2_user_data_size_and_telemetry_directory_binary_handlers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(uc2_staging, "get_staging_base_dir", lambda: tmp_path / "uc2_staged")
    manifest = inspect_vm_image(
        manifest_override={"selected_user_paths": ["/home/lacastrilp/Descargas"]},
        target_provider="aws",
    )
    compat = evaluate_vm_image_compatibility(manifest, target_provider="aws")
    cmir = build_vm_image_cmir(manifest, target_provider="aws")
    arts = generate_vm_image_migration_artifacts(
        manifest,
        compat,
        cmir,
        target_provider="aws",
        stage_meta={
            "stage_id": "uc2stg-verify01",
            "status": "READY",
            "download_token": "tok_secret_123",
            "sync_token": "sync_secret_456",
            "files_count": 5,
        },
        public_api_url="https://digitalcafeluna.store",
    )

    ud = arts["files"]["user_data.sh"]
    gz_b64 = base64.b64encode(gzip.compress(ud.encode("utf-8")))
    assert len(gz_b64) <= 16384
    assert "sync_ebs.sh" in ud
    assert "sync_stage.sh" in ud
    assert "uc2stg-verify01" in ud

    # Extract embedded telemetry_server.py and verify /files/view on directory & binary PDF
    m = re.search(
        r"cat << 'EOF_SERVER' > /opt/cloudmove/os_capture/telemetry_server\.py\n(.*?)\nEOF_SERVER",
        ud,
        re.DOTALL,
    )
    assert m
    srv_file = tmp_path / "telemetry_server.py"
    srv_file.write_text(m.group(1), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("uc2_telemetry_srv", str(srv_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rd = tmp_path / "rootfs"
    ed = tmp_path / "ebs"
    (rd / "home" / "lacastrilp" / "Descargas" / "docs").mkdir(parents=True)
    (ed / "rootfs").mkdir(parents=True)
    pdf_bytes = b"%PDF-1.4\x00\xff\xfeSAMPLE"
    (rd / "home" / "lacastrilp" / "Descargas" / "docs" / "guia.pdf").write_bytes(pdf_bytes)
    (rd / "home" / "lacastrilp" / "Descargas" / "leeme.txt").write_text("archivo texto", encoding="utf-8")
    tok_file = tmp_path / "sync_token"
    tok_file.write_text("sync_secret_456", encoding="utf-8")

    mod.RD = str(rd)
    mod.ED = str(ed)
    mod.TK = str(tok_file)

    import http.server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), mod.H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/files/view?path=home/lacastrilp/Descargas")
        r_dir = conn.getresponse()
        body_dir = r_dir.read().decode("utf-8")
        assert r_dir.status == 200
        assert "leeme.txt" in body_dir
        assert "docs" in body_dir

        conn.request("GET", "/files/view?path=home/lacastrilp/Descargas/docs/guia.pdf")
        r_bin = conn.getresponse()
        body_bin = r_bin.read().decode("utf-8")
        assert r_bin.status == 200
        assert "Archivo binario migrado" in body_bin
        assert hashlib.sha256(pdf_bytes).hexdigest()[:16] in body_bin

        conn.request("GET", "/files/download?path=home/lacastrilp/Descargas/docs/guia.pdf")
        r_dl = conn.getresponse()
        raw_dl = r_dl.read()
        assert r_dl.status == 200
        assert raw_dl == pdf_bytes

        conn.request("POST", "/sync-stage", body=b'{"bundle_url":"https://digitalcafeluna.store/x"}', headers={"X-CloudMove-Sync-Token": "wrong"})
        assert conn.getresponse().status == 403
    finally:
        srv.shutdown()
        srv.server_close()
