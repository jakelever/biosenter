# biosenter - Sentence splitting for biomedical research articles

biosenter is a small spaCy sentence-boundary model
plus markup-aware pre/post-processing, trained and evaluated specifically
against real PMC full text and PubMed abstracts.

**Why?**: Generic sentence splitters break constantly on biomedical text: `Fig. 1`,
`et al.`. They also don't deal nicely with citations (that often get attached to the wrong sentence) 

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

### 2. Citation-aware, with bioconverters (`split_into_sentences`)

For real PMC full text, which carries inline markup and citation markers
that a plain spaCy `Doc` can't represent correctly. `split_into_sentences`
expects text extracted with this exact `parse_pmcxml` call -- `keep_tags`
matches what `biosenter/markup.py` recognizes, and `inject_citations=True`
is what produces the `<citation>` markers the reattachment logic needs:

```python
from bioconverters import parse_pmcxml
from bioconverters.pmc_constants import PMC_KEEP_TAGS

from biosenter import split_into_sentences

for article in parse_pmcxml(
    'PMC1234567.xml',
    return_xml=True,
    keep_tags=PMC_KEEP_TAGS,
    inject_citations=True,
    clean_numeric_citations=False,
    clean_xrefs_in_brackets=False,
    clear_empty_brackets=False,
    fix_exponentials=False,
):
    for text in article.iter_text(['title', 'abstract', 'article']):
        for start, end, sentence in split_into_sentences(text):
            print(sentence)
```

## Benchmarks

Sentence-boundary F1 against `corpora/difficult_cases.json` (51 hand-labelled
hard-case paragraphs, 214 sentences) and `corpora/validation/` (50 held-out
PMC articles). Every model is run through the same citation/markup-handling
wrapper (`split_into_sentences`), so this isolates boundary judgement itself
rather than penalizing spaCy/scispacy for markup handling they were never
built for.

| Model | `difficult_cases.json` | `validation/` |
|---|---|---|
| spaCy rule-based sentencizer | F1 0.9364 (P 0.8852, R 0.9939) | F1 0.9180 (P 0.8886, R 0.9494) |
| `en_core_web_sm` | F1 0.9271 (P 0.8833, R 0.9755) | F1 0.9537 (P 0.9289, R 0.9799) |
| scispacy `en_core_sci_sm` | F1 0.9726 (P 0.9639, R 0.9816) | F1 0.9728 (P 0.9830, R 0.9628) |
| **biosenter (bundled)** | **F1 0.9877 (P 0.9938, R 0.9816)** | **F1 0.9832 (P 0.9834, R 0.9831)** |

Reproduce with `scripts/evaluate_senter.py`, which loads any of these by
name (they're all just installed spaCy packages):

```
pip install en_core_web_sm  # or: python -m spacy download en_core_web_sm
python scripts/evaluate_senter.py --models rule en_core_web_sm biosenter/model \
  --pmc_eval corpora/difficult_cases.json --pmc_eval_dir corpora/validation
```

scispacy's released models pin to an older spaCy than biosenter requires
(`en_core_sci_sm` 0.5.4 needs `spacy<3.8`) -- their own README recommends an
isolated environment for exactly this reason, so run it separately:

```
pip install scispacy
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
pip install --no-deps -e .  # biosenter itself, for split_into_sentences -- skip its spacy>=3.8 pin here
python scripts/evaluate_senter.py --models en_core_sci_sm \
  --pmc_eval corpora/difficult_cases.json --pmc_eval_dir corpora/validation
```

## Retraining / evaluating

The bundled model, the corpus it was trained on, and the tooling to rebuild
or extend either are all included:

- `corpora/difficult_cases.json` -- 51 hand-labelled paragraphs used
  to evaluate the splitter against exactly the patterns that break generic
  splitters. See `corpora/README.md` for the dataset schema and how it
  was built.
- `corpora/train/` and `corpora/validation/` -- 150
  hand-corrected PMC articles used to train the bundled model.
- `scripts/fetch_pmc.py` -- fetch more PMC Open Access articles (random or
  by PMCID), filtered to commercially-redistributable licenses by default.
- `scripts/prepare_pmc_senter_corpus.py` -- convert `corpora/{train,validation}`
  into spaCy training data.
- `scripts/train_senter.py` -- train a new model.
- `scripts/evaluate_senter.py` -- score a model against the hand-labelled
  eval set.

```
python scripts/prepare_pmc_senter_corpus.py --corpus_dir corpora/train --out_path data/senter/pmc_train.spacy
python scripts/prepare_pmc_senter_corpus.py --corpus_dir corpora/validation --out_path data/senter/pmc_val.spacy
python scripts/train_senter.py --data_dir data/senter --run_name my_run
python scripts/evaluate_senter.py --models rule runs/my_run/model-best --pmc_eval corpora/difficult_cases.json --verbose
```

## License

MIT. See `LICENSE`.
