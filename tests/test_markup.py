from biosenter.markup import render, strip_markup


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
