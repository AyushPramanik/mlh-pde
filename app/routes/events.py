import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.models.event import Event

events_bp = Blueprint("events", __name__, url_prefix="/events")


def _event_dict(event):
    details = event.details
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (ValueError, TypeError):
            pass
    return {
        "id": event.id,
        "url_id": event.url_id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "timestamp": str(event.timestamp),
        "details": details,
    }


@events_bp.route("", methods=["GET"])
def list_events():
    url_id = request.args.get("url_id", type=int)
    user_id = request.args.get("user_id", type=int)
    event_type = request.args.get("event_type")

    query = Event.select()

    if url_id is not None:
        query = query.where(Event.url_id == url_id)

    if user_id is not None:
        query = query.where(Event.user_id == user_id)

    if event_type is not None:
        query = query.where(Event.event_type == event_type)

    return jsonify([_event_dict(e) for e in query])


@events_bp.route("", methods=["POST"])
def create_event():
    data = request.get_json(force=True, silent=True)
    if not data or "event_type" not in data or "url_id" not in data:
        return jsonify({"error": "event_type and url_id are required"}), 400

    details = data.get("details")
    if details is not None and not isinstance(details, str):
        details = json.dumps(details)

    try:
        event = Event.create(
            url_id=data["url_id"],
            user_id=data.get("user_id"),
            event_type=data["event_type"],
            timestamp=datetime.now(timezone.utc),
            details=details,
        )
    except IntegrityError:
        return jsonify({"error": "invalid url_id or constraint violation"}), 400

    return jsonify(_event_dict(event)), 201


@events_bp.route("/<int:event_id>", methods=["GET"])
def get_event(event_id):
    try:
        event = Event.get_by_id(event_id)
        return jsonify(_event_dict(event))
    except Event.DoesNotExist:
        return jsonify({"error": "not found"}), 404
