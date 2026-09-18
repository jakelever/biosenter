# biosenter

Sentence splitting for biomedical research articles from PubMed and PMC.

Generic sentence splitters break constantly on biomedical text: `Fig. 1`,
`et al. (2007)`, `p.G2019S`, `no. 21`, and trailing citation markers
(`...observed.[31] The next...`) all get mis-split by rule-based or
generic-domain models. biosenter is a small spaCy sentence-boundary model
plus markup-aware pre/post-processing, trained and evaluated specifically
against real PMC full text and PubMed abstracts.

It integrates directly with [bioconverters](https://pypi.org/project/bioconverters/)
for extracting text from PMC JATS XML and PubMed baseline/update XML.

## Install

```
pip install biosenter
```

A trained model ships with the package, so `split_into_sentences` works out
of the box with no extra configuration.

## Usage

There are two ways to use biosenter, depending on what your text looks like.

### 1. With bioconverters, citation-aware (`split_into_sentences`)

Real PMC full text carries inline markup and citation markers, and that's
exactly what breaks generic splitters -- a citation glued to a
sentence-final abbreviation (`...a chip.22 Real-time...`) gets wrongly
split, or a gene symbol like `<italic>S. pneumoniae</italic>` gets cut in
half. `split_into_sentences` hides markup/citations from the model and
restores them afterwards, so neither happens:

```python
from biosenter import split_into_sentences

text = 'It was observed in every region of the sample.<citation ref-id="b1">22</citation> Real-time mapping confirmed this.'
for start, end, sentence in split_into_sentences(text):
    print(sentence)
```

```
It was observed in every region of the sample.<citation ref-id="b1">22</citation>
Real-time mapping confirmed this.
```

`biosenter.pmc` and `biosenter.pubmed` wrap `bioconverters`' `parse_pmcxml`/
`parse_pubmedxml` to produce simple doc records (`{'doc_id', 'source',
'sections': [{'name', 'text'}, ...]}`) with exactly this kind of inline
markup already in the section text (see `biosenter/markup.py`).
`doc_to_sentence_records` runs `split_into_sentences` over every section
and turns the result into one flat record per sentence:

```python
from biosenter.pmc import parse_pmc_articles
from biosenter.sentences import doc_to_sentence_records

for doc in parse_pmc_articles('PMC1234567.xml'):
    for sentence in doc_to_sentence_records(doc):
        print(sentence['section'], sentence['text'])
```

### 2. Direct spaCy usage, plain text

For text you already know has no inline markup in it (e.g. PubMed
abstracts from `biosenter.pubmed`, or plain text from elsewhere), the
bundled model is loadable by name through spaCy's own API, with no
`import biosenter` in your code at all:

```python
import spacy
nlp = spacy.load("biosenter")
doc = nlp("As shown in Fig. 1, expression increased. A second effect was seen in Fig. 2.")
for sent in doc.sents:
    print(sent.text)
```

This is the raw senter model with none of `split_into_sentences`'s markup
handling or citation reattachment, so it behaves identically to
`split_into_sentences` only when there's no markup/citations to handle in
the first place. A `spacy.Doc` is tokenized from whatever text it's built
from, so there's no way for a plain spaCy pipeline to both tokenize
citation-elided text *and* hand back sentence spans of the original
marked-up text -- that remapping only happens in `split_into_sentences`,
which is why real PMC full text needs use case 1, not this one.

### Overriding the model

Either use case respects `BIOSENTER_MODEL`:

```
BIOSENTER_MODEL=/path/to/another/model python your_script.py
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
