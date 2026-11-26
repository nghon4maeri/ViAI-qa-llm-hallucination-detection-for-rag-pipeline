# docs/diagrams/architecture.py
"""
Pipeline diagrams for the README, drawn with mingrammer/diagrams (https://diagrams.mingrammer.com).

    pip install diagrams==0.24.4 cairosvg==2.8.2 "fonttools[woff]==4.60.1"   # + Graphviz `dot` on PATH
    python docs/diagrams/architecture.py                                      # or: make diagrams

Writes docs/images/architecture/<name>.png. Each diagram follows one path of the architecture overview
(docs/images/overview.png) and copies its Excalidraw look: Excalidraw's hand-drawn Virgil font, pastel
rounded boxes with dark outlines, black arrows. One node (and one icon) per component, short labels,
only the main flow; details live in the README next to each image.

- Font: docs/diagrams/fonts/Virgil.woff2 is the unmodified file from github.com/excalidraw/virgil
  (SIL OFL 1.1, see LICENSE.md there). fontconfig cannot read woff2, so the first run converts it to
  ~/.local/share/fonts/Virgil.otf for local use only.
- Rendering: Graphviz writes SVG and cairosvg rasterises it at 2x, because Graphviz's own PNG
  renderer drops the outline of rounded, filled clusters below penwidth 2.
- Icons the library lacks (DVC, KServe, MinIO, MLServer, LightGBM, Hugging Face, Claude, Jupyter,
  MLflow) are in docs/diagrams/icons/.
"""
import os
import shutil
import subprocess
import sys

from diagrams import Cluster, Diagram, Edge
from diagrams.custom import Custom
from diagrams.gcp.compute import GKE
from diagrams.gcp.database import SQL
from diagrams.gcp.storage import GCS
from diagrams.k8s import K8S
from diagrams.k8s.ecosystem import Helm
from diagrams.onprem.ci import GithubActions, Jenkins
from diagrams.onprem.client import User, Users
from diagrams.onprem.container import Docker
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.iac import Ansible, Terraform
from diagrams.onprem.logging import Loki
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Nginx
from diagrams.onprem.tracing import Jaeger
from diagrams.onprem.vcs import Github
from diagrams.programming.framework import FastAPI, Svelte, Vercel
from diagrams.programming.language import Python

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "images", "architecture")
ICON = os.path.join(HERE, "icons")

# Excalidraw look of docs/images/overview.png
FONT = "Virgil 3 YOFF"  # family name inside docs/diagrams/fonts/Virgil.woff2
FONT_SRC = os.path.join(HERE, "fonts", "Virgil.woff2")
FONT_DST = os.path.expanduser("~/.local/share/fonts/Virgil.otf")


def ensure_font() -> None:
    """Make Virgil visible to fontconfig (and so to Graphviz and cairosvg)."""
    if shutil.which("fc-list") and FONT in subprocess.run(["fc-list", ":", "family"], capture_output=True,
                                                         text=True).stdout:
        return
    from fontTools.ttLib import TTFont  # needs fonttools[woff] for woff2 (brotli)

    os.makedirs(os.path.dirname(FONT_DST), exist_ok=True)
    font = TTFont(FONT_SRC)
    font.flavor = None
    font.save(FONT_DST)
    if shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", os.path.dirname(FONT_DST)], check=False)
    print(f"[INFO] installed {FONT_DST} for local rendering")


INK = "#1e1e1e"
GRAPH = {"fontname": FONT, "fontsize": "28", "fontcolor": INK, "labelloc": "t", "pad": "0.5",
         "nodesep": "0.7", "ranksep": "1.1", "splines": "spline", "bgcolor": "white"}
NODE = {"fontname": FONT, "fontsize": "16", "fontcolor": INK}
EDGE = {"fontname": FONT, "fontsize": "15", "fontcolor": INK, "color": INK, "penwidth": "1.4",
        "arrowhead": "vee", "arrowsize": "0.9"}

# box fills sampled from the overview
LOCAL = "#f6e3cc"      # "Local Environment"
VM = "#ece3e8"         # Jenkins on Compute Engine
CLUSTER = "#ebe7e0"    # GKE area
SERVICE = "#dfe9ec"    # Inference / Preprocessing Service boxes
STORAGE = "#f1e2de"    # "Storage"
MONITOR = "#f4ead9"    # "Monitoring Stack"


def group(label: str, fill: str) -> Cluster:
    # "filled" + fillcolor, not bgcolor: Graphviz only draws the dark outline (pencolor) that way
    return Cluster(label, graph_attr={"style": "rounded,filled", "fillcolor": fill, "bgcolor": fill,
                                      "pencolor": INK, "penwidth": "1.6", "margin": "20",
                                      "fontname": FONT, "fontsize": "20", "fontcolor": INK})


def icon(name: str, label: str) -> Custom:
    return Custom(label, os.path.join(ICON, f"{name}.png"))


def flow(label: str = "", outside: bool = False, side: bool = False, **kw) -> Edge:
    """
    Hand-drawn style edge. Edge() hardcodes Sans-Serif, so the font is set here on every edge.
    outside=True uses xlabel, which keeps the label off a cluster title the edge crosses.
    side=True (constraint=false) draws the edge without letting it rank nodes: return paths and side
    branches stay visible but do not push nodes into new rows, so the main flow stays one row.
    """
    text = {"xlabel": label} if outside else {"label": label}
    extra = {"constraint": "false"} if side else {}
    return Edge(**text, **{**EDGE, **extra, **kw})


def place() -> Edge:
    """Invisible edge that only puts a node one column to the right of another."""
    return Edge(style="invis")


def diagram(title: str, name: str, **graph) -> Diagram:
    # left to right: every pipeline reads as one horizontal flow
    return Diagram(title, filename=os.path.join(OUT, name), outformat="svg", show=False,
                   direction="LR", graph_attr={**GRAPH, **graph}, node_attr=NODE, edge_attr=EDGE)


def rasterise(name: str) -> None:
    """
    SVG -> committed PNG. Graphviz links each icon by absolute path; cairosvg refuses external
    files by default, so the icons are inlined as data URIs first (no unsafe mode needed).
    """
    import base64
    import re

    import cairosvg

    svg_path = os.path.join(OUT, f"{name}.svg")
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()

    def inline(match):
        path = match.group(2)
        with open(path, "rb") as img:
            data = base64.b64encode(img.read()).decode("ascii")
        return f'{match.group(1)}="data:image/png;base64,{data}"'

    svg = re.sub(r'((?:xlink:)?href)="(/[^"]+\.png)"', inline, svg)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=os.path.join(OUT, f"{name}.png"),
                     scale=2, background_color="white")
    os.remove(svg_path)


def data_training():
    """Overview steps 1-6."""
    with diagram("Data & training pipeline", "data-training-pipeline"):
        engineer = User("AI engineer")
        with group("Local Environment", LOCAL):
            notebook = icon("jupyter", "Notebooks")
            dvc = icon("dvc", "DVC\ndata + pipeline")
            phobert = icon("huggingface", "PhoBERT\nembeddings")
            lgbm = icon("lightgbm", "LightGBM\n5-fold")
        with group("GKE", CLUSTER):
            mlflow = icon("mlflow", "MLflow\ntracking + registry")
            audits = PostgreSQL("Audit feedback")
        with group("Storage", STORAGE):
            sql = SQL("Cloud SQL\nmetadata")
            gcs = GCS("GCS\nmodel artifacts")
            minio = icon("minio", "MinIO\nDVC remote")

        engineer >> flow("1. clean") >> notebook >> flow("2. version") >> dvc
        dvc >> flow("dvc repro") >> phobert >> flow("778 features") >> lgbm >> flow("3. log run") >> mlflow
        mlflow >> flow("5") >> sql
        mlflow >> flow("4, 6") >> gcs
        lgbm >> place() >> audits
        mlflow >> place() >> minio
        dvc >> flow("dvc push", side=True, style="dashed") >> minio
        audits >> flow("feedback -> retrain", side=True, style="dashed") >> dvc


def serving():
    """Overview steps 12, 14, 15."""
    with diagram("Serving pipeline", "serving-pipeline"):
        clients = Users("Web / SDK / MCP")
        with group("GKE", CLUSTER):
            nginx = Nginx("NGINX\ngateway")
            api = FastAPI("Backend API")
            db = PostgreSQL("Audits")
            with group("KServe InferenceService", SERVICE):
                transformer = icon("kserve", "Transformer\nfeatures + guardrails")
                predictor = icon("mlserver", "MLServer\nLightGBM")
        with group("Storage", STORAGE):
            gcs = GCS("GCS\nmodel")

        clients >> flow("14") >> nginx >> flow("15") >> api >> flow("text") >> transformer
        transformer >> flow("778 features") >> predictor << flow("12. mount") << gcs
        predictor >> flow("probabilities", side=True, style="dashed") >> transformer
        transformer >> flow("verdict", side=True, style="dashed") >> api
        api >> db


def rag_evaluation():
    """The evaluation platform around a RAG application."""
    with diagram("RAG evaluation & guard pipeline", "rag-evaluation-pipeline"):
        patient = Users("User")
        with group("RAG application", LOCAL):
            rag = Python("RAG app\nretrieve + generate")
        with group("ViAI-QA platform", CLUSTER):
            guard = FastAPI("Guard\nclaim × context")
            db = PostgreSQL("Audits")
            judge = icon("anthropic", "Claude judge\n(doubtful claims)")
            trace = Svelte("Trace View")
        with group("Training", SERVICE):
            dvc = icon("dvc", "Retrain")

        patient >> flow("question") >> rag >> flow("answer + contexts") >> guard >> flow("audit") >> db
        db >> flow("deep audit", style="dashed") >> judge
        db >> trace
        db >> flow("flywheel", style="dashed") >> dvc
        guard >> flow("pass / block", side=True) >> patient
        guard >> flow("regenerate", side=True, color="#b7791f") >> rag
        judge >> flow("verdicts", side=True, style="dashed") >> db
        trace >> flow("feedback", side=True) >> db


def ci_cd():
    """Overview steps 7-11, 13."""
    with diagram("CI/CD pipeline", "ci-cd-pipeline"):
        engineer = User("AI engineer")
        github = Github("GitHub")
        ci = GithubActions("CI\ntest · web · build")
        registry = Docker("GHCR")
        vercel = Vercel("Vercel")
        with group("Compute Engine VM", VM):
            cd = Jenkins("Jenkins CD\ndeploy · smoke test")
        with group("GKE", CLUSTER):
            mlflow = icon("mlflow", "MLflow\n@production")
            helm = Helm("Helm")
            gke = GKE("hallucination-prod")

        engineer >> flow("7. push") >> github >> flow("8") >> ci >> flow("main") >> cd
        cd >> flow("11, 13") >> helm >> gke
        cd << flow("model") << mlflow
        ci >> flow("9. image") >> registry >> flow("10. pull", style="dashed") >> gke
        github >> flow("web", style="dashed") >> vercel


def provisioning():
    """Overview dashed paths (Terraform, Ansible) + Helm releases; minikube for local tests."""
    # compound: one "creates" arrow can end on the GCP box instead of two long curves
    with diagram("Infrastructure pipeline", "infrastructure-pipeline", compound="true"):
        engineer = User("AI engineer")
        terraform = Terraform("")  # the icon already reads "Terraform"
        ansible = Ansible("Ansible")
        helm = Helm("Helm charts")
        with group("GCP", CLUSTER):
            gke = GKE("GKE cluster")
            sql = SQL("Cloud SQL")
        with group("Local Environment", LOCAL):
            minikube = K8S("minikube\n(local test)")

        engineer >> flow("1. provision") >> terraform >> flow("2. bootstrap") >> ansible
        ansible >> flow("3. release") >> helm >> flow("backend,\nInferenceService") >> gke
        helm >> place() >> sql
        helm >> flow("same chart", style="dashed") >> minikube
        terraform >> flow("creates GKE + Cloud SQL", side=True, style="dashed", lhead="cluster_GCP") >> sql
        ansible >> flow("KServe, MLflow, monitoring", side=True, style="dashed") >> gke


def observability():
    """Overview step 16."""
    with diagram("Observability pipeline", "observability-pipeline"):
        clients = Users("Requests")
        with group("GKE", CLUSTER):
            nginx = Nginx("NGINX")
            api = FastAPI("Backend API")
        with group("Monitoring Stack", MONITOR):
            prom = Prometheus("Prometheus")
            jaeger = Jaeger("Jaeger")
            loki = Loki("Loki")
            drift = Python("Evidently\ndrift")
            grafana = Grafana("Grafana")

        clients >> nginx >> api
        api >> flow("metrics") >> prom
        api >> flow("16. traces") >> jaeger
        api >> flow("logs", side=True) >> loki
        api >> flow("audits", side=True) >> drift
        # 2 x 2 grid instead of one tall column: logs and drift sit one column to the right
        prom >> place() >> loki
        jaeger >> place() >> drift
        [prom, jaeger, loki, drift] >> grafana


DIAGRAMS = {
    "data-training-pipeline": data_training,
    "serving-pipeline": serving,
    "rag-evaluation-pipeline": rag_evaluation,
    "ci-cd-pipeline": ci_cd,
    "infrastructure-pipeline": provisioning,
    "observability-pipeline": observability,
}


if __name__ == "__main__":
    ensure_font()
    os.makedirs(OUT, exist_ok=True)
    for name in sys.argv[1:] or DIAGRAMS:
        DIAGRAMS[name]()
        rasterise(name)
        print(f"[OK] docs/images/architecture/{name}.png")
