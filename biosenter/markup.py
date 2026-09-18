"""Inline markup carried inside extracted text.

Some JATS markup is meaningful and can't be recovered once flattened:
<italic> distinguishes a gene symbol from its protein and marks binomial
species names, <citation> (bioconverters' resolved-and-retagged bibr
<xref>, see biosenter/pmc.py) says "this number is a citation marker, not
prose", and <sup>/<sub> carry chemical and mathematical notation
(Ca<sup>2+</sup>, IC<sub>50</sub>) as well as genuine exponents
(5 x 10<sup>5</sup>/well) that read as a different, wrong number once
the tag is discarded. These and bioconverters' other formatting tags
(PMC_KEEP_TAGS: bold, underline, monospace, sc, overline, strike) are all
kept inline in the extracted text rather than in a parallel field, so a
sentence string stays self-contained as it moves through the pipeline and
into the UI -- and, deliberately, so nothing reaches for "strip it back to
plain text" as a default shortcut. If something downstream genuinely
cannot consume markup (a pretrained tokenizer that has never seen these
tags, for instance), that is a real gap to close at that boundary
specifically, not a reason to discard markup upstream -- see ROADMAP.md.

The extracted text is well-formed XML: everything emitted as literal
text (as opposed to one of the tags below) is entity-escaped, so any
standard XML parser can read it. biosenter/pmc.py's underlying extractor
(bioconverters) escapes at the point text is first extracted from JATS
source; this module escapes again wherever it synthesises new marked-up
text (render()).

`strip_markup()` parses marked-up text into (plain_text, spans) using
the standard library's XML parser; `render()` goes the other way for any
character range of the plain text. That round trip is what lets the
sentence splitter (biosenter/sentences.py) run its model on clean text
and still emit marked-up sentences.
"""

import re
import xml.etree.ElementTree as ET

from bioconverters.pmc_constants import PMC_KEEP_TAGS

# Only these tags are markup. Unlike the lenient regex parser this module
# used to use, a standard XML parser has no "leave it as text" fallback
# for something unrecognised -- an unescaped '<' or a stray tag is a real
# bug upstream (almost certainly in the escaping done at extraction time),
# not text to shrug off, so it surfaces as ET.ParseError rather than being
# silently absorbed as literal text. Derived from bioconverters' own
# PMC_KEEP_TAGS (the keep_tags biosenter/pmc.py passes to parse_pmcxml)
# plus 'citation' (what inject_citations=True retags a resolved bibr xref
# to) rather than hardcoded, so the two can't silently drift apart.
TAGS = tuple(sorted(PMC_KEEP_TAGS)) + ('citation',)

# Only biosenter/pmc.py's own output escapes literal '<'/'&'. This module
# is shared by callers whose text was never meant to carry any markup at
# all (MedMentions, tmVar -- raw BioC/PubTator text passed straight into
# split_into_sentences()), and that text legitimately contains a bare '<'
# ("particles <5 nm"). Requiring it to be well-formed XML would break
# every one of those callers over ordinary prose that happens to contain
# our tag names nowhere. So a string is only ever run through the strict
# XML parser if it could plausibly contain one of *our* tags in the first
# place; otherwise it is returned untouched, with no spans -- "this text
# is well-formed" is a property biosenter/pmc.py's own output has to earn,
# not one every string passed to this module is assumed to have.
_LOOKS_LIKE_MARKUP_RE = re.compile('|'.join(rf'</?{tag}\b' for tag in TAGS))

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


def strip_markup(text):
	"""Marked-up text -> (plain_text, [Span, ...]) with span offsets
	relative to plain_text. Text containing none of TAGS is returned
	untouched with no spans, without being parsed as XML at all -- see the
	note on _LOOKS_LIKE_MARKUP_RE."""
	if not _LOOKS_LIKE_MARKUP_RE.search(text):
		return text, []

	root = _parse(text)
	parts = []
	spans = []
	length = 0

	def emit(chunk):
		nonlocal length
		if chunk:
			parts.append(chunk)
			length += len(chunk)

	def walk(element):
		emit(element.text)
		for child in element:
			start = length
			walk(child)
			spans.append(Span(child.tag, dict(child.attrib), start, length))
			emit(child.tail)

	walk(root)
	spans.sort(key=lambda span: (span.start, -span.end))
	return ''.join(parts), spans


def _nest(flat_spans):
	"""Flat spans, sorted by (start, -end) and properly nested (guaranteed
	by coming from a real parse) -> [(span, [nested children]), ...] for
	the top-level ones, so render() can rebuild an element tree instead of
	hand-tracking an open/close stack."""
	remaining = list(flat_spans)

	def consume(limit):
		items = []
		while remaining and remaining[0].start < limit:
			span = remaining.pop(0)
			items.append((span, consume(span.end)))
		return items

	return consume(float('inf'))


def _fill(parent, cursor, limit, plain, nested):
	"""Fill `parent` (an ET.Element) with text/children built from `plain`
	between `cursor` and `limit`, consuming `nested` (see _nest()).

	Text is assigned to .text/.tail *unescaped* -- ET.tostring() escapes
	special characters in element text automatically during serialisation,
	so escaping it here too would double-escape ('&lt;' -> '&amp;lt;')."""
	position = cursor
	last_child = None
	for span, children in nested:
		gap = plain[position:span.start]
		if last_child is None:
			parent.text = (parent.text or '') + gap
		else:
			last_child.tail = (last_child.tail or '') + gap
		child = ET.SubElement(parent, span.tag, span.attrs)
		_fill(child, span.start, span.end, plain, children)
		last_child = child
		position = span.end

	gap = plain[position:limit]
	if last_child is None:
		parent.text = (parent.text or '') + gap
	else:
		last_child.tail = (last_child.tail or '') + gap


def render(plain, spans, start=0, end=None):
	"""(plain_text, spans) -> marked-up text for plain[start:end], with any
	span overlapping that range clipped to it. The inverse of
	strip_markup() when called over the whole string."""
	if end is None:
		end = len(plain)

	clipped = []
	for span in spans:
		span_start = max(span.start, start)
		span_end = min(span.end, end)
		if span_start < span_end:
			clipped.append(Span(span.tag, span.attrs, span_start, span_end))
	clipped.sort(key=lambda span: (span.start, -span.end))

	root = ET.Element(_ROOT)
	_fill(root, start, end, plain, _nest(clipped))

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
