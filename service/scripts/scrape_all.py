import os
import sys
import datetime
import importlib.util
import logging
from typing import List

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
	sys.path.insert(0, _SERVICE_ROOT)

import models

logger = logging.getLogger(__name__)

# Try to import mongo collection; wrap in a local name so we can handle missing env/config gracefully
try:
	from util import mongo as _mongo_module
	_BRONZE_COLLECTION = getattr(_mongo_module, 'bronze_links', None)
except Exception:
	_BRONZE_COLLECTION = None


def _discover_scrapers(scrape_dir: str) -> List[str]:
	"""Return list of absolute python file paths in `scrape_dir` to consider as scrapers."""
	files = []
	if not os.path.isdir(scrape_dir):
		return files
	for name in os.listdir(scrape_dir):
		if not name.endswith('.py'):
			continue
		if name.startswith('_'):
			continue
		if name == '__init__.py':
			continue
		files.append(os.path.join(scrape_dir, name))
	return sorted(files)


def _load_module_from_path(path: str, module_name: str):
	spec = importlib.util.spec_from_file_location(module_name, path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Cannot load module from {path}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def merge_link_results(results: List[models.LinkAggregationResult]) -> models.LinkAggregationResult:
	# Collect all articles
	all_articles = []
	for r in results:
		if r is None:
			continue
		if hasattr(r, 'articles'):
			all_articles.extend(r.articles)

	# Deduplicate by link, keeping the newest date
	by_link = {}
	for a in all_articles:
		existing = by_link.get(a.link)
		if existing is None or a.date > existing.date:
			by_link[a.link] = a

	merged = list(by_link.values())
	merged.sort(key=lambda x: x.date, reverse=True)
	return models.LinkAggregationResult(articles=merged)


def run_all(date: datetime.date) -> models.LinkAggregationResult:
	scrape_dir = os.path.join(_HERE, 'scrape')
	files = _discover_scrapers(scrape_dir)
	results = []
	for i, path in enumerate(files):
		module_name = f"scrape_module_{i}_{os.path.splitext(os.path.basename(path))[0]}"
		try:
			logger.info(f"Loading scraper module: {path}")
			module = _load_module_from_path(path, module_name)
		except Exception as e:
			logger.exception(f"Failed to load module {path}: {e}")
			continue

		scrape_fn = getattr(module, 'scrape', None)
		if not callable(scrape_fn):
			logger.info(f"Module {path} has no callable 'scrape' function, skipping")
			continue

		try:
			logger.info(f"Running scrape() from {path}")
			res = scrape_fn(date)
			# If the scraper returned a LinkAggregationStep (or list of steps), try to convert
			if isinstance(res, models.LinkAggregationResult):
				results.append(res)
			elif hasattr(res, 'articles'):
				# Accept any object with 'articles' attribute
				results.append(models.LinkAggregationResult(articles=list(res.articles)))
			elif isinstance(res, list):
				# Possibly a list of LinkAggregationStep
				try:
					results.append(models.LinkAggregationResult.from_steps(res))
				except Exception:
					logger.exception("Failed to convert list result to LinkAggregationResult")
			else:
				logger.warning(f"scrape() from {path} returned unexpected type: {type(res)}")
		except Exception as e:
			logger.exception(f"Error running scrape() from {path}: {e}")

	merged = merge_link_results(results)
	return merged


def _parse_date_arg(arg: str) -> datetime.date:
	try:
		return datetime.datetime.strptime(arg, '%Y-%m-%d').date()
	except Exception:
		raise ValueError("Date must be in YYYY-MM-DD format")


def main(argv=None):
	if argv is None:
		argv = sys.argv[1:]
	logging.basicConfig(level=logging.INFO)
	if len(argv) >= 1:
		date = _parse_date_arg(argv[0])
	else:
		try:
			from util.timezone import pipeline_yesterday
			date = pipeline_yesterday()
		except Exception:
			date = datetime.date.today() - datetime.timedelta(days=1)
	print(f"Running scrapers for date: {date}")
	print(argv)
	combined = run_all(date)
	print(f"Combined articles: {len(combined.articles)}")
	# Persist to mongo if available
	if _BRONZE_COLLECTION is not None:
		try:
			inserted = 0
			updated = 0
			for a in combined.articles:
				# Convert ArticleLink to dict and normalize date to datetime
				doc = a.dict()
				try:
					# Convert date (datetime.date) to datetime for Mongo
					if isinstance(doc.get('date'), datetime.date):
						doc['date'] = datetime.datetime.combine(doc['date'], datetime.time())
				except Exception:
					# leave as-is if conversion fails
					pass

				# Upsert by link
				try:
					res = _BRONZE_COLLECTION.update_one(
						{'link': doc.get('link')},
						{'$set': doc, '$setOnInsert': {'inserted_at': datetime.datetime.utcnow()}},
						upsert=True,
					)
					if getattr(res, 'upserted_id', None) is not None:
						inserted += 1
					else:
						updated += 1
				except Exception:
					logger.exception(f"Failed to upsert document for link {doc.get('link')}")

			print(f"Mongo: inserted={inserted}, updated={updated}")
		except Exception:
			logger.exception("Error while saving to mongo")
	else:
		logger.info("Mongo collection `bronze_links` not available; skipping persistence")
	try:
		print(combined.model_dump_json(indent=2, ensure_ascii=False))
	except Exception:
		# Fallback simple print
		for a in combined.articles:
			print(f"{a.date} - {a.title} - {a.link}")


if __name__ == '__main__':
	main()

