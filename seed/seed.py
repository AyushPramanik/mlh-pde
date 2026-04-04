"""
Seed the database from CSV files.

Usage:
    uv run python seed/seed.py
"""

import csv
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from app.logging_config import configure_logging

logger = configure_logging()

from peewee import PostgresqlDatabase

from app.database import db
from app.models.user import User
from app.models.url import URL
from app.models.event import Event

SEED_DIR = os.path.dirname(__file__)


def init():
    database = PostgresqlDatabase(
        os.environ.get("DATABASE_NAME", "hackathon_db"),
        host=os.environ.get("DATABASE_HOST", "localhost"),
        port=int(os.environ.get("DATABASE_PORT", 5432)),
        user=os.environ.get("DATABASE_USER", "postgres"),
        password=os.environ.get("DATABASE_PASSWORD", "postgres"),
    )
    db.initialize(database)
    db.connect()


def create_tables():
    db.create_tables([User, URL, Event], safe=True)
    logger.info("tables_created")


def seed_users():
    with open(os.path.join(SEED_DIR, "users.csv")) as f:
        rows = list(csv.DictReader(f))
    with db.atomic():
        for batch in chunks(rows, 100):
            User.insert_many(batch).on_conflict_ignore().execute()
    logger.info("seeded_users", extra={"count": len(rows)})


def seed_urls():
    with open(os.path.join(SEED_DIR, "urls.csv")) as f:
        rows = [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "short_code": r["short_code"],
                "original_url": r["original_url"],
                "title": r["title"],
                "is_active": r["is_active"].lower() == "true",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in csv.DictReader(f)
        ]
    with db.atomic():
        for batch in chunks(rows, 100):
            URL.insert_many(batch).on_conflict_ignore().execute()
    logger.info("seeded_urls", extra={"count": len(rows)})


def seed_events():
    with open(os.path.join(SEED_DIR, "events.csv")) as f:
        rows = list(csv.DictReader(f))
    with db.atomic():
        for batch in chunks(rows, 100):
            Event.insert_many(batch).on_conflict_ignore().execute()
    logger.info("seeded_events", extra={"count": len(rows)})


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


if __name__ == "__main__":
    init()
    create_tables()
    seed_users()
    seed_urls()
    seed_events()
    db.close()
    logger.info("seed_complete")
