# machine-learning/pipelines/generate_hard_medical.py
"""
generate_hard_medical.py
LLM-written hallucinations for ViMedHallu: Claude rewrites a gold ViMedAQA answer so it carries exactly
one intrinsic or extrinsic error. These are harder and more natural than the rule-based corruptions in
build_medical_hallu.py, so they form a separate "hard" split to report on.

Uses the Message Batches API (50% cheaper, async; most batches finish within an hour) in two steps:

  python machine-learning/pipelines/generate_hard_medical.py submit  --split test --n 600
  python machine-learning/pipelines/generate_hard_medical.py collect --split test

Needs ANTHROPIC_API_KEY. Cost-first defaults: claude-haiku-5-5, effort low
(~600 rows ≈ $0.06 at batch prices; check usage in the Console after the first run).
Output: data/processed/vimedhallu-hard/vimedhallu-hard-{split}.csv (ViHallu format + generator metadata).
"""

import argparse
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "params.yaml")) as _f:
    PARAMS = yaml.safe_load(_f)

SRC_DIR = "data/raw/vimedaqa"
OUT_DIR = "data/processed/vimedhallu-hard"
MODEL = os.getenv("GENERATOR_MODEL", PARAMS["generate_hard"]["model"])
EFFORT = os.getenv("GENERATOR_EFFORT", PARAMS["generate_hard"]["effort"])
SEED = PARAMS["medical"]["seed"]
TOPICS = {0: "body-part", 1: "disease", 2: "drug", 3: "medicine"}

INSTRUCTIONS = {
    "intrinsic": (
        "Rewrite the answer so it contradicts or distorts exactly one fact the passage states: a dose, duration, "
        "frequency, age group, before/after meals, should/should not, or which drug or condition. Use only "
        "entities and facts that appear in the passage; do not add new information."
    ),
    "extrinsic": (
        "Rewrite the answer so it keeps every fact from the passage correct but adds exactly one plausible "
        "medical claim the passage does not contain (an extra side effect, dose, indication, interaction or "
        "recommendation). The added claim must not contradict the passage."
    ),
}

PROMPT = """You are building a test set for a hallucination detector used on a Vietnamese medical chatbot. The detector will be scored on whether it catches the error you introduce, so the error must be subtle and the rewritten answer must read like a fluent, confident chatbot reply in Vietnamese, with the same tone and roughly the same length as the original.

<passage>
{context}
</passage>

<question>
{question}
</question>

<correct_answer>
{answer}
</correct_answer>

{instruction}

Return the rewritten answer and a short English note describing exactly what you changed."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "response": {"type": "string"},
            "change": {"type": "string"},
        },
        "required": ["response", "change"],
        "additionalProperties": False,
    },
}


def state_path(split: str) -> str:
    return f"{OUT_DIR}/batch-{split}.json"


def sample_rows(split: str, n: int) -> List[Dict[str, Any]]:
    df = pd.read_parquet(f"{SRC_DIR}/vimedaqa-{split}.parquet")
    df = df[df.context.str.len().between(50, 4000) & (df.answer.str.len() > 5)]
    df = df.sample(n=min(n, len(df)), random_state=SEED).reset_index(drop=True)
    return [
        {
            "custom_id": f"{r.question_idx}-{'intrinsic' if i % 2 == 0 else 'extrinsic'}",
            "label": "intrinsic" if i % 2 == 0 else "extrinsic",
            "context": r.context,
            "prompt": r.question,
            "gold": r.answer,
            "topic": TOPICS.get(int(r.topic), str(r.topic)),
            "source_url": r.article_url,
        }
        for i, r in enumerate(df.itertuples(index=False))
    ]


def build_request(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "custom_id": row["custom_id"],
        "params": {
            "model": MODEL,
            "max_tokens": 4000,
            "output_config": {"effort": EFFORT, "format": OUTPUT_SCHEMA},
            "messages": [{
                "role": "user",
                "content": PROMPT.format(
                    context=row["context"], question=row["prompt"], answer=row["gold"],
                    instruction=INSTRUCTIONS[row["label"]],
                ),
            }],
        },
    }


def accept(row: Dict[str, Any], response: str) -> Optional[str]:
    """Return a rejection reason, or None if the rewrite is usable."""
    resp = response.strip()
    if not resp:
        return "empty"
    if resp == row["gold"].strip():
        return "unchanged"
    if not 0.5 <= len(resp) / max(len(row["gold"]), 1) <= 3.0:
        return "length"
    return None


def submit(client, split: str, n: int) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = sample_rows(split, n)
    batch = client.messages.batches.create(requests=[build_request(r) for r in rows])
    with open(state_path(split), "w", encoding="utf-8") as f:
        json.dump({"batch_id": batch.id, "model": MODEL, "rows": rows}, f, ensure_ascii=False)
    print(f"[INFO] Submitted {len(rows)} requests as batch {batch.id}")
    return batch.id


def collect(client, split: str) -> Optional[pd.DataFrame]:
    with open(state_path(split), encoding="utf-8") as f:
        state = json.load(f)
    batch = client.messages.batches.retrieve(state["batch_id"])
    if batch.processing_status != "ended":
        print(f"[INFO] Batch {batch.id} is {batch.processing_status}; run collect again later")
        return None

    rows = {r["custom_id"]: r for r in state["rows"]}  # results arrive in any order
    kept, rejected = [], {}
    for result in client.messages.batches.results(batch.id):
        row = rows.get(result.custom_id)
        if row is None:
            continue
        if result.result.type != "succeeded":
            rejected[result.result.type] = rejected.get(result.result.type, 0) + 1
            continue
        msg = result.result.message
        if msg.stop_reason != "end_turn":
            rejected[msg.stop_reason] = rejected.get(msg.stop_reason, 0) + 1
            continue
        out = json.loads(next(b.text for b in msg.content if b.type == "text"))
        reason = accept(row, out["response"])
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        kept.append({
            "id": row["custom_id"], "context": row["context"], "prompt": row["prompt"],
            "response": out["response"].strip(), "label": row["label"], "topic": row["topic"],
            "corruption": f"llm_{row['label']}", "source_url": row["source_url"],
            "generator": state["model"], "change": out["change"],
            # Machine-written labels: spot-check before reporting numbers on this split
            "reviewed": False,
        })

    # Grounded rows from the same passages keep the split balanced against the two error types
    gold = [{"id": f"{r['custom_id'].rsplit('-', 1)[0]}-no", "context": r["context"], "prompt": r["prompt"],
             "response": r["gold"], "label": "no", "topic": r["topic"], "corruption": "none",
             "source_url": r["source_url"], "generator": "gold", "change": "", "reviewed": True}
            for r in state["rows"][: max(len(kept) // 2, 1)]]
    df = pd.DataFrame(kept + gold)
    path = f"{OUT_DIR}/vimedhallu-hard-{split}.csv"
    df.to_csv(path, index=False)
    print(f"[INFO] {len(kept)} rewrites kept, rejected: {rejected or 'none'} -> {path}")
    print(f"       labels: {df.label.value_counts().to_dict()}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["submit", "collect"])
    ap.add_argument("--split", default="test", choices=["train", "validation", "test"])
    ap.add_argument("--n", type=int, default=PARAMS["generate_hard"]["n"])
    args = ap.parse_args()

    import anthropic
    client = anthropic.Anthropic()
    if args.step == "submit":
        submit(client, args.split, args.n)
    else:
        collect(client, args.split)


if __name__ == "__main__":
    main()
