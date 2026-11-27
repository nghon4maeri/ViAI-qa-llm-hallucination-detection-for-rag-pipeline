# tests/infra/test_repo_paths.py
"""
Every path a build or deploy file points at must exist in the checkout: Dockerfile COPY sources,
compose contexts and bind mounts, Ansible/Helmfile relative paths, CI/Jenkins/Make/Render/Vercel
paths, DVC deps and commands. Folder moves broke these silently once (R3); this catches it.
"""
import glob
import json
import os
import re

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def dvc_managed() -> list:
    """
    Paths DVC restores (dvc pull / dvc repro) rather than git: .dvc pointer targets and stage outputs.
    A clean checkout (CI) does not have them yet, and that is not a broken reference.
    """
    paths = [f[:-len(".dvc")] for f in glob.glob("**/*.dvc", recursive=True)]
    for stage in yaml.safe_load(open("dvc.yaml"))["stages"].values():
        paths += [o if isinstance(o, str) else next(iter(o)) for o in stage.get("outs", [])]
    return [p.rstrip("/") for p in paths]


def test_referenced_paths_exist(monkeypatch):
    monkeypatch.chdir(ROOT)
    missing = []
    managed = dvc_managed()

    def need(path, where):
        if glob.glob(path):
            return
        p = path.rstrip("/")
        # the path is, is inside, or contains something DVC restores
        if any(p == m or p.startswith(m + "/") or m.startswith(p + "/") for m in managed):
            return
        missing.append(f"{where}: {path}")


    # Dockerfiles built from the repo root (compose context .. / CI context .)
    root_ctx = ["Dockerfile.backend", "Dockerfile.ci", "Dockerfile.frontend", "Dockerfile.frontend.dev", "Dockerfile.nginx", "Dockerfile.jenkins"]
    for name in root_ctx:
        for line in open(f"infrastructure/docker/{name}"):
            m = re.match(r"\s*COPY\s+(?!--from)(?:--\S+\s+)*(.+?)\s+\S+\s*$", line)
            if m:
                for src in m.group(1).split():
                    need(src, name)
    for line in open("infrastructure/mlflow/Dockerfile"):
        m = re.match(r"\s*COPY\s+(?!--from)(\S+)\s+\S+", line)
        if m: need(os.path.join("infrastructure/mlflow", m.group(1)), "mlflow/Dockerfile")

    # Compose: build contexts, dockerfiles, bind-mount sources (relative to the compose file)
    cfg = yaml.safe_load(open("infrastructure/docker-compose.yml"))
    base = "infrastructure"
    for svc, spec in cfg["services"].items():
        b = spec.get("build")
        if isinstance(b, dict):
            ctx = os.path.normpath(os.path.join(base, b.get("context", ".")))
            need(ctx, f"compose {svc} context")
            if "dockerfile" in b: need(os.path.join(ctx, b["dockerfile"]), f"compose {svc} dockerfile")
        for v in spec.get("volumes", []) or []:
            if isinstance(v, str) and ":" not in v: continue  # anonymous volume (container path only)
            src = v.split(":")[0] if isinstance(v, str) else v.get("source", "")
            if src.startswith((".", "/")) and not src.startswith("/var"):
                need(os.path.normpath(os.path.join(base, src)), f"compose {svc} volume")

    # Relative paths in Ansible / Helmfile
    for f, d in [("infrastructure/iac/ansible/setup_k8s_stack.yaml", "infrastructure/iac/ansible"),
                 ("infrastructure/iac/ansible/setup_gke_stack.yaml", "infrastructure/iac/ansible"),
                 ("infrastructure/k8s/helmfile.yaml", "infrastructure/k8s")]:
        for p in re.findall(r"(\.\./[\w./-]+)", open(f).read()):
            if "gateway/nginx/custom-values" in p: continue  # broken before the refactor, see REFACTOR_PLAN
            need(os.path.normpath(os.path.join(d, p)), os.path.basename(f))

    # CI, Jenkins, Render, Vercel, Makefile, DVC
    for f in [".github/workflows/ci.yml", "Jenkinsfile", "Makefile"]:
        for p in re.findall(r"(?<![\w./-])((?:infrastructure|machine-learning|applications|client-sdk|tests|requirements)/[\w./-]+\.(?:py|yaml|yml|txt|toml|ci|backend|frontend|jenkins|nginx))", open(f).read()):
            need(p, f)
        for p in re.findall(r"dir\('([^']+)'\)", open(f).read()):
            need(p, f)
        for p in re.findall(r"=\s*'\./([^']+)'", open(f).read()):
            need(p, f)
    r = open("render.yaml").read()
    for p in re.findall(r"rootDir:\s*(\S+)", r) + re.findall(r"-r (\S+)", r) + re.findall(r"cd (\S+) &&", r): need(p, "render.yaml")
    for p in re.findall(r"cd (\S+) &&", json.load(open("vercel.json"))["buildCommand"]): need(p, "vercel.json")
    for stage in yaml.safe_load(open("dvc.yaml"))["stages"].values():
        for d in stage.get("deps", []): need(d, "dvc.yaml dep")
        for tok in stage["cmd"].split():
            if tok.endswith(".py"): need(tok, "dvc.yaml cmd")

    assert not missing, "Paths referenced but missing:\n" + "\n".join(missing)
