import json
from pathlib import Path

from evaluate_senter import parse_boundaries

from biosenter.sentences import split_into_sentences

_TEST_CORPUS = Path(__file__).resolve().parent.parent / 'corpora' / 'test'


def _assert_splits_correctly(record):
	for passage in record['passages']:
		text, gold_starts = parse_boundaries(passage['text'])
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


def test_bundled_model_matches_hand_labelled_test_corpus():
	# A couple of small, representative articles from corpora/test/ -- not
	# the full 75-article set (that's evaluate_senter.py's job), just a
	# fast smoke test that the packaged model + pipeline agree with the
	# gold data it was scored against.
	for pmcid in ('PMC6840524', 'PMC4368106', 'PMC3479843'):
		record = json.loads((_TEST_CORPUS / f'{pmcid}.json').read_text(encoding='utf8'))
		_assert_splits_correctly(record)
