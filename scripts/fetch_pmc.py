import argparse
import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# NCBI retired the old oa_bulk/ tar-package FTP structure in favor of
# per-article objects in this public, anonymous-read S3 bucket (confirmed
# live via a ListObjectsV2 request -- no AWS credentials needed).
BASE_URL = "https://pmc-oa-opendata.s3.amazonaws.com"

_S3_NS = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}

# Rough span of PMCID numbers actually present in the bucket, wide enough
# to land in different journals/years/eras of the OA subset rather than
# clustering in one corner of the ID space.
_RANDOM_ID_RANGE = (1_000_000, 12_000_000)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def _esearch_page(query, retstart, page_size, retries=3):
	"""One esearch page of PMCIDs (db=pmc, OA-restricted) -- retried on
	failure, since unauthenticated eutils (no api_key, capped at 3 req/s)
	occasionally answers a request with a truncated/non-JSON body rather
	than a clean HTTP error, which would otherwise crash a whole
	multi-page search_pmcids() call over one bad page."""
	last_error = None
	for attempt in range(retries):
		if attempt:
			time.sleep(2 ** attempt)
		try:
			response = requests.get(_ESEARCH_URL, params={
				'db': 'pmc', 'term': f'{query} AND open access[filter]',
				'retmax': page_size, 'retstart': retstart, 'retmode': 'json',
			}, timeout=30)
			response.raise_for_status()
			return response.json()['esearchresult']['idlist']
		except (requests.RequestException, ValueError, KeyError) as error:
			last_error = error
	raise RuntimeError(f'esearch failed after {retries} attempts (retstart={retstart}): {last_error}') from last_error


def normalize_key(raw_pmcid):
	"""'10000000' / 'PMC10000000' / 'PMC10000000.2' -> 'PMC10000000.1' (version
	defaults to .1 unless one is already given)."""
	pmcid = raw_pmcid.strip().upper()
	if not pmcid.startswith('PMC'):
		pmcid = f'PMC{pmcid}'
	return pmcid if '.' in pmcid else f'{pmcid}.1'


# The <license xlink:href="..."> element in PMC's JATS XML points at the
# specific Creative Commons deed (or, for some publishers, a bespoke terms
# page that isn't CC at all). CC BY / CC BY-SA / CC BY-ND / CC0 all permit
# commercial use; CC BY-NC / CC BY-NC-SA / CC BY-NC-ND and anything that
# isn't recognisably creativecommons.org do not.
_LICENSE_HREF_RE = re.compile(r'<license\b[^>]*xlink:href="([^"]+)"', re.IGNORECASE)


def extract_license_href(xml_bytes):
	"""Article XML bytes -> the <license> xlink:href, or None if absent."""
	match = _LICENSE_HREF_RE.search(xml_bytes.decode('utf8', errors='ignore'))
	return match.group(1) if match else None


def allows_commercial_use(href):
	"""True only for a creativecommons.org license without an NC (non-
	commercial) restriction. False for CC BY-NC variants, for non-CC/
	publisher-specific license pages, and for no license at all."""
	if not href:
		return False
	href = href.lower()
	if 'creativecommons.org' not in href:
		return False
	return '-nc' not in href


def random_pmcids(n, rng, commercial_only=True):
	"""Sample n distinct PMCIDs actually present in the OA bucket.

	The bucket lists keys in lexicographic order, so a ListObjectsV2 call
	with a random `start-after` token lands on a genuinely different
	article each time rather than always the alphabetically-first ones --
	a random PMCID guessed outright would mostly 404, since not every
	numeric id is in the Open Access subset or exists at all.

	When `commercial_only` is set (the default), each candidate's XML is
	fetched to check its license before being accepted, and rejected/non-
	CC-BY-NC candidates are skipped rather than counted -- this corpus is
	used to train/eval models that may end up in commercial use, so
	non-commercial-licensed source text shouldn't be in it. The fetched
	content is cached and returned so the caller (main()) doesn't have to
	download the same article twice.
	"""
	pmcids = []
	content_cache = {}
	seen = set()
	attempts = 0
	while len(pmcids) < n and attempts < n * 10:
		attempts += 1
		start_after = f"PMC{rng.randint(*_RANDOM_ID_RANGE)}.1/"
		response = requests.get(BASE_URL, params={'list-type': '2', 'max-keys': '20', 'start-after': start_after}, timeout=30)
		response.raise_for_status()
		root = ET.fromstring(response.content)
		for contents in root.findall('s3:Contents', _S3_NS):
			key = contents.find('s3:Key', _S3_NS).text
			if not key.endswith('.xml'):
				continue
			pmcid = key.split('/')[0]
			if pmcid in seen:
				continue
			seen.add(pmcid)
			if commercial_only:
				article_response = requests.get(f"{BASE_URL}/{key}", timeout=60)
				if article_response.status_code == 404:
					continue
				article_response.raise_for_status()
				href = extract_license_href(article_response.content)
				if not allows_commercial_use(href):
					continue
				content_cache[pmcid] = article_response.content
			pmcids.append(pmcid)
			break
	return pmcids, content_cache


def search_pmcids(query, n, commercial_only=True, exclude=frozenset()):
	"""Find n distinct PMCIDs matching a free-text query, restricted to the
	PMC Open Access subset, via NCBI's esearch (db=pmc).

	Unlike random_pmcids() (which lands on whatever article a random S3
	listing token happens to hit), this targets articles actually likely to
	contain a specific pattern -- e.g. "HGVS nomenclature" for
	clinical-genetics case reports carrying protein/cDNA variant notation
	(p.G2019S, c.6055G>A), which is vanishingly rare in an unweighted random
	sample (~4 mentions across an entire 182-article batch, see
	corpora/README.md's "Known gap").

	Same license-check and content-caching behaviour as random_pmcids();
	`exclude` additionally skips PMCIDs already present elsewhere (e.g. in
	an existing corpus) so a search-derived batch can't collide with it.
	esearch's default sort for db=pmc is most-recent-first, which also
	biases toward articles using PMC's currently-recommended metadata/
	license practices.
	"""
	pmcids = []
	content_cache = {}
	seen = set(exclude)
	retstart = 0
	page_size = 100
	while len(pmcids) < n:
		uids = _esearch_page(query, retstart, page_size)
		if not uids:
			break
		retstart += page_size

		for uid in uids:
			if len(pmcids) >= n:
				break
			pmcid = f'PMC{uid}'
			if pmcid in seen:
				continue
			seen.add(pmcid)
			key = normalize_key(pmcid)
			article_response = requests.get(f"{BASE_URL}/{key}/{key}.xml", timeout=60)
			if article_response.status_code == 404:
				continue
			article_response.raise_for_status()
			if commercial_only and not allows_commercial_use(extract_license_href(article_response.content)):
				continue
			content_cache[pmcid] = article_response.content
			pmcids.append(pmcid)
	return pmcids, content_cache


def main():
	parser = argparse.ArgumentParser(description='Download PMC Open Access article XML files from the public pmc-oa-opendata S3 bucket')
	parser.add_argument('--out_dir', required=True, type=str, help='Directory to save the downloaded files into')
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument('--pmcids', nargs='+', help='PMCIDs to fetch, e.g. 10000000 or PMC10000000 (version defaults to .1; pass PMCxxxxxxx.N for a specific version)')
	group.add_argument('--random', type=int, metavar='N', help='Fetch N randomly-sampled PMCIDs from the bucket instead of a fixed list')
	group.add_argument('--search', type=str, metavar='QUERY', help='Fetch PMCIDs matching a free-text query (esearch db=pmc, restricted to the OA subset) instead of a fixed list')
	parser.add_argument('--search_n', type=int, default=None, metavar='N', help='Number of PMCIDs to fetch for --search')
	parser.add_argument('--exclude', nargs='*', default=[], help='For --search: PMCIDs to skip even if matched (e.g. ones already in the corpus)')
	parser.add_argument('--seed', type=int, default=None, help='Seed for --random sampling (default: unseeded, a different sample each run)')
	parser.add_argument('--allow_any_license', action='store_true', help='For --random/--search: skip the commercial-use license check (default is CC BY/BY-SA/BY-ND/CC0 only)')
	args = parser.parse_args()

	if args.search and not args.search_n:
		parser.error('--search requires --search_n')

	out_dir = Path(args.out_dir)
	out_dir.mkdir(parents=True, exist_ok=True)

	content_cache = {}
	if args.random:
		pmcids, content_cache = random_pmcids(args.random, random.Random(args.seed), commercial_only=not args.allow_any_license)
		print(f"Sampled {len(pmcids)} random PMCIDs: {', '.join(pmcids)}")
	elif args.search:
		exclude = {normalize_key(pmcid).split('.')[0] for pmcid in args.exclude}
		pmcids, content_cache = search_pmcids(args.search, args.search_n, commercial_only=not args.allow_any_license, exclude=exclude)
		print(f"Found {len(pmcids)} PMCIDs matching {args.search!r}: {', '.join(pmcids)}")
	else:
		pmcids = args.pmcids

	for raw_pmcid in pmcids:
		key = normalize_key(raw_pmcid)
		out_path = out_dir / f"{key}.xml"
		if raw_pmcid in content_cache:
			print(f"Saving (license pre-checked) -> {out_path}")
			out_path.write_bytes(content_cache[raw_pmcid])
			continue
		url = f"{BASE_URL}/{key}/{key}.xml"
		print(f"Downloading {url} -> {out_path}")
		response = requests.get(url, timeout=60)
		if response.status_code == 404:
			print(f"  Not found (skipping): {url}")
			continue
		response.raise_for_status()
		out_path.write_bytes(response.content)

	print("Done")


if __name__ == '__main__':
	main()
