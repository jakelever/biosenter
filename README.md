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
that a plain spaCy `Doc` can't represent correctly:

```python
from biosenter.pmc import parse_pmc_articles
from biosenter.sentences import doc_to_sentence_records

for doc in parse_pmc_articles('PMC1234567.xml'):
    for sentence in doc_to_sentence_records(doc):
        print(sentence['section'], sentence['text'])
```

`doc_to_sentence_records` runs `split_into_sentences` under the hood, which
you can also call directly on marked-up text:

```python
from biosenter import split_into_sentences

text = 'It was observed in every region of the sample.<citation ref-id="b1">22</citation> Real-time mapping confirmed this.'
for start, end, sentence in split_into_sentences(text):
    print(sentence)
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
