"""MongoDB-backed models for Pennies."""

import os
import logging
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson import ObjectId

logger = logging.getLogger(__name__)

_MONGO_URI = os.environ.get("MONGODB_URI") or ""
print(f"[Pennies] MONGODB_URI loaded at import: set={bool(_MONGO_URI)}, len={len(_MONGO_URI)}, "
      f"preview={_MONGO_URI[:35]}***" if _MONGO_URI else "[Pennies] MONGODB_URI loaded at import: NOT SET",
      flush=True)

_client = None
_db = None


def get_db():
    """Return the PyMongo database instance (lazy singleton)."""
    global _client, _db
    if _db is None:
        uri = _MONGO_URI or os.environ.get("MONGODB_URI") or "mongodb://localhost:27017/pennies"
        if "localhost" in uri:
            print(f"[Pennies WARNING] Using localhost fallback! MONGODB_URI env={os.environ.get('MONGODB_URI')!r}",
                  flush=True)
        masked = uri[:35] + "***" if len(uri) > 35 else uri
        print(f"[Pennies] Connecting to: {masked}", flush=True)
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
        print("[Pennies] MongoDB connection OK", flush=True)
        db_name = uri.rsplit("/", 1)[-1].split("?")[0] or "pennies"
        _db = _client[db_name]
        _db.users.create_index("email", unique=True)
        _db.watchlist.create_index([("user_id", 1), ("ticker", 1)], unique=True)
    return _db


class User(UserMixin):
    """Wraps a MongoDB document from the `users` collection."""

    def __init__(self, doc):
        self._doc = doc

    @property
    def id(self):
        return str(self._doc["_id"])

    @property
    def email(self):
        return self._doc["email"]

    @property
    def password_hash(self):
        return self._doc["password_hash"]

    def get_id(self):
        return str(self._doc["_id"])

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def find_by_email(email: str):
        doc = get_db().users.find_one({"email": email})
        return User(doc) if doc else None

    @staticmethod
    def find_by_id(user_id: str):
        try:
            doc = get_db().users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None
        return User(doc) if doc else None

    @staticmethod
    def create(email: str, password: str):
        doc = {
            "email": email,
            "password_hash": generate_password_hash(password),
            "created_at": datetime.now(timezone.utc),
        }
        result = get_db().users.insert_one(doc)
        doc["_id"] = result.inserted_id
        return User(doc)
