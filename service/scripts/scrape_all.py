import os
import sys
import datetime
import importlib.util
import logging
import json
import re
from typing import List, Dict, Optional

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
	_LOCALE_COLLECTION = getattr(_mongo_module, 'locale_subscriptions', None)
	from util.slug import generate_unique_slug as _gen_slug
except Exception:
	_BRONZE_COLLECTION = None
	_LOCALE_COLLECTION = None

_LOCALE_METADATA_NAME = "locale.json"


def _normalize_locale_value(value: Optional[str]) -> str:
	if value is None:
		return ""
	return str(value).strip().lower()


def _build_locale_key(metadata: Dict[str, object]) -> str:
	parts = [
		_normalize_locale_value(metadata.get("country")),
		_normalize_locale_value(metadata.get("province")),
		_normalize_locale_value(metadata.get("county")),
	]
	subdivisions = metadata.get("subdivisions") or {}
	if isinstance(subdivisions, dict):
		for key in sorted(subdivisions.keys()):
			val = _normalize_locale_value(subdivisions.get(key))
			if val:
				parts.append(f"{key}:{val}")
	return "|".join([p for p in parts if p])


def _load_locale_metadata(folder: str) -> Optional[Dict[str, object]]:
	meta_path = os.path.join(folder, _LOCALE_METADATA_NAME)
	if not os.path.isfile(meta_path):
		return None
	try:
		with open(meta_path, "r", encoding="utf-8") as handle:
			data = json.load(handle)
	except Exception as exc:
		logger.exception(f"Failed to read locale metadata {meta_path}: {exc}")
		return None

	if not isinstance(data, dict):
		logger.error(f"Locale metadata must be a JSON object: {meta_path}")
		return None

	return data


def _locale_has_subscribers(metadata: Dict[str, object]) -> bool:
	if _LOCALE_COLLECTION is None:
		logger.warning("Locale subscriptions collection unavailable; skipping locale-specific scrapers.")
		return False
	key = _build_locale_key(metadata)
	if not key:
		logger.warning("Locale metadata missing required fields (country/province/county); skipping.")
		return False
	regex = f"^{re.escape(key)}(\\||$)"
	try:
		return _LOCALE_COLLECTION.count_documents({"active": True, "location_key": {"$regex": regex}}) > 0
	except Exception as exc:
		logger.exception(f"Failed to query locale subscriptions for {metadata}: {exc}")
		return False


def _discover_scrapers_in_folder(scrape_dir: str) -> List[str]:
	files = []
	if not os.path.isdir(scrape_dir):
		return files
	for name in os.listdir(scrape_dir):
		path = os.path.join(scrape_dir, name)
		if not os.path.isfile(path):
			continue
		if not name.endswith('.py'):
			continue
		if name.startswith('_'):
			continue
		if name == '__init__.py':
			continue
		files.append(path)
	return sorted(files)


def _discover_scrapers(scrape_dir: str) -> List[str]:
	"""Return list of absolute python file paths in `scrape_dir` to consider as scrapers."""
	files = []
	if not os.path.isdir(scrape_dir):
		return files
	for name in os.listdir(scrape_dir):
		path = os.path.join(scrape_dir, name)
		if os.path.isdir(path):
			metadata = _load_locale_metadata(path)
			if metadata is None:
				logger.info(f"Skipping folder without locale metadata: {path}")
				continue
			if not _locale_has_subscribers(metadata):
				logger.info(f"No subscribers for locale folder {path}; skipping")
				continue
			files.extend(_discover_scrapers_in_folder(path))
			continue
		if not name.endswith('.py'):
			continue
		if name.startswith('_'):
			continue
		if name == '__init__.py':
			continue
		files.append(path)
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
		date = datetime.date.today()
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

				# Ensure a unique slug for the article (based on title)
				try:
					art_date = None
					try:
						if isinstance(doc.get('date'), datetime.datetime):
							art_date = doc['date'].date()
					except Exception:
						art_date = None
					doc['slug'] = _gen_slug(_BRONZE_COLLECTION, doc.get('title', '') or doc.get('link', ''), date=art_date)
				except Exception:
					# If slug generation fails, skip setting it
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
