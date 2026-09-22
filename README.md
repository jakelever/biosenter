# biosenter - Sentence splitting for biomedical text

[![PyPi](https://img.shields.io/pypi/v/biosenter.svg)](https://pypi.org/project/biosenter/) [![License](https://img.shields.io/pypi/l/biosenter.svg)](https://www.tldrlegal.com/license/mit-license) [![build](https://github.com/jakelever/biosenter/actions/workflows/tests.yml/badge.svg)](https://github.com/jakelever/biosenter/actions)

biosenter is a small spaCy sentence-boundary model
plus markup-aware pre/post-processing, trained and evaluated specifically
against PMC full text and PubMed abstracts with LLM-annotated sentence boundaries.

## Why?

- Generic sentence splitters break constantly on biomedical text
- Full stops appear everywhere in biomedical text (`Fig. 1`, `et al.`) and can easily fool a parser into splitting sentence in the wrong place
- Other tools don't deal nicely with citations that hang at the ends of sentences

## Install

```
pip install biosenter
```

A trained model ships with the package, so `split_into_sentences` works out
of the box with no extra configuration. It integrates directly with [bioconverters](https://pypi.org/project/bioconverters/)
for extracting text from PMC JATS XML and PubMed baseline/update XML.

## Usage

### 1. Direct spaCy usage

For plain, markup-free text (e.g. PubMed abstracts):

```python
import spacy
nlp = spacy.load("biosenter")
doc = nlp("As shown in Fig. 1, expression increased. A second effect was seen in Fig. 2.")
for sent in doc.sents:
    print(sent.text)
```

### 2. Formatting &amp; citation-aware  with [bioconverters](https://github.com/jakelever/bioconverters)

Real PMC full text carries inline markup and citation markers that spaCy won't treat nicely. Combine functionality from the [bioconverters](https://github.com/jakelever/bioconverters) package with the `split_into_sentences` function to keep formatting and citations in the right sentences:

```python
from bioconverters import pmcxml2tagged
from biosenter import split_into_sentences

# pmcxml2tagged() yields (metadata, text) pairs with inline markup and
# citations preserved, e.g.:
#   'Recurrent <italic>C. difficile</italic> infection is common
#   (<citation pmid="23079555">1</citation>).'
for meta, text in pmcxml2tagged('PMC1234567.xml'):
    for start, end, sentence in split_into_sentences(text):
        print(sentence)
```

## Benchmarks

Sentence-boundary F1 against `corpus/test/` -- 100 randomly-sampled PMC
articles that the model was neither trained nor checkpoint-selected on --
excluding the formatting/citation handling. The articles used to train and
evaluate with were annotated by Claude Sonnet and Opus.

| Model | `corpus/test/` |
|---|---|
| spaCy rule-based sentencizer | F1 0.9107 (P 0.8701, R 0.9552) |
| `en_core_web_sm` | F1 0.9506 (P 0.9192, R 0.9843) |
| scispacy `en_core_sci_sm` | F1 0.9763 (P 0.9846, R 0.9681) |
| **biosenter (bundled)** | **F1 0.9891 (P 0.9854, R 0.9928)** |

A single F1 hides where the differences are, because the boundaries this
package exists for are a small fraction of any corpus. Recall on
`corpus/test/`, split by what precedes the boundary (every model is run
through `split_into_sentences()`, so they all get the same markup and
citation handling and only the model differs):

| Model | citation run after the stop (170) | `?` / `!` (23) | everything else (14,053) |
|---|---|---|---|
| spaCy rule-based sentencizer | 0.9059 | 0.9130 | 0.9559 |
| `en_core_web_sm` | 0.8353 | **1.0000** | 0.9861 |
| scispacy `en_core_sci_sm` | 0.7412 | 0.3913 | 0.9717 |
| **biosenter (bundled)** | **0.9353** | 0.6087 | **0.9941** |

"Citation run after the stop" is `...in every region of a chip.22 Real-time
mapping...`, where the reference is set after the full stop it belongs
behind. biosenter leads there and on ordinary prose, which is where nearly
all of the corpus lives: 83 missed boundaries against `en_core_web_sm`'s
195, and -- the bigger difference -- 209 false splits across the whole
test set against its 1,233.

`?`/`!` is a known weakness, not a win: 14 of 23, where the plain
rule-based sentencizer gets 21. The previous release got 0 of 23 -- the
corpus only grew question/exclamation boundaries recently and there are
still just 82 of them in `corpus/train/`, which is not enough for the
model to learn the pattern outright. Only 23 boundaries in this test set
turn on it, so it barely moves the headline F1, but it is the clearest
thing to fix next.

Reproduce with `scripts/evaluate_senter.py`, which loads any of these by
name (they're all just installed spaCy packages):

```
pip install en_core_web_sm  # or: python -m spacy download en_core_web_sm
python scripts/evaluate_senter.py --models rule en_core_web_sm biosenter/model \
  --pmc_eval_dir corpus/test
```

scispacy's released models pin to an older spaCy than biosenter requires
(`en_core_sci_sm` 0.5.4 needs `spacy<3.8`) -- their own README recommends an
isolated environment for exactly this reason, so run it separately:

```
pip install scispacy
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
pip install --no-deps -e .  # biosenter itself, for split_into_sentences -- skip its spacy>=3.8 pin here
python scripts/evaluate_senter.py --models en_core_sci_sm --pmc_eval_dir corpus/test
```

### Reading these numbers honestly

`corpus/test/`'s boundaries were bootstrapped from the *previous* bundled
model and then hand-corrected (see `corpus/README.md`), so the gold still
contains whatever errors of that model the correction pass missed. Every
other model, including this one, is penalised for disagreeing with them.

That effect is measurable, and it is larger than it looks: the previous
bundled model scores F1 0.9947 on this split, while a model retrained from
scratch on *its own training data* scores 0.9906. Nothing about the older
model is better -- 0.9947 is the score of agreeing with yourself. Treat
cross-model gaps of a few tenths of a point here as noise, and the
per-category recall table above as the real comparison.

## Retraining / evaluating

The bundled model, the corpus it was trained on, and the tooling to rebuild
or extend either are all included:

- `corpus/train/` (300), `corpus/validation/` (100) and `corpus/test/`
  (100) -- LLM-annotated PMC articles used to train, tune and score the
  bundled model. See `corpus/README.md` for the dataset schema, the
  annotation conventions, and how it was built.
- `scripts/fetch_pmc.py` -- fetch more PMC Open Access articles (random or
  by PMCID), filtered to commercially-redistributable licenses by default.
- `scripts/build_senter_corpus.py` -- turn fetched XML into corpus records
  with boundaries bootstrapped from the current model, ready to correct.
- `scripts/flag_boundaries.py` -- screen a split for likely boundary
  mistakes (see `corpus/README.md`) before/after correcting it.
- `scripts/prepare_pmc_senter_corpus.py` -- convert `corpus/{train,validation,test}`
  into spaCy training data.
- `scripts/train_senter.py` -- train a new model.
- `scripts/evaluate_senter.py` -- score a model against the hand-labelled
  eval set.

```
python scripts/prepare_pmc_senter_corpus.py --corpus_dir corpus/train --out_path data/senter/pmc_train.spacy
python scripts/prepare_pmc_senter_corpus.py --corpus_dir corpus/validation --out_path data/senter/pmc_val.spacy
python scripts/train_senter.py --data_dir data/senter --run_name my_run --seed 0
python scripts/evaluate_senter.py --models rule runs/my_run/model-best --pmc_eval_dir corpus/validation
```

Runs of this model vary by a couple of tenths of an F1 point seed to seed
(three seeds of the bundled configuration scored 0.9897/0.9898/0.9900 on
`corpus/validation/`), so train a few and pick on `corpus/validation/`.
Score the chosen one on `corpus/test/` once, at the end -- selecting on
`test/` turns it into another validation set.

## License

MIT. See `LICENSE`.
