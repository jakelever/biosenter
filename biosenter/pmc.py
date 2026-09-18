from bioconverters import parse_pmcxml
from bioconverters.pmc_constants import PMC_KEEP_TAGS

# The six PMCArticle text fields, in the order they should appear in a doc's
# section list. Also doubles as the full set of `section` values a PMC
# sentence record can carry -- see biosenter/sentences.py.
_SECTION_NAMES = ('title', 'subtitle', 'abstract', 'article', 'back', 'floating')


def parse_pmc_articles(path):
	"""Parse a JATS XML file (e.g. fetch_pmc.py output) into doc records:
	{'doc_id', 'source': 'pmc', 'sections': [{'name', 'text'}, ...]}, one
	per usable article. A generator (not a single doc) because one file can
	contain a main article plus sub-articles, each yielded separately.
	`name` is one of title/subtitle/abstract/article/back/floating -- the
	coarse categories bioconverters exposes; there is no sub-section
	heading or sec-type available below that (see spans_and_trees.
	spans_to_passages, which returns passage text/spans only, nothing about
	the enclosing element). Section text carries inline markup -- see
	biosenter/markup.py. An article with no PMC id or no usable text is
	skipped rather than yielded."""
	for article in parse_pmcxml(
		path,
		return_xml=True,
		keep_tags=PMC_KEEP_TAGS,
		inject_citations=True,
		clean_numeric_citations=False,
		clean_xrefs_in_brackets=False,
		clear_empty_brackets=False,
		fix_exponentials=False,
	):
		doc_id = article.pmcid
		if doc_id and not doc_id.upper().startswith('PMC'):
			# The DTD-standard pub-id-type="pmcid" case already carries the
			# "PMC" prefix; this only fires for a publisher using the older
			# bare-digit pub-id-type="pmc" convention (see fetch_pmc.py's
			# normalize_key, which does the same thing on the fetch side).
			doc_id = f'PMC{doc_id}'

		sections = [
			{'name': name, 'text': text}
			for name in _SECTION_NAMES
			for text in article.iter_text([name])
		]

		if not doc_id or not sections:
			continue
		yield {'doc_id': doc_id, 'source': 'pmc', 'sections': sections}
