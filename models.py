"""MongoDB-backed models for Pennies."""

import os
import logging
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson import ObjectId

logger = logging.getLogger(__name__)

_client = None
_db = None


def get_db():
    """Return the PyMongo database instance (lazy singleton, fork-safe)."""
    global _client, _db
    if _db is None:
        uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/pennies")
        masked = uri[:30] + "***" if len(uri) > 30 else uri
        logger.info(f"Connecting to MongoDB: {masked}")
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
        logger.info("MongoDB connection OK")
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
