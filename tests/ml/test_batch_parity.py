# tests/ml/test_batch_parity.py
"""
Batched detector == one triple at a time. Tiny randomly initialised models of the real classes
(BERT for PhoBERT and NLI, Qwen2 for the LLM) stand in for the weights, so padding, left padding and
position ids are exercised the way the real models see them, with nothing to download.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")

import vihallu_features as vf  # noqa: E402

from backend.app.inference.inference_model import HallucinationPipeline  # noqa: E402

CONTEXTS = ["Hà Nội là thủ đô của Việt Nam.",
            "Paracetamol hạ sốt, người lớn dùng 500mg mỗi lần, tối đa 4g mỗi ngày.",
            ""]
PROMPT = "Câu hỏi về thuốc và địa lý?"
CLAIMS = ["Thủ đô là Hà Nội.", "Paracetamol dùng tối đa 8g mỗi ngày.", "Paris là thủ đô.", ""]


def char_tokenizer(texts, pair_template):
    from tokenizers import Regex, Tokenizer, models, pre_tokenizers, processors

    specials = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"]
    chars = sorted(set("".join(texts)) | set("0123456789"))
    vocab = {t: i for i, t in enumerate(specials + chars)}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Split(Regex("."), behavior="isolated")
    if pair_template:
        tok.post_processor = processors.TemplateProcessing(
            single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B [SEP]",
            special_tokens=[("[CLS]", vocab["[CLS]"]), ("[SEP]", vocab["[SEP]"])])
    fast = transformers.PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="[UNK]", pad_token="[PAD]",
                                                cls_token="[CLS]", sep_token="[SEP]")
    fast.chat_template = "{% for m in messages %}{{ m['role'] }}: {{ m['content'] }}\n{% endfor %}assistant:"
    return fast


class FakeNER:
    """Capitalised words are entities; takes one text or a list, like a transformers pipeline."""

    def __call__(self, texts, **_):
        one = lambda t: [{"word": w.strip(".,")} for w in t.split() if w[:1].isupper()]
        return one(texts) if isinstance(texts, str) else [one(t) for t in texts]


class FakeBooster:
    def predict(self, x):
        z = np.stack([x[:, 768], x[:, 774], x[:, 776]], axis=1)  # row-wise: each row scores on its own
        e = np.exp(np.tanh(z / 100.0))
        return e / e.sum(axis=1, keepdims=True)


@pytest.fixture(scope="module")
def pipeline():
    torch.manual_seed(0)
    pipe = HallucinationPipeline()
    texts = CONTEXTS + CLAIMS + [PROMPT]
    bert_tok = char_tokenizer(texts, pair_template=True)
    pipe.embed_tokenizer = pipe.nli_tokenizer = bert_tok
    bert = dict(vocab_size=bert_tok.vocab_size, num_hidden_layers=1, num_attention_heads=4, intermediate_size=64,
                max_position_embeddings=600)
    pipe.embed_model = transformers.BertModel(transformers.BertConfig(hidden_size=vf.EMBEDDING_DIM, **bert)).eval()
    pipe.nli_model = transformers.BertForSequenceClassification(transformers.BertConfig(
        hidden_size=32, num_labels=3, id2label={0: "ENTAILMENT", 1: "NEUTRAL", 2: "CONTRADICTION"}, **bert)).eval()
    pipe.ner_pipeline = FakeNER()

    # the LLM vocabulary must cover the rendered chat prompt, so render it with a first tokenizer
    pipe.vistral_tokenizer = char_tokenizer(texts, pair_template=False)
    rendered = [pipe._vistral_text(c, PROMPT, r) for c in CONTEXTS for r in CLAIMS]
    pipe.vistral_tokenizer = char_tokenizer(rendered, pair_template=False)
    pipe.vistral_model = transformers.Qwen2ForCausalLM(transformers.Qwen2Config(
        vocab_size=pipe.vistral_tokenizer.vocab_size, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
        num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=4096)).eval()

    pipe.lgbm_models = [FakeBooster()]
    pipe.embed_centroid = np.random.default_rng(0).normal(size=(1, vf.EMBEDDING_DIM))
    pipe.feature_dim = vf.FEATURE_DIM
    pipe.device_cpu = torch.device("cpu")
    pipe.disabled, pipe._is_loaded = False, True
    return pipe


def test_batched_signals_equal_one_at_a_time(pipeline):
    triples = [(c, PROMPT, r) for r in CLAIMS for c in CONTEXTS]   # 12 triples, mixed lengths, blanks
    pipeline.batch_size = 1
    alone = pipeline.extract_signals_batch(triples)
    pipeline.batch_size = 5                                       # several padded batches
    batched = pipeline.extract_signals_batch(triples)

    for a, b in zip(alone, batched):
        np.testing.assert_allclose(b["features"], a["features"], rtol=1e-4, atol=1e-5)
        for key in ("p_entailment", "p_neutral", "p_contradiction", "entity_overlap_ratio", "vistral_extrinsic_prob"):
            assert b[key] == pytest.approx(a[key], abs=1e-5), key
        assert b["new_entity_count"] == a["new_entity_count"]


def test_predict_batch_equals_predict(pipeline):
    pipeline.batch_size = 4
    triples = [(c, PROMPT, r) for r in CLAIMS for c in CONTEXTS]
    batched = pipeline.predict_batch(triples)
    single = [pipeline.predict(*t) for t in triples]
    assert [b["label"] for b in batched] == [s["label"] for s in single]
    np.testing.assert_allclose([b["confidence"] for b in batched], [s["confidence"] for s in single], atol=1e-5)


def test_each_distinct_text_goes_through_ner_once(pipeline):
    calls = []

    class CountingNER(FakeNER):
        def __call__(self, texts, **kw):
            calls.append(list(texts) if not isinstance(texts, str) else [texts])
            return super().__call__(texts, **kw)

    pipeline.ner_pipeline = CountingNER()
    try:
        pipeline._ner_features(CONTEXTS[:2] * 5, CLAIMS[:2] * 5)
    finally:
        pipeline.ner_pipeline = FakeNER()
    assert len(calls) == 1 and sorted(calls[0]) == sorted(CONTEXTS[:2] + CLAIMS[:2])
