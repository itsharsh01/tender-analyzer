from pymongo import MongoClient
from pymongo.database import Database
from pymongo.server_api import ServerApi

from app.utils.settings import settings


_client: MongoClient | None = None
_db: Database | None = None


def init_db() -> Database:
    global _client, _db

    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set in environment.")

    _client = MongoClient(settings.mongodb_uri, server_api=ServerApi("1"))
    _client.admin.command("ping")
    _db = _client[settings.mongodb_db]
    return _db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database is not initialized.")
    return _db

