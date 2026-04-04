from flask import Blueprint, jsonify

from app.models.event import Event

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.route("/", methods=["GET"])
def list_events():
    events = list(Event.select().dicts())
    return jsonify(events)


@events_bp.route("/<int:event_id>", methods=["GET"])
def get_event(event_id):
    try:
        event = Event.get_by_id(event_id)
        return jsonify({
            "id": event.id,
            "url_id": event.url_id,
            "user_id": event.user_id,
            "event_type": event.event_type,
            "timestamp": str(event.timestamp),
            "details": event.details,
        })
    except Event.DoesNotExist:
        return jsonify({"error": "not found"}), 404
