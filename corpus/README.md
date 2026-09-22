# Sentence-splitter data

`train/` and `test/` -- 200 and 100 PMC articles respectively, both real
full text with hand-checked sentence boundaries. `train/` is what the
bundled model is fit on; `test/` is held out from it, used both to pick
the best checkpoint during training and to report the scores in the
top-level README -- there's no separate, untouched final-scoring set.
One file per article (`PMC<id>.json`):

```json
{"pmid": 12345 | null, "pmcid": 67890, "source": "pmc",
 "passages": [{"section": "abstract", "text": "..."}, ...]}
```

`pmid`/`pmcid` are integers or `null`; `source` is `"pmc"` or `"pubmed"`;
`section` is one of bioconverters' coarse categories (PMC:
`title`/`subtitle`/`abstract`/`article`/`back`/`floating`).

All PMC source articles are restricted to Creative Commons licenses that
permit commercial use (CC BY / CC BY-SA / CC BY-ND / CC0), so this data can
be redistributed and used commercially.

Sentence boundaries are marked directly in `text` with a
`<sentence_start/>` tag at the start of every sentence after the first (the
first always starts at 0). `text` also carries real inline markup
(`<italic>`/`<xref>`/`<sup>`/`<sub>`/`<citation>`, see `biosenter/markup.py`)
-- it is `bioconverters`' actual well-formed-XML output (via
`pmcxml2tagged()`, documented in the top-level README), not a
plain-text simplification of it. `scripts/evaluate_senter.py`'s
`parse_boundaries()` strips the `<sentence_start/>` markers back out and
reconstructs the offsets.

## Why it exists

GENIA-style corpora are 1999-era molecular-biology *abstracts*, and most of
what breaks a sentence splitter on real biomedical text lives in modern
*full text*: `Fig. 1`, `et al. (2007)`, `no. 21`, trailing citation markers,
and so on barely occur in abstract-only training data. This dataset is
built specifically to exercise (and evaluate against) the patterns that
matter here, including:

- Abbreviations that are not sentence-final (`Fig.`, `et al.`, `no.`,
  `etc.`, `i.p.`, `p.i.`, `spp.`, and other domain-specific dotted forms)
- Citation markers glued to a sentence-final period, including bracketed,
  numeric-superscript, and hyphenated-range styles
- Narrative citations (`Author et al. (YEAR) VERB...`) as a sentence's
  subject, not just a bracketed reference at its end
- `Fig. N` / reagent names followed by a capitalized panel letter or word
- Registered-trademark symbols (`®`) and other non-letter sentence-final
  punctuation
- Species/taxonomic abbreviations and name-initial abbreviations that look
  like sentence ends (`S. pneumoniae`, `Dr. J. Smith`)
- HGVS protein/cDNA variant notation (`p.G2019S`, `c.6055G>A`) -- the
  internal period reads exactly like a sentence-final abbreviation
  followed by a capitalized word

A splitter can score well on a generic abstract-only benchmark and still
fail most of these.

## How it was built

Boundaries were bootstrapped from the current best trained model via
`split_into_sentences()`, then screened for likely mistakes (a sentence
starting lowercase; a non-final sentence not ending in terminal
punctuation; grep for known trigger patterns), and every flagged case was
checked by hand against the full passage and corrected where it was a real
error. Most flagged candidates turn out to be correct behaviour rather than
mistakes -- e.g. a case-sensitive gene/plasmid identifier or figure-panel
label starting lowercase -- so flags are a starting point for review, not
automatically applied.

## Usage

```
python scripts/evaluate_senter.py \
  --models rule biosenter/model \
  --pmc_eval_dir corpus/test --verbose
```
