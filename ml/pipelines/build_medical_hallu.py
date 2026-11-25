# ml/pipelines/build_medical_hallu.py
"""
build_medical_hallu.py
Turn ViMedAQA (context, question, answer) into a labelled medical hallucination set
in the ViHallu format (id, context, prompt, response, label) - "ViMedHallu".

  no         the gold answer, grounded in the passage
  intrinsic  the gold answer edited to contradict the passage (number, negation, direction)
  extrinsic  the gold answer plus a real medical sentence from another article of the same topic

Rule-based so labels are exact and the build is reproducible. LLM-written corruptions
(more natural, harder) are added later by the Phase 2 agent.
Outputs: data/vimedhallu-dataset/vimedhallu-{train,validation,test}.csv
"""

import os
import random
import re
from typing import Callable, List, Optional

import pandas as pd

SRC_DIR = "data/vimedaqa-dataset"
OUT_DIR = "data/vimedhallu-dataset"
SPLITS = ["train", "validation", "test"]
SEED = 42
TOPICS = {0: "body-part", 1: "disease", 2: "drug", 3: "medicine"}

# Longest phrase first so "không nên" is matched before "nên"
NEGATION_FLIPS = [
    ("không nên", "nên"), ("không thể", "có thể"), ("không cần", "cần"), ("không được", "được"),
    ("nên", "không nên"), ("có thể", "không thể"), ("cần", "không cần"), ("được", "không được"),
]
DIRECTION_SWAPS = [("trước", "sau"), ("sau", "trước"), ("tăng", "giảm"), ("giảm", "tăng"),
                   ("cao", "thấp"), ("thấp", "cao"), ("nhiều", "ít"), ("ít", "nhiều")]
# "như sau:" introduces a list; flipping it gives nonsense, not a contradiction
SKIP_DIRECTION = re.compile(r"như sau|sau đây")
# Syllables inside compounds ("tăng cường", "thuyên giảm", "nâng cao", "sau đó") must not be swapped
COMPOUND_PREV = {"thuyên", "suy", "nâng", "gia", "đề", "cắt", "phía", "trở", "dần"}
COMPOUND_NEXT = {"cường", "cấp", "đó", "này", "đây", "lương", "su", "tuổi", "điểm", "nhất"}
# Dosages like "500mg" are fair game; digits inside names ("Vitamin D3", "B12", "Covid-19") are not
NUMBER = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)?")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _replace_first(text: str, pairs) -> Optional[str]:
    for old, new in pairs:
        m = re.search(rf"(?<!\w){re.escape(old)}(?!\w)", text, flags=re.IGNORECASE)
        if m:
            if m.group()[0].isupper():
                new = new[0].upper() + new[1:]
            return text[: m.start()] + new + text[m.end():]
    return None


def flip_negation(answer: str, rng: random.Random) -> Optional[str]:
    return _replace_first(answer, NEGATION_FLIPS)


def swap_direction(answer: str, rng: random.Random) -> Optional[str]:
    if SKIP_DIRECTION.search(answer):
        return None
    for old, new in DIRECTION_SWAPS:
        for m in re.finditer(rf"(?<!\w){old}(?!\w)", answer):
            prev = answer[: m.start()].split()[-1:] or [""]
            nxt = answer[m.end():].split()[:1] or [""]
            if prev[0].lower() in COMPOUND_PREV or nxt[0].lower().strip(",.") in COMPOUND_NEXT:
                continue
            return answer[: m.start()] + new + answer[m.end():]
    return None


def change_number(answer: str, rng: random.Random) -> Optional[str]:
    matches = list(NUMBER.finditer(answer))
    if not matches:
        return None
    m = rng.choice(matches)
    value = float(m.group().replace(",", "."))
    new = value * rng.choice([2, 3, 0.5]) if value > 1 else value + rng.choice([1, 2])
    new_str = str(int(new)) if float(new).is_integer() else f"{new:g}".replace(".", ",")
    if new_str == m.group():
        return None
    return answer[: m.start()] + new_str + answer[m.end():]


INTRINSIC_RULES: List[Callable[[str, random.Random], Optional[str]]] = [change_number, flip_negation, swap_direction]


def make_intrinsic(answer: str, rng: random.Random):
    rules = INTRINSIC_RULES[:]
    rng.shuffle(rules)
    for rule in rules:
        out = rule(answer, rng)
        if out and out != answer:
            return out, rule.__name__
    return None, None


def make_extrinsic(row, pool: pd.DataFrame, rng: random.Random):
    """Append one sentence from a different article on the same topic that the passage does not contain."""
    others = pool[(pool.topic == row.topic) & (pool.article_url != row.article_url)]
    for _ in range(20):
        other = others.iloc[rng.randrange(len(others))]
        sentences = [s for s in SENTENCE_END.split(other.context) if 30 <= len(s) <= 200]
        if not sentences:
            continue
        sentence = rng.choice(sentences).strip().lstrip("-•* ").strip()
        if sentence not in row.context:
            return f"{row.answer.rstrip()} {sentence}", "foreign_sentence"
    return None, None


def build_split(df: pd.DataFrame, rng: random.Random) -> pd.DataFrame:
    df = df.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    # A third of the rows become intrinsic, drawn from answers some rule can edit
    edits = {i: make_intrinsic(a, rng) for i, a in enumerate(df.answer)}
    editable = [i for i, (resp, _) in edits.items() if resp]
    intrinsic = set(rng.sample(editable, min(len(editable), len(df) // 3)))

    out, rest = [], 0
    for i, row in enumerate(df.itertuples(index=False)):
        if i in intrinsic:
            target, (response, corruption) = "intrinsic", edits[i]
        else:
            target = "no" if rest % 2 == 0 else "extrinsic"
            rest += 1
            response, corruption = row.answer, "none"
            if target == "extrinsic":
                response, corruption = make_extrinsic(row, df, rng)
                if not response:
                    target, response, corruption = "no", row.answer, "none"

        out.append({
            "id": f"{row.question_idx}-{target}",
            "context": row.context,
            "prompt": row.question,
            "response": response,
            "label": target,
            "topic": TOPICS.get(int(row.topic), str(row.topic)),
            "corruption": corruption,
            "source_url": row.article_url,
        })
    return pd.DataFrame(out)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = random.Random(SEED)
    for split in SPLITS:
        src = pd.read_parquet(f"{SRC_DIR}/vimedaqa-{split}.parquet")
        src = src[src.context.str.len().between(50, 4000) & (src.answer.str.len() > 5)]
        out = build_split(src, rng)
        path = f"{OUT_DIR}/vimedhallu-{split}.csv"
        out.to_csv(path, index=False)
        print(f"[INFO] {split}: {len(out)} rows -> {path}")
        print("       labels:", out.label.value_counts().to_dict())
        print("       corruptions:", out.corruption.value_counts().to_dict())


if __name__ == "__main__":
    main()
