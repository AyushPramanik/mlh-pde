from peewee import CharField
from app.database import BaseModel


class URL(BaseModel):
    original_url = CharField()
    short_code = CharField(unique=True)
