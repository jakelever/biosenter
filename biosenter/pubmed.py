import gzip

from bioconverters import parse_pubmedxml


def parse_pubmed_baseline(path):
	"""Stream-parse a gzipped PubMed baseline/update XML file (MEDLINE XML,
	unnamespaced), yielding one doc record per PubmedArticle with a title
	and/or abstract: {'doc_id', 'source': 'pubmed', 'sections': [{'name',
	'text'}]}. Articles with neither a PMID nor any title/abstract text are
	skipped. parse_pubmedxml always returns plain text (no return_xml/
	keep_tags option exists for it), matching this module's previous
	itertext()-only behavior."""
	with gzip.open(path, 'rt', encoding='utf8') as f:
		for article in parse_pubmedxml(f):
			sections = []
			if article.title:
				sections.append({'name': 'title', 'text': article.title})
			for text in article.abstract:
				sections.append({'name': 'abstract', 'text': text})

			if article.pmid and sections:
				yield {'doc_id': f'PMID:{article.pmid}', 'source': 'pubmed', 'sections': sections}
