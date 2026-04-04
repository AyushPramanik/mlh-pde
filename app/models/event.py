from peewee import AutoField, CharField, DateTimeField, ForeignKeyField, TextField

from app.database import BaseModel
from app.models.url import URL
from app.models.user import User


class Event(BaseModel):
    id = AutoField()
    url = ForeignKeyField(URL, backref="events", column_name="url_id")
    user = ForeignKeyField(User, backref="events", null=True, column_name="user_id")
    event_type = CharField()  # created | updated | deleted
    timestamp = DateTimeField()
    details = TextField(null=True)

    class Meta:
        table_name = "events"
