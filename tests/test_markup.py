from biosenter.markup import render, strip_markup


def test_no_markup_is_returned_untouched():
	text = "Particles under <5 nm were observed."
	plain, spans = strip_markup(text)
	assert plain == text
	assert spans == []


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
