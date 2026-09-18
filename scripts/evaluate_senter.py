"""Score a sentence splitter against the hand-labelled PMC/PubMed eval set
(and, optionally, any other spaCy-Doc-boundary test set you supply).

corpora/difficult_cases.json exists precisely because generic
sentence-splitter benchmarks don't contain much of what actually breaks
this pipeline -- "Fig. 1", "et al.", "no. 21", "p.G2019S", "Cannabis
sativa L.", "St. Louis", "(N.A. 0.25)".

Scoring is on sentence *boundaries*, ignoring the trivial one at the start
of each text, so the numbers are not inflated by a decision no model can
get wrong.
"""

import argparse
import glob
import json
import re

import spacy
from spacy.tokens import DocBin

from biosenter.sentences import split_into_sentences

# Marks the start of every gold sentence after the first, directly inside
# corpora/difficult_cases.json's "text" field -- the first sentence
# always starts at 0, so it needs no marker. Scoped to this eval tooling
# rather than biosenter/markup.py's TAGS: it is a zero-width annotation
# artifact, never present in a real doc record, unlike <italic>/<xref>/
# <sup>/<sub> which flow through the production pipeline. Chosen over
# numeric offsets specifically so an LLM (or a person) can author/check
# boundaries by placing a tag at the right point in the text, rather than
# counting characters.
_SENTENCE_START_RE = re.compile(r'<sentence_start\s*/>')


def parse_boundaries(tagged_text):
	"""Text containing <sentence_start/> markers -> (text, [start_offset,
	...]), with the markers removed and offsets into the returned text.
	The returned text still carries ordinary <italic>/<xref>/<sup>/<sub>
	markup (see biosenter/markup.py) -- this only handles the marker tag
	above, not that."""
	parts = []
	starts = [0]
	position = 0
	cursor = 0
	for match in _SENTENCE_START_RE.finditer(tagged_text):
		chunk = tagged_text[cursor:match.start()]
		parts.append(chunk)
		position += len(chunk)
		starts.append(position)
		cursor = match.end()
	parts.append(tagged_text[cursor:])
	return ''.join(parts), starts


def _load_splitter(model):
	"""'rule' -> spaCy's rule-based sentencizer, otherwise a trained model."""
	if model == 'rule':
		nlp = spacy.blank('en')
		nlp.add_pipe('sentencizer')
		return nlp
	return spacy.load(model)


def _score(gold_and_predicted):
	"""[(gold_starts, predicted_starts), ...] -> (precision, recall, f1, counts)"""
	true_positives = false_positives = false_negatives = 0
	for gold, predicted in gold_and_predicted:
		# Drop the boundary at offset 0: every splitter gets it for free.
		gold = {offset for offset in gold if offset > 0}
		predicted = {offset for offset in predicted if offset > 0}
		true_positives += len(gold & predicted)
		false_positives += len(predicted - gold)
		false_negatives += len(gold - predicted)

	precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0
	recall = true_positives / (true_positives + false_negatives) if true_positives + false_negatives else 0.0
	f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
	return precision, recall, f1, (true_positives, false_positives, false_negatives)


def _evaluate_docbin(nlp, path):
	"""Score against a plain spaCy DocBin of gold-sentence-boundary Docs
	(e.g. built from your own labelled data) -- runs the model directly,
	not through split_into_sentences(), so it only makes sense for text
	with no biosenter markup/citation markers in it."""
	doc_bin = DocBin().from_disk(path)
	pairs = []
	for gold_doc in doc_bin.get_docs(nlp.vocab):
		gold = {sent.start_char for sent in gold_doc.sents}
		predicted = {sent.start_char for sent in nlp(gold_doc.text).sents}
		pairs.append((gold, predicted))
	return pairs


def _load_flat_entries(path):
	"""corpora/difficult_cases.json's schema: a flat list of
	{pmid, pmcid, source, section, text}."""
	with open(path, encoding='utf8') as f:
		return json.load(f)


def _load_dir_entries(dir_path):
	"""corpora/train or validation's schema: one file per article,
	{pmid, pmcid, source, passages: [{section, text}]}. Flattened to the
	same {pmid, pmcid, source, section, text} shape _evaluate_pmc expects,
	one entry per passage."""
	entries = []
	for path in sorted(glob.glob(f'{dir_path}/*.json')):
		with open(path, encoding='utf8') as f:
			record = json.load(f)
		for passage in record['passages']:
			entries.append({
				'pmid': record['pmid'], 'pmcid': record['pmcid'], 'source': record['source'],
				'section': passage['section'], 'text': passage['text'],
			})
	return entries


def _evaluate_pmc(nlp, entries, verbose=False):
	"""Runs through biosenter.sentences.split_into_sentences() -- the real
	production splitter, markup handling included -- rather than calling
	the spaCy model directly on entry['text']. That text carries real
	<italic>/<xref>/<sup>/<sub> markup (see biosenter/markup.py); feeding
	it to the model raw would tokenize the tags themselves (a citation's
	resolved DOI, e.g., contains a literal '.') and misrepresent how the
	deployed splitter actually behaves on this text."""
	pairs = []
	for entry in entries:
		text, gold = parse_boundaries(entry['text'])
		predicted = {start for start, _end, _text in split_into_sentences(text, model=nlp)}
		pairs.append((set(gold), predicted))
		if verbose:
			for offset in sorted(predicted - set(gold)):
				if offset > 0:
					print(f"  SPLIT MID-SENTENCE {entry['pmcid']}: ...{text[max(0, offset - 45):offset]!r}"
						f" | {text[offset:offset + 25]!r}")
			for offset in sorted(set(gold) - predicted):
				if offset > 0:
					print(f"  MISSED BOUNDARY    {entry['pmcid']}: ...{text[max(0, offset - 45):offset]!r}"
						f" | {text[offset:offset + 25]!r}")
	return pairs


def main():
	parser = argparse.ArgumentParser(description='Score sentence splitters on the hand-labelled PMC/PubMed eval set')
	parser.add_argument('--models', required=True, nargs='+', type=str,
		help="Model paths to score, and/or the literal 'rule' for the rule-based baseline")
	parser.add_argument('--docbin_test', default=None, type=str, help='An optional plain spaCy DocBin test set')
	parser.add_argument('--pmc_eval', default=None, type=str, help='corpora/difficult_cases.json')
	parser.add_argument('--pmc_eval_dir', default=None, type=str,
		help='corpora/validation or corpora/train (one file per article, {pmid,pmcid,source,passages})')
	parser.add_argument('--verbose', action='store_true', help='Print every individual error on the PMC set(s)')
	args = parser.parse_args()

	if not args.docbin_test and not args.pmc_eval and not args.pmc_eval_dir:
		parser.error('give at least one of --docbin_test / --pmc_eval / --pmc_eval_dir')

	print(f"{'model':28s} {'set':10s} {'P':>7s} {'R':>7s} {'F1':>7s}   {'TP/FP/FN'}")
	for model in args.models:
		nlp = _load_splitter(model)
		# A model-dir path (".../runs/senter_v5/model-best") names itself by its
		# parent directory; an installed package name (e.g. "en_core_web_sm") has
		# no parent segment to take, so falls back to the name as given.
		parts = model.rstrip('/').split('/')
		name = model if model == 'rule' else (parts[-2] if len(parts) > 1 else parts[-1])
		for label, pairs in (
			('docbin', _evaluate_docbin(nlp, args.docbin_test) if args.docbin_test else None),
			('pmc', _evaluate_pmc(nlp, _load_flat_entries(args.pmc_eval), args.verbose) if args.pmc_eval else None),
			('pmc_dir', _evaluate_pmc(nlp, _load_dir_entries(args.pmc_eval_dir), args.verbose) if args.pmc_eval_dir else None),
		):
			if pairs is None:
				continue
			precision, recall, f1, counts = _score(pairs)
			print(f'{name:28s} {label:10s} {precision:7.4f} {recall:7.4f} {f1:7.4f}   {counts[0]}/{counts[1]}/{counts[2]}')


if __name__ == '__main__':
	main()
