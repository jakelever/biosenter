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

## License

MIT. See `LICENSE`.
