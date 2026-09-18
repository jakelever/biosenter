import spacy

from biosenter import split_into_sentences


def test_spacy_load_by_name_resolves_to_bundled_model():
	nlp = spacy.load('biosenter')
	assert 'senter' in nlp.pipe_names


def test_spacy_load_matches_split_into_sentences_on_markup_free_text():
	text = "As shown in Fig. 1, expression increased. A second effect was seen in Fig. 2."
	nlp = spacy.load('biosenter')
	via_spacy = [sent.text for sent in nlp(text).sents]
	via_biosenter = [sentence for _start, _end, sentence in split_into_sentences(text)]
	assert via_spacy == via_biosenter
