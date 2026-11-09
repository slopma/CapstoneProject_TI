"""
Automated Cloud Deployment Runner & Interactive Terraform Console Engine for CloudMove.

Executes autonomous infrastructure provisioning, secret injection,
container bootstrapping, real-time log streaming, process cancellation,
state inspection, and post-cutover verification directly from CloudMove.
Supports both AWS and GCP targets.
"""

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class CloudDeploymentRunner:
    """
    Orchestrates the end-to-end and interactive execution of a planned migration job
    directly from CloudMove, handling:
    1. Cloud provider authentication & caller verification (AWS STS / GCP).
    2. Real-time streaming Terraform execution (`init`, `validate`, `plan`, `apply`, `continue`, `refresh`, `destroy`, `output`, `state`, `unlock`).
    3. Active process tracking and immediate operator cancellation (`SIGTERM` / `SIGKILL` + lock cleanup).
    4. Live `terraform.tfstate` resource and output inspection (EC2 Public IP, VPC, Subnets, Security Groups, Endpoints).
    5. Persistent execution logs per migration job on disk (`terraform_execution.log` & `terraform_status.json`).
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path(__file__).resolve().parent.parent.parent.parent
        self._lock = threading.Lock()
        self._active_processes: Dict[str, subprocess.Popen] = {}
        self._active_commands: Dict[str, str] = {}
        self._cancelled_flags: Dict[str, bool] = {}
        self._job_logs: Dict[str, List[str]] = {}
        self._job_status: Dict[str, Dict[str, Any]] = {}
        self._last_credentials: Optional[Dict[str, str]] = None

    def resolve_job_dir(self, migration_id: str, job: Optional[Dict[str, Any]] = None) -> Path:
        """
        Locate or create the persistent Terraform working directory for a migration job.
        Prioritizes existing directories with a `terraform.tfstate` file.
        """
        candidates = [
            Path("generated/deployments") / migration_id,
            self.workspace_root / "generated" / "deployments" / migration_id,
        ]
        if job:
            use_case = job.get("use_case", "app_source")
            provider = job.get("target_provider", "aws")
            candidates.insert(0, Path.cwd() / f"cloudmove-{use_case}-{provider}-{migration_id}")
            candidates.insert(1, self.workspace_root / f"cloudmove-{use_case}-{provider}-{migration_id}")

        for cand in candidates:
            if (cand / "terraform.tfstate").exists():
                return cand
        for cand in candidates:
            if cand.exists() and (cand / "main.tf").exists():
                return cand

        default_dir = self.workspace_root / "generated" / "deployments" / migration_id
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def _build_env(self, credentials: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = os.environ.copy()
        effective_creds = credentials
        if effective_creds and effective_creds.get("aws_access_key_id") and effective_creds.get("aws_secret_access_key"):
            with self._lock:
                self._last_credentials = dict(effective_creds)
        elif not effective_creds:
            with self._lock:
                effective_creds = self._last_credentials
        if effective_creds:
            if effective_creds.get("aws_access_key_id"):
                env["AWS_ACCESS_KEY_ID"] = effective_creds["aws_access_key_id"].strip()
            if effective_creds.get("aws_secret_access_key"):
                env["AWS_SECRET_ACCESS_KEY"] = effective_creds["aws_secret_access_key"].strip()
            if effective_creds.get("aws_session_token"):
                env["AWS_SESSION_TOKEN"] = effective_creds["aws_session_token"].strip()
            if effective_creds.get("aws_region"):
                env["AWS_DEFAULT_REGION"] = effective_creds["aws_region"].strip()
            for k, v in effective_creds.items():
                if v and k.upper() not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION"):
                    env[k.upper()] = str(v).strip()
        return env

    def _append_log(self, migration_id: str, job_dir: Path, line: str) -> None:
        clean_line = line.rstrip("\r\n")
        with self._lock:
            if migration_id not in self._job_logs:
                self._job_logs[migration_id] = self._load_persisted_logs(job_dir)
            self._job_logs[migration_id].append(clean_line)
            if len(self._job_logs[migration_id]) > 3000:
                self._job_logs[migration_id] = self._job_logs[migration_id][-3000:]
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            log_file = job_dir / "terraform_execution.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(clean_line + "\n")
        except Exception:
            pass

    def _load_persisted_logs(self, job_dir: Path) -> List[str]:
        log_file = job_dir / "terraform_execution.log"
        if log_file.is_file():
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                return lines[-2000:]
            except Exception:
                return []
        return []

    def _save_status_meta(self, migration_id: str, job_dir: Path, meta: Dict[str, Any]) -> None:
        with self._lock:
            self._job_status[migration_id] = meta
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            status_file = job_dir / "terraform_status.json"
            status_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_status_meta(self, migration_id: str, job_dir: Path) -> Dict[str, Any]:
        with self._lock:
            if migration_id in self._job_status:
                return dict(self._job_status[migration_id])
        status_file = job_dir / "terraform_status.json"
        if status_file.is_file():
            try:
                return json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        # If terraform.tfstate exists with resources, infer initial status
        state_info = self.inspect_tfstate(job_dir)
        if state_info["resource_count"] > 0:
            return {
                "status": "SUCCESS",
                "stage": "DEPLOYMENT_COMPLETED",
                "active_command": None,
                "is_running": False,
                "message": f"Infraestructura activa en la nube ({state_info['resource_count']} recursos en terraform.tfstate).",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        return {
            "status": "IDLE",
            "stage": "READY",
            "active_command": None,
            "is_running": False,
            "message": "Listo para ejecutar comandos de Terraform.",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def inspect_tfstate(self, job_dir: Path) -> Dict[str, Any]:
        """
        Parse `terraform.tfstate` directly to extract live provisioned resources,
        IDs, public IPs, DNS hostnames, and synthesized outputs even if `outputs.tf`
        had not yet exported them.
        """
        tfstate_path = job_dir / "terraform.tfstate"
        result: Dict[str, Any] = {
            "has_state_file": tfstate_path.is_file(),
            "serial": 0,
            "terraform_version": None,
            "resource_count": 0,
            "resources": [],
            "outputs": {},
            "primary_instance": None,
        }
        if not tfstate_path.is_file():
            return result

        try:
            raw = json.loads(tfstate_path.read_text(encoding="utf-8"))
            result["serial"] = raw.get("serial", 0)
            result["terraform_version"] = raw.get("terraform_version")

            # 1. Explicit outputs from tfstate
            raw_outputs = raw.get("outputs") or {}
            for k, v in raw_outputs.items():
                if isinstance(v, dict):
                    result["outputs"][k] = {
                        "value": v.get("value"),
                        "type": v.get("type", "string"),
                    }

            # 2. Extract resources from tfstate
            resources_list: List[Dict[str, Any]] = []
            for r in raw.get("resources") or []:
                mode = r.get("mode", "managed")
                r_type = r.get("type", "")
                r_name = r.get("name", "")
                address = f"{'data.' if mode == 'data' else ''}{r_type}.{r_name}"
                for idx, inst in enumerate(r.get("instances") or []):
                    attrs = inst.get("attributes") or {}
                    res_id = attrs.get("id") or attrs.get("arn") or ""
                    item = {
                        "address": address if idx == 0 else f"{address}[{idx}]",
                        "mode": mode,
                        "type": r_type,
                        "name": r_name,
                        "id": res_id,
                        "arn": attrs.get("arn"),
                        "public_ip": attrs.get("public_ip"),
                        "private_ip": attrs.get("private_ip"),
                        "public_dns": attrs.get("public_dns"),
                        "instance_state": attrs.get("instance_state"),
                        "instance_type": attrs.get("instance_type"),
                        "cidr_block": attrs.get("cidr_block"),
                        "availability_zone": attrs.get("availability_zone"),
                        "dns_name": attrs.get("dns_name"),
                        "tags": attrs.get("tags") or {},
                    }
                    resources_list.append(item)

                    if mode == "managed" and r_type == "aws_instance":
                        result["primary_instance"] = item
                        pub_ip = attrs.get("public_ip")
                        pub_dns = attrs.get("public_dns")
                        if res_id and "instance_id" not in result["outputs"]:
                            result["outputs"]["instance_id"] = {"value": res_id, "type": "string"}
                        if pub_ip:
                            result["outputs"].setdefault("instance_public_ip", {"value": pub_ip, "type": "string"})
                            result["outputs"].setdefault("frontend_url", {"value": f"http://{pub_ip}:3000", "type": "string"})
                            result["outputs"].setdefault("backend_api_url", {"value": f"http://{pub_ip}:8000", "type": "string"})
                            result["outputs"].setdefault("app_endpoint", {"value": f"http://{pub_ip}:3000", "type": "string"})
                            result["outputs"].setdefault("ssh_command", {"value": f"ssh ubuntu@{pub_ip}", "type": "string"})
                        if pub_dns:
                            result["outputs"].setdefault("instance_public_dns", {"value": pub_dns, "type": "string"})
                    elif mode == "managed" and r_type == "google_compute_instance":
                        result["primary_instance"] = item
                        pub_ip = None
                        net_ifs = attrs.get("network_interface") or []
                        if isinstance(net_ifs, list) and len(net_ifs) > 0:
                            acc_configs = net_ifs[0].get("access_config") or []
                            if isinstance(acc_configs, list) and len(acc_configs) > 0:
                                pub_ip = acc_configs[0].get("nat_ip")
                        if res_id and "instance_id" not in result["outputs"]:
                            result["outputs"]["instance_id"] = {"value": res_id, "type": "string"}
                        if pub_ip:
                            item["public_ip"] = pub_ip
                            result["outputs"].setdefault("instance_public_ip", {"value": pub_ip, "type": "string"})
                            result["outputs"].setdefault("frontend_url", {"value": f"http://{pub_ip}:3000", "type": "string"})
                            result["outputs"].setdefault("backend_api_url", {"value": f"http://{pub_ip}:8000", "type": "string"})
                            result["outputs"].setdefault("app_endpoint", {"value": f"http://{pub_ip}:3000", "type": "string"})
                            result["outputs"].setdefault("ssh_command", {"value": f"ssh cloudmove@{pub_ip}", "type": "string"})
                    elif mode == "managed" and r_type == "aws_vpc" and res_id:
                        result["outputs"].setdefault("vpc_id", {"value": res_id, "type": "string"})
                    elif mode == "managed" and r_type == "aws_security_group" and res_id:
                        result["outputs"].setdefault("security_group_id", {"value": res_id, "type": "string"})

            managed_resources = [x for x in resources_list if x["mode"] == "managed"]
            result["resources"] = resources_list
            result["managed_resources"] = managed_resources
            result["resource_count"] = len(managed_resources)
        except Exception as exc:
            result["parse_error"] = str(exc)

        return result

    def materialize_job_files(
        self,
        job_dir: Path,
        artifacts_files: Optional[Dict[str, Any]] = None,
        secrets: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        Write generated Terraform and runbook files into `job_dir` without clobbering
        existing `terraform.tfstate` or `.terraform` state.
        """
        job_dir.mkdir(parents=True, exist_ok=True)
        notes: List[str] = []
        if artifacts_files:
            for fname, content in artifacts_files.items():
                if fname in ("terraform.tfstate", "terraform.tfstate.backup", "terraform_execution.log", "terraform_status.json"):
                    continue
                target_file = job_dir / fname
                # Prevent stale browser state from overwriting fixed user_data.sh on disk
                if (
                    fname in ("user_data.sh", "docker-compose.cloudmove.yml", "main.tf")
                    and target_file.exists()
                    and isinstance(content, str)
                ):
                    existing_txt = target_file.read_text(encoding="utf-8", errors="ignore")
                    if "run_compose()" in existing_txt and "run_compose()" not in content:
                        continue
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, str):
                    target_file.write_text(content, encoding="utf-8")
                elif isinstance(content, bytes):
                    target_file.write_bytes(content)

        if secrets:
            env_file = job_dir / ".env"
            env_content = "\n".join([f"{k}={v}" for k, v in secrets.items() if v])
            env_file.write_text(env_content, encoding="utf-8")
            try:
                os.chmod(env_file, 0o600)
            except Exception:
                pass
            notes.append(f"[CloudMove] Archivo .env actualizado con {len(secrets)} variables (chmod 600).")

        return notes

    def _run_streaming_subprocess(
        self,
        migration_id: str,
        job_dir: Path,
        cmd: List[str],
        env: Dict[str, str],
        timeout_sec: int = 1500,
    ) -> Dict[str, Any]:
        """
        Run a single Terraform command via `subprocess.Popen`, streaming every line of
        stdout/stderr to the live log buffer and disk log file, while checking for
        operator cancellation.
        """
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(job_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
            )
        except Exception as exc:
            err_line = f"[ERROR] No se pudo iniciar el proceso {' '.join(cmd)}: {exc}"
            self._append_log(migration_id, job_dir, err_line)
            return {"returncode": -1, "cancelled": False, "error": str(exc)}

        with self._lock:
            self._active_processes[migration_id] = proc

        start_ts = time.time()
        collected_lines: List[str] = []
        cancelled = False

        try:
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, ""):
                if not raw_line:
                    break
                self._append_log(migration_id, job_dir, raw_line)
                collected_lines.append(raw_line.rstrip("\r\n"))

                with self._lock:
                    if self._cancelled_flags.get(migration_id):
                        cancelled = True
                        break

                if time.time() - start_ts > timeout_sec:
                    self._append_log(
                        migration_id,
                        job_dir,
                        f"[TIMEOUT] El comando superó el tiempo límite ({timeout_sec}s). Abortando proceso...",
                    )
                    self._terminate_process(proc)
                    return {
                        "returncode": 124,
                        "cancelled": False,
                        "error": f"Tiempo de espera agotado ({timeout_sec}s)",
                        "output": "\n".join(collected_lines[-200:]),
                    }

            proc.wait(timeout=10)
        except Exception as exc:
            self._append_log(migration_id, job_dir, f"[WARN] Interrupción leyendo stream del proceso: {exc}")
        finally:
            with self._lock:
                self._active_processes.pop(migration_id, None)
                if self._cancelled_flags.get(migration_id):
                    cancelled = True

        if cancelled:
            self._terminate_process(proc)
            return {
                "returncode": -15,
                "cancelled": True,
                "error": "Ejecución cancelada explícitamente por el operador.",
                "output": "\n".join(collected_lines[-200:]),
            }

        rc = proc.returncode if proc.returncode is not None else 0
        combined_tail = "\n".join(collected_lines[-40:])
        if rc != 0 and ("voc-cancel-cred" in combined_tail or "ExpiredToken" in combined_tail):
            self._append_log(
                migration_id,
                job_dir,
                "================================================================================",
            )
            self._append_log(
                migration_id,
                job_dir,
                "[DIAGNOSTICO AWS ACADEMY / VOCAREUM] Sesion de laboratorio expirada o detenida (policy/voc-cancel-cred).",
            )
            self._append_log(
                migration_id,
                job_dir,
                "Causa: AWS Academy adjunto la politica 'voc-cancel-cred' (Explicit Deny en EC2) a tus credenciales temporales ASIA...",
            )
            self._append_log(
                migration_id,
                job_dir,
                "Solucion: 1) En AWS Academy Learner Lab pulsa 'Start Lab' hasta que el indicador este en verde.",
            )
            self._append_log(
                migration_id,
                job_dir,
                "          2) Abre 'AWS Details' -> 'AWS CLI: Show' y copia el nuevo bloque de credenciales (Access Key, Secret Key y Session Token).",
            )
            self._append_log(
                migration_id,
                job_dir,
                "          3) Pegalas arriba en 'Autenticacion y Credenciales Cloud (AWS)' y pulsa 'Continuar / Aplicar (terraform apply)'.",
            )
            self._append_log(
                migration_id,
                job_dir,
                "================================================================================",
            )
        return {
            "returncode": rc,
            "cancelled": False,
            "error": "\n".join(collected_lines[-30:]) if rc != 0 else None,
            "output": "\n".join(collected_lines[-200:]),
        }

    def _terminate_process(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            for _ in range(15):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                proc.terminate()
                proc.kill()
            except Exception:
                pass

    def cancel_terraform_execution(self, migration_id: str, job_dir: Path) -> Dict[str, Any]:
        """
        Immediately cancel an active Terraform command for `migration_id` and clean up
        any stale `.terraform.tfstate.lock.info` lock file if necessary.
        """
        with self._lock:
            self._cancelled_flags[migration_id] = True
            proc = self._active_processes.get(migration_id)
            active_cmd = self._active_commands.get(migration_id)

        ts = time.strftime("%X")
        if proc and proc.poll() is None:
            self._append_log(
                migration_id,
                job_dir,
                f"[{ts}] [CANCELAR] Señal de interrupción (SIGTERM) enviada al proceso Terraform activo ('{active_cmd}')...",
            )
            self._terminate_process(proc)
            self._append_log(
                migration_id,
                job_dir,
                f"[{ts}] [CANCELADO] El comando Terraform ('{active_cmd}') fue detenido por el operador.",
            )
        else:
            self._append_log(
                migration_id,
                job_dir,
                f"[{ts}] [INFO] Solicitud de cancelación recibida (no había subproceso activo en este instante).",
            )

        # Clean up local state lock file if left behind by interrupted process
        lock_file = job_dir / ".terraform.tfstate.lock.info"
        if lock_file.exists():
            try:
                lock_file.unlink()
                self._append_log(
                    migration_id,
                    job_dir,
                    f"[{ts}] [UNLOCK] Archivo de bloqueo '.terraform.tfstate.lock.info' liberado automáticamente.",
                )
            except Exception:
                pass

        with self._lock:
            self._active_processes.pop(migration_id, None)
            self._active_commands.pop(migration_id, None)

        meta = {
            "status": "CANCELLED",
            "stage": "CANCELLED_BY_OPERATOR",
            "active_command": None,
            "is_running": False,
            "message": f"Ejecución de Terraform ('{active_cmd or 'proceso'}') cancelada por el operador.",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._save_status_meta(migration_id, job_dir, meta)
        return self.get_terraform_status(migration_id, job_dir)

    def clear_terraform_logs(self, migration_id: str, job_dir: Path) -> Dict[str, Any]:
        """Clear in-memory and persisted Terraform terminal logs for `migration_id`."""
        with self._lock:
            self._job_logs[migration_id] = []
        log_file = job_dir / "terraform_execution.log"
        if log_file.exists():
            try:
                log_file.unlink()
            except Exception:
                pass
        return self.get_terraform_status(migration_id, job_dir)

    def get_terraform_status(self, migration_id: str, job_dir: Path) -> Dict[str, Any]:
        """
        Return the complete operational status, live logs, `terraform.tfstate` resources,
        and extracted outputs for the interactive Terraform console.
        """
        with self._lock:
            proc = self._active_processes.get(migration_id)
            is_running = bool(proc and proc.poll() is None)
            active_cmd = self._active_commands.get(migration_id) if is_running else None
            if migration_id not in self._job_logs:
                self._job_logs[migration_id] = self._load_persisted_logs(job_dir)
            logs = list(self._job_logs.get(migration_id, []))

        meta = self._load_status_meta(migration_id, job_dir)
        if is_running:
            meta["is_running"] = True
            meta["status"] = "RUNNING"
            meta["active_command"] = active_cmd
        else:
            meta["is_running"] = False
            meta["active_command"] = None
            if meta.get("status") == "RUNNING":
                meta["status"] = "IDLE"

        state_info = self.inspect_tfstate(job_dir)
        lock_exists = (job_dir / ".terraform.tfstate.lock.info").exists()

        return {
            "migration_id": migration_id,
            "workspace_dir": str(job_dir),
            "is_running": meta["is_running"],
            "active_command": meta["active_command"],
            "status": meta.get("status", "IDLE"),
            "stage": meta.get("stage", "READY"),
            "message": meta.get("message", ""),
            "error": meta.get("error"),
            "updated_at": meta.get("updated_at"),
            "has_state_file": state_info["has_state_file"],
            "is_locked": lock_exists,
            "resource_count": state_info["resource_count"],
            "managed_resources": state_info.get("managed_resources", []),
            "primary_instance": state_info.get("primary_instance"),
            "outputs": state_info.get("outputs", {}),
            "logs": logs,
        }

    def execute_terraform_command(
        self,
        migration_id: str,
        job_dir: Path,
        action: str,
        provider: str = "aws",
        credentials: Optional[Dict[str, str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        artifacts_files: Optional[Dict[str, Any]] = None,
        async_exec: bool = True,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a specific Terraform action (`init`, `validate`, `plan`, `apply`, `continue`,
        `refresh`, `destroy`, `output`, `state`, `unlock`, `full_deploy`, `dry_run`) either
        asynchronously (streaming logs in background thread) or synchronously.
        """
        clean_action = action.lower().strip()
        with self._lock:
            proc = self._active_processes.get(migration_id)
            if proc and proc.poll() is None:
                active_cmd = self._active_commands.get(migration_id)
                return {
                    "success": False,
                    "already_running": True,
                    "error": f"Ya hay un comando Terraform en ejecución ('{active_cmd}'). Cancélalo o espera a que finalice.",
                    **self.get_terraform_status(migration_id, job_dir),
                }
            self._cancelled_flags[migration_id] = False
            self._active_commands[migration_id] = clean_action

        self.materialize_job_files(job_dir, artifacts_files=artifacts_files, secrets=secrets)

        terraform_bin = shutil.which("terraform")
        if not terraform_bin:
            with self._lock:
                self._active_commands.pop(migration_id, None)
            err_msg = "El ejecutor de Terraform ('terraform') no está instalado en el sistema."
            self._append_log(migration_id, job_dir, f"[ERROR] {err_msg}")
            return {
                "success": False,
                "error": err_msg,
                **self.get_terraform_status(migration_id, job_dir),
            }

        if not (job_dir / "main.tf").exists():
            with self._lock:
                self._active_commands.pop(migration_id, None)
            err_msg = f"El directorio {job_dir} no contiene main.tf."
            self._append_log(migration_id, job_dir, f"[ERROR] {err_msg}")
            return {
                "success": False,
                "error": err_msg,
                **self.get_terraform_status(migration_id, job_dir),
            }

        def _worker() -> Dict[str, Any]:
            env = self._build_env(credentials)
            ts = time.strftime("%X")
            self._append_log(
                migration_id,
                job_dir,
                f"\n================================================================================",
            )
            self._append_log(
                migration_id,
                job_dir,
                f"[{ts}] [CloudMove Terraform Runner] Ejecutando acción: '{clean_action.upper()}' en {job_dir.name}",
            )
            self._append_log(
                migration_id,
                job_dir,
                f"================================================================================",
            )

            self._save_status_meta(
                migration_id,
                job_dir,
                {
                    "status": "RUNNING",
                    "stage": f"TERRAFORM_{clean_action.upper()}",
                    "active_command": clean_action,
                    "is_running": True,
                    "message": f"Ejecutando 'terraform {clean_action}' en {provider.upper()}...",
                    "error": None,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )

            def _auto_import_orphaned_rds() -> None:
                try:
                    main_tf_path = job_dir / "main.tf"
                    if not main_tf_path.exists() or not (job_dir / ".terraform").exists():
                        return
                    main_tf_text = main_tf_path.read_text(encoding="utf-8", errors="ignore")
                    tfstate_text = ""
                    tfstate_path = job_dir / "terraform.tfstate"
                    if tfstate_path.exists():
                        tfstate_text = tfstate_path.read_text(encoding="utf-8", errors="ignore")
                    import re as _re
                    for match in _re.finditer(
                        r'resource\s+"aws_db_instance"\s+"([^"]+)"\s*\{([^}]*)\}',
                        main_tf_text,
                        _re.DOTALL,
                    ):
                        r_id = match.group(1)
                        body = match.group(2)
                        id_match = _re.search(r'identifier\s*=\s*"([^"]+)"', body)
                        if not id_match:
                            continue
                        db_ident = id_match.group(1)
                        if f'"name": "{r_id}"' in tfstate_text and '"type": "aws_db_instance"' in tfstate_text:
                            continue
                        imp_res = subprocess.run(
                            [terraform_bin, "import", "-no-color", "-input=false", f"aws_db_instance.{r_id}", db_ident],
                            cwd=str(job_dir),
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=45,
                        )
                        if imp_res.returncode == 0:
                            self._append_log(
                                migration_id,
                                job_dir,
                                f"[{time.strftime('%X')}] [AUTO-RECOVERY] Instancia RDS existente '{db_ident}' detectada en AWS e importada automáticamente a terraform.tfstate.",
                            )
                except Exception:
                    pass

            def _ensure_initialized() -> Optional[Dict[str, Any]]:
                if not (job_dir / ".terraform").exists():
                    self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] -> Directorio .terraform no inicializado; ejecutando 'terraform init' automáticamente...")
                    res = self._run_streaming_subprocess(
                        migration_id,
                        job_dir,
                        [terraform_bin, "init", "-no-color", "-input=false"],
                        env=env,
                        timeout_sec=180,
                    )
                    if res["returncode"] != 0:
                        return res
                _auto_import_orphaned_rds()
                return None

            steps_to_run: List[tuple[str, List[str], int]] = []
            if clean_action == "init":
                steps_to_run.append((" Inicializando proveedores y backend (terraform init)...", [terraform_bin, "init", "-no-color", "-input=false"], 180))
            elif clean_action == "validate":
                init_err = _ensure_initialized()
                if init_err:
                    return _finalize(False, "TERRAFORM_INIT", init_err)
                steps_to_run.append((" Validando sintaxis y consistencia HCL (terraform validate)...", [terraform_bin, "validate", "-no-color"], 60))
            elif clean_action == "plan":
                init_err = _ensure_initialized()
                if init_err:
                    return _finalize(False, "TERRAFORM_INIT", init_err)
                steps_to_run.append((" Generando plan de ejecución especulativo (terraform plan)...", [terraform_bin, "plan", "-no-color", "-input=false"], 180))
            elif clean_action in ("apply", "continue"):
                init_err = _ensure_initialized()
                if init_err:
                    return _finalize(False, "TERRAFORM_INIT", init_err)
                label = (
                    f" Continuando / aplicando aprovisionamiento en {provider.upper()} (terraform apply -auto-approve)..."
                    if clean_action == "continue"
                    else f" Aprovisionando infraestructura en la nube real {provider.upper()} (terraform apply -auto-approve)..."
                )
                steps_to_run.append((label, [terraform_bin, "apply", "-auto-approve", "-no-color", "-input=false"], 1500))
            elif clean_action == "refresh":
                init_err = _ensure_initialized()
                if init_err:
                    return _finalize(False, "TERRAFORM_INIT", init_err)
                steps_to_run.append((" Sincronizando estado con la nube real (terraform apply -refresh-only)...", [terraform_bin, "apply", "-refresh-only", "-auto-approve", "-no-color", "-input=false"], 180))
            elif clean_action == "destroy":
                init_err = _ensure_initialized()
                if init_err:
                    return _finalize(False, "TERRAFORM_INIT", init_err)
                steps_to_run.append((f" Destruyendo recursos aprovisionados en {provider.upper()} (terraform destroy -auto-approve)...", [terraform_bin, "destroy", "-auto-approve", "-no-color", "-input=false"], 1500))
            elif clean_action == "output":
                steps_to_run.append((" Consultando salidas de infraestructura (terraform output)...", [terraform_bin, "output", "-no-color"], 30))
            elif clean_action == "state":
                steps_to_run.append((" Listando recursos registrados en terraform.tfstate (terraform state list)...", [terraform_bin, "state", "list"], 30))
            elif clean_action == "unlock":
                lock_file = job_dir / ".terraform.tfstate.lock.info"
                if lock_file.exists():
                    try:
                        lock_file.unlink()
                        self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] [OK] Archivo de bloqueo '.terraform.tfstate.lock.info' eliminado exitosamente.")
                    except Exception as exc:
                        return _finalize(False, "TERRAFORM_UNLOCK", {"returncode": 1, "cancelled": False, "error": str(exc)})
                else:
                    self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] [OK] No existe bloqueo activo en el estado de Terraform.")
                return _finalize(True, "TERRAFORM_UNLOCK", {"returncode": 0, "cancelled": False})
            elif clean_action == "dry_run":
                steps_to_run.extend([
                    ("[1/3] Inicializando Terraform...", [terraform_bin, "init", "-no-color", "-input=false"], 180),
                    ("[2/3] Validando sintaxis y consistencia de recursos...", [terraform_bin, "validate", "-no-color"], 60),
                    ("[3/3] Generando plan de ejecución especulativo (Dry-Run)...", [terraform_bin, "plan", "-no-color", "-input=false"], 180),
                ])
            else:
                # full_deploy
                steps_to_run.extend([
                    ("[1/4] Inicializando Terraform...", [terraform_bin, "init", "-no-color", "-input=false"], 180),
                    ("[2/4] Validando sintaxis y consistencia de recursos...", [terraform_bin, "validate", "-no-color"], 60),
                    ("[3/4] Generando plan de ejecución especulativo...", [terraform_bin, "plan", "-no-color", "-input=false"], 180),
                    (f"[4/4] Aprovisionando infraestructura en la nube real ({provider.upper()})...", [terraform_bin, "apply", "-auto-approve", "-no-color", "-input=false"], 1500),
                ])

            last_res: Dict[str, Any] = {"returncode": 0, "cancelled": False}
            for step_label, cmd, timeout_s in steps_to_run:
                if len(cmd) >= 2 and cmd[1] in ("plan", "apply", "destroy"):
                    _auto_import_orphaned_rds()
                self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] {step_label}")
                last_res = self._run_streaming_subprocess(migration_id, job_dir, cmd, env=env, timeout_sec=timeout_s)
                if last_res.get("cancelled"):
                    return _finalize(False, "CANCELLED", last_res)
                if last_res.get("returncode", 0) != 0:
                    return _finalize(False, f"FAILED_{clean_action.upper()}", last_res)

            # For state / output commands, also append a summary of live resources in terraform.tfstate
            st_summary = self.inspect_tfstate(job_dir)
            if st_summary["resource_count"] > 0 and clean_action in ("apply", "continue", "full_deploy", "output", "state", "refresh"):
                self._append_log(
                    migration_id,
                    job_dir,
                    f"\n[{time.strftime('%X')}] [Resumen de Estado Terraform] {st_summary['resource_count']} recurso(s) activos en {provider.upper()}:",
                )
                for mr in st_summary.get("managed_resources", []):
                    extra = f" | IP Pública: {mr['public_ip']}" if mr.get("public_ip") else ""
                    self._append_log(
                        migration_id,
                        job_dir,
                        f"  • {mr['address']} -> id={mr['id']}{extra}",
                    )

            return _finalize(True, f"COMPLETED_{clean_action.upper()}", last_res)

        def _finalize(success: bool, stage_name: str, res_dict: Dict[str, Any]) -> Dict[str, Any]:
            with self._lock:
                self._active_processes.pop(migration_id, None)
                self._active_commands.pop(migration_id, None)

            cancelled = bool(res_dict.get("cancelled"))
            status_str = "CANCELLED" if cancelled else ("SUCCESS" if success else "FAILED")
            st_info = self.inspect_tfstate(job_dir)

            if cancelled:
                msg = f"Comando '{clean_action}' cancelado por el operador."
            elif success:
                if clean_action == "destroy":
                    msg = "Infraestructura destruida exitosamente en la nube (0 recursos activos)."
                elif clean_action in ("apply", "continue", "full_deploy"):
                    msg = f"Infraestructura aprovisionada exitosamente ({st_info['resource_count']} recursos activos en la nube)."
                elif clean_action in ("plan", "dry_run"):
                    msg = "Planificación y validación de Terraform completadas sin errores."
                else:
                    msg = f"Comando 'terraform {clean_action}' completado exitosamente."
                self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] [OK] {msg}")
            else:
                msg = f"El comando 'terraform {clean_action}' finalizó con errores."
                self._append_log(migration_id, job_dir, f"[{time.strftime('%X')}] [ERROR] {msg}")

            meta = {
                "status": status_str,
                "stage": stage_name,
                "active_command": None,
                "is_running": False,
                "message": msg,
                "error": res_dict.get("error") if not success else None,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._save_status_meta(migration_id, job_dir, meta)

            full_status = self.get_terraform_status(migration_id, job_dir)
            full_status["success"] = success
            full_status["action"] = clean_action
            full_status["dry_run"] = clean_action in ("dry_run", "plan", "validate", "init")

            if on_complete:
                try:
                    on_complete(full_status)
                except Exception:
                    pass

            return full_status

        if async_exec:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            # Give the worker thread a brief moment to initialize status
            time.sleep(0.08)
            status_payload = self.get_terraform_status(migration_id, job_dir)
            status_payload["success"] = True
            status_payload["started"] = True
            status_payload["action"] = clean_action
            return status_payload
        else:
            return _worker()

    def verify_cloud_provider_credentials(
        self,
        provider: str = "aws",
        credentials: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Verify cloud credentials and caller identity without modifying resources.
        """
        clean_provider = provider.lower().strip()
        env = self._build_env(credentials)

        if clean_provider == "aws":
            has_creds = bool(
                (credentials and credentials.get("aws_access_key_id") and credentials.get("aws_secret_access_key"))
                or (env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"))
                or (Path.home() / ".aws" / "credentials").is_file()
            )
            if not has_creds:
                return {
                    "valid": False,
                    "provider": "aws",
                    "requires_input": True,
                    "error": "No se han proporcionado credenciales de AWS. Ingrese su AWS Access Key ID y AWS Secret Access Key para autenticar la identidad con AWS STS.",
                }

            aws_bin = shutil.which("aws")
            if not aws_bin:
                return {
                    "valid": False,
                    "provider": "aws",
                    "error": "AWS CLI no está instalado en el servidor de CloudMove.",
                }
            try:
                proc = subprocess.run(
                    [aws_bin, "sts", "get-caller-identity", "--output", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
                if proc.returncode == 0:
                    identity = json.loads(proc.stdout)
                    # Also verify that Vocareum / AWS Academy has not attached `policy/voc-cancel-cred`
                    ec2_check = subprocess.run(
                        [aws_bin, "ec2", "describe-regions", "--region-names", "us-east-1", "--output", "json"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=env,
                    )
                    if ec2_check.returncode != 0 and "voc-cancel-cred" in (ec2_check.stderr or ""):
                        return {
                            "valid": False,
                            "provider": "aws",
                            "account": identity.get("Account"),
                            "arn": identity.get("Arn"),
                            "error": (
                                f"Credenciales revocadas por AWS Academy / Vocareum (policy/voc-cancel-cred) para {identity.get('Arn')}. "
                                "El laboratorio se detuvo o expiró: ve a AWS Academy Learner Lab, haz clic en 'Start Lab' y copia las nuevas credenciales (Access Key, Secret Key y Session Token)."
                            ),
                        }
                    return {
                        "valid": True,
                        "provider": "aws",
                        "account": identity.get("Account"),
                        "arn": identity.get("Arn"),
                        "user_id": identity.get("UserId"),
                        "message": f"Identidad AWS y permisos EC2 activos confirmados para {identity.get('Arn')}.",
                    }
                else:
                    err = proc.stderr.strip() or "Credenciales no configuradas o inválidas."
                    return {
                        "valid": False,
                        "provider": "aws",
                        "error": f"Fallo al autenticar con AWS STS: {err}",
                    }
            except Exception as exc:
                return {
                    "valid": False,
                    "provider": "aws",
                    "error": f"Error ejecutando verificación AWS: {str(exc)}",
                }

        return {
            "valid": False,
            "provider": clean_provider,
            "error": f"Proveedor '{provider}' requiere configuración de Service Account / ADC.",
        }

    def execute_job_deployment(
        self,
        job_dir: Path,
        provider: str = "aws",
        dry_run: bool = False,
        credentials: Optional[Dict[str, str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        artifacts_files: Optional[Dict[str, Any]] = None,
        migration_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute Terraform initialization, validation, and optional apply synchronously
        while streaming logs to the job's persistent log file.
        """
        mig_id = migration_id or job_dir.name
        action = "dry_run" if dry_run else "full_deploy"
        return self.execute_terraform_command(
            migration_id=mig_id,
            job_dir=job_dir,
            action=action,
            provider=provider,
            credentials=credentials,
            secrets=secrets,
            artifacts_files=artifacts_files,
            async_exec=False,
        )

    def execute_rollback(
        self,
        job_dir: Path,
        credentials: Optional[Dict[str, str]] = None,
        migration_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute automated rollback by running terraform destroy.
        """
        mig_id = migration_id or job_dir.name
        res = self.execute_terraform_command(
            migration_id=mig_id,
            job_dir=job_dir,
            action="destroy",
            credentials=credentials,
            async_exec=False,
        )
        return {
            "success": res.get("success", False),
            "error": res.get("error"),
            "stdout": "\n".join(res.get("logs", [])[-50:]),
            **res,
        }


cloud_deployer = CloudDeploymentRunner()
