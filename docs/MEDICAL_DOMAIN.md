# Medical Domain: Data and Evaluation Plan

**Decision (2026-11-25):** the platform stays domain-agnostic, but **data, benchmarks, fine-tuning and the demo focus on Vietnamese healthcare.**

## Why narrow the domain

- The detector was trained on ViHallu, which is encyclopedic, Wikipedia-style text (~800-character passages). How it behaves on medical text is unknown; until it is measured, "evaluates any RAG system" is an unsupported claim.
- In a single domain we can build a labelled test set, report a domain F1, fine-tune, and demo against a real RAG.
- Medical hallucinations have clear, high-stakes shapes: wrong dosage, a flipped contraindication ("nên" ↔ "không nên"), before/after meals, invented treatments.

**Safety scope:** ViAI-QA evaluates RAG answers. It does not give medical advice. Only public, non-patient text is used: health articles, drug leaflets, published research datasets. No medical records.

## Data sources

| Dataset | What it has | Use | License |
|---|---|---|---|
| **ViMedAQA** (Tran et al., ACL SRW 2024) · [HF](https://huggingface.co/datasets/tmnam20/ViMedAQA) · [paper](https://aclanthology.org/2024.acl-srw.31/) | 39,881 / 2,215 / 2,217 (train/val/test) `context, question, answer`; topics body-part, disease, drug, medicine; source article URL | **Base of ViMedHallu** | **None declared** on HF or GitHub. Academic use with citation; ask the authors before any other use |
| ViHealthQA (SPBERTQA, KSEM 2022) · [HF](https://huggingface.co/datasets/tarudesu/ViHealthQA) | 10,015 question / doctor-answer passages (Vinmec, VnExpress) | Candidate for retrieval / real-question demo | None declared; the card warns it may contain crawled personal information, so **not used** for now |
| vietnamese-medical-qa · [HF](https://huggingface.co/datasets/hungnm/vietnamese-medical-qa) | 9,335 QA pairs (edoctor, Vinmec), no passages | Candidate questions for the Phase 6 demo | Apache-2.0 |
| ViHERMES · [arXiv 2602.07361](https://arxiv.org/pdf/2602.07361) | Multi-hop QA over Vietnamese healthcare regulations | Possible harder RAG benchmark later | Not checked |
| ViHallu (DSC 2025) | 7,000 general-domain triples | **Kept** as the general benchmark (checks that domain fine-tuning does not break general ability) | Competition data |

## ViMedHallu (built here)

`ml/pipelines/build_medical_hallu.py` is a DVC stage (`build_medical`). It reads `data/vimedaqa-dataset/` and writes `data/vimedhallu-dataset/vimedhallu-{train,validation,test}.csv` in the ViHallu format, plus `topic`, `corruption` and `source_url` columns.

| Label | How it is made | Share |
|---|---|---|
| `no` | Gold ViMedAQA answer, grounded in the passage | 1/3 |
| `intrinsic` | Gold answer with one edit that contradicts the passage. `change_number` changes a dose, duration or percentage (digits inside names such as *Vitamin D3*, *B12*, *Covid-19* are left alone). `flip_negation` swaps *nên ↔ không nên*, *có thể ↔ không thể*, *cần*, *được*. `swap_direction` swaps *trước ↔ sau*, *tăng ↔ giảm*, *cao ↔ thấp*, *nhiều ↔ ít*, but skips compounds such as *tăng cường*, *thuyên giảm*, *nâng cao*, *sau đó*, and the phrase *như sau* | 1/3 (rules cover about 50% of answers) |
| `extrinsic` | Gold answer plus a real sentence from **another article on the same topic** that the passage does not contain | 1/3 |

Sizes: train 39,495 · validation 2,194 · test 2,195, with the three labels exactly balanced.

**Quality checks:**
- The generated edits were read by hand. That review found two bugs, both fixed and covered by tests: compound words were being broken (*tăng cường* → "giảm cường") and digits inside drug names were being changed.
- `tests/unit/test_build_medical_hallu.py` (11 tests).

**Known limitation:** the corruptions are rule-based and therefore easier and more regular than real LLM hallucinations. A model trained on them can learn the rules instead of the task. Mitigations:
1. Report scores per corruption type, not only overall.
2. Add LLM-written corruptions (Phase 2 agent) as a separate, harder test split.
3. Never claim results on synthetic data alone.

## Baseline and fine-tuning

`ml/pipelines/evaluate_detector.py --data <csv> [--limit N] --out reports/<name>.json` scores the **serving** LightGBM path. It uses the same `HallucinationPipeline` feature code as production and reports:
- Macro-F1, both overall and per topic
- accuracy per corruption type
- an LLM-only Macro-F1, for reference

LLM probabilities are cached in `features/<data>_llm_probs.csv` so fine-tuning can reuse them. The code path is verified with a stubbed LLM.

**Blocked:** the baseline needs Qwen2.5-1.5B-Instruct (3 GB) for the three `prob_*` features. HuggingFace currently downloads at about 20 KB/s from this machine, which would take roughly 40 hours. Even with the weights present, computing the LLM feature takes about 1–3 s per row on CPU, so roughly 20+ hours for the 39k training rows. Options:

1. Run `evaluate_detector.py` on a GPU notebook such as Kaggle or Colab (fast network; minutes per thousand rows), then bring back the cached `*_llm_probs.csv`.
2. Copy the Qwen weights from a faster network into `$HF_HOME`.
3. Train a medical model variant that does not need the LLM feature (PhoBERT plus cheap grounding features). This is faster, but it changes the model design.

## Next steps

1. Get the baseline Macro-F1 on ViMedHallu test, plus the same script on in-domain ViHallu rows (this also measures the Vistral-trained, Qwen-served gap).
2. Fine-tune LightGBM on ViHallu + ViMedHallu train (existing DVC `train` stage) and compare on both test sets.
3. LLM-written hard split (Phase 2), then the medical RAG demo (Phase 6).
