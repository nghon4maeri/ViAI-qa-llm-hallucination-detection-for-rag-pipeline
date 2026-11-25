# ml/pipelines/evaluate_detector.py
"""
evaluate_detector.py
Score the serving LightGBM path on any labelled ViHallu-format CSV
(id, context, prompt, response, label) and report Macro-F1 overall and per slice.

Uses HallucinationPipeline's own feature code, so the number is what production would get.
LLM probabilities are cached next to the features (one Qwen forward pass per row is the slow part)
so fine-tuning can reuse them.

  python ml/pipelines/evaluate_detector.py --data data/vimedhallu-dataset/vimedhallu-test.csv \
      --limit 600 --out reports/medical_baseline.json
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, f1_score

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "api")]  # ml/ and the `backend` package

LABELS = ["extrinsic", "no", "intrinsic"]  # class ids 0, 1, 2 (artifacts/models/feature_schema.json)


def load_pipeline():
    import torch
    from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer
    from backend.app.inference.inference_model import VISTRAL_MODEL_NAME, HallucinationPipeline

    p = HallucinationPipeline()
    p.device_cpu = torch.device("cpu")
    # Only what the LightGBM path needs; NLI/NER feed the guardrails, not the model
    p.embed_tokenizer = AutoTokenizer.from_pretrained(os.getenv("PHOBERT_TOKENIZER", "artifacts/models/phobert_tokenizer"))
    p.embed_model = AutoModel.from_pretrained(os.getenv("PHOBERT_MODEL", "artifacts/models/phobert")).eval()
    p.vistral_tokenizer = AutoTokenizer.from_pretrained(VISTRAL_MODEL_NAME)
    p.vistral_model = AutoModelForCausalLM.from_pretrained(
        VISTRAL_MODEL_NAME, torch_dtype=torch.float32, device_map="cpu", low_cpu_mem_usage=True
    ).eval()
    p._load_lgbm_ensemble()
    return p


def llm_probs(pipeline, df: pd.DataFrame, cache_path: str) -> pd.DataFrame:
    """[prob_no, prob_extrinsic, prob_intrinsic] per row, same columns as the Vistral training file."""
    cache = pd.read_csv(cache_path).set_index("id") if os.path.exists(cache_path) else pd.DataFrame()
    rows = []
    for i, r in enumerate(df.itertuples(index=False), start=1):
        if r.id in cache.index:
            rows.append(cache.loc[r.id].to_dict() | {"id": r.id})
            continue
        ext, intr, no = pipeline._get_vistral_probs(r.context, r.prompt, r.response)[0]
        rows.append({"id": r.id, "prob_no": no, "prob_extrinsic": ext, "prob_intrinsic": intr})
        if i % 25 == 0:
            pd.DataFrame(rows).to_csv(cache_path, index=False)
            print(f"  LLM probs {i}/{len(df)}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(cache_path, index=False)
    return out.set_index("id").loc[df.id]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--limit", type=int, default=0, help="Stratified subsample size (0 = all rows)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.data).fillna("")
    if args.limit and args.limit < len(df):
        per_label = args.limit // df.label.nunique()
        df = df.groupby("label", group_keys=False).apply(lambda g: g.sample(min(len(g), per_label), random_state=42))
    df = df.reset_index(drop=True)
    print(f"[INFO] {len(df)} rows from {args.data}: {df.label.value_counts().to_dict()}")

    pipeline = load_pipeline()
    base = os.path.splitext(os.path.basename(args.data))[0]
    os.makedirs("artifacts/features", exist_ok=True)
    probs = llm_probs(pipeline, df, f"artifacts/features/{base}_llm_probs.csv")

    X = []
    for r, (_, pr) in zip(df.itertuples(index=False), probs.iterrows()):
        c, p, resp = str(r.context).strip(), str(r.prompt).strip(), str(r.response).strip()
        f_embed = pipeline._extract_embeddings([f"{c} {p} {resp}"])
        X.append(pipeline._build_model_features(
            f_embed, c, p, resp, np.array([[pr.prob_no, pr.prob_extrinsic, pr.prob_intrinsic]])
        )[0])
    pred = pipeline._predict_ensemble(np.vstack(X)).argmax(axis=1)
    df["pred"] = [LABELS[i] for i in pred]
    llm_pred = probs[["prob_extrinsic", "prob_no", "prob_intrinsic"]].values.argmax(axis=1)
    df["llm_pred"] = [LABELS[i] for i in llm_pred]

    def macro(sub, col="pred"):
        return round(float(f1_score(sub.label, sub[col], labels=LABELS, average="macro", zero_division=0)), 4)

    report = {
        "data": args.data,
        "rows": len(df),
        "macro_f1": macro(df),
        "llm_only_macro_f1": macro(df, "llm_pred"),
        "per_label": classification_report(df.label, df.pred, labels=LABELS, output_dict=True, zero_division=0),
        # Recall within each slice: does the detector catch this kind of corruption?
        "accuracy_by_corruption": {k: round(float((g.pred == g.label).mean()), 4) for k, g in df.groupby("corruption")}
        if "corruption" in df else None,
        "macro_f1_by_topic": {k: macro(g) for k, g in df.groupby("topic")} if "topic" in df else None,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    df.to_csv(os.path.splitext(args.out)[0] + "_predictions.csv", index=False)
    print(json.dumps({k: report[k] for k in ("rows", "macro_f1", "llm_only_macro_f1", "accuracy_by_corruption", "macro_f1_by_topic")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
