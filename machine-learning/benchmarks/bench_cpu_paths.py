# machine-learning/benchmarks/bench_cpu_paths.py
"""
R0 of docs/GO_RUST_MIGRATION_PLAN.md: time the CPU-side paths that are candidates for Rust, the same
way every time, so the plan's numbers (and any Rust speed-up) can be reproduced.

    python machine-learning/benchmarks/bench_cpu_paths.py                 # real data if present (dvc pull)
    python machine-learning/benchmarks/bench_cpu_paths.py --synthetic     # no data needed (CI)
    python machine-learning/benchmarks/bench_cpu_paths.py --json out.json

Paths measured (no model weights needed):
  build_feature_matrix   vihallu_features, 7,000 rows x 778
  simple_features        its Python per-row part
  split_claims           RAG evaluator claim splitter
  tfidf_build / _query   rag-demo TfidfRetriever on 17,835 passages (the R1 target)
Synthetic data matches the real mean lengths (measured 2026-11-27): context 830 chars / 180 words,
prompt 121 / 27, response 181 / 39, passage 501 / 110. Vietnamese syllables with diacritics, so the
character n-grams look like the real ones.
"""
import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in ("machine-learning", "applications/api", "applications/rag-demo"):
    sys.path.insert(0, os.path.join(ROOT, p))

import numpy as np  # noqa: E402

import vihallu_features as vf  # noqa: E402

SYLLABLES = ("thuốc uống liều dùng bệnh nhân điều trị viêm gan tiểu đường huyết áp ngày lần sau ăn "
             "trước khi ngủ trẻ em người lớn tác dụng phụ chống chỉ định bác sĩ dược sĩ kháng sinh vitamin "
             "đau đầu sốt ho tiêm truyền bảo quản nhiệt độ phòng tránh ánh sáng của và các có không được").split()


def synthetic_text(rng: random.Random, words: int) -> str:
    n = max(1, int(rng.gauss(words, words / 4)))
    out = " ".join(rng.choice(SYLLABLES) for _ in range(n))
    return out[0].upper() + out[1:] + "."


def load_rows(synthetic: bool):
    path = os.path.join(ROOT, "data/raw/vihallu/vihallu-train.csv")
    if not synthetic and os.path.exists(path):
        import pandas as pd
        df = pd.read_csv(path)
        return list(df.context), list(df.prompt), list(df.response), "vihallu-train.csv"
    rng = random.Random(0)
    n = 7000
    return ([synthetic_text(rng, 180) for _ in range(n)], [synthetic_text(rng, 27) for _ in range(n)],
            [synthetic_text(rng, 39) for _ in range(n)], "synthetic")


def load_passages(synthetic: bool):
    files = [os.path.join(ROOT, f"data/raw/vimedaqa/vimedaqa-{s}.parquet") for s in ("train", "test")]
    if not synthetic and all(os.path.exists(f) for f in files):
        import pandas as pd
        return pd.concat([pd.read_parquet(f) for f in files]).context.drop_duplicates().tolist(), "vimedaqa"
    rng = random.Random(1)
    return [synthetic_text(rng, 110) for _ in range(17835)], "synthetic"


def timeit(fn, repeat: int) -> dict:
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return {"median_ms": round(statistics.median(times) * 1000, 2), "min_ms": round(min(times) * 1000, 2), "runs": repeat}


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="generated data with the real mean lengths")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--json", help="also write the results here")
    args = ap.parse_args()

    from backend.app.evaluation.rag import split_claims
    from rag_demo.retriever import TfidfRetriever

    contexts, prompts, responses, rows_src = load_rows(args.synthetic)
    n = len(contexts)
    rng = np.random.default_rng(0)
    emb = rng.normal(size=(n, vf.EMBEDDING_DIM))
    probs = np.full((n, len(vf.LLM_PROB_COLUMNS)), 1 / len(vf.LLM_PROB_COLUMNS))
    centroid = emb.mean(axis=0)

    passages, pass_src = load_passages(args.synthetic)
    docs = [SimpleNamespace(text=t, title="", source_url="") for t in passages]
    query = "Uống thuốc Comiaryl đúng cách như thế nào?"
    retriever = {}

    results = {
        "build_feature_matrix": timeit(lambda: vf.build_feature_matrix(emb, contexts, prompts, responses, probs, centroid), args.repeat),
        "simple_features": timeit(lambda: [vf.simple_features(c, p, r) for c, p, r in zip(contexts, prompts, responses)], args.repeat),
        "split_claims": timeit(lambda: [split_claims(r) for r in responses], args.repeat),
        "tfidf_build": timeit(lambda: retriever.__setitem__("r", TfidfRetriever(docs)), args.repeat),
    }
    results["tfidf_query"] = timeit(lambda: retriever["r"].search(query, k=3), max(args.repeat, 20))
    report = {
        "data": {"rows": n, "rows_source": rows_src, "passages": len(passages), "passages_source": pass_src},
        "machine": {"python": platform.python_version(), "cpu": platform.processor() or platform.machine(), "cpus": os.cpu_count()},
        "results": results,
    }
    width = max(len(k) for k in results)
    print(f"data: {n} rows ({rows_src}), {len(passages)} passages ({pass_src}); python {report['machine']['python']}, {os.cpu_count()} cpus")
    for name, r in results.items():
        print(f"  {name:<{width}}  median {r['median_ms']:>9.2f} ms   min {r['min_ms']:>9.2f} ms   ({r['runs']} runs)")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
    return report


if __name__ == "__main__":
    main()
