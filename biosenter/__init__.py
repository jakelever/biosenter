from biosenter._model import resolve_model_path
from biosenter.sentences import doc_to_sentence_records, split_into_sentences

__all__ = ['split_into_sentences', 'doc_to_sentence_records', 'load']


def load(**overrides):
	"""Entry point for `spacy.load("biosenter")` -- spaCy resolves a name
	that isn't a path by checking whether a package with that name is
	installed, then calling `<package>.load(...)`, so this makes the
	bundled model loadable directly through spaCy's own API, with no
	import of `biosenter` in the caller's code:

		import spacy
		nlp = spacy.load("biosenter")

	This returns the raw senter pipeline -- appropriate for markup-free
	text (e.g. plain PubMed abstracts, or any text you already know has no
	inline markup/citation spans in it), where it behaves identically to
	split_into_sentences(). It does *not* include split_into_sentences()'s
	markup-stripping or citation-reattachment steps, which have no
	well-defined equivalent as a plain spaCy pipeline (see README) --
	for real PMC full text with inline markup, use
	biosenter.split_into_sentences() instead of this.
	"""
	import spacy
	return spacy.load(resolve_model_path(), **overrides)
