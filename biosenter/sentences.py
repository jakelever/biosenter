import spacy

from biosenter._model import resolve_model_path
from biosenter.markup import marked_offsets, render, strip_markup

_NLP = None

# Characters allowed to sit between a sentence-final full stop and a
# citation marker that still belongs to that sentence: whitespace, the
# brackets some publishers wrap citations in, and the separators between
# consecutive markers ("[1], [2]" / ".1,2").
_CITATION_GAP_CHARS = ' \t [(,;'
_CITATION_CLOSE_CHARS = ' \t ])'


def _get_nlp(model=None):
	"""The sentence splitter to use. `model` overrides everything else --
	an already-loaded spaCy Language, for a caller (evaluate_senter.py)
	that wants to run a *specific* model rather than the default, e.g. to
	compare several in one process.

	With no override: the model BIOSENTER_MODEL points at, or the model
	bundled with this package install, cached at module level since this
	is the hot path for bulk PMC/PubMed extraction."""
	if model is not None:
		return model

	global _NLP
	if _NLP is None:
		_NLP = spacy.load(resolve_model_path())
	return _NLP


def _segment(plain, model=None):
	"""Plain text -> [(start, end), ...] sentence bounds, offsets into plain.

	Newlines are hard boundaries. bioconverters collapses all whitespace, so
	real PMC/PubMed text extracted through it never contains one; this only
	matters for callers whose text can
	legitimately carry a literal '\n' from elsewhere, where the sentencizer
	would otherwise run a whole bullet list together into one
	pseudo-sentence, since list items rarely carry terminal punctuation of
	their own.
	"""
	nlp = _get_nlp(model)
	bounds = []
	offset = 0
	for line in plain.split('\n'):
		if line.strip():
			for sent in nlp(line).sents:
				start, end = sent.start_char, sent.end_char
				if plain[offset + start:offset + end].strip():
					bounds.append((offset + start, offset + end))
		offset += len(line) + 1
	return bounds


def _citation_run_end(plain, spans, position, limit):
	"""If a run of bibliographic citation markers starts at `position`,
	return the offset just past it, else None.

	Publishers routinely set citations *after* the full stop that ends the
	sentence they belong to -- "...in every region of a chip.22 Real-time
	mapping..." for superscript styles, "...was observed. [31] The next..."
	for bracketed ones. Splitting on the stop alone strands the citation at
	the head of the following sentence, attributing it to the wrong claim.
	Because the markers survive as <citation> markup (bioconverters'
	inject_citations=True) rather than as bare digits, they can be
	recognised exactly instead of guessed at from the text.
	"""
	citations = {span.start: span for span in spans if span.tag == 'citation'}

	cursor = position
	found = False
	while cursor < limit:
		if cursor in citations:
			cursor = citations[cursor].end
			found = True
			continue
		if plain[cursor] in (_CITATION_GAP_CHARS if not found else _CITATION_GAP_CHARS + _CITATION_CLOSE_CHARS):
			# Only cross a gap that actually leads to another marker.
			ahead = cursor
			while ahead < limit and plain[ahead] in _CITATION_GAP_CHARS + _CITATION_CLOSE_CHARS:
				ahead += 1
			if ahead in citations:
				cursor = ahead
				continue
			# Trailing brackets/punctuation that close a run we already found.
			if found:
				while cursor < limit and plain[cursor] in _CITATION_CLOSE_CHARS + '.':
					if plain[cursor] in ' \t ':
						break
					cursor += 1
			break
		break

	return cursor if found else None


def _attach_trailing_citations(plain, spans, bounds):
	"""Move any citation markers stranded at the start of a sentence back
	onto the sentence before them (see _citation_run_end)."""
	if not any(span.tag == 'citation' for span in spans):
		return bounds

	adjusted = []
	for start, end in bounds:
		if adjusted:
			run_end = _citation_run_end(plain, spans, start, end)
			if run_end is not None:
				previous_start, _previous_end = adjusted[-1]
				adjusted[-1] = (previous_start, run_end)
				start = run_end
				while start < end and plain[start] in ' \t ':
					start += 1
				if start >= end:
					continue
		adjusted.append((start, end))
	return adjusted


def _bibr_spans(spans):
	return [span for span in spans if span.tag == 'citation']


def _elide_citations(plain, spans):
	"""Plain text -> (text_without_citation_markers, model_to_plain_offsets).

	The marker text itself is hidden from the splitter, not just its tags.
	Superscript-style citations leave no space behind them ("...region of a
	chip.22 Real-time mapping..."), so the splitter sees "chip.22" as a
	single token and never offers a boundary there at all -- there would be
	nothing for _attach_trailing_citations() to move. With the marker
	removed the same text reads "...a chip. Real-time mapping...", which
	splits normally, and the offset map puts the marker back on the end of
	the sentence it belongs to.
	"""
	parts = []
	mapping = []
	position = 0
	for span in sorted(_bibr_spans(spans), key=lambda span: span.start):
		if span.start < position:
			continue
		parts.append(plain[position:span.start])
		mapping.extend(range(position, span.start))
		position = span.end
	parts.append(plain[position:])
	mapping.extend(range(position, len(plain)))
	mapping.append(len(plain))
	return ''.join(parts), mapping


def _merge_boundaries_inside_spans(spans, bounds):
	"""Drop any boundary between two adjacent sentences that falls strictly
	inside a markup span, merging them back into one sentence.

	A proposed boundary landing between "S." and "pneumoniae" inside
	<italic>S. pneumoniae</italic> is a splitter false positive on exactly
	the kind of abbreviation this project exists to get right, not a
	legitimate place to end a sentence -- "S. pneumoniae" appears 73 times
	in one 182-article PMC batch, so this is a real risk, not a
	hypothetical one. It also keeps render()'s output faithful to the
	original text: closing a span early to honour a mid-span boundary is
	still well-formed XML, but it is no longer the same text.
	"""
	if not spans or len(bounds) < 2:
		return bounds

	merged = [bounds[0]]
	for start, end in bounds[1:]:
		boundary = merged[-1][1]
		if any(span.start < boundary < span.end for span in spans):
			merged[-1] = (merged[-1][0], end)
		else:
			merged.append((start, end))
	return merged


def split_into_sentences(text, model=None):
	"""Split text into sentences, returning a list of (start, end, sentence_text)
	tuples with character offsets relative to the start of text.

	Inline markup (biosenter/markup.py) is hidden from the splitter and
	restored afterwards, so the model never sees tags but the returned
	sentences keep them, and the offsets refer to `text` as passed in.
	Text with no markup is unaffected.

	`model` picks a specific spaCy Language to split with, overriding the
	default (BIOSENTER_MODEL, or the bundled model) -- see _get_nlp()."""
	plain, spans = strip_markup(text)
	model_text, model_to_plain = _elide_citations(plain, spans)
	bounds = [(model_to_plain[start], model_to_plain[end]) for start, end in _segment(model_text, model)]
	bounds = _attach_trailing_citations(plain, spans, bounds)
	bounds = _merge_boundaries_inside_spans(spans, bounds)
	if plain == text:
		# Optimisation: bounds are already offsets into `text` itself, and
		# there's nothing for render() to re-escape, so skip straight to
		# slicing. Deliberately `plain == text`, not `not spans` -- those
		# aren't equivalent: text with entities but no tags (e.g. "account
		# for &gt;98%") has no spans either, but strip_markup() still
		# decodes it, so `plain` is shorter than `text` and `bounds` are
		# offsets into the *decoded* string. Slicing `plain` directly would
		# be correct text but wrong offsets; falling through to render()
		# below re-escapes and remaps them back onto `text` correctly.
		return [(start, end, plain[start:end]) for start, end in bounds]

	offsets = marked_offsets(plain, spans, [offset for bound in bounds for offset in bound])
	return [(offsets[start], offsets[end], render(plain, spans, start, end)) for start, end in bounds]
