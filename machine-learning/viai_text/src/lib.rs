//! Rust hot loops for ViAI-QA (docs/GO_RUST_MIGRATION_PLAN.md, R1).
//!
//! [`CharTfidf`] is a character n-gram TF-IDF index that reproduces scikit-learn's
//! `TfidfVectorizer(analyzer="char_wb", ngram_range=(min_n, max_n), sublinear_tf=True)` with its
//! defaults (lowercase, smooth idf, L2 norm), plus cosine top-k search. The rag-demo retriever uses
//! it behind the same Python interface; scikit-learn stays as the fallback.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};

/// Small multiplicative hasher for the packed n-gram keys (u128); SipHash is the bottleneck otherwise.
#[derive(Default)]
struct FxHasher(u64);

const SEED: u64 = 0x51_7c_c1_b7_27_22_0a_95;

impl Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.write_u64(b as u64);
        }
    }
    fn write_u64(&mut self, x: u64) {
        self.0 = (self.0.rotate_left(5) ^ x).wrapping_mul(SEED);
    }
    fn write_u128(&mut self, x: u128) {
        self.write_u64(x as u64);
        self.write_u64((x >> 64) as u64);
    }
}

type FxMap<K, V> = HashMap<K, V, BuildHasherDefault<FxHasher>>;

/// One n-gram (up to 4 chars) packed into a u128: 21 bits per char (all of Unicode) and the length,
/// so n-grams of different lengths never collide.
type Key = u128;

pub const MAX_N: usize = 4;

/// Calls `emit` for every n-gram of `text`, in exactly the order and multiplicity of scikit-learn's
/// `_char_wb_ngrams` after its default preprocessing (lowercase):
/// each whitespace-separated word is padded with one space on both sides; for n in min_n..=max_n a
/// window slides over it; a word no longer than n is emitted once and stops the larger n.
pub fn char_wb_ngrams(text: &str, min_n: usize, max_n: usize, mut emit: impl FnMut(Key)) {
    let lower = text.to_lowercase();
    let mut w: Vec<char> = Vec::with_capacity(32);
    for word in lower.split_whitespace() {
        w.clear();
        w.push(' ');
        w.extend(word.chars());
        w.push(' ');
        let len = w.len();
        for n in min_n..=max_n {
            let mut offset = 0;
            emit(pack(&w[..n.min(len)]));
            while offset + n < len {
                offset += 1;
                emit(pack(&w[offset..offset + n]));
            }
            if offset == 0 {
                break; // a short word (len <= n) is counted only once
            }
        }
    }
}

fn pack(chars: &[char]) -> Key {
    let mut k: Key = chars.len() as Key;
    for &c in chars {
        k = (k << 21) | c as Key;
    }
    k
}

/// Character n-gram TF-IDF index with an inverted index for cosine search.
pub struct CharTfidf {
    min_n: usize,
    max_n: usize,
    vocab: FxMap<Key, u32>,
    idf: Vec<f64>,
    postings: Vec<Vec<(u32, f32)>>, // term -> (document, L2-normalised tf-idf weight)
    n_docs: usize,
}

impl CharTfidf {
    pub fn fit(texts: &[&str], min_n: usize, max_n: usize) -> Result<Self, String> {
        if min_n == 0 || min_n > max_n || max_n > MAX_N {
            return Err(format!("ngram range must satisfy 1 <= min_n <= max_n <= {MAX_N}, got ({min_n}, {max_n})"));
        }
        if texts.is_empty() {
            return Err("cannot fit on an empty corpus".into());
        }
        let mut vocab: FxMap<Key, u32> = FxMap::default();
        let mut df: Vec<u32> = Vec::new();
        let mut docs: Vec<Vec<(u32, u32)>> = Vec::with_capacity(texts.len()); // per doc: (term, count)
        let mut counts: FxMap<u32, u32> = FxMap::default();

        for text in texts {
            counts.clear();
            char_wb_ngrams(text, min_n, max_n, |key| {
                let next = vocab.len() as u32;
                let term = *vocab.entry(key).or_insert(next);
                *counts.entry(term).or_insert(0) += 1;
            });
            df.resize(vocab.len(), 0);
            let mut doc: Vec<(u32, u32)> = counts.iter().map(|(&t, &c)| (t, c)).collect();
            doc.sort_unstable();
            for &(t, _) in &doc {
                df[t as usize] += 1;
            }
            docs.push(doc);
        }

        // smooth idf: ln((1 + n) / (1 + df)) + 1
        let n = texts.len() as f64;
        let idf: Vec<f64> = df.iter().map(|&d| ((1.0 + n) / (1.0 + d as f64)).ln() + 1.0).collect();

        let mut postings: Vec<Vec<(u32, f32)>> = vec![Vec::new(); vocab.len()];
        for (doc_id, doc) in docs.iter().enumerate() {
            let weights: Vec<f64> = doc.iter().map(|&(t, c)| (1.0 + (c as f64).ln()) * idf[t as usize]).collect();
            let norm = weights.iter().map(|w| w * w).sum::<f64>().sqrt();
            if norm == 0.0 {
                continue; // a document with no n-grams (empty or whitespace) is never returned
            }
            for (&(t, _), w) in doc.iter().zip(weights) {
                postings[t as usize].push((doc_id as u32, (w / norm) as f32));
            }
        }
        Ok(Self { min_n, max_n, vocab, idf, postings, n_docs: texts.len() })
    }

    pub fn n_docs(&self) -> usize {
        self.n_docs
    }

    pub fn n_features(&self) -> usize {
        self.vocab.len()
    }

    /// Cosine score of `query` against every document (scikit-learn: transform + dot product).
    /// N-grams unseen during fit are ignored, as `transform` does.
    pub fn scores(&self, query: &str) -> Vec<f64> {
        let mut counts: FxMap<u32, u32> = FxMap::default();
        char_wb_ngrams(query, self.min_n, self.max_n, |key| {
            if let Some(&t) = self.vocab.get(&key) {
                *counts.entry(t).or_insert(0) += 1;
            }
        });
        let q: Vec<(u32, f64)> = counts.iter().map(|(&t, &c)| (t, (1.0 + (c as f64).ln()) * self.idf[t as usize])).collect();
        let norm = q.iter().map(|(_, w)| w * w).sum::<f64>().sqrt();
        let mut scores = vec![0.0f64; self.n_docs];
        if norm == 0.0 {
            return scores;
        }
        for (t, w) in q {
            let qw = w / norm;
            for &(d, dw) in &self.postings[t as usize] {
                scores[d as usize] += qw * dw as f64;
            }
        }
        scores
    }

    /// Top `k` documents by cosine score, highest first; documents scoring 0 are left out.
    pub fn search(&self, query: &str, k: usize) -> Vec<(usize, f64)> {
        let scores = self.scores(query);
        let mut hits: Vec<(usize, f64)> = scores.into_iter().enumerate().filter(|&(_, s)| s > 0.0).collect();
        let by_score = |a: &(usize, f64), b: &(usize, f64)| b.1.total_cmp(&a.1).then(b.0.cmp(&a.0));
        if hits.len() > k {
            hits.select_nth_unstable_by(k, by_score);
            hits.truncate(k);
        }
        hits.sort_unstable_by(by_score);
        hits
    }
}

#[cfg(feature = "python")]
mod python {
    use super::CharTfidf;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    /// Character n-gram TF-IDF index, identical to scikit-learn's
    /// TfidfVectorizer(analyzer="char_wb", ngram_range=(min_n, max_n), sublinear_tf=True).
    #[pyclass(name = "CharTfidfIndex", module = "viai_text", frozen)]
    struct CharTfidfIndex {
        inner: CharTfidf,
    }

    #[pymethods]
    impl CharTfidfIndex {
        #[new]
        #[pyo3(signature = (texts, min_n = 2, max_n = 4))]
        fn new(py: Python<'_>, texts: Vec<String>, min_n: usize, max_n: usize) -> PyResult<Self> {
            let inner = py
                .detach(|| {
                    let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
                    CharTfidf::fit(&refs, min_n, max_n)
                })
                .map_err(PyValueError::new_err)?;
            Ok(Self { inner })
        }

        /// [(document index, cosine score), ...] for the top k documents, highest first.
        #[pyo3(signature = (query, k = 3))]
        fn search(&self, py: Python<'_>, query: &str, k: usize) -> Vec<(usize, f64)> {
            py.detach(|| self.inner.search(query, k))
        }

        /// Cosine score of the query against every document, in corpus order.
        fn scores(&self, py: Python<'_>, query: &str) -> Vec<f64> {
            py.detach(|| self.inner.scores(query))
        }

        #[getter]
        fn n_docs(&self) -> usize {
            self.inner.n_docs()
        }

        #[getter]
        fn n_features(&self) -> usize {
            self.inner.n_features()
        }
    }

    #[pymodule]
    fn viai_text(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<CharTfidfIndex>()?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grams(text: &str) -> Vec<String> {
        let mut out = Vec::new();
        char_wb_ngrams(text, 2, 4, |k| out.push(unpack(k)));
        out
    }

    fn unpack(mut k: Key) -> String {
        // 21 bits per char, length (<= MAX_N) in the top bits; test texts have no chars <= 4
        let mut chars = Vec::new();
        while k > MAX_N as Key {
            chars.push(char::from_u32((k & 0x1F_FFFF) as u32).unwrap());
            k >>= 21;
        }
        chars.reverse();
        chars.into_iter().collect()
    }

    #[test]
    fn ngrams_match_scikit_learn_char_wb() {
        // TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).build_analyzer()("Ho thuốc A")
        let want = [" h", "ho", "o ", " ho", "ho ", " ho ", " t", "th", "hu", "uố", "ốc", "c ", " th", "thu", "huố", "uốc", "ốc ",
                    " thu", "thuố", "huốc", "uốc ", " a", "a ", " a "];
        assert_eq!(grams("Ho thuốc A"), want);
    }

    #[test]
    fn short_word_is_counted_once_and_stops_larger_n() {
        // " a " has length 3: n=2 slides, n=3 is the whole word once, n=4 is not reached
        assert_eq!(grams("a"), [" a", "a ", " a "]);
    }

    #[test]
    fn search_ranks_the_matching_document_first() {
        let docs = ["Hà Nội là thủ đô của Việt Nam.", "Paracetamol hạ sốt cho người lớn.", "Vitamin D3 nên bảo quản nơi khô ráo."];
        let idx = CharTfidf::fit(&docs, 2, 4).unwrap();
        let hits = idx.search("bảo quản vitamin D3", 2);
        assert_eq!(hits[0].0, 2);
        assert!(hits[0].1 > hits[1].1);
        assert!(idx.search("", 3).is_empty());
    }

    #[test]
    fn rejects_bad_ranges_and_empty_corpus() {
        assert!(CharTfidf::fit(&["x"], 2, 5).is_err());
        assert!(CharTfidf::fit(&["x"], 3, 2).is_err());
        assert!(CharTfidf::fit(&[], 2, 4).is_err());
    }
}
