import os
import sys
import numpy as np
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModel
from tqdm import tqdm

# Shared feature builder; works installed (pip install ./machine-learning) or straight from the checkout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vihallu_features as vf  # noqa: E402

PHOBERT_MODEL = os.getenv("PHOBERT_MODEL", "vinai/phobert-base")
PHOBERT_TOKENIZER = os.getenv("PHOBERT_TOKENIZER", PHOBERT_MODEL)
DEVICE = "cpu"
BATCH_SIZE = 8

DATA_PATH = "data/raw/vihallu/vihallu-train.csv"
OUT_DIR = "artifacts/features"
OUT_FILE = f"{OUT_DIR}/phobert_embeddings.npy"

os.makedirs(OUT_DIR, exist_ok=True)

def load_texts():
    df = pd.read_csv(DATA_PATH)
    return [vf.embedding_text(c, p, r) for c, p, r in zip(df["context"], df["prompt"], df["response"])]

def main():
    texts = load_texts()

    tokenizer = AutoTokenizer.from_pretrained(PHOBERT_TOKENIZER)
    model = AutoModel.from_pretrained(PHOBERT_MODEL).to(DEVICE).eval()

    all_embs = []

    for i in tqdm(range(0, len(texts), BATCH_SIZE)):
        batch = texts[i:i+BATCH_SIZE]

        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=vf.MAX_LENGTH,
            return_tensors="pt"
        )

        with torch.no_grad():
            outputs = model(**inputs)
            # Masked mean: plain mean(dim=1) averaged padding tokens into short texts
            emb = vf.masked_mean(outputs.last_hidden_state, inputs["attention_mask"])

        all_embs.append(emb.cpu().numpy())

        del inputs, outputs, emb
        torch.cuda.empty_cache()

    X = np.vstack(all_embs)
    np.save(OUT_FILE, X)

    print(f"Saved embeddings to {OUT_FILE}, shape={X.shape}")

if __name__ == "__main__":
    main()