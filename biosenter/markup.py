"""Inline markup carried inside extracted text.

Some JATS markup is meaningful and can't be recovered once flattened:
<italic> distinguishes a gene symbol from its protein and marks binomial
species names, <citation> (bioconverters' resolved-and-retagged bibr
<xref>, see the README's bioconverters example) says "this number is a
citation marker, not prose", and <sup>/<sub> carry chemical and
mathematical notation (Ca<sup>2+</sup>, IC<sub>50</sub>) as well as
genuine exponents (5 x 10<sup>5</sup>/well) that read as a different,
wrong number once the tag is discarded. These and bioconverters' other
formatting tags (PMC_KEEP_TAGS: bold, underline, monospace, sc, overline,
strike) are all kept inline in the extracted text rather than in a
parallel field, so a sentence string stays self-contained as it moves
through the pipeline -- and, deliberately, so nothing reaches for "strip
it back to plain text" as a default shortcut. If something downstream
genuinely cannot consume markup (a pretrained tokenizer that has never
seen these tags, for instance), that is a real gap to close at that
boundary specifically, not a reason to discard markup upstream.

The extracted text is well-formed XML: everything emitted as literal
text (as opposed to one of the tags below) is entity-escaped, so any
standard XML parser can read it. bioconverters escapes at the point text
is first extracted from JATS source (see the README for
`pmcxml2tagged()`, the bioconverters function this module expects its
input to come from); this module escapes again wherever it synthesises
new marked-up text (render()).

`strip_markup()` parses marked-up text into (plain_text, spans) using
the standard library's XML parser; `render()` goes the other way for any
character range of the plain text. That round trip is what lets the
sentence splitter (biosenter/sentences.py) run its model on clean text
and still emit marked-up sentences. The tree<->span conversion itself
(walking a parsed element tree into flat spans, and back) is delegated
to `spans_and_trees` -- a small, focused sibling library (also used
internally by bioconverters) for exactly this, rather than a second
hand-rolled implementation of the same tree-walking logic living here.
This module still owns the string<->tree step (_parse()/_try_parse(),
i.e. deciding whether text is well-formed XML at all) and the `Span`
type everything outside this module uses.
"""

import xml.etree.ElementTree as ET

from bioconverters.pmc_constants import PMC_KEEP_TAGS
from spans_and_trees import spans_to_tree, tree_to_spans

# Only these tags are markup. Unlike the lenient regex parser this module
# used to use, a standard XML parser has no "leave it as text" fallback
# for something unrecognised -- an unescaped '<' or a stray tag is a real
# bug upstream (almost certainly in the escaping done at extraction time),
# not text to shrug off, so it surfaces as ET.ParseError rather than being
# silently absorbed as literal text. Derived from bioconverters' own
# PMC_KEEP_TAGS (pmcxml2tagged()'s default keep_tags) plus 'citation'
# (what its citation injection retags a resolved bibr xref to) rather
# than hardcoded, so the two can't silently drift apart.
TAGS = tuple(sorted(PMC_KEEP_TAGS)) + ('citation',)

# Synthetic wrapping element: text handed to this module is always a
# fragment (a sentence, a paragraph), never a single well-formed document
# with one root, so parsing/serialising always goes through this wrapper.
_ROOT = 'markup'


class Span:
	"""One markup element, with offsets into the *plain* text."""

	__slots__ = ('tag', 'attrs', 'start', 'end')

	def __init__(self, tag, attrs, start, end):
		self.tag = tag
		self.attrs = attrs
		self.start = start
		self.end = end

	def __repr__(self):
		return f'Span({self.tag!r}, {self.attrs!r}, {self.start}, {self.end})'

	def __eq__(self, other):
		return (isinstance(other, Span) and self.tag == other.tag and self.attrs == other.attrs
			and self.start == other.start and self.end == other.end)


def _parse(text):
	try:
		return ET.fromstring(f'<{_ROOT}>{text}</{_ROOT}>')
	except ET.ParseError as error:
		raise ValueError(
			f'not well-formed markup (only {TAGS} tags are recognised; literal text must be entity-escaped): {error}'
		) from error


def _try_parse(text):
	"""Like _parse(), but returns None instead of raising when text isn't
	well-formed XML -- for strip_markup(), which needs to tell "this was
	never meant to be markup at all" (a bare '<'/'&' in ordinary prose,
	e.g. "particles <5 nm") apart from a hard error, rather than raising
	on both alike the way _parse()'s other callers want."""
	try:
		return ET.fromstring(f'<{_ROOT}>{text}</{_ROOT}>')
	except ET.ParseError:
		return None


def strip_markup(text):
	"""Marked-up text -> (plain_text, [Span, ...]) with span offsets
	relative to plain_text. Text that isn't well-formed XML -- a bare
	'<'/'&' in ordinary prose that was never meant to carry markup -- is
	returned untouched with no spans instead of raising. Well-formed text
	with no recognised tags at all is still parsed, not skipped: entity
	decoding ('&gt;' -> '>') is part of what a real parse does, not just
	tag-stripping, and there is no cheap way to tell "well-formed, no
	tags, but has entities to decode" apart from "well-formed, no tags,
	nothing to decode" without just parsing it. render() has no
	equivalent skip and always re-escapes on the way back out, so
	skipping the parse here would silently double-escape a string like
	'account for &gt;98%' on a strip-then-render round trip."""
	root = _try_parse(text)
	if root is None:
		return text, []

	plain, span_tuples = tree_to_spans(root)
	spans = [Span(tag, attrs, offset, offset + length) for offset, length, tag, attrs in span_tuples]
	# tree_to_spans() sorts by (start, -length, tag) -- the trailing tag
	# tiebreak only matters for two sibling spans with byte-identical
	# start/end, which real markup never produces (see test_markup.py),
	# but re-sort to this module's own (start, -end) convention anyway so
	# spans' ordering doesn't depend on a tiebreak nothing else here uses.
	spans.sort(key=lambda span: (span.start, -span.end))
	return plain, spans


def render(plain, spans, start=0, end=None):
	"""(plain_text, spans) -> marked-up text for plain[start:end], with any
	span overlapping that range clipped to it. The inverse of
	strip_markup() when called over the whole string."""
	if end is None:
		end = len(plain)

	clipped = []
	for span in spans:
		if span.start == span.end:
			# A zero-width span (a self-closing tag with no content, e.g.
			# <br/> -- not just the corpus's <sentence_start/>
			# convention, any tag with no text between its open and close)
			# is a *point* annotation, not a range, so it needs point-
			# membership semantics here rather than interval overlap:
			# max(span.start, start) < min(span.end, end) is never true
			# for start == end, since an empty interval never "overlaps"
			# anything by that definition -- silently dropping every
			# zero-width span regardless of position, not just ones
			# outside [start, end). Half-open like the rest of this
			# function's own [start, end) contract, so a point exactly at
			# `end` belongs to whichever later call starts there instead
			# of appearing twice across adjacent render() calls.
			if start <= span.start < end:
				clipped.append((span.start - start, 0, span.tag, span.attrs))
			continue

		span_start = max(span.start, start)
		span_end = min(span.end, end)
		if span_start < span_end:
			# spans_to_tree() takes offsets relative to the text it's given,
			# not absolute ones -- shift by -start to match plain[start:end].
			clipped.append((span_start - start, span_end - span_start, span.tag, span.attrs))

	root = spans_to_tree(plain[start:end], clipped, root_tag=_ROOT)
	serialised = ET.tostring(root, encoding='unicode')
	return serialised[len(f'<{_ROOT}>'):-len(f'</{_ROOT}>')]


def marked_offsets(plain, spans, positions):
	"""Plain-text offsets -> the matching offsets in the marked-up text,
	i.e. marked_offsets(plain, spans, [p])[p] == len(render(plain, spans, 0, p)).

	Defined directly in terms of render() rather than a separate tally of
	tag lengths, so the two can never drift apart -- including when a
	position falls *inside* a span rather than at its boundary (a
	sentence-final period inside an italicised species abbreviation,
	"<italic>S. pneumoniae</italic>", say), where render() closes the tag
	early instead of leaving it dangling, and this has to agree exactly."""
	return {position: len(render(plain, spans, 0, position)) for position in sorted(set(positions))}


def spans_in(spans, start, end):
	"""The spans that overlap the plain-text range [start, end)."""
	return [span for span in spans if span.start < end and span.end > start]
