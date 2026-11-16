"""
Cloud-Init Autonomous Rehydration & Live Telemetry Portal Generator for UC2.

Generates `user_data.sh`, the embedded multithreaded Python telemetry & file-explorer
service (`telemetry_server.py`), safe chunk extraction (`apply_tar.sh` / `sync_stage.sh`),
and guarantees payload fits within AWS EC2's 16,384-byte UserData limit.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from app.core.text_utils import utc_now_iso as _utc_now


def build_uc2_rehydration_user_data(
    manifest: Dict[str, Any],
    slug: str,
    provider_clean: str = "aws",
    diff_report: Optional[Dict[str, Any]] = None,
    stage_meta: Optional[Dict[str, Any]] = None,
    public_api_url: Optional[str] = None,
) -> str:
    """Build `user_data.sh` embedding captured OS configs and the live telemetry portal."""
    diff_report = diff_report or {}
    # 4. Autonomous cloud-init user_data.sh for Case 2 (OS state reconstruction + real OS files bundle + live telemetry portal)
    # Compressed via base64gzip in main.tf so the full OS files bundle fits well inside AWS EC2's 16 KB UserData limit.
    import base64
    import gzip
    bundled_files_meta: List[Dict[str, Any]] = []
    bundled_files_contents: Dict[str, str] = {}
    selected_paths = [
        str(p).strip() for p in (manifest.get("selected_user_paths") or []) if str(p).strip()
    ][:50]

    # Resolve persisted remote file stage bundle URL & tokens when selected_user_paths exist
    resolved_stage = stage_meta
    if resolved_stage is None and selected_paths:
        try:
            from app.migration.uc2_staging import find_ready_stage

            resolved_stage = find_ready_stage(
                stage_id=manifest.get("stage_id"),
                migration_id=manifest.get("migration_id"),
                agent_id=(manifest.get("live_capture_details") or {}).get("captured_via", "").replace("agent:", "") or None,
                selected_paths=selected_paths,
                include_secrets=True,
            )
        except Exception:
            resolved_stage = None

    stage_bundle_url = ""
    stage_sync_token = (
        str(manifest.get("uc2_sync_token") or "").strip()
        or str((resolved_stage or {}).get("sync_token") or "").strip()
        or hashlib.sha256(f"{slug}:{manifest.get('sha256', '')}".encode("utf-8")).hexdigest()[:24]
    )
    if resolved_stage and resolved_stage.get("status") == "READY" and resolved_stage.get("download_token"):
        api_base = str(public_api_url or os.getenv("CLOUDMOVE_API_URL") or "").strip().rstrip("/")
        if api_base:
            from app.migration.uc2_staging import build_stage_download_url

            stage_bundle_url = build_stage_download_url(api_base, resolved_stage)

    sensitive_tokens = (".env", "id_rsa", "id_ed25519", ".pem", ".key", "secret", "password", ".aws/credentials")
    try:
        seen_arcnames = set()
        if True:
            def _add_virtual_file(arcname: str, text_content: str) -> None:
                clean_arc = arcname.lstrip("/")
                if not clean_arc or clean_arc in seen_arcnames:
                    return
                seen_arcnames.add(clean_arc)
                raw_bytes = text_content.encode("utf-8", errors="replace")
                bundled_files_contents[clean_arc] = text_content
                bundled_files_meta.append({
                    "path": clean_arc,
                    "size_bytes": len(raw_bytes),
                    "sha256": hashlib.sha256(raw_bytes).hexdigest()[:16],
                })

            # 4a. Real /etc configuration files from the source OS
            etc_candidates = [
                "/etc/os-release",
                "/etc/hostname",
                "/etc/fstab",
                "/etc/hosts",
                "/etc/passwd",
                "/etc/group",
                "/etc/shells",
                "/etc/issue",
                "/etc/debian_version",
                "/etc/crontab",
                "/etc/nsswitch.conf",
                "/etc/resolv.conf",
                "/etc/sysctl.conf",
            ]
            for etc_p in etc_candidates:
                p_obj = Path(etc_p)
                if p_obj.is_file():
                    try:
                        txt = p_obj.read_text(encoding="utf-8", errors="replace")[:3500]
                        _add_virtual_file(etc_p.lstrip("/"), txt)
                    except Exception:
                        pass

            # 4b. Real user home directory & project workspace inventory from the source OS
            home_lines = [
                f"=== INVENTARIO REAL DE ARCHIVOS DEL USUARIO EN SO ORIGEN ({manifest.get('name', 'host')}) ===",
                f"Fecha de captura: {_utc_now()}",
                "",
            ]
            home_root = Path("/home")
            if home_root.is_dir():
                for user_dir in sorted(home_root.iterdir())[:4]:
                    if user_dir.is_dir():
                        home_lines.append(f"[Directorio Usuario: {user_dir}]")
                        try:
                            for entry in sorted(user_dir.iterdir())[:30]:
                                if entry.name.startswith("."):
                                    continue
                                kind = "DIR " if entry.is_dir() else "FILE"
                                sz = entry.stat().st_size if entry.is_file() else 0
                                home_lines.append(f"  {kind}  {sz:>10} bytes  {entry.name}")
                        except Exception:
                            pass
                        home_lines.append("")

            cwd_root = Path.cwd()
            home_lines.append(f"[Workspace Activo en SO Origen: {cwd_root}]")
            try:
                for entry in sorted(cwd_root.iterdir())[:30]:
                    if entry.name.startswith("."):
                        continue
                    kind = "DIR " if entry.is_dir() else "FILE"
                    sz = entry.stat().st_size if entry.is_file() else 0
                    home_lines.append(f"  {kind}  {sz:>10} bytes  {entry.name}")
            except Exception:
                pass
            _add_virtual_file("var/log/cloudmove_origin_workspace.txt", "\n".join(home_lines))

            # 4b2. Explicit traceability map for user-selected files/folders + safe content inclusion
            if selected_paths:
                sel_map = []
                extra_captured = 0
                for sp in selected_paths:
                    rel_sp = sp.lstrip("/")
                    sel_map.append({
                        "origin_path": sp,
                        "rootfs_path": f"/opt/cloudmove/os_capture/rootfs/{rel_sp}",
                        "ebs_path": f"/mnt/cloudmove_ebs/rootfs/{rel_sp}",
                    })
                    lower_sp = sp.lower()
                    if (
                        extra_captured < 6
                        and not any(tok in lower_sp for tok in sensitive_tokens)
                    ):
                        p_sel = Path(sp)
                        if p_sel.is_file():
                            try:
                                if p_sel.stat().st_size <= 2500:
                                    _add_virtual_file(rel_sp, p_sel.read_text(encoding="utf-8", errors="replace"))
                                    extra_captured += 1
                            except Exception:
                                pass
                        elif p_sel.is_dir():
                            try:
                                for child in sorted(p_sel.rglob("*"))[:12]:
                                    if extra_captured >= 6:
                                        break
                                    if child.is_file() and not child.is_symlink() and child.stat().st_size <= 2000:
                                        c_low = str(child).lower()
                                        if not any(tok in c_low for tok in sensitive_tokens):
                                            _add_virtual_file(str(child).lstrip("/"), child.read_text(encoding="utf-8", errors="replace"))
                                            extra_captured += 1
                            except Exception:
                                pass
                _add_virtual_file(
                    "var/log/cloudmove_selected_paths_map.json",
                    json.dumps(sel_map, indent=2, ensure_ascii=False),
                )

            # 4c. Real README.md from the active workspace on the host OS (when available)
            readme_p = cwd_root / "README.md"
            if readme_p.is_file():
                try:
                    _add_virtual_file(
                        "var/log/cloudmove_workspace_readme.md",
                        readme_p.read_text(encoding="utf-8", errors="replace")[:700],
                    )
                except Exception:
                    pass

            # 4d. Real disk/partition snapshot (lsblk + df -hT) from source OS
            try:
                lsblk_src = subprocess.run(
                    ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT"],
                    capture_output=True, text=True, timeout=4,
                ).stdout
                df_src = subprocess.run(
                    ["df", "-hT"], capture_output=True, text=True, timeout=4,
                ).stdout
                _add_virtual_file(
                    "var/log/cloudmove_source_lsblk_df.txt",
                    f"=== lsblk ===\n{lsblk_src[:900]}\n=== df -hT ===\n{df_src[:900]}",
                )
            except Exception:
                pass

            # 4e. Real processes & listening ports snapshot from source OS
            try:
                ps_src = subprocess.run(
                    ["ps", "-eo", "pid,user,pcpu,pmem,comm", "--sort=-pmem"],
                    capture_output=True, text=True, timeout=4,
                ).stdout
                _add_virtual_file(
                    "var/log/cloudmove_source_processes_ports.txt",
                    "\n".join(l[:90] for l in ps_src.splitlines()[:18]),
                )
            except Exception:
                pass

            # 4f. Real installed packages sample (dpkg-query) from source OS
            try:
                dpkg_src = subprocess.run(
                    ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\n"],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                if dpkg_src:
                    _add_virtual_file(
                        "var/log/cloudmove_source_dpkg_packages.txt",
                        "\n".join(dpkg_src.splitlines()[:15]),
                    )
            except Exception:
                pass

    except Exception:
        pass

    compact_os_state = {
        "image_id": manifest.get("image_id"),
        "name": manifest.get("name"),
        "sha256": (manifest.get("sha256") or "")[:16],
        "format": manifest.get("format"),
        "boot_mode": manifest.get("boot_mode"),
        "total_provisioned_gib": manifest.get("total_provisioned_gib"),
        "os": manifest.get("os", {}),
        "resources": manifest.get("resources", {}),
        "disks": [
            {"device": d.get("device"), "size_gib": d.get("size_gib"), "is_boot": d.get("is_boot")}
            for d in (manifest.get("disks") or [])[:4]
        ],
        "local_users": manifest.get("local_users", []),
        "systemd_services": [
            {"name": s.get("name"), "active_state": s.get("active_state"), "port": s.get("port")}
            for s in (manifest.get("systemd_services") or [])[:4]
        ],
        "running_processes": [
            {"pid": p.get("pid"), "user": p.get("user"), "name": p.get("name"), "cpu": p.get("cpu_percent"), "mem": p.get("mem_percent")}
            for p in (manifest.get("running_processes") or [])[:4]
        ],
        "listening_ports": manifest.get("listening_ports", [])[:8],
        "selected_user_paths": selected_paths,
        "staged_bundle_id": (resolved_stage or {}).get("stage_id"),
        "staged_files_count": (resolved_stage or {}).get("files_count", 0),
        "uploaded_os_files": [{"path": f["path"], "size_bytes": f["size_bytes"]} for f in bundled_files_meta],
        "installed_packages_count": (manifest.get("installed_packages_summary") or {}).get("total_count", 0),
        "target_provider": provider_clean,
        "parity_score_percent": diff_report.get("parity_score_percent", 100.0),
    }
    compact_os_json = json.dumps(compact_os_state, separators=(",", ":"), ensure_ascii=False)
    sysctl_lines = "\n".join(
        f"{k} = {v}" for k, v in (manifest.get("sysctl_parameters") or {}).items()
    ) or "# Baseline sysctl parameters preserved"
    users_csv = " ".join(
        u for u in (manifest.get("local_users") or []) if u not in ("root", "nobody", "ubuntu", "admin")
    )

    telemetry_server_py = r'''import hashlib,hmac,http.server,json,os,platform,pwd,re,shutil,socket,subprocess,threading,urllib.parse
MP="/opt/cloudmove/os_capture/image_manifest.json";RD="/opt/cloudmove/os_capture/rootfs";ED="/mnt/cloudmove_ebs";BP="/opt/cloudmove/os_capture/os_real_files_bundle.tar.gz";TK="/opt/cloudmove/os_capture/sync_token";CD="/tmp/cm_up"
_r=lambda c:subprocess.run(c,capture_output=True,text=True).stdout
def _sha(fp):
    h=hashlib.sha256()
    with open(fp,"rb") as f:
        while ch:=f.read(65536): h.update(ch)
    return h.hexdigest()[:16]
def uf():
    seen={};er=ED+"/rootfs"
    for b in (er,RD):
        for rt,_,fs in (os.walk(b) if os.path.isdir(b) else []):
            for fn in sorted(fs):
                if len(seen)>=2500: break
                fp=os.path.join(rt,fn);rp=os.path.relpath(fp,b)
                if rp in seen: continue
                try:
                    rf=os.path.join(RD,rp);et=os.path.join(er,rp);ec=os.path.exists(et);st=os.stat(fp)
                    seen[rp]={"path":rp,"origin_path":"/"+rp,"disk_path":fp,"rootfs_path":rf,"ebs_path":et if ec else None,"ebs_expected_path":et,"ebs_mirrored":ec,"is_dir":False,"category":"config" if rp.startswith("etc/") else ("user" if rp.startswith(("home/","opt/","srv/","app/")) else "logs"),"size_bytes":st.st_size,"sha256":_sha(fp) if st.st_size<2097152 else f"sz-{st.st_size}","view_url":"/files/view?path="+urllib.parse.quote(rp)}
                except Exception: pass
    return sorted(seen.values(),key=lambda x:x["path"])
def _resolve(rel):
    for b in (ED+"/rootfs",RD):
        br=os.path.realpath(b);sf=os.path.realpath(os.path.join(b,rel))
        if (sf==br or sf.startswith(br+"/")) and os.path.exists(sf): return sf
    return None
def tel():
    try:
        with open(MP,encoding="utf-8") as f: m=json.load(f)
    except Exception: m={}
    if not os.path.ismount(ED) and os.path.isfile("/opt/cloudmove/os_capture/sync_ebs.sh"):
        subprocess.run(["bash","/opt/cloudmove/os_capture/sync_ebs.sh","1"],capture_output=True)
    lr=_r(["lsblk","-o","NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID"]);lrows=[]
    try:
        def w(ns,d=0):
            for n in ns or []: lrows.append({"name":n.get("name",""),"depth":d,"size":n.get("size",""),"type":n.get("type",""),"fstype":n.get("fstype") or "-","mountpoint":n.get("mountpoint") or "-","uuid":n.get("uuid") or "-"});w(n.get("children"),d+1)
        w(json.loads(_r(["lsblk","-J","-o","NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID"]) or "{}").get("blockdevices"))
    except Exception: pass
    dr=_r(["df","-hT"]);pr=_r(["ps","-eo","pid,user,pcpu,pmem,comm","--sort=-pcpu"]);fs=uf();su=set(m.get("local_users") or []);u=[]
    try: u=sorted([{"username":e.pw_name,"uid":e.pw_uid,"gid":e.pw_gid,"home":e.pw_dir,"shell":e.pw_shell,"is_source_user":e.pw_name in su,"home_exists":os.path.isdir(e.pw_dir)} for e in pwd.getpwall() if e.pw_uid==0 or e.pw_uid>=1000 or e.pw_name in su],key=lambda x:(not x["is_source_user"],x["uid"]))
    except Exception: pass
    em=os.path.ismount(ED)
    return {"status":"ONLINE","use_case":"vm_image","cloud_hostname":socket.gethostname(),"cloud_kernel":platform.release(),"cloud_arch":platform.machine(),"cloud_uptime":_r(["uptime","-p"]).strip(),"rootfs_dir":RD,"ebs_mount_dir":ED+"/rootfs","ebs_mounted":em,"ebs_mirrored_count":sum(1 for f in fs if f["ebs_mirrored"]),"uploaded_files_count":len(fs),"total_bytes":sum(f["size_bytes"] for f in fs),"uploaded_files":fs,"selected_user_paths":m.get("selected_user_paths",[]),"lsblk_live":lr,"lsblk_rows":lrows,"df_live":dr,"df_rows":[{"filesystem":p[0],"fstype":p[1],"size":p[2],"used":p[3],"avail":p[4],"use_pct":p[5],"mountpoint":" ".join(p[6:])} for l in dr.splitlines()[1:] if len(p:=l.split())>=7],"ps_live":"\n".join(pr.splitlines()[:25]),"ps_rows":[{"pid":p[0],"user":p[1],"cpu":p[2],"mem":p[3],"command":p[4]} for l in pr.splitlines()[1:30] if len(p:=l.split(None,4))==5],"passwd_users":u,"captured_os_manifest":m}

HTML=r"""<!DOCTYPE html><html lang=es><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>CloudMove AWS</title><style>
*{box-sizing:border-box}body{font:13px/1.4 system-ui;background:#f2f3f3;color:#16191f;margin:0}
.f,.x{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.x{justify-content:space-between}.nv{background:#232f3e;color:#fff;padding:8px 14px}
.b{padding:4px 8px;border-radius:4px;font:700 12px system-ui;cursor:pointer;border:1px solid #aab7b8;background:#fff;color:#16191f;text-decoration:none}
.bp{background:#ff9900;border-color:#ff9900;color:#000}.bb,.fb.a{background:#0972d3;border-color:#0972d3;color:#fff}.bg{background:#37475a;color:#fff}
.w{max-width:1320px;margin:auto;padding:10px}.c,.c0{background:#fff;border:1px solid #d5dbdb;border-radius:5px;padding:9px;margin-bottom:8px}.c0{margin:0}
.p{padding:2px 7px;border-radius:9px;font:700 11px system-ui;border:1px solid #d5dbdb}.ok{background:#ecfdf5;color:#037f0c;border-color:#a7f3d0}.wn{background:#fffbeb;color:#b45309;border-color:#fde68a}
.g{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}.sp{grid-template-columns:1.1fr .9fr}@media(max-width:900px){.sp{grid-template-columns:1fr}}
.d{font:11px monospace;color:#545b64;word-break:break-all}.tb{background:0;border:0;border-bottom:3px solid #0000;padding:6px 8px;font:700 12px system-ui;color:#545b64;cursor:pointer}.tb.a{color:#0972d3;border-bottom-color:#ff9900;background:#fff}
.pn{display:none}.pn.a{display:block}.tw{overflow:auto;max-height:340px;border:1px solid #eaeded}
table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#fafafa;text-align:left;padding:5px;border-bottom:2px solid #d5dbdb}
td{padding:5px;border-bottom:1px solid #f0f2f2;vertical-align:top}tr.s td{background:#e7f3ff}code{font:11.5px monospace;word-break:break-all}
.vc{margin:0;padding:8px;max-height:330px;overflow:auto;background:#0f172a;color:#e2e8f0;font:11.5px monospace}
.ln{display:inline-block;width:22px;color:#64748b;text-align:right;padding-right:5px}
</style></head><body><div id=nv class="nv x"></div><div class=w><div class=c id=hd></div><div id=ts class=f style="border-bottom:2px solid #d5dbdb;margin-bottom:8px"></div><div id=p0 class="pn a"></div><div id=p1 class=pn></div><div id=p2 class=pn></div><div id=p3 class=pn></div></div><script>
let D=__INITIAL_DATA_JSON__,F=D.uploaded_files||[],CAT='all',SEL='',RAW='',NL=String.fromCharCode(10);
const RD='/opt/cloudmove/os_capture/rootfs',ED='/mnt/cloudmove_ebs',G=x=>document.getElementById(x),M=(a,f)=>(a||[]).map(f).join('');
const E=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),B=b=>b<1024?b+' B':(b<1048576?(b/1024).toFixed(1)+' KiB':(b/1048576).toFixed(2)+' MiB'),K=v=>'<code>'+E(v)+'</code>';
const T=(h,r,c)=>'<table><thead><tr>'+M(h,x=>'<th>'+x+'</th>')+'</tr></thead><tbody>'+(r.length?M(r,(w,i)=>'<tr'+(c?c(i):'')+'>'+M(w,x=>'<td>'+x+'</td>')+'</tr>'):'<tr><td colspan='+h.length+'>Sin datos</td></tr>')+'</tbody></table>';
const C=(t,h,r,x='')=>'<div class=c><b style=display:block;margin-bottom:5px>'+t+'</b><div class=tw>'+T(h,r)+'</div>'+x+'</div>';
const bx=(x,w,s,t,a,b)=>'<rect x='+x+' y=18 width='+w+' height=62 rx=5 fill=#fff stroke='+s+' stroke-width=1.5 /><text x='+(x+6)+' y=35 font-size=11 font-weight=700>'+E(t)+'</text><text x='+(x+6)+' y=51 font-size=10 fill=#545b64>'+E(a)+'</text><text x='+(x+6)+' y=66 font-size=10 fill='+s+' font-weight=700>'+E(b)+'</text>';
G('nv').innerHTML='<b>CloudMove · Caso 2 AWS <span class=d style=color:#cbd5e1 id=hh></span></b><div class=f><button class="b bp" onclick=runHC()>¿Funcionó mi despliegue?</button><a class="b bg" href=/bundle.tar.gz>Bundle .tar.gz</a><a class="b bg" href=/files target=_blank>/files</a><a class="b bg" href=/health target=_blank>/health</a></div>';
G('ts').innerHTML=M(['1. Salud','2. Explorador','3. Discos EBS','4. Usuarios y PS'],(t,i)=>'<button class="tb'+(i?'':' a')+'" onclick="sw('+i+',this)">'+t+'</button>');
function sw(i,b){document.querySelectorAll('.pn,.tb').forEach(x=>x.classList.remove('a'));G('p'+i).classList.add('a');b.classList.add('a')}
function sC(c,b){CAT=c;document.querySelectorAll('.fb').forEach(x=>x.classList.remove('a'));b.classList.add('a');rF()}
function draw(h,f,ms){
  const m=D.captured_os_manifest||{},os=m.os||{},tot=F.reduce((a,x)=>a+(x.size_bytes||0),0),ebs=!!D.ebs_mounted,mir=F.filter(x=>x.ebs_mirrored).length,exp=Math.max(F.length,(m.uploaded_os_files||[]).length);
  G('hh').textContent=(m.name||'OS')+' -> '+(D.cloud_hostname||'aws');
  G('hd').innerHTML='<div class=x style=margin-bottom:6px><div class=f>'+M([[h,h?'Despliegue Exitoso':'Validando'],[f,'Archivos '+F.length+'/'+exp+' ('+B(tot)+')'],[ebs,ebs?'EBS OK ('+mir+')':'RootFS nvme0n1']],x=>'<span class="p '+(x[0]?'ok':'wn')+'">'+x[1]+'</span>')+'</div><span class=d>'+E(D._t||'Verificado')+'</span></div><div class=g>'+M([[h,'/health',h?'200 · '+ms+' ms':'...'],[f,'/files',f?'200 · '+F.length+' arch':'...'],[F.length>0,'RootFS',RD],[ebs,'EBS nvme1n1',ebs?ED+'/rootfs':'Pendiente']],c=>'<div class="c0 f" style="background:'+(c[0]?'#f6fef9;border-color:#a7f3d0':'#fafafa')+'"><b style=color:'+(c[0]?'#037f0c':'#b45309')+'>'+(c[0]?'OK':'...')+'</b><div><b>'+c[1]+'</b><div class=d>'+E(c[2])+'</div></div></div>')+'</div>';
  G('p0').innerHTML='<div class=g style=margin-bottom:8px>'+M([['Host',D.cloud_hostname,m.name||'OS'],['Kernel',os.distro||'Linux',D.cloud_kernel],['Uptime',D.cloud_uptime||'Activo','80/3000/8000'],['Archivos',F.length+'/'+exp,B(tot)]],x=>'<div class=c0><div class=d><b>'+x[0]+'</b></div><b>'+E(x[1])+'</b><div class=d>'+E(x[2])+'</div></div>')+'</div><div class=c><b style=display:block;margin-bottom:6px>Trazabilidad y Topología EBS (Archify)</b><div class=g style=margin-bottom:7px>'+M([['Origen','/etc/*, /home/*, /var/log/*'],['RootFS nvme0n1',RD+'/'],['EBS nvme1n1',ED+'/rootfs/']],x=>'<div class=c0 style=background:#f8fafc><b>'+x[0]+'</b><br>'+K(x[1])+'</div>')+'</div><div style=overflow-x:auto><svg viewBox="0 0 790 88" style=width:100%;min-width:500px;display:block>'+bx(2,140,'#545b64','SO Origen',m.name||'Host',F.length+' arch')+'<path d="M142 49H170l-5-4m5 4-5 4" stroke=#0972d3 stroke-width=2 fill=none /><rect x=174 y=4 width=390 height=80 rx=6 fill=#f2f8fd stroke=#0972d3 stroke-dasharray="4 3"/><text x=184 y=15 font-size=10.5 font-weight=700 fill=#0972d3>EC2 ('+E(D.cloud_hostname)+')</text>'+bx(184,182,'#ff9900','RootFS nvme0n1','/opt/.../os_capture/rootfs',':3000/:8000')+bx(380,174,ebs?'#037f0c':'#aab7b8','EBS nvme1n1',ED+'/rootfs',ebs?'OK ('+mir+')':'Pendiente')+'<path d="M564 49H592l-5-4m5 4-5 4" stroke=#0972d3 stroke-width=2 fill=none />'+bx(596,190,'#037f0c','API /etc/passwd','/health · /files',(D.passwd_users||[]).filter(u=>u.is_source_user).length+' users OK')+'</svg></div></div>';
  if(!G('fq'))G('p1').innerHTML='<div class=c><div class=x style=margin-bottom:6px><b>Explorador de Archivos</b><span id=fsb class=p>0</span></div><div class=f style=margin-bottom:7px><input id=fq style="padding:5px;border:1px solid #879596;border-radius:4px;flex:1" placeholder="Buscar ruta o SHA..." oninput=rF()>'+M([['all','Todos'],['config','/etc'],['user','/home'],['logs','/var']],(x,i)=>'<button class="b fb'+(i?'':' a')+'" onclick="sC(\''+x[0]+'\',this)">'+x[1]+'</button>')+'</div><div class="g sp"><div class=tw id=ftw onclick="var b=event.target.closest(\'[data-r]\');if(b)loadF(b.dataset.r)"></div><div style=border-radius:5px;overflow:hidden><div class=x style="padding:6px 9px;background:#1e293b;color:#fff"><div><b id=vo></b><div class=d style=color:#94a3b8 id=vp></div></div><div class=f><button class=b onclick="if(RAW)navigator.clipboard?.writeText(RAW)">Copiar</button><a id=vr class="b bb" target=_blank>Raw</a></div></div><pre class=vc id=vb></pre></div></div></div>';
  G('p2').innerHTML=C('Discos (lsblk)',['Dev','Size','Type','FS','Mount','UUID'],(D.lsblk_rows||[]).map(r=>[K(' '.repeat(r.depth*2)+r.name),'<b>'+E(r.size)+'</b>',E(r.type),K(r.fstype),K(r.mountpoint),K(r.uuid)]))+C('Uso FS (df -hT)',['FS','Type','Size','Used','Avail','Uso','Mount'],(D.df_rows||[]).map(r=>[K(r.filesystem),E(r.fstype),E(r.size),E(r.used),E(r.avail),'<b>'+E(r.use_pct)+'</b><div style=height:4px;background:#e5e7eb><div style="height:100%;background:#0972d3;width:'+E(r.use_pct)+'"></div></div>',K(r.mountpoint)]),'<details style=margin-top:6px><summary style=cursor:pointer;color:#0972d3;font-weight:700>CLI raw</summary><pre class=vc>'+E((D.lsblk_live||'')+NL+(D.df_live||''))+'</pre></details>');
  G('p3').innerHTML=C('Cuentas /etc/passwd',['User','UID/GID','Home','Shell','Estado'],(D.passwd_users||[]).map(u=>['<b>'+K(u.username)+'</b>',K(u.uid+'/'+u.gid),K(u.home),K(u.shell),(u.is_source_user?'<span class="p ok">Origen</span>':'<span class=p>EC2</span>')+(u.home_exists?' Home':'')]))+C('Procesos (ps)',['PID','User','CPU','MEM','Cmd'],(D.ps_rows||[]).map(p=>[K(p.pid),K(p.user),E(p.cpu)+'%',E(p.mem)+'%','<b>'+E(p.command)+'</b>']));
  rF();
}
function rF(){
  const q=(G('fq').value||'').trim().toLowerCase(),lst=F.filter(f=>(CAT==='all'||f.category===CAT)&&(!q||f.path.toLowerCase().includes(q)||f.sha256.includes(q)));
  G('fsb').textContent=lst.length+'/'+F.length+' ('+B(lst.reduce((a,f)=>a+(f.size_bytes||0),0))+')';
  G('ftw').innerHTML=T(['Origen','AWS RootFS / EBS','Tam','SHA','Ver'],lst.map(f=>['<b>'+K(f.origin_path)+'</b>',K(f.rootfs_path)+(f.ebs_mirrored?'<div style=color:#037f0c>EBS: '+K(f.ebs_path)+'</div>':''),B(f.size_bytes),K(f.sha256.slice(0,8)),'<button class="b bb" style="padding:2px 6px" data-r="'+E(f.path)+'">Ver</button> <a class=b href="/files/download?path='+encodeURIComponent(f.path)+'">DL</a>']),i=>(SEL===lst[i].path?' class=s':''));
}
function hi(t,p){return M(t.split(NL),(l,i)=>{let h=E(l);if(p.endsWith('.json'))h=h.replace(/"([^"]+)":/g,'<span style=color:#38bdf8>"$1"</span>:');else if(h.trim()[0]=='#')h='<span style=color:#94a3b8>'+h+'</span>';else if(/^\w+=/.test(h))h=h.replace(/^([^=]+)=(.*)$/,'<span style=color:#38bdf8>$1</span>=<span style=color:#86efac>$2</span>');return '<div><span class=ln>'+(i+1)+'</span>'+h+'</div>'})}
async function loadF(rp){
  SEL=rp;rF();G('vo').textContent='/'+rp;G('vp').textContent=RD+'/'+rp+' | '+ED+'/rootfs/'+rp;G('vr').href='/files/view?path='+encodeURIComponent(rp);G('vb').textContent='Cargando...';
  try{RAW=await(await fetch('/files/view?path='+encodeURIComponent(rp))).text();G('vb').innerHTML=hi(RAW,rp)}catch(e){G('vb').textContent='Error: '+e}
}
async function runHC(){
  const t0=performance.now();
  try{const[hr,fr]=await Promise.all([fetch('/health'),fetch('/files')]);const ms=Math.round(performance.now()-t0);if(hr.ok)D=await hr.json();if(fr.ok){const fd=await fr.json();if(fd.files)F=fd.files}D._t=new Date().toLocaleTimeString()+' ('+ms+' ms)';draw(hr.ok,fr.ok,ms)}catch(e){draw(false,false,0)}
}
draw(true,true,0);if(F.length)loadF(F[0].path);runHC();
</script></body></html>"""

class H(http.server.BaseHTTPRequestHandler):
    def _w(self,c,t,b,cd=""):
        b=b.encode("utf-8") if isinstance(b,str) else b;self.send_response(c);self.send_header("Content-Type",t);self.send_header("Access-Control-Allow-Origin","*")
        if cd: self.send_header("Content-Disposition",cd)
        self.end_headers();self.wfile.write(b)
    def do_GET(self):
        try:
            u=urllib.parse.urlparse(self.path);p=u.path;q=urllib.parse.parse_qs(u.query);rr=os.path.realpath(RD)
            if p=="/bundle.tar.gz" and os.path.isfile(BP):
                with open(BP,"rb") as f: self._w(200,"application/gzip",f.read(),'attachment;filename="os_real_files_bundle.tar.gz"');return
            if p=="/files": fl=uf();self._w(200,"application/json; charset=utf-8",json.dumps({"status":"OK","rootfs_dir":RD,"ebs_mount_dir":ED+"/rootfs","ebs_mounted":os.path.ismount(ED),"total_files":len(fl),"total_bytes":sum(f["size_bytes"] for f in fl),"files":fl},separators=(",",":"),ensure_ascii=False));return
            if p in ("/files/view","/files/download"):
                rel=(q.get("path") or ["etc/os-release"])[0].lstrip("/");sf=_resolve(rel)
                if not sf: self._w(404,"text/plain",f"No encontrado: {rel}");return
                if p=="/files/view" and os.path.isdir(sf):
                    en=[f"{'[DIR] ' if os.path.isdir(os.path.join(sf,x)) else '[FILE]'} {x} ({os.path.getsize(os.path.join(sf,x)) if os.path.isfile(os.path.join(sf,x)) else 0} B)" for x in sorted(os.listdir(sf))[:200]]
                    self._w(200,"text/plain; charset=utf-8",f"# Directorio: /{rel}\n# RootFS: {RD}/{rel}\n# EBS: {ED}/rootfs/{rel}\n# Entradas: {len(en)}\n\n"+("\n".join(en) or "(vacío)"));return
                if not os.path.isfile(sf): self._w(404,"text/plain",f"No encontrado: {rel}");return
                if p=="/files/download":
                    with open(sf,"rb") as f: self._w(200,"application/octet-stream",f.read(),f'attachment;filename="{os.path.basename(sf)}"');return
                st=os.stat(sf)
                with open(sf,"rb") as f: raw=f.read(131072)
                if b"\x00" in raw[:2048]:
                    self._w(200,"text/plain; charset=utf-8",f"# Archivo binario migrado: /{rel}\n# Tamaño: {st.st_size} bytes\n# SHA-256: {_sha(sf)}\n# Ruta RootFS: {RD}/{rel}\n# Ruta EBS: {ED}/rootfs/{rel}\n# Descarga: /files/download?path={urllib.parse.quote(rel)}\n");return
                self._w(200,"text/plain; charset=utf-8",raw.decode("utf-8",errors="replace"));return
            d=tel()
            if p.startswith(("/health","/api/")): self._w(200,"application/json; charset=utf-8",json.dumps(d,separators=(",",":"),ensure_ascii=False));return
            self._w(200,"text/html; charset=utf-8",HTML.replace("__INITIAL_DATA_JSON__",json.dumps(d,separators=(",",":"),ensure_ascii=False).replace("<",r"\u003c")))
        except Exception as exc: self._w(500,"text/plain",f"Error: {exc}")
    def do_POST(self):
        try:
            u=urllib.parse.urlparse(self.path);p=u.path;q=urllib.parse.parse_qs(u.query)
            tok=open(TK,encoding="utf-8").read().strip() if os.path.isfile(TK) else ""
            if not tok or not hmac.compare_digest(tok,self.headers.get("X-CloudMove-Sync-Token","")):
                self._w(403,"application/json",'{"error":"forbidden"}');return
            n=int(self.headers.get("Content-Length","0") or "0")
            if n<0 or n>134217728: self._w(413,"application/json",'{"error":"payload_too_large"}');return
            raw=self.rfile.read(n)
            def _sid_ok(v): return bool(re.fullmatch(r"[A-Za-z0-9_.\-]{3,80}",str(v or "").strip()) and ".." not in str(v or ""))
            if p=="/sync-stage":
                bu=str(json.loads(raw.decode("utf-8")).get("bundle_url") or "")
                if not bu.startswith(("https://","http://")): self._w(400,"application/json",'{"error":"invalid url"}');return
                threading.Thread(target=lambda:subprocess.run(["bash","/opt/cloudmove/os_capture/sync_stage.sh",bu],capture_output=True),daemon=True).start()
                self._w(202,"application/json",'{"status":"sync_started"}');return
            if p=="/upload-chunk":
                sid=(q.get("stage_id") or [""])[0].strip();ci=int((q.get("chunk_index") or ["0"])[0])
                if not _sid_ok(sid) or ci<0: self._w(400,"application/json",'{"error":"invalid_stage_id"}');return
                sd=os.path.join(CD,sid);os.makedirs(sd,exist_ok=True)
                open(os.path.join(sd,f"p{ci:06d}"),"wb").write(raw)
                self._w(200,"application/json",'{"ok":true}');return
            if p=="/upload-commit":
                b=json.loads(raw.decode("utf-8"));sid=str(b.get("stage_id") or "").strip();tc=int(b["total_chunks"])
                if not _sid_ok(sid) or tc<1: self._w(400,"application/json",'{"error":"invalid_stage_id"}');return
                sd=os.path.join(CD,sid);tfp=sd+".tar.gz";h=hashlib.sha256()
                with open(tfp,"wb") as out:
                    for i in range(tc):
                        d=open(os.path.join(sd,f"p{i:06d}"),"rb").read();h.update(d);out.write(d)
                shutil.rmtree(sd,ignore_errors=True)
                if b.get("expected_sha256") and h.hexdigest()!=b["expected_sha256"]: os.unlink(tfp);self._w(400,"application/json",'{"error":"sha"}');return
                tg=ED+"/rootfs" if os.path.ismount(ED) else RD
                subprocess.run(["bash","/opt/cloudmove/os_capture/apply_tar.sh",tfp,tg],check=False)
                self._w(200,"application/json",'{"status":"extracted"}');return
            self._w(404,"application/json",'{"error":"not found"}')
        except Exception as exc: self._w(500,"application/json",json.dumps({"error":str(exc)}))

if __name__=="__main__":
    for pt in (80,3000,8000): threading.Thread(target=lambda x:http.server.ThreadingHTTPServer(("0.0.0.0",x),H).serve_forever(),args=(pt,),daemon=True).start()
    threading.Event().wait()
'''

    def _build_uc2_user_data(files_dict: Dict[str, str], manifest_json_txt: str) -> str:
        files_json_txt = json.dumps(files_dict, separators=(",", ":"), ensure_ascii=False)
        return f"""#!/usr/bin/env bash
set -uo pipefail
exec > >(tee -a /var/log/cloudmove-os-bootstrap.log) 2>&1
mkdir -p /opt/cloudmove/os_capture/rootfs /mnt/cloudmove_ebs
cat << 'EOF_MANIFEST' > /opt/cloudmove/os_capture/image_manifest.json
{manifest_json_txt}
EOF_MANIFEST
cat << 'EOF_FILES_JSON' > /opt/cloudmove/os_capture/os_files_map.json
{files_json_txt}
EOF_FILES_JSON
printf '%s' '{stage_sync_token}' > /opt/cloudmove/os_capture/sync_token && chmod 600 /opt/cloudmove/os_capture/sync_token
python3 - << 'PY_EXTRACT'
import json,os,tarfile
R="/opt/cloudmove/os_capture/rootfs"
fm=json.load(open("/opt/cloudmove/os_capture/os_files_map.json",encoding="utf-8"))
for rel,txt in fm.items():
    d=os.path.realpath(os.path.join(R,rel.lstrip("/")))
    if not d.startswith(os.path.realpath(R)): continue
    os.makedirs(os.path.dirname(d),exist_ok=True)
    with open(d,"w",encoding="utf-8") as o: o.write(txt)
with tarfile.open("/opt/cloudmove/os_capture/os_real_files_bundle.tar.gz","w:gz") as tf:
    for rel in fm:
        p=os.path.join(R,rel.lstrip("/"))
        if os.path.isfile(p): tf.add(p,arcname=rel.lstrip("/"))
PY_EXTRACT
cat << 'EOF_SYSCTL' > /etc/sysctl.d/99-cloudmove-migrated.conf
{sysctl_lines}
EOF_SYSCTL
sysctl --system >/dev/null 2>&1 || true
for U in {users_csv}; do
    id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash "$U" >/dev/null 2>&1 || true
    [ -d "/opt/cloudmove/os_capture/rootfs/home/$U" ] && [ -d "/home/$U" ] && cp -rn "/opt/cloudmove/os_capture/rootfs/home/$U/"* "/home/$U/" 2>/dev/null && chown -R "$U:$U" "/home/$U" 2>/dev/null || true
done
cat << 'EOF_EBS' > /opt/cloudmove/os_capture/sync_ebs.sh
#!/usr/bin/env bash
TRIES="${{1:-60}}"
RD=$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null | head -n1)
for _ in $(seq 1 "$TRIES"); do
    M=0
    mountpoint -q /mnt/cloudmove_ebs && M=1
    for D in /dev/nvme1n1 /dev/nvme2n1 /dev/xvdf /dev/sdf; do
        [ -b "$D" ] || continue
        BN=$(basename "$D")
        [ "$BN" = "$RD" ] || [ "$BN" = "nvme0n1" ] || [ "$BN" = "xvda" ] && continue
        if [ "$M" = "0" ]; then
            blkid "$D" >/dev/null 2>&1 || mkfs.ext4 -F -L CLOUDMOVE_OS "$D" >/dev/null 2>&1 || true
            mount "$D" /mnt/cloudmove_ebs 2>/dev/null && M=1 || true
            U=$(blkid -s UUID -o value "$D" 2>/dev/null || true)
            [ -n "$U" ] && ! grep -q "$U" /etc/fstab && echo "UUID=$U /mnt/cloudmove_ebs ext4 defaults,nofail 0 2" >> /etc/fstab || true
        fi
        if [ "$M" = "1" ]; then
            mkdir -p /mnt/cloudmove_ebs/rootfs && cp -ru /opt/cloudmove/os_capture/rootfs/. /mnt/cloudmove_ebs/rootfs/ 2>/dev/null || cp -r /opt/cloudmove/os_capture/rootfs/* /mnt/cloudmove_ebs/rootfs/ 2>/dev/null || true
            cp /opt/cloudmove/os_capture/image_manifest.json /mnt/cloudmove_ebs/ 2>/dev/null || true
            exit 0
        fi
    done
    [ "$TRIES" -gt 1 ] && sleep 5
done
EOF_EBS
chmod +x /opt/cloudmove/os_capture/sync_ebs.sh
cat << 'EOF_APPLY' > /opt/cloudmove/os_capture/apply_tar.sh
#!/usr/bin/env bash
set -uo pipefail
T="$1";TG="${{2:-/mnt/cloudmove_ebs/rootfs}}"
mkdir -p "$TG"
python3 - "$T" "$TG" <<'PY'
import os,sys,tarfile as t
d=os.path.realpath(sys.argv[2])
with t.open(sys.argv[1],"r:gz") as f:
 m=[]
 for x in f.getmembers():
  r=x.name.lstrip("/")
  if r.startswith("./"):r=r[2:]
  p=os.path.realpath(os.path.join(d,r))
  if r and r!="." and ".." not in r.split("/") and not(x.issym() or x.islnk()) and (x.isfile() or x.isdir()) and (p==d or p.startswith(d+os.sep)):x.name=r;m.append(x)
 try:f.extractall(d,members=m,filter="data")
 except TypeError:f.extractall(d,members=m)
PY
rm -f "$T"
for HD in "$TG"/home/*; do
    [ -d "$HD" ] || continue
    U=$(basename "$HD")
    id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash "$U" >/dev/null 2>&1 || true
    mkdir -p "/opt/cloudmove/os_capture/rootfs/home/$U" "/home/$U"
    for SUB in "$HD"/*; do
        [ -e "$SUB" ] || continue
        BN=$(basename "$SUB")
        ln -sfn "$SUB" "/opt/cloudmove/os_capture/rootfs/home/$U/$BN" 2>/dev/null || true
        ln -sfn "$SUB" "/home/$U/$BN" 2>/dev/null || true
    done
done
EOF_APPLY
chmod +x /opt/cloudmove/os_capture/apply_tar.sh
cat << 'EOF_STAGE' > /opt/cloudmove/os_capture/sync_stage.sh
#!/usr/bin/env bash
set -uo pipefail
URL="${{1:-}}"
[ -z "$URL" ] && exit 0
bash /opt/cloudmove/os_capture/sync_ebs.sh 36 >/var/log/cloudmove-ebs.log 2>&1 || true
TG=/opt/cloudmove/os_capture/rootfs
mountpoint -q /mnt/cloudmove_ebs && TG=/mnt/cloudmove_ebs/rootfs
mkdir -p "$TG"
curl -fsSL --retry 4 --retry-delay 2 -o /tmp/cm_st.tgz "$URL" && bash /opt/cloudmove/os_capture/apply_tar.sh /tmp/cm_st.tgz "$TG" || exit 1
if [ "$TG" != "/mnt/cloudmove_ebs/rootfs" ]; then
    for HD in /opt/cloudmove/os_capture/rootfs/home/*; do
        [ -d "$HD" ] || continue
        U=$(basename "$HD")
        [ -d "/home/$U" ] && cp -rnu "$HD/." "/home/$U/" 2>/dev/null && chown -R "$U:$U" "/home/$U" 2>/dev/null || true
    done
fi
EOF_STAGE
chmod +x /opt/cloudmove/os_capture/sync_stage.sh
cat << 'EOF_SERVER' > /opt/cloudmove/os_capture/telemetry_server.py
{telemetry_server_py}
EOF_SERVER
cat << 'EOF_UNIT' > /etc/systemd/system/cloudmove-os-telemetry.service
[Unit]
Description=CloudMove UC2 Telemetry
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/cloudmove/os_capture/telemetry_server.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF_UNIT
systemctl daemon-reload && systemctl enable --now cloudmove-os-telemetry.service
nohup bash /opt/cloudmove/os_capture/sync_ebs.sh 60 >/var/log/cloudmove-ebs.log 2>&1 &
STAGE_URL="{stage_bundle_url}"
[ -n "$STAGE_URL" ] && nohup bash /opt/cloudmove/os_capture/sync_stage.sh "$STAGE_URL" >/var/log/cloudmove-stage.log 2>&1 &
"""

    user_data_script = _build_uc2_user_data(bundled_files_contents, compact_os_json)
    trim_order = [
        "var/log/cloudmove_source_dpkg_packages.txt",
        "var/log/cloudmove_source_processes_ports.txt",
        "var/log/cloudmove_source_lsblk_df.txt",
        "etc/nsswitch.conf",
        "etc/sysctl.conf",
        "etc/crontab",
        "etc/group",
    ]
    for trim_key in trim_order:
        if len(base64.b64encode(gzip.compress(user_data_script.encode("utf-8")))) <= 15200:
            break
        if trim_key in bundled_files_contents:
            bundled_files_contents[trim_key] = bundled_files_contents[trim_key][:200] + "\n# [Compactado EC2 16 KB]"
            user_data_script = _build_uc2_user_data(bundled_files_contents, compact_os_json)

    protected = {
        "etc/fstab",
        "etc/os-release",
        "etc/passwd",
        "etc/hosts",
        "var/log/cloudmove_selected_paths_map.json",
    } | {p.lstrip("/") for p in selected_paths}
    for longest_k in sorted(bundled_files_contents, key=lambda k: (k in protected, -len(bundled_files_contents[k]))):
        if len(base64.b64encode(gzip.compress(user_data_script.encode("utf-8")))) <= 15200:
            break
        if len(bundled_files_contents[longest_k]) > 450:
            bundled_files_contents[longest_k] = bundled_files_contents[longest_k][:450] + "\n# [Recortado]"
            user_data_script = _build_uc2_user_data(bundled_files_contents, compact_os_json)

    # Hard safety pass: ensure AWS EC2 16,384-byte compressed+b64 limit is never exceeded
    if len(base64.b64encode(gzip.compress(user_data_script.encode("utf-8")))) > 15800:
        core_keep = {"etc/os-release", "etc/fstab", "etc/hostname"}
        for drop_k in sorted(
            list(bundled_files_contents.keys()),
            key=lambda k: (k in core_keep, -len(bundled_files_contents.get(k, ""))),
        ):
            if len(base64.b64encode(gzip.compress(user_data_script.encode("utf-8")))) <= 15800:
                break
            if drop_k in core_keep:
                continue
            bundled_files_contents.pop(drop_k, None)
            user_data_script = _build_uc2_user_data(bundled_files_contents, compact_os_json)

    if len(base64.b64encode(gzip.compress(user_data_script.encode("utf-8")))) > 15800:
        compact_os_state["uploaded_os_files"] = (compact_os_state.get("uploaded_os_files") or [])[:12]
        compact_os_state.pop("installed_packages_sample", None)
        compact_os_json = json.dumps(compact_os_state, separators=(",", ":"), ensure_ascii=False)
        user_data_script = _build_uc2_user_data(bundled_files_contents, compact_os_json)


    return user_data_script
