import re

from biosenter.markup import Span, render, strip_markup


def test_no_markup_is_returned_untouched():
	text = "Particles under <5 nm were observed."
	plain, spans = strip_markup(text)
	assert plain == text
	assert spans == []


def test_bare_ampersand_is_returned_untouched():
	# Not well-formed XML (a bare '&' must start a valid entity reference),
	# same "never meant to be markup" case as a bare '<' above -- must
	# fall back to verbatim rather than raise.
	text = "Tukey & Fisher"
	plain, spans = strip_markup(text)
	assert plain == text
	assert spans == []


def test_round_trip_identity_for_escaped_text_with_no_tags():
	# Regression test: strip_markup() used to skip parsing entirely for
	# text with no recognised tags, so the entity decoding a real parse
	# does ('&gt;' -> '>') never happened -- but render() has no matching
	# skip and always re-escapes, so a strip-then-render round trip used
	# to silently double-escape this class of input ('&gt;' -> '&amp;gt;').
	for text in ("account for &gt;98% of cases", "Tukey &amp; Fisher"):
		plain, spans = strip_markup(text)
		assert render(plain, spans) == text


def test_round_trip_preserves_inline_markup():
	text = "<italic>S. pneumoniae</italic> causes disease."
	plain, spans = strip_markup(text)
	assert plain == "S. pneumoniae causes disease."
	assert render(plain, spans) == text


def test_round_trip_with_nested_and_multiple_spans():
	text = "See <citation>1</citation> and <sup>2+</sup> for Ca<sup>2+</sup>."
	plain, spans = strip_markup(text)
	assert render(plain, spans) == text


def test_render_clips_spans_to_requested_range():
	text = "<italic>Escherichia coli</italic> grows fast."
	plain, spans = strip_markup(text)
	# "Escherichia" ends at index 11 in the plain text, inside the italic span.
	clipped = render(plain, spans, 0, 11)
	assert clipped == "<italic>Escherichia</italic>"


def _respace_empty_tags(marked_up_text):
	# ET.tostring() always serialises an empty element as "<tag />" (with a
	# space before the self-closing slash), regardless of how it was
	# originally written -- a standard, harmless DOM-serialisation quirk,
	# not a content difference. Normalise it away for exact-text assertions.
	return re.sub(r'<(\w+)\s*/>', r'<\1/>', marked_up_text)


def test_zero_width_tag_round_trips():
	# Regression test: render()'s clip check used interval-overlap semantics
	# (max(span.start, start) < min(span.end, end)), which is never true for
	# a zero-width span (start == end, a self-closing tag with no content,
	# e.g. <br/>) regardless of where it sits -- silently dropping it from
	# every render() call, not just ones outside the requested range.
	text = "First line.<br/>Second line."
	plain, spans = strip_markup(text)
	assert plain == "First line.Second line."
	assert spans == [Span('br', {}, 11, 11)]
	assert _respace_empty_tags(render(plain, spans)) == text


def test_zero_width_tag_outside_requested_range_is_excluded():
	text = "AAA<br/>BBBBBBBBBB"
	plain, spans = strip_markup(text)
	# The marker sits at plain-offset 3; a range starting after it shouldn't
	# see it, the same as any other span entirely outside [start, end).
	assert '<br' not in render(plain, spans, 4, len(plain))


def test_zero_width_tag_at_a_range_boundary_appears_exactly_once():
	# Half-open [start, end) semantics, consistent with the rest of this
	# function's contract (and with plain[start:end] slicing): a marker
	# sitting exactly on the boundary between two adjacent render() calls
	# belongs to the one that *starts* there, not the one that just ended --
	# it must not be duplicated across both, or dropped by both.
	text = "AAA<br/>BBB"
	plain, spans = strip_markup(text)
	before = render(plain, spans, 0, 3)
	after = render(plain, spans, 3, len(plain))
	assert '<br' not in before
	assert '<br' in after
