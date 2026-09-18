"""Convert corpora/train/ (or validation/) into spaCy training data
for the sentence splitter, the same one-file-per-article, hand-corrected
corpus documented in corpora/README.md.

Each passage's `text` carries real inline markup (biosenter/markup.py)
plus `<sentence_start/>` markers. The model itself is never shown either:
biosenter.sentences.split_into_sentences() strips markup and elides
citation markers before handing text to the trained spaCy component,
then reattaches citations and repairs mid-span boundaries afterwards as a
separate, non-learned step (see biosenter/sentences.py). Training data
has to go through the same transformation, or the model would be trained
on a different distribution than the one it is run on -- most visibly for
superscript citations glued to a period ("...a chip.22 Real-time..."),
where the gold boundary doesn't land on a token start until the citation
digits are removed from view.

`<sentence_start/>` isn't in biosenter/markup.py's TAGS, but strip_markup()
parses whatever well-formed tags are present regardless -- passing text
that still has the marker in it turns each one into an ordinary
zero-width Span (tag='sentence_start'), which is a convenient way to get
its plain-text offset for free rather than hand-rolling a second parser.
"""

import argparse
import bisect
import glob
import json
from pathlib import Path

import spacy
from spacy.tokens import DocBin

from biosenter.markup import strip_markup
from biosenter.sentences import _elide_citations


def _model_offsets(plain, spans):
	"""(plain_text, spans) -> (model_text, gold_model_offsets), applying
	the same citation elision the production splitter runs before
	tokenizing, and carrying the gold `sentence_start` offsets through it.

	A gold offset that lands inside an elided citation span (rare, but
	possible if a sentence boundary was placed right at a citation's
	start) is snapped to the nearest kept position before it -- the same
	place _attach_trailing_citations() would put a predicted boundary.
	"""
	model_text, model_to_plain = _elide_citations(plain, spans)
	gold_plain = sorted({0} | {span.start for span in spans if span.tag == 'sentence_start'})
	gold_model = []
	for offset in gold_plain:
		index = bisect.bisect_right(model_to_plain, offset) - 1
		gold_model.append(max(index, 0))
	return model_text, sorted(set(gold_model))


def _snap_past_whitespace(offset, text):
	"""A boundary computed from an elided citation's start can land on a
	run of whitespace rather than the next word -- eliding "<citation>...
	</citation> published" leaves "  published" where the marker pointed
	at the first space, not the token start. Advance past whitespace so
	the offset lands where a token (never whitespace itself) can start."""
	while offset < len(text) and text[offset].isspace():
		offset += 1
	return offset


def _make_doc(nlp, model_text, gold_model_offsets):
	"""-> Doc with gold sentence starts set, or None if a boundary doesn't
	land on a token start (unrepresentable to a senter, which can only
	predict boundaries between tokens)."""
	gold_model_offsets = sorted({_snap_past_whitespace(offset, model_text) for offset in gold_model_offsets})
	doc = nlp.make_doc(model_text)
	token_starts = {token.idx for token in doc}
	if not set(gold_model_offsets) <= token_starts:
		return None
	for token in doc:
		token.is_sent_start = token.idx in gold_model_offsets
	return doc


def build_doc_bin(corpus_dir, nlp):
	doc_bin = DocBin()
	n_docs = n_sentences = n_skipped = 0
	for path in sorted(glob.glob(f'{corpus_dir}/*.json')):
		record = json.load(open(path, encoding='utf8'))
		for passage in record['passages']:
			plain, spans = strip_markup(passage['text'])
			model_text, gold_model_offsets = _model_offsets(plain, spans)
			doc = _make_doc(nlp, model_text, gold_model_offsets)
			if doc is None:
				n_skipped += 1
				continue
			doc_bin.add(doc)
			n_docs += 1
			n_sentences += len(gold_model_offsets)
	return doc_bin, n_docs, n_sentences, n_skipped


def main():
	parser = argparse.ArgumentParser(description='Build spaCy senter training data from corpora/train or validation')
	parser.add_argument('--corpus_dir', required=True, type=str, help='corpora/train or corpora/validation')
	parser.add_argument('--out_path', required=True, type=str, help='Output .spacy file')
	args = parser.parse_args()

	nlp = spacy.blank('en')
	doc_bin, n_docs, n_sentences, n_skipped = build_doc_bin(args.corpus_dir, nlp)

	out_path = Path(args.out_path)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	doc_bin.to_disk(out_path)

	print(f"{out_path}: {n_docs} docs, {n_sentences} sentences")
	if n_skipped:
		print(f"Skipped {n_skipped} passages whose boundaries don't land on token starts")


if __name__ == '__main__':
	main()
