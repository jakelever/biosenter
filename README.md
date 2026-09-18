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

```python
from biosenter import split_into_sentences

text = "As shown in Fig. 1, expression increased in the treated group (P < 0.05). A second effect was seen in Fig. 2."
for start, end, sentence in split_into_sentences(text):
    print(sentence)
```

```
As shown in Fig. 1, expression increased in the treated group (P < 0.05).
A second effect was seen in Fig. 2.
```

### With bioconverters

`biosenter.pmc` and `biosenter.pubmed` wrap `bioconverters`' `parse_pmcxml`/
`parse_pubmedxml` to produce simple doc records (`{'doc_id', 'source',
'sections': [{'name', 'text'}, ...]}`), which `doc_to_sentence_records`
turns into one flat record per sentence:

```python
from biosenter.pmc import parse_pmc_articles
from biosenter.sentences import doc_to_sentence_records

for doc in parse_pmc_articles('PMC1234567.xml'):
    for sentence in doc_to_sentence_records(doc):
        print(sentence['section'], sentence['text'])
```

Section text from `biosenter.pmc`/`biosenter.pubmed` carries the article's
real inline markup (`<italic>`, `<sup>`, `<sub>`, resolved `<citation>`
markers, etc. -- see `biosenter/markup.py`). `split_into_sentences` hides
this from the model and restores it in the output, so a gene symbol like
`<italic>S. pneumoniae</italic>` is never split in the middle, and a
citation glued to a sentence-final abbreviation (`...a chip.22 Real-time...`)
stays attached to the sentence it belongs to.

### Using it directly through spaCy

The bundled model is also loadable by name through spaCy's own API, with no
`import biosenter` in your code:

```python
import spacy
nlp = spacy.load("biosenter")
doc = nlp("As shown in Fig. 1, expression increased. A second effect was seen in Fig. 2.")
for sent in doc.sents:
    print(sent.text)
```

This is the raw senter model with none of `split_into_sentences`'s markup
handling or citation reattachment -- correct for plain, markup-free text
(e.g. PubMed abstracts from `biosenter.pubmed`, or any text you know has no
inline markup in it), where it behaves identically to
`split_into_sentences`. For real PMC full text carrying inline markup and
citations, use `biosenter.split_into_sentences` instead: a `spacy.Doc` is
tokenized from whatever text it's built from, so there's no way for a plain
spaCy pipeline to both tokenize citation-elided text *and* hand back
sentence spans of the original marked-up text -- that remapping only
happens in `split_into_sentences`.

### Overriding the model

```
BIOSENTER_MODEL=/path/to/another/model python your_script.py
```

This also applies when loading via `spacy.load("biosenter")`.

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
