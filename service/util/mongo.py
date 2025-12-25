from pymongo import MongoClient
from dotenv import load_dotenv
import os, sys


_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

load_dotenv(os.path.join(_SERVICE_ROOT, '.env'))
client = MongoClient(os.environ.get('MONGO_URI'))
DB = client.get_database("TheFollowup")
bronze_links = DB.get_collection("bronze_links")
silver_claims = DB.get_collection("silver_claims")
silver_updates = DB.get_collection("silver_updates")


def normalize_dates(obj: object) -> object:
	"""Recursively ensure date/datetime/Date_Delta objects have tzinfo.

	Instead of serializing to strings, attach tzinfo (default EST, UTC-05:00)
	to naive datetime values. For date values, convert to a midnight datetime
	with EST tzinfo. If tzinfo is already present on a datetime, leave as-is.
	Other object types pass through unchanged.
	"""
	try:
		import datetime as _dt
		from models import Date_Delta
	except Exception:
		# If imports fail for some reason, fall back to returning the object.
		return obj

	# Fixed-offset EST timezone (UTC-05:00). Intentionally not DST-aware.
	_EST_TZ = _dt.timezone(_dt.timedelta(hours=-5), name="EST")

	def _norm(o: object):
		if o is None:
			return None
		# Handle datetime first (subclass of date)
		if isinstance(o, _dt.datetime):
			if o.tzinfo is None:
				return o.replace(tzinfo=_EST_TZ)
			return o
		# For plain dates, convert to midnight datetime with EST tzinfo
		if isinstance(o, _dt.date):
			return _dt.datetime(o.year, o.month, o.day, tzinfo=_EST_TZ)
		if isinstance(o, Date_Delta):
			return _norm(o._resolve_date())
		if isinstance(o, dict):
			return {k: _norm(v) for k, v in o.items()}
		if isinstance(o, list):
			return [_norm(v) for v in o]
		return o

	return _norm(obj)