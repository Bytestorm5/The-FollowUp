from pymongo import MongoClient
from dotenv import load_dotenv
import os
load_dotenv()
client = MongoClient(os.environ.get('MONGO_URI'))
DB = client.get_database("TheFollowup")
bronze_links = DB.get_collection("bronze_links")
silver_claims = DB.get_collection("silver_claims")
silver_updates = DB.get_collection("silver_updates")


def normalize_dates(obj: object) -> object:
	"""Recursively convert date/datetime/Date_Delta objects to ISO 8601 strings.

	Mirrors the helper used in `claim_process.py`, centralized here so all
	Mongo insertion code can reuse a consistent serializer.
	"""
	try:
		import datetime as _dt
		from models import Date_Delta
	except Exception:
		# If imports fail for some reason, fall back to returning the object.
		return obj

	def _norm(o: object):
		if o is None:
			return None
		if isinstance(o, _dt.datetime):
			return o.isoformat()
		if isinstance(o, _dt.date):
			return o.isoformat()
		if isinstance(o, Date_Delta):
			return _norm(o._resolve_date())
		if isinstance(o, dict):
			return {k: _norm(v) for k, v in o.items()}
		if isinstance(o, list):
			return [_norm(v) for v in o]
		return o

	return _norm(obj)