"""Screen a corpus split for likely sentence-boundary mistakes.

corpus/README.md's "How it was built" describes this pass in prose: after
boundaries are bootstrapped from the model (scripts/build_senter_corpus.py),
every article is screened for suspicious boundaries and each flag is
checked by hand. This is that screen, made reproducible.

Flags are deliberately over-inclusive -- most of what is reported is
correct behaviour, not an error (a case-sensitive gene symbol legitimately
starts a sentence lowercase; "Fig. 4b Comparison of..." really is a caption
that runs on). The point is recall over the *errors*, so nothing is
silently applied: a flag is a place to look, and the checks are named so a
whole category can be reviewed together, where correct-vs-wrong is a much
faster judgement than it is one isolated case at a time.

	python scripts/flag_boundaries.py --corpus_dir corpus/test
	python scripts/flag_boundaries.py --corpus_dir corpus/test --checks leading_citation --show
"""

import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from biosenter.markup import strip_markup
from evaluate_senter import parse_boundaries

# Dotted forms that are almost never sentence-final, so a "sentence" ending
# in one is more likely a false split than a real boundary. Matched
# case-insensitively against the last whitespace-delimited word.
_ABBREVIATIONS = {
	'fig', 'figs', 'al', 'et', 'no', 'nos', 'vs', 'etc', 'eg', 'e.g', 'ie', 'i.e', 'ca',
	'approx', 'eq', 'eqs', 'ref', 'refs', 'dr', 'prof', 'mr', 'mrs', 'ms', 'st', 'jr', 'sr',
	'spp', 'sp', 'var', 'subsp', 'cf', 'i.p', 'i.v', 's.c', 'p.o', 'p.i', 'a.m', 'p.m',
	'ph.d', 'm.d', 'b.sc', 'm.sc', 'inc', 'ltd', 'corp', 'dept', 'univ', 'vol',
	'tab', 'suppl', 'chap', 'pp', 'eds',
}

# Deliberately *not* in that set, despite looking like abbreviations: unit
# and duration words ("min", "sec", "hr", "wk", "yr", "max") end real
# sentences constantly in methods sections ("...centrifuged for 10 min."),
# so flagging them buries the genuine hits under hundreds of correct ones.

# Author initials ("G.S.", "J.P.C.", "U.S.") read exactly like an
# abbreviation followed by a capitalised word, and back-matter
# contribution statements are made of them.
_INITIALS_RE = re.compile(r'^(?:[a-z]\.)*[a-z]$')

# A full stop, a short run of digits (one citation, or a comma/dash-joined
# run of them), then the start of what reads like a new sentence. The
# lookbehind wants *two* word characters before the stop, which keeps out
# decimals ("pH 7.4 The..."), software versions ("SPSS Statistics v.30
# (IBM...") and HGVS notation ("a mutation (c.694 A>T, p.I232F)") -- all
# of which are one letter or digit in front of the dot, never a citation.
_NUMERIC_MARKER_RE = re.compile(r'[\[(]?[\d,;\u2013\u2014\- ]+[\])]?')

_STRANDED_CITATION_RE = re.compile(
	r'(?<=[A-Za-z)\]\u2019\u201d"\'][A-Za-z)\]\u2019\u201d"\'])'
	r'\.(?:\d{1,3}(?:\s?[,\u2013\u2014-]\s?\d{1,3})*)\s+(?=[A-Z\u201c"(\[])')


# A sentence may legitimately end on one of these *after* its terminal
# punctuation -- a closing quote, a bracket, a trademark symbol.
_TRAILING_CHARS = '"\'’”)]}®™  \t'

_TERMINAL_PUNCTUATION = '.?!'

# A citation run hanging off the end of a sentence, after its full stop.
_TRAILING_CITATION_RE = re.compile(r'(?<=[.?!])\s*[\[(]?\d{1,3}(?:\s?[,;\u2013\u2014-]\s?\d{1,3})*[\])]?\s*$')

# Headings, list items, table cells and captions routinely carry no
# terminal punctuation at all and are a passage unto themselves, so an
# unpunctuated *single-sentence* passage is normal rather than suspicious.
_MAX_HEADING_CHARS = 120


def _sentences(tagged_text):
	"""Passage text with <sentence_start/> markers -> [(boundary_offset,
	plain_sentence_text, spans_in_sentence), ...], one per sentence.

	Offsets and spans are relative to the marker-stripped, markup-bearing
	passage text -- the same coordinates split_into_sentences() returns and
	the ones an edit has to be expressed in."""
	text, starts = parse_boundaries(tagged_text)
	bounds = list(zip(starts, starts[1:] + [len(text)]))
	out = []
	for start, end in bounds:
		plain, spans = strip_markup(text[start:end])
		out.append((start, plain, spans))
	return text, out


def _last_word(plain):
	stripped = plain.rstrip(_TRAILING_CHARS)
	if not stripped.endswith('.'):
		return None
	return stripped[:-1].split()[-1].lower() if stripped[:-1].split() else None


def _first_alpha(plain):
	for character in plain:
		if character.isalpha():
			return character
	return None


def check_lowercase_start(index, plain, spans, previous, n_sentences):
	"""A sentence whose first letter is lowercase -- either a false split,
	or a real boundary onto a case-sensitive identifier (kras, p53)."""
	if index == 0:
		return None
	first = _first_alpha(plain[:40])
	return 'sentence starts lowercase' if first and first.islower() else None


def check_no_terminal_punctuation(index, plain, spans, previous, n_sentences):
	"""A non-final sentence not ending in . ? ! -- either a boundary placed
	where the text has no punctuation at all (a heading or list item run
	into the next), or a missing full stop in the source."""
	if index == n_sentences - 1:
		return None
	# A sentence that ends on its own trailing citation run ("...a chip.22")
	# is punctuated correctly; the marker just sits after the stop.
	stripped = _TRAILING_CITATION_RE.sub('', plain.rstrip(_TRAILING_CHARS)).rstrip(_TRAILING_CHARS)
	if stripped and stripped[-1] not in _TERMINAL_PUNCTUATION:
		return f'sentence ends {stripped[-1]!r}, not terminal punctuation'
	return None


def check_unpunctuated_run_on(index, plain, spans, previous, n_sentences):
	"""A long passage held as one unsplit sentence with no terminal
	punctuation anywhere -- the shape of a heading/list item that actually
	contains several sentences the splitter never separated."""
	if n_sentences != 1 or len(plain) <= _MAX_HEADING_CHARS:
		return None
	if any(character in plain for character in _TERMINAL_PUNCTUATION):
		return None
	return f'{len(plain)}-char passage held as one unpunctuated sentence'


def check_internal_question_mark(index, plain, spans, previous, n_sentences):
	"""A ? or ! inside a sentence, followed by something that looks like a
	new sentence -- the boundary style the splitter sees least often."""
	body = plain.rstrip(_TRAILING_CHARS)
	match = re.search(r'[?!]["\'’”)\]]*\s+(?=[A-Z“"(\[])', body[:-1] if body else '')
	return f'internal {body[match.start()]!r} mid-sentence' if match else None


def check_internal_period(index, plain, spans, previous, n_sentences):
	"""A full stop mid-sentence followed by a capitalised word, where the
	preceding word is not a known abbreviation -- a missed boundary, or a
	dotted form this screen doesn't know about."""
	hits = []
	for match in re.finditer(r'(\S*?)\.["\'’”)\]]*\s+(?=[A-Z])', plain):
		word = match.group(1).lower().lstrip('([“"\'')
		if word in _ABBREVIATIONS or len(word) <= 1 or any(character.isdigit() for character in word):
			continue
		if _INITIALS_RE.match(word):
			continue
		# Every hit, not just the first: a sentence full of "Mt. Etna" can
		# still hide one real missed boundary further along.
		hits.append(f'{word}. {plain[match.end():match.end() + 12]}')
	return 'internal ' + '; '.join(repr(hit) for hit in hits) if hits else None


def check_abbreviation_end(index, plain, spans, previous, n_sentences):
	"""A sentence ending on a dotted abbreviation -- "...shown in Fig." is
	a split inside "Fig. 3", not a sentence end."""
	word = _last_word(plain)
	return f'ends on abbreviation {word + "."!r}' if word in _ABBREVIATIONS else None


def check_leading_citation(index, plain, spans, previous, n_sentences):
	"""A sentence that opens with a bare citation marker: the citation
	belongs to the claim in the *previous* sentence, and has been stranded
	at the head of this one.

	Only numeric markers count. A narrative citation ("Allen et al. (2011)
	found that...") is the subject of its own sentence and belongs exactly
	where it is -- bioconverters marks up the whole phrase, author name
	included, so the two are easy to tell apart."""
	if index == 0:
		return None
	citations = [span for span in spans if span.tag == 'citation']
	if not citations:
		return None
	if not _NUMERIC_MARKER_RE.fullmatch(plain[citations[0].start:citations[0].end]):
		return None
	# Only brackets/whitespace between the boundary and the marker: the
	# sentence genuinely opens on it rather than merely containing one.
	if all(character in ' \t\u00a0([' for character in plain[:citations[0].start]):
		return f'opens on a citation marker: {plain[:citations[0].end + 3]!r}'
	return None


def check_stranded_citation_run(index, plain, spans, previous, n_sentences):
	"""Digits glued onto a mid-sentence full stop, then a capitalised word
	("...of a chip.22 Real-time mapping...") -- a superscript citation the
	publisher set after the stop, which bioconverters did not resolve into
	a <citation> marker. The splitter cannot fix these itself: with the
	digits left in the text "chip.22" is a single token, so there is no
	boundary to offer, and the citation ends up reading as part of the
	next sentence. The boundary belongs after the digit run."""
	match = _STRANDED_CITATION_RE.search(plain)
	return f'stranded citation run: ...{plain[max(0, match.start() - 30):match.end() + 20]!r}' if match else None


def check_trailing_dangle(index, plain, spans, previous, n_sentences):
	"""A sentence ending in an opening bracket or a dangling connective --
	a split made in the middle of a parenthetical or a clause."""
	stripped = plain.rstrip(_TRAILING_CHARS + _TERMINAL_PUNCTUATION)
	if re.search(r'[(\[,;]$|\b(?:and|or|of|the|a|an|in|to|with|for|that|which|as|by)$', stripped, re.IGNORECASE):
		return f'ends dangling: ...{stripped[-30:]!r}'
	return None


def check_unbalanced_brackets(index, plain, spans, previous, n_sentences):
	"""Unbalanced ( or [ within a sentence -- the other half is in the
	neighbouring sentence, so the boundary fell inside a parenthetical."""
	for opening, closing in ('()', '[]'):
		if plain.count(opening) != plain.count(closing):
			return f'unbalanced {opening}{closing}'
	return None


CHECKS = {
	name[len('check_'):]: function
	for name, function in sorted(globals().items()) if name.startswith('check_')
}


def flag_split(corpus_dir, checks):
	"""-> [(pmcid, passage_index, section, offset, check_name, message,
	context), ...] for every flagged sentence in the split."""
	flags = []
	for path in sorted(glob.glob(f'{corpus_dir}/*.json')):
		record = json.load(open(path, encoding='utf8'))
		for passage_index, passage in enumerate(record['passages']):
			text, sentences = _sentences(passage['text'])
			for index, (offset, plain, spans) in enumerate(sentences):
				previous = sentences[index - 1][1] if index else None
				for name in checks:
					message = CHECKS[name](index, plain, spans, previous, len(sentences))
					if message:
						flags.append((record['pmcid'], passage_index, passage['section'], offset, name, message, plain))
	return flags


def main():
	parser = argparse.ArgumentParser(description='Flag likely sentence-boundary mistakes in a corpus split')
	parser.add_argument('--corpus_dir', required=True, type=str, help='corpus/train, corpus/validation or corpus/test')
	parser.add_argument('--checks', nargs='+', default=sorted(CHECKS), choices=sorted(CHECKS), help='Which checks to run (default: all)')
	parser.add_argument('--show', action='store_true', help='Print every flag, not just the per-check counts')
	parser.add_argument('--context', type=int, default=90, help='Characters of the flagged sentence to print with --show')
	parser.add_argument('--json_out', default=None, type=str, help='Also write the flags to this path as JSON, for a review pass to work through')
	args = parser.parse_args()

	flags = flag_split(args.corpus_dir, args.checks)

	if args.show:
		for pmcid, passage_index, section, offset, name, message, plain in flags:
			print(f'{name:26s} PMC{pmcid} p{passage_index}[{section}] @{offset}: {message}')
			print(f'    {plain[:args.context]!r}')

	counts = Counter(name for *_rest, name, _message, _plain in flags)
	print(f'\n{len(flags)} flags over {len(set(flag[0] for flag in flags))} articles in {args.corpus_dir}')
	for name in sorted(CHECKS):
		if name in args.checks:
			print(f'  {name:26s} {counts[name]:6d}')

	if args.json_out:
		Path(args.json_out).write_text(json.dumps([
			{'pmcid': pmcid, 'passage': passage_index, 'section': section, 'offset': offset,
			 'check': name, 'message': message, 'sentence': plain}
			for pmcid, passage_index, section, offset, name, message, plain in flags
		], indent=1), encoding='utf8')


if __name__ == '__main__':
	main()
