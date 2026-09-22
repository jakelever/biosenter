# Sentence-splitter data

`train/`, `validation/` and `test/` -- 300, 100 and 100 PMC articles, all
real full text with hand-checked sentence boundaries. `train/` is what the
bundled model is fit on; `validation/` is held out from it and picks the
best checkpoint during training, which is also what the top-level README's
scores are measured on; `test/` is a later, randomly-sampled batch that
nothing has been fitted or selected against. One file per article
(`PMC<id>.json`):

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

`train/` is deliberately weighted toward hard material: a third of it was
sourced by searching PMC for qualitative/interview studies, questionnaire
papers, case reports, systematic reviews, guidelines and medical-education
articles, then ranked by how many question/exclamation sentence ends,
post-stop citation runs, dotted abbreviations and unpunctuated list
passages each article actually contains, and earlier batches were targeted
the same way at HGVS notation and a.m./p.m.-style abbreviations.
`validation/` carries some of that targeting too. Only `test/` is an
unweighted random sample of the OA subset, so it is the one split whose
score means "how the splitter does on PMC full text" rather than "on the
parts of it we already knew were hard".

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

Three scripted steps, then a human pass:

```
python scripts/fetch_pmc.py --out_dir xml/ --random 110 --seed 20260922
python scripts/build_senter_corpus.py --xml_dir xml/ --out_dir corpus/test
python scripts/flag_boundaries.py --corpus_dir corpus/test --show
```

`build_senter_corpus.py` bootstraps boundaries from the current best model
via `split_into_sentences()`. `flag_boundaries.py` then screens them with
ten deliberately over-inclusive checks, and every flag is checked by hand
against the full passage and corrected where it is a real error. Most
flagged candidates turn out to be correct behaviour rather than mistakes --
a case-sensitive gene identifier or figure-panel label starting lowercase,
a methods sentence genuinely ending "for 10 min." -- so flags are a
starting point for review, never applied automatically.

**The scores any bootstrapped split gives are optimistic.** Gold starts as
the model's own output, so every model error the screen fails to catch
stays in the data as "correct" and is scored as a hit. The 150 corrections
to `test/` are the errors the screen did catch; an unknown remainder did
not surface. Treat the headline F1 as an upper bound, and read the
per-error output of `evaluate_senter.py --verbose` rather than the number
alone.

## Annotation conventions

Decided while correcting, and applied consistently across all three
splits:

- **No boundary strictly inside a markup span.** `split_into_sentences()`
  drops those by design (`_merge_boundaries_inside_spans`), so annotating
  one creates a boundary the pipeline can never produce. This has a real
  cost: a block quote set as one `<italic>` span -- common in qualitative
  papers -- can hold only one sentence however many it actually contains,
  and two otherwise-good articles were dropped from `train/` for being
  made of them.
- **Citation runs set after the full stop belong to the sentence before
  them**, including bare superscript digits the converter did not resolve
  into a `<citation>` marker ("...of a chip.22 Real-time mapping..." splits
  after the 22).
- **A narrative citation opens its own sentence** ("Weenk et al. (2019)
  found that...") -- only bare numeric markers are ever stranded.
- **An attribution stays with the quote it follows**: "...as they wish.
  (P2, Psychologist)" is one sentence, as is "...at large." (P3)".
- **A title is one sentence** even when it contains a `?` ("MeVO: To Treat
  or Not To Treat? Review of the Latest Evidence").
- **A colon-introduced list of questions is one sentence** ("(1) Has a
  doctor advised you...? (2) When did you...?"), but the prose that
  resumes after the list starts a new one.

## Usage

```
python scripts/evaluate_senter.py \
  --models rule biosenter/model \
  --pmc_eval_dir corpus/test --verbose
```
