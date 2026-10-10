from datetime import datetime, timezone

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)



def usage(five=0, weekly=9):
    return {"rate_limits_available": True, "rate_limits": {
        "five_hour": {"utilization": five, "resets_at": None},
        "seven_day": {"utilization": weekly, "resets_at": "2026-09-15T00:00:00.123456Z"}}}



def envelope(identifier, data=None, subtype="success"):
    return {"type": "control_response", "response": {
        "subtype": subtype, "request_id": identifier, "response": {} if data is None else data}}
