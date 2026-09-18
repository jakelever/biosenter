# Sentence-splitter evaluation data

`difficult_cases.json` -- 51 hand-labelled full-text paragraphs (49 PMC,
2 PubMed), 214 sentences. History: 51 paragraphs/155 sentences before
the "Refresh: switch to bioconverters" section removed 17 that couldn't
be carried over; 34/110 before "A fourth batch" added 8 (all PMC);
42/162 before "A fifth batch" added 5 more (3 PMC, 2 PubMed, the first
non-PMC entries in the file); 47/195 before "A sixth batch" below added
4 more (all PMC). This is an **evaluation set only**; nothing is trained
on it.

Each entry: `{pmid, pmcid, source, section, text}`. `pmid`/`pmcid` are
integers or `null`, backfilled via NCBI's PMC ID Converter API where the
source article's own XML didn't carry both (see "Refresh: numeric ids +
coarse section" below) -- a PubMed-only entry's `pmcid` is `null` when
the article genuinely has no PMC deposit (both current PubMed entries
predate PMC's existence). `source` is `"pmc"` or `"pubmed"`. `section`
is one of bioconverters' coarse categories (PMC:
`title`/`subtitle`/`abstract`/`article`/`back`/`floating`; PubMed only
ever produces `title`/`abstract`), not the free-text sub-heading a
paragraph appeared under.

## Why it exists

GENIA supplies the training data, but it cannot measure whether the
splitter works on this project's text. It is 1999-era molecular-biology
*abstracts*, and the failures that motivated a custom splitter live in
modern *full text*. Counted across GENIA (3.0M chars) versus a 182-article
PMC batch (5.5M chars): `Fig.` 0 vs 361, `et al.` 12 vs 1096, `no. N` 0 vs
21, HGVS `p.`/`c.` 0 vs 4, `[12]` citations 20 vs 9367. A splitter can
score 0.998 on GENIA and still cut `(Fig. 1)` in half.

## How it was built

Paragraphs were sampled from `data/pmc_batch` with
`biosenter/pmc.py`'s extractor, deliberately enriched for the hard cases:
28 of the 40 contain at least one abbreviation trigger (`Fig.`, `et al.`,
`no.`, `e.g.`, `vs.`, `Dr.`, `Table N`, ...), and 12 are ordinary prose
sampled at random so the set also catches a model that has learned to
under-split.

Boundaries are marked directly in the text with a `<sentence_start/>`
tag placed at the start of every sentence after the first (the first
always starts at 0, so it needs no marker) -- this replaced an earlier
numeric-offset format, since writing/checking a boundary by inserting a
tag at the right point in the text is far less error-prone, for both a
person and an LLM, than counting characters. `scripts/evaluate_senter.py`'s
`parse_boundaries()` strips the markers back out and reconstructs the
offsets.

Text carries the real inline markup (`<italic>`/`<xref>`/`<sup>`/`<sub>`,
see `biosenter/markup.py`) alongside the `<sentence_start/>` markers --
it is biosenter/pmc.py's actual well-formed-XML output, not a
plain-text simplification of it. Evaluation runs through
`biosenter.sentences.split_into_sentences()`, the real production
splitter, rather than calling a spaCy model directly on this text: that
is what makes the markup-driven behaviour (keeping a trailing citation
with the sentence it belongs to, never splitting inside a span) part of
what gets measured, not a separate concern.

Two paragraphs (`pmcid` 8000078 and 8000075) have genuinely arguable
segmentation -- a bare trailing `(Table 3, Figure 2).` parenthetical, and
a correction notice that runs an article title into a journal reference.
They are kept rather than dropped, since excluding every hard case is
how an eval set flatters a model. (Originally recorded in a `note` field
on each entry; dropped when the schema was normalized to
`{pmid, pmcid, source, section, text}` -- see "Refresh: numeric ids +
coarse section" below.)

## A second batch: random sampling, not enrichment

The first 40 paragraphs were sampled from a fixed 182-article batch and
deliberately enriched for known trigger words. The 8 added afterwards
came from a different process: `scripts/fetch_pmc.py --random N`
pulls genuinely random PMCIDs from the public PMC Open Access S3 bucket
(via a random `start-after` listing token, since the bucket has no
search API), spanning PMCID 150011 through 11903251 -- old and new,
across many journals, nothing hand-picked.

30 such articles (`data/pmc_random1/`, gitignored, reproducible via
`--random 30 --seed 42`) were split with `senter_v3` and screened for
suspicious structure (a sentence starting lowercase, mainly) rather than
read sentence-by-sentence -- 5,423 sentences is too many to eyeball.
Every flagged candidate was checked against the source XML before being
trusted; several flagged cases turned out to be correct behaviour (a
capitalised abbreviation like "hs-CRP" starting a sentence isn't a
lowercase start) or genuine typos in the source article itself, and
were left out.

8 held up as real, reproducible mistakes and were added: `etc.` (0
occurrences in GENIA, same story as `Fig.`/`et al.` before it), `spp.`
(a taxonomic abbreviation), `c.a.` (a dotted spelling of circa/
approximately distinct from `ca.`, which was already covered), `Suppl.`
(supplementary-material references), a middle initial before a surname
("Dr. Alan S. Verkman"), and a narrative citation form GENIA has no
equivalent for at all -- "Author et al. (YEAR) VERB..." as the subject
of a sentence, rather than a bracketed reference at its end. Adding
these dropped `senter_v3`'s PMC F1 from 0.9895 to 0.9444 (2 -> 12 false
splits) -- exactly the point: the original 40 were not exercising these
patterns, so the score was overstating how well the model generalises.

Two further, larger issues turned up during this same sweep but are
**not** represented in this file, because no amount of eval-labelling or
model retraining can fix either one -- they are bugs in the extraction/
splitting pipeline itself, not gaps in what a model has learned:

- **Literal newlines embedded in JATS source text get treated as hard
  sentence boundaries.** `biosenter/sentences.py`'s `_segment()` splits
  on `\n` unconditionally, which is correct for breaks it inserts itself
  (list items, dropped display formulae) but wrong when a publisher's
  own XML hard-wraps body text at a fixed column width using literal
  `\n` characters -- confirmed in 2 of the 30 random articles (90
  newlines across 11 `<p>` blocks in one, 918 across 58 `<p>` blocks in
  the other), which come out almost entirely shredded into one- or
  two-word fragments regardless of which model is used.
- **A run of 3+ separate, comma-separated `<xref>` citations isn't fully
  reattached.** `_elide_citations()`/`_attach_trailing_citations()`
  handle a single trailing citation (or a tightly-packed run like
  `18,19`) correctly, but a citation of the form `.[11], [12], [13]
  Moreover...` only reattaches the first marker, leaving `, [12], [13]`
  stranded as its own one-token "sentence" -- reproduced directly against
  `data/pmc_random1/PMC9478454.1.xml`.

## A third batch: the newline bug is worse than it looked

A second random sample (35 articles, `data/pmc_random2/`, PMCID 150011
through 11903251 again but a different seed, `--random 35 --seed 137`)
turned up 3 more clean, addable patterns -- 51 paragraphs, 155 sentences
total now. The heuristic scanner needed a fix too: plasmid names
(`pDEST14-...`), gene symbols (`cMyc`), and plural forms of already-
covered abbreviations (`cDNAs`, `miRNAs`) were flooding the flagged list
as false positives, since the word-boundary check that recognised the
singular form didn't match when another letter followed it directly.

New additions: a bare URL's literal href text (`http://rna.tbi.univie.
ac.at/...`) read as an abbreviation continuation at "ac." -- `<ext-link>`
isn't elided the way a bibr citation is, so the model sees the raw URL
string; and `no.` followed by an alphanumeric accession number
(`accession no. D42046`) rather than the bare digits the training
augmentation covered. One more `etc.` example (a different phrasing)
was added too. `senter_v3`'s PMC F1: 0.9444 -> 0.9327 (12 -> 15 false
splits).

Two candidates looked like mistakes but turned out to be genuine
punctuation errors in the *published* article itself (a stray period
before a lowercase "and", a period where a comma belonged in a
parenthetical stats list) -- left out, same reasoning as the two
genuinely-arguable paragraphs kept above: the model's behaviour was
reasonable given what the sentence actually contained.

The bigger finding is that **the newline bug from the second batch is
not confined to publishers who hard-wrap whole paragraphs.** A second,
more common variant showed up repeatedly: a literal `\n` sitting in an
inline element's *tail* text, right after a citation, figure, or table
reference -- `<xref ...>Fig. 1</xref>\n, we present...` in the source XML
becomes two "sentences", `"Fig. 1"` and `"we present..."`, with nothing
for either the model or eval-labelling to fix, for the same reason as
before: `_segment()` splits on that `\n` before any model runs. One
article (`PMC9815856`) had this after nearly every inline figure/table
reference in the whole document -- `"In Fig. 1"`, `"Fig. 5"`, `"Table 4"`
and more, each stranded as its own fragment. Confirmed in at least 4 of
the 35 articles in this batch (`PMC9815856`, `PMC9224413`,
`PMC11226126`, arguably `PMC7792801`), on top of the 2 from the batch
before. This looks like a fairly common convention among JATS-generating
tools, not a couple of outlier publishers -- worth treating as higher
priority than the citation-reattachment gap when this does get fixed.

## Refresh: switch to bioconverters

`biosenter/pmc.py` was rewritten to extract text via the `bioconverters`
PyPI package instead of hand-parsing JATS XML -- see `LOG.md`. Both bugs
in the section above are fixed by construction: bioconverters collapses
all whitespace unconditionally (no literal `\n` ever survives into a
passage's text), and citations are resolved via `inject_citations=True`
onto a `<citation>` tag rather than reassembled from bare `<xref>`
markup.

This changed what a single passage of text *is*: bioconverters splits on
every `<p>`/`<title>`/`<list-item>`/etc., rather than joining a whole
`<sec>`'s paragraphs (and any sub-section titles) into one string the way
the old extractor did. So this file's 51 entries were refreshed against
the new extractor's output: for each entry, its old text (all markup
stripped, `<sentence_start/>` positions kept) was matched by exact
whitespace/dash-normalized plain text against every passage of the
freshly re-extracted article (title/subtitle/abstract/article/back/
floating -- not just body text, since 3 of the 51 entries are drawn from
article titles). Where the match was exact, the old `<sentence_start/>`
positions were carried onto the new passage's real markup, unchanged.

34 of the 51 carried over cleanly. The other 17 didn't have an exact
matching passage -- almost entirely because the new extractor no longer
inserts a paragraph break where the old one dropped a
`<disp-formula>`/similar (so text that used to be two separate
hand-labelled paragraphs is now one longer passage, and the boundary at
that join is no longer decided for free by an inserted `\n` -- it needs
an actual judgment call), plus a couple of cases where a sub-heading is
typeset as a run of `<bold>` text inside the same `<p>` rather than its
own `<title>` element, so it no longer arrives as a separable passage.
Rather than leave 17 paragraphs sitting in an eval set with stale,
pre-refresh text (and pre-refresh markup nothing downstream still
recognises -- see `biosenter/markup.py`'s `TAGS`), those 17 were
**deleted** rather than re-labelled. Re-adding coverage for the
disp-formula-merge case they were mostly exercising is follow-up work,
not done here -- see `LOG.md`.

senter_v3's score on the resulting 34-paragraph/110-sentence set: PMC F1
0.9870 (P=0.9744, R=1.0000, 76/2/0) -- higher than the pre-refresh number
below, which is expected and not a sign the splitter improved: the 17
removed paragraphs were disproportionately the harder, formula-adjacent
cases, so this number is not comparable to the ones in the table above.

## Refresh: numeric ids + coarse section

Each entry's schema was normalized to `{pmid, pmcid, source, section,
text}` (previously `pmcid, section, section_type, text[, note]`, with
`pmcid` a string like `"PMC8000011"` and `section` a free-text
sub-heading). `pmid` is new -- every entry here is PMC-sourced and
mostly had no `pmid` on file, so it's backfilled via NCBI's PMC ID
Converter API (`https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/`),
batched by `pmcid`; resolved cleanly for all 34. `section` is now
whichever of bioconverters' coarse categories (title/subtitle/abstract/
article/back/floating) the paragraph's re-extracted passage actually
falls under, found the same way the "switch to bioconverters" refresh
above matched text -- normalized-plain-text comparison against the
freshly re-extracted article, this time against `doc['sections']`
(paragraph-level passages) rather than individual sentences, and with
proper entity-unescaping (`&gt;` -> `>`) before comparing, both real
bugs caught by a first pass matching 0/34 and 13/321 (in the equivalent
pass over `train.json`) instead of all of them. `section_type`
and the two entries' `note` field were dropped -- the "arguable
segmentation" context the `note`s recorded is now in prose above instead
of the data itself. Nothing about `text` or the sentence-boundary
markers changed.

## A fourth batch: post-bioconverters mistakes

The batches above all predate the switch to `bioconverters` -- every
mistake they document was found against the old hand-rolled extractor's
output, which is why the newline and citation-run bugs got fixed by the
switch rather than by anything in this file. This batch is the first
built against the new extractor's actual output: 30 freshly-sampled
random PMCIDs (`scripts/fetch_pmc.py --random 30 --seed 2026`,
`data/pmc_random3/`, gitignored), split with `senter_v3`, screened two
ways -- the established lowercase-sentence-start heuristic, plus a
second pass flagging any non-final sentence in a paragraph that doesn't
end in terminal punctuation (`.`/`!`/`?`, optionally followed by a
closing quote/bracket), which catches a wrong split whose *second* half
happens to start capitalized (the lowercase heuristic alone would miss
it). 6,498 sentences produced 54 + 97 flagged candidates.

Most flagged candidates were correct behaviour, not mistakes -- worth
recording since they show what the heuristics catch besides real bugs:
abbreviation-list glossary entries and case-sensitive abbreviations
starting a sentence (`rAAV`, `iPSC`, `cDNA`, `p-Toluenesulfonyl...`, same
story as `hs-CRP` in the second batch); bullet-list items that are noun
phrases, not sentences (a symptom list: "coughing up blood", "new
confusion"); figure/table caption fragments ("n = 6 mice..."); and, by
far the largest cluster, a numeric citation marker directly after a
sentence-final period (`...therapy.[2]`, `...UTIs.13`) -- correctly kept
attached to the sentence it ends, not split off, which is exactly what
`_attach_trailing_citations` is for. One historical/OCR'd article
(`PMC9236009`, an 1887 journal digitization full of garbled text like
"io cts." and "$i.oo per year.") produced garbage flags that aren't a
splitter defect at all -- the source text itself is corrupted, nothing
downstream can fix that.

8 new paragraphs were added, 6 confirmed mistakes and 2 kept as
genuinely arguable (`note` field, reintroduced for these two after being
dropped in the refresh above -- dropping it there was about conforming
existing entries to a fixed schema, not a decision to never use the
field again):

- **A citation mid-sentence, not at its end.** `_attach_trailing_citations`
  only reattaches a citation stranded at the *start* of the following
  sentence; it has no logic for one sitting in the *middle* of a clause
  that should never have been split at all -- "As reported by Rosengren
  et al. (16) two different signals were observed..." split right after
  `(16)`. A different shape of citation problem than anything the
  earlier batches found.
- **The narrative-citation form still doesn't fully generalize.**
  "Boucher et al. (2007) studied participant's ability..." and "...
  following Folch et al. (1957) with some modifications." both split
  wrongly, despite this exact `Author et al. (YEAR) VERB...` pattern
  being deliberately covered by training augmentation (second batch,
  `LOG.md` session 11). The PMC2721960 entry keeps a *second*,
  correctly-handled instance of the same pattern two sentences later in
  the same paragraph, so it's not a blanket failure -- more data would
  help distinguish exactly what's still missing.
- **A chemical name split mid-word.** `3-(4,5-Dimethylthiazol-2-yl)-2,5-
  diphenyltetrazolium bromide` (the MTT assay reagent) split right after
  `3-(4,5-`. Nothing in the augmentation targets chemical nomenclature
  specifically.
- **`Fig. N` + panel letter, split apart.** By far the most common new
  pattern: "As shown in Fig. 1 F, ..." splits into "Fig. 1" | "F, ...".
  One article (`PMC8543956`) has 25+ near-identical instances (`Fig. 2
  A-C`, `Fig. 3 A-B`, `Fig. 6 A-F`, etc.) -- `Fig.` itself is a
  well-covered abbreviation (GENIA has 0 instances, the PMC set forced
  it into training early on), but a bare number immediately followed by
  a capitalized panel letter isn't the same shape as what was trained
  on. One representative instance was added rather than all 25+.
- **A registered-trademark symbol treated as sentence-final.** "IBM
  SPSS® Statistics for Windows" split right after `®`.
- **Two genuinely arguable cases, kept with a `note`:** a display
  equation dropped between two sentences leaves nothing behind but 3
  empty `<sub></sub>` remnants (`PMC_IGNORE_TAGS`) -- the sentence that
  would have introduced the equation is gone entirely, not just the
  equation, so there's no clean antecedent for the following "where A0
  represents..." clause to attach to either way; and a figure-footnote
  caption ("a Based on MRI parameters: b Based on DAT-SBR.") where `a`/
  `b` are bolded footnote-letter markers concatenated by a colon rather
  than genuine sentence-continuation prose -- defensible to split there
  or not, so the model's own (unmerged) behaviour was kept as the label.

`senter_v3`'s score on the full 42-paragraph/162-sentence set: PMC F1
0.9677 (P=0.9375, R=1.0000, 120/8/0) -- lower than the 34-paragraph
0.9870 above, as expected: 6 of the 8 new paragraphs were specifically
chosen because the model gets them wrong.

## A fifth batch: PubMed, and a citation-range variant

Same idea as the fourth batch, this time deliberately covering PubMed
too, not just PMC -- everything before this was PMC-only (`source` was
never anything else in this file until now). 30 more freshly-sampled
random PMCIDs (`--seed 3141`, `data/pmc_random4/`, gitignored) plus 400
titles+abstracts sampled (seed 3141, `random.sample`) from a fresh,
previously-unused PubMed baseline shard (`pubmed26n0100.xml.gz` --
release 26 file 100, files 1-16 were already in use elsewhere;
`data/pubmed_random1/`, gitignored). Same two screening heuristics as
the fourth batch. 8,859 sentences across both sources produced 79 + 38
flagged candidates.

Confirmed correct behaviour turned up the same categories as before
(abbreviation glossaries, case-sensitive gene/plasmid/SNP identifiers
starting a sentence, bullet-list noun phrases) plus a large PMC cluster
of comma-separated numeric citation runs *without* enclosing brackets
(`...aneuploid embryos .2, 3, 4, 5, 6 Researchers have...`) that turned
out to already be handled correctly -- `_attach_trailing_citations`
generalizes to this un-bracketed format fine, this just wasn't tested
against it directly before.

5 new confirmed mistakes were added (3 PMC, 2 PubMed):

- **A hyphenated citation range split apart internally.** `[3-6]` (two
  separate `<citation>` spans for the endpoints, joined by a bare,
  untagged hyphen) split right between them -- `_citation_run_end`'s
  gap-scanning only recognises ` `, `(`, `,`, `;` as characters that
  continue a citation run, not `-`. A hyphen-joined sibling of the
  comma-separated multi-marker gap in the "Known gap" section below;
  two instances added (`PMC1685661`, `PMC5010028` -- the latter has 5 in
  one article, only 1 included).
- **A number split from its unit.** `81.7 and 163.4` | `cm2 membrane
  surface areas` split right before the superscript in `cm<sup>2</sup>`.
- **Two new abbreviation triggers, both PubMed, both the same failure
  shape:** `i.p.` (intraperitoneal) and `mo.` (months) each wrongly
  treated as sentence-final when followed by a lowercase continuation
  of the same clause (`...bicuculline i.p.` | `during 10 days.`; `...8
  mo.` | `before, and the patient...`). Neither abbreviation appears to
  be covered by the GENIA-abbreviation training augmentation from
  session 11 -- PubMed text has no markup at all (`parse_pubmedxml` is
  always plain text), so this is purely about token-level abbreviation
  coverage, no citation/formatting angle.

`senter_v3`'s score on the full 47-paragraph/195-sentence set: PMC F1
0.9446 (P=0.9119, R=0.9797, 145/14/3) -- lower again, as expected (all 5
new paragraphs chosen because the model gets them wrong). Mixed PMC +
PubMed now, despite the `--pmc_eval`/"PMC F1" naming throughout this
file and `evaluate_senter.py` -- that naming predates PubMed entries and
hasn't been updated, since the flag/label still accurately describes
what the set mostly is.

## A sixth batch: product names, and confirming what already works

Same methodology again: 30 more random PMC articles (`--seed 9973`,
`data/pmc_random5/`) plus 400 abstracts sampled from a third,
previously-unused PubMed baseline shard (`pubmed26n0250.xml.gz`,
`data/pubmed_random2/`), both gitignored. 10,228 sentences, 108 + 102
flagged candidates.

Worth recording even though nothing was added from it: one PMC article
(`PMC10168667`, a sociology paper) contributed 44 of the 108
lowercase-start flags, every single one a bare numeric superscript
citation correctly reattached to its sentence (`...enforce the law.1` |
`To accomplish this...`) -- the single largest confirmation yet that
`_attach_trailing_citations` handles this shape robustly at scale, not
just in small samples. A second old, OCR-digitized article (1954 this
time, `PMC2007967`) produced more garbled-source-text flags, same
non-issue as the 1887 one in the fourth batch. All PubMed candidates in
this batch turned out to be correct behaviour or a source-text
capitalization quirk (a `neither X nor Y...` clause that just wasn't
capitalized in the original abstract) -- this batch added no PubMed
entries, despite sampling PubMed at the same scale as PMC.

4 new confirmed mistakes, all PMC, all a variant of the "product name
split in half" pattern first seen in the fourth batch's MTT entry:

- **`Wizard® Genomic DNA Purification Kit`** -- a second, independent
  instance of the exact `®`-treated-as-sentence-final mistake from the
  fourth batch's IBM SPSS® entry, different product. Confirms it's a
  general symbol-handling gap, not something specific to that one name.
- **`NanoString mouse PanCancer Immune Profiling panel`** -- split with
  no obvious single trigger character (no `®`, no hyphen, no digit
  immediately before the break).
- **`FuGene 6 Transfection Reagent`** -- split right after the bare
  number `6`, echoing the `Fig. N` + capitalized-word pattern from the
  fourth batch but for a reagent name instead of a figure reference.
- **`p.i.` (post-infection), a new abbreviation trigger** -- same
  failure shape as the fourth/fifth batches' `i.p.`/`mo.` (an
  abbreviation-final period followed by a lowercase continuation of the
  same clause). Recurs 3 times in one article (`PMC1963315`); only 1
  instance included.

`senter_v3`'s score on the full 51-paragraph/214-sentence set: F1 0.9384
(P=0.8989, R=0.9816, 160/18/3).

## `corpora/train/`: a bulk training corpus

`difficult_cases.json` above is deliberately small and hand-curated -- fine for
scoring a model, useless for training one (spaCy's existing GENIA-derived
training data is ~29K sentences; the eval set is 214). `corpora/train/`
is a separate, much larger corpus built to actually move training data
volume, one file per source article (`PMC<id>.json`):

```json
{"pmid": 12345 | null, "pmcid": 67890, "source": "pmc",
 "passages": [{"section": "abstract", "text": "..."}, ...]}
```

(`pmid`/`pmcid`/`source` live once per file rather than once per passage,
unlike `difficult_cases.json`, since they're constant for every passage in a
given article.)

**Source**: 50 randomly-sampled PMC articles (`--seed 42`, `data/pmc_train1/`,
gitignored), restricted to articles under a Creative Commons license that
permits commercial use (CC BY / CC BY-SA / CC BY-ND / CC0 -- `fetch_pmc.py`'s
`--random` now checks each candidate's `<license>` element and defaults to
this filter; `--allow_any_license` opts out). Every passage bioconverters
produces is included -- title, subtitle, abstract, article body, back
matter, floating (figure/table captions) -- not just abstracts: 3095
passages, 9782 sentences total.

**Method**: hand-authoring `<sentence_start/>` tags one sentence at a time,
the way `difficult_cases.json` was built, doesn't scale to this volume. Instead:
1. Bootstrap every passage's boundaries from `senter_v3` (the current best
   trained model) via `split_into_sentences`.
2. Screen the whole corpus with the same two heuristics used to hunt for
   `difficult_cases.json` mistakes (lowercase sentence start; non-final sentence
   not ending in terminal punctuation), plus a grep for the specific trigger
   patterns already confirmed in `difficult_cases.json` (`Fig. N`+letter, `®`,
   hyphenated citation ranges, `i.p.`/`p.i.`/`mo.`).
3. Read the full passage (not just the flagged sentence in isolation) for
   every flag, and hand-correct genuine mistakes by editing the
   `<sentence_start/>` placement directly -- same no-offset-computation rule
   as `difficult_cases.json`. Left alone where the flag was a false positive
   (overwhelmingly: lowercase gene/variable names, footnote/list markers,
   data-table rows, figure-panel labels -- all of which are correctly
   segmented despite starting lowercase).

~90 boundary corrections were made this way across ~20 of the 50 articles.
The single biggest cluster: one review article on heavy-metal plant stress
(`PMC4744854`) that cites constantly in the form "Author et al. (YEAR) have
shown that..." -- `senter_v3` splits almost every one of these right after
the year, 20+ times in one article, always the same shape. `etc.` mid-clause
(`"...Cd, Cr, Pb, Al, Hg, etc., although being non-essential..."`) is the
second most common recurring trigger, alongside already-known abbreviations
(`equiv.`, `vers.`, `b.p.`) and a statistics-reporting one not seen before:
`p = .XX` decimals inside a parenthetical results list, e.g. `(b = -.10,
p = .11]; emotional hostility: b = ...)`, where the model repeatedly treats
`.11` as sentence-final.

Two non-boundary bugs surfaced along the way and were hand-corrected with a
`note` rather than folded silently into the merge count: `PMC4823498`'s
abstract had a boundary land *inside* an `<italic>` span (`Case Repo` |
`rt.`), which `sentences.py`'s `_merge_boundaries_inside_spans` is supposed
to prevent -- worth a closer look as a real bug in that function, not just
a training gap. `PMC4842845` had two adjacent figure captions concatenated
with no separator by bioconverters (`Fig. 1.Fig. 2`), a passage-boundary
quirk rather than a sentence one.

**Follow-up round**: the same single-capital-letter-initial screen that
found 84 bootstrap errors in `validation/` (see below) was run against
`train/` too. 11 real corrections, the same shape throughout --
acknowledgments/author-contribution lists wrongly split at a name's
middle initial (`"grateful to J. Patouraux and S. | Veyrenc"`, `"Dr. B. |
MacCallum"`, five more in one `PMC2867825` acknowledgments passage
alone) and a taxonomic authority citation split mid-name (`"Vigna radiata
L. | Wilczek"`, the "L." being Linnaeus's abbreviation, not a sentence
end). `data/senter/pmc_train.spacy` regenerated afterward. Most of the
36 candidate hits were false positives, same pattern as `validation/`:
temperature/unit symbols (`°C`, `K`, `W`), a chemical element symbol,
and figure-panel labels (`A.`/`B.`) -- all already correct. Two
`PMC3770370` hits (`"contains datablock(s) global, I. DOI:"`) were left
alone as genuinely ambiguous CIF-style crystallography metadata rather
than real prose with a clear right answer.

## `corpora/train/`, round 2: 50 more articles

Same pipeline again: 50 more license-filtered PMC articles (`--seed
4242`, `data/pmc_train2/`, one swap after a collision with `validation/`),
added alongside the first 50 rather than replacing them -- `train/` is
now 100 files, 6283 passages, 20043 sentences. Bootstrap, screen
(including the single-capital-letter-initial screen from the
`validation/` follow-up round, run against this batch from the start
this time), hand-correct: 30 corrections. Same trigger shapes as before
(`et al. (YEAR)`, `etc.`, `i.p.`, name-initial splits in acknowledgments
and author-contribution sections, `Fig. N`+letter, a species-abbreviation
split `"S. | coelicolor"`) plus one new one: a citation-number list split
mid-list (`"etc. [6] | , [7], [8], [9], [10]."`).

One passage (`PMC7260969`, entries 46 and 48) turned up a real bug in the
bootstrap step itself, not the source text: `<sentence_start/>` landed
*inside* a tag -- once splitting a citation's own closing tag
(`</citati<sentence_start/>on>`), once inside a DOI attribute value and
once mid-word (`d<sentence_start/>ecision`) -- silently tolerated by the
regex-based marker parsing used everywhere until now, but breaking real
XML parsing (`biosenter.markup.strip_markup`, which
`prepare_pmc_senter_corpus.py` needs and the older tooling never called
on this file). Hand-corrected: one relocated to the real boundary it was
clearly meant to represent (before "However,"), two removed outright
(no real boundary at either broken position). Confirmed via a full
`strip_markup` well-formedness pass that no other passage in `train/` or
`validation/` has the same problem. `data/senter/pmc_train.spacy`
regenerated.

## `corpora/validation/`: a second, disjoint batch

Same schema, same source (license-filtered `--random` PMC), same
bootstrap-then-hand-correct method as `corpora/train/` above, in a
sibling `corpora/validation/` directory -- a held-out split for
model selection during training, distinct from both `train/` (fitting) and
`difficult_cases.json` (final scoring, still completely untouched by any of
this). 50 more articles (`--seed 777`, `data/pmc_validation1/`, one swapped
out and re-fetched with `--seed 778` after it collided with an article
already in the `train/` batch -- confirmed the two sets are now disjoint by
PMCID), 3378 passages, 10319 sentences after corrections.

~75 corrections made, same trigger patterns as `train/` (`et al. (YEAR)`,
`etc.`, `i.p.`, `Eq.`/`Fig. N`, `®`) plus a few new ones: `r.p.m.`,
`vol.`/initials inside a bibliography-style reference entry, and a
taxonomy paper (`PMC3817441`) with `sp. n.` (species nova) and single-
letter-initial abbreviations (`S. China`, collector names) causing
several false splits -- including one entry that was a single ~40-sentence
false-split passage: a specimen-collection list entirely delimited by
semicolons where the only real sentence boundary was the final period;
every internal period was an abbreviation (`leg.`, `coll.`, or a collector's
initials). Also reconfirmed, at this scale, that bare-digit/bracketed
trailing citations are handled correctly even in citation-dense articles
(`PMC4150008`, `PMC6490293`, `PMC7430228` each had 10+ heuristic flags that
were all already-correct segmentation, not real mistakes).

**Follow-up round**: training `senter_v4` on `train/` and scoring it
against `validation/` (see "Retraining: senter_v4" below) surfaced a
whole class of bootstrap errors in `validation/` that the original
lowercase-start/non-terminal-punctuation screening never catches: a
proper-name or reference list wrongly split at a single-capital-letter
initial (`"grants to C. | Jobin"`, `"Kijoung S. | Song, Xin Yuan, Theodore
M. | Danoff..."`) reads as two grammatically-plausible capitalized
fragments to both heuristics. Found by grepping for
`<sentence_start/>` immediately preceded by a lone capital letter and a
period, then hand-checking each hit against its full passage (most hits
were false positives -- units like `°C`/`mg/L`, chemical element symbols,
`troponin I`, figure-panel labels `A.`/`B.`/`C.` -- all already correct).
84 more boundaries corrected across 7 files, concentrated in
`PMC3817441` (four more specimen-list passages with the same
all-internal-periods-are-abbreviations shape as the one above) and a
references-cited section in `PMC5848052` (bibliography entries split at
every author initial). `data/senter/pmc_val.spacy` regenerated afterward.

## Retraining: senter_v4

`scripts/prepare_pmc_senter_corpus.py` converts `train/` or
`validation/` into a spaCy `.spacy` DocBin, mirroring the exact
transformation `split_into_sentences()` applies at inference time
(markup stripped, citation markers elided before tokenizing) rather than
training on raw plain text -- otherwise a superscript citation glued to a
period (`"...a chip.22 Real-time..."`) makes the gold boundary
unrepresentable at a token start, and training would silently drop
exactly the hard cases this corpus exists for. A gold offset that lands
inside an elided citation span, or on the whitespace left behind by one,
is snapped forward to the next real token start.

`senter_v4` was trained on `train/` alone (`pmc_train.spacy`, 3095 docs,
8243 sentences) with `validation/` as the dev set for model selection
(`pmc_val.spacy`) -- no GENIA this round. Scored via `evaluate_senter.py`
(now accepting `--pmc_eval_dir` for the one-file-per-article schema,
flattened to the same entry shape `--pmc_eval` uses):

|              | difficult_cases.json | validation/ |
|--------------|----------------------|-------------|
| senter_v3    | F1 0.9384 (18 FP/3 FN) | F1 0.9885 (160 FP/0 FN) |
| senter_v4    | F1 0.9786 (4 FP/3 FN)  | F1 0.9831 (52 FP/177 FN) |

Clean win on `difficult_cases.json` (same recall, false positives
18 -> 4). `validation/` is more mixed: `senter_v4` has real recall loss
that survived the gold-data corrections above. `train/` has 90 examples
of `Fig. N` appearing mid-sentence (correctly not split) against only 2
where it's genuinely sentence-final -- without GENIA's `_SENTENCE_FINAL`
counterexamples (`prepare_senter_corpus.py`) balancing that out, the
model over-generalised to "never split after `Fig. N`", which alone
accounts for ~76 of the missed boundaries (concentrated in `PMC4847587`,
`PMC4226470`). Not yet fixed -- see Open follow-ups in `LOG.md`.

## Retraining: senter_v5

Retrained after `train/` grew to 100 articles (round 2, above) and both
the round-1 `train/` and `validation/` corpora got the single-capital-
initial fix -- `pmc_train.spacy` is now 6283 docs/20043 sentences,
`pmc_val.spacy` 3378 docs, both regenerated via
`prepare_pmc_senter_corpus.py` against the corrected corpora. Same setup
as `senter_v4` otherwise (`train/` only, no GENIA; `validation/` as the
dev set):

|              | difficult_cases.json | validation/ |
|--------------|----------------------|-------------|
| senter_v3    | F1 0.9384 (18 FP/3 FN) | F1 0.9885 (160 FP/0 FN) |
| senter_v4    | F1 0.9786 (4 FP/3 FN)  | F1 0.9831 (52 FP/177 FN) |
| senter_v5    | F1 0.9877 (1 FP/3 FN)  | F1 0.9832 (114 FP/116 FN) |

Clean win on `difficult_cases.json` again (false positives 4 -> 1, same
recall). `validation/` F1 is essentially flat vs. `senter_v4` (0.9832 vs
0.9831) but the error balance shifted: FN dropped from 177 to 116 while
FP rose from 52 to 114, consistent with round 2's more diverse `Fig. N`
examples partially correcting the over-generalised "never split after
`Fig. N`" behaviour noted above -- not confirmed by re-diagnosis, and the
imbalance itself hasn't been directly fixed, so this is likely still a
partial improvement rather than a resolved gap. `senter_v3` still edges
out both retrained models on `validation/` alone (0.9885), but trails
badly on `difficult_cases.json` (0.9384), the set this project actually
cares about getting right.

`senter_v5` is the model biosenter ships as its bundled default
(`biosenter/model/`) -- see the package README for how `BIOSENTER_MODEL`
can override it with a different trained model.

## Known gap




The sample contains **no** HGVS variants (`p.G2019S`, `c.343A>G`) --
there are only 4 HGVS mentions in the whole 182-article batch this was
originally built from. That class is currently verified by spot-check
only, not by this set. Closing that gap needs paragraphs drawn from
clinical-genetics articles, which this batch barely contains. (`Fig.`
itself is no longer a gap -- the fourth batch added several instances,
including the `Fig. N` + panel-letter mistake pattern above.)

## Usage

```
python scripts/evaluate_senter.py \
  --models rule biosenter/model \
  --pmc_eval corpora/difficult_cases.json --verbose
```
