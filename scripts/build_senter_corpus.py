"""Turn fetched PMC XML (scripts/fetch_pmc.py) into corpus/{train,validation,
test} JSON records, with sentence boundaries bootstrapped from the current
model rather than left for a human to place from scratch.

The output is the schema documented in corpus/README.md -- one
`PMC<id>.json` per article, `{pmid, pmcid, source, passages}` -- with a
`<sentence_start/>` marker at the start of every sentence after the first.
Those markers are a *draft*: the model is ~99% right per boundary, which
still leaves a couple of errors per article, so every batch produced here
has to go through the screen-and-correct pass described in
corpus/README.md before it is worth training or scoring on.

Passages are kept separate (one entry per abstract paragraph, body
paragraph, caption, ...) rather than joined into one string the way
bioconverters' own pmcxml2tagged() does, since that is the unit the corpus
stores and the unit the splitter is run on. Everything else about the
extraction -- kept tags, injected citations, no bracket/exponent cleanup --
matches pmcxml2tagged() exactly, so corpus text is the same text a caller
following the top-level README's example would get.
"""

import argparse
import glob
import json
from pathlib import Path

from bioconverters import parse_pmcxml
from bioconverters.pmc_constants import PMC_KEEP_TAGS

from biosenter.sentences import split_into_sentences

# Also pmcxml2tagged()'s default, and the order corpus records store
# passages in: an article reads title-first.
SECTIONS = ('title', 'subtitle', 'abstract', 'article', 'back', 'floating')

_MARKER = '<sentence_start/>'


def tagged_articles(xml_path):
	"""One PMC XML file -> [(PMCArticle, [(section, marked_up_text), ...])].

	A file can hold sub-articles (commentaries, corrections) alongside the
	main one, so this yields a list, not a single article."""
	articles = []
	for doc in parse_pmcxml(
		str(xml_path),
		keep_tags=PMC_KEEP_TAGS,
		return_xml=True,
		inject_citations=True,
		clean_numeric_citations=False,
		clean_xrefs_in_brackets=False,
		clear_empty_brackets=False,
		fix_exponentials=False,
	):
		passages = []
		for section in SECTIONS:
			value = getattr(doc, section)
			for text in ((value,) if isinstance(value, str) else value):
				if text:
					passages.append((section, text))
		articles.append((doc, passages))
	return articles


def mark_sentences(text, model=None):
	"""Marked-up passage text -> the same text with `<sentence_start/>`
	inserted at every sentence start after the first.

	Inserting into the tagged text (rather than recording offsets) is what
	makes the result reviewable by eye, and is the format
	evaluate_senter.py's parse_boundaries() reads back."""
	starts = [start for start, _end, _sentence in split_into_sentences(text, model=model) if start > 0]
	pieces = []
	cursor = 0
	for start in starts:
		pieces.append(text[cursor:start])
		pieces.append(_MARKER)
		cursor = start
	pieces.append(text[cursor:])
	return ''.join(pieces)


def _as_int(value):
	"""PMCArticle carries ids as strings, PMCIDs with their 'PMC' prefix
	and either as '' when absent; the corpus schema stores both as bare
	ints, or null."""
	digits = str(value or '').removeprefix('PMC')
	return int(digits) if digits.isdigit() else None


def build_record(doc, passages, model=None):
	return {
		'pmid': _as_int(doc.pmid),
		'pmcid': _as_int(doc.pmcid),
		'source': 'pmc',
		'passages': [
			{'section': section, 'text': mark_sentences(text, model=model)}
			for section, text in passages
		],
	}


def main():
	parser = argparse.ArgumentParser(description='Build bootstrapped corpus JSON records from fetched PMC XML')
	parser.add_argument('--xml_dir', required=True, type=str, help='Directory of PMC XML files from scripts/fetch_pmc.py')
	parser.add_argument('--out_dir', required=True, type=str, help='Corpus split to write into, e.g. corpus/test')
	parser.add_argument('--overwrite', action='store_true', help='Rewrite records that already exist in --out_dir (default: leave them alone, so a hand-corrected file is never clobbered by a re-run)')
	args = parser.parse_args()

	out_dir = Path(args.out_dir)
	out_dir.mkdir(parents=True, exist_ok=True)

	n_written = n_skipped = 0
	for xml_path in sorted(glob.glob(f'{args.xml_dir}/*.xml')):
		for doc, passages in tagged_articles(xml_path):
			pmcid = _as_int(doc.pmcid)
			if pmcid is None or not passages:
				print(f'  No PMCID/text, skipping: {xml_path}')
				continue
			out_path = out_dir / f'PMC{pmcid}.json'
			if out_path.exists() and not args.overwrite:
				n_skipped += 1
				continue
			record = build_record(doc, passages)
			# indent=1, no trailing newline: byte-for-byte what the existing
			# 300 records are formatted as.
			out_path.write_text(json.dumps(record, indent=1), encoding='utf8')
			n_written += 1
			print(f'{out_path}: {len(passages)} passages')

	print(f'Wrote {n_written} records to {out_dir}' + (f', left {n_skipped} existing ones alone' if n_skipped else ''))


if __name__ == '__main__':
	main()
