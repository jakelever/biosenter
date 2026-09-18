import json
from pathlib import Path

from evaluate_senter import parse_boundaries

from biosenter.sentences import split_into_sentences

_DIFFICULT_CASES = Path(__file__).resolve().parent.parent / 'corpora' / 'difficult_cases.json'


def _entries_by_pmcid():
	entries = json.loads(_DIFFICULT_CASES.read_text(encoding='utf8'))
	return {entry['pmcid']: entry for entry in entries}


def _assert_splits_correctly(entry):
	text, gold_starts = parse_boundaries(entry['text'])
	predicted_starts = {start for start, _end, _text in split_into_sentences(text)}
	assert predicted_starts == set(gold_starts)


def test_abbreviation_period_not_a_boundary():
	# Plain examples, independent of the bundled model, exercising the
	# citation/markup-handling logic directly.
	text = "As shown in Fig. 1, expression increased. A second effect was seen in Fig. 2."
	sentences = [s for _start, _end, s in split_into_sentences(text)]
	assert sentences == [
		"As shown in Fig. 1, expression increased.",
		"A second effect was seen in Fig. 2.",
	]


def test_trailing_citation_marker_stays_attached():
	text = (
		'It was observed in every region of the sample.<citation ref-id="b1">22</citation> '
		'Real-time mapping confirmed this.'
	)
	sentences = [s for _start, _end, s in split_into_sentences(text)]
	assert sentences == [
		'It was observed in every region of the sample.<citation ref-id="b1">22</citation>',
		'Real-time mapping confirmed this.',
	]


def test_boundary_inside_italic_span_is_merged():
	text = "This concerns <italic>S. pneumoniae</italic> and related species."
	sentences = [s for _start, _end, s in split_into_sentences(text)]
	assert len(sentences) == 1
	assert sentences[0] == text


def test_bundled_model_matches_hand_labelled_difficult_cases():
	entries = _entries_by_pmcid()
	# A representative sample spanning ordinary prose, an abbreviation
	# trigger (Fig. N + panel letter), and a trailing-citation case --
	# not the full 51-paragraph set (that's evaluate_senter.py's job),
	# just a fast smoke test that the packaged model + pipeline agree
	# with the gold data it was scored against.
	for pmcid in (8000011, 8000078, 8000136):
		_assert_splits_correctly(entries[pmcid])
