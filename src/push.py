import os
from datetime import datetime, timedelta
import pytz
import requests
from src.db import NotifierDB

# Single module logger instance
try:
    from src.logger import Logger
    _LOGGER = Logger()
except Exception:
    _LOGGER = None


def _parse_event_datetime(ev: dict, tz):
    """Return (ev_date: date|None, time_str: str|None).
    Accepts ISO datetimes or already-formatted HH:MM strings; also checks start.date.
    Keeps parsing defensive and logs on parse failures.
    """
    ev_date = None
    time_str = ''

    sdt = ev.get('start.dateTime')
    if sdt:
        if 'T' in sdt:
            try:
                dt = datetime.fromisoformat(sdt)
                if dt.tzinfo is None:
                    dt = tz.localize(dt)
                dt = dt.astimezone(tz)
                time_str = dt.strftime('%H:%M')
                ev_date = dt.date()
            except Exception:
                time_str = sdt
                if _LOGGER:
                    _LOGGER.debug(f"_parse_event_datetime: failed to parse start.dateTime '{sdt}'")
        else:
            # already a time string like 'HH:MM'
            time_str = sdt

    # If explicit start.date provided, prefer it for date resolution
    sd = ev.get('start.date')
    if sd:
        try:
            if '-' in sd:
                ev_date = datetime.strptime(sd, '%Y-%m-%d').date()
            elif '/' in sd:
                ev_date = datetime.strptime(sd, '%d/%m/%Y').date()
        except Exception:
            if _LOGGER:
                _LOGGER.debug(f"_parse_event_datetime: failed to parse start.date '{sd}'")

    return ev_date, time_str


def _build_body_for_event(ev: dict, tz, today, tomorrow):
    ev_date, time_str = _parse_event_datetime(ev, tz)

    # Use formatted time if available (from main.py format_event_for_display)
    formatted_time = ev.get('_formatted_time')
    if formatted_time:
        time_str = formatted_time

    # Determine human readable day descriptor
    if ev_date == today:
        when = 'Oggi'
    elif ev_date == tomorrow:
        when = 'Domani'
    elif ev_date is not None:
        when = ev_date.strftime('%d/%m/%Y')
    else:
        when = ''

    summary = ev.get('summary', '').strip()
    if when and time_str:
        return f"{when} alle {time_str}: {summary}"
    if time_str:
        if when:
            return f"{when} {time_str}: {summary}"
        return f"Alle {time_str} {summary}"
    if when:
        return f"{when} {summary}"
    return summary


def send_push_notification(sub_endpoint, events, notification_type, user_id=None, device_id=None):
    """Send push notifications. For Daily Notification a single summary message is sent
    (or a single-event detailed message). For Last Minute / immediate notifications each
    event is sent as a separate POST to the backend notify endpoint.
    Returns True/False or list of booleans for per-event sends.
    """
    notification_api_key = os.getenv("NOTIFICATION_API_KEY")
    headers = {"Content-Type": "application/json"}
    if notification_api_key:
        headers["Authorization"] = f"Bearer {notification_api_key}"

    if _LOGGER:
        _LOGGER.debug(str(events))

    tz = pytz.timezone("Europe/Rome")
    today = datetime.now(tz).date()
    tomorrow = today + timedelta(days=1)

    notify_url = os.getenv("BACKEND_URL") + "/user/push/notify"

    def _post_and_store(session, payload, event_uids=None):
        try:
            resp = session.post(notify_url, headers=headers, json=payload, timeout=10)
            ok = resp.status_code == 200
            if not ok and _LOGGER:
                _LOGGER.error(f"[push-notifier] notify POST failed: {resp.status_code} {resp.text}")
            else:
                if _LOGGER:
                    _LOGGER.debug(f"[push-notifier] notify POST succeeded: title={payload.get('title')}")
            if ok and event_uids and user_id and device_id:
                try:
                    db = NotifierDB()
                    for uid in event_uids:
                        if uid:
                            db.store_push_sent(user_id, uid, device_id)
                    db.close_connection()
                except Exception:
                    if _LOGGER:
                        _LOGGER.error("[push-notifier] failed to store push_sent entries")
            return ok
        except Exception as e:
            if _LOGGER:
                _LOGGER.error(f"[push-notifier] notify request exception: {e}")
            return False

    if notification_type == "Daily Notification":
        # single notification summarizing the day's events
        count = len(events)
        title = f"Daily Notification ({count} {'evento' if count == 1 else 'eventi'})"
        if count > 1:
            body = f"Sono previsti {count} eventi."
            payload = {"title": title, "body": body, "url": "/dashboard", "endpoint": sub_endpoint}
            with requests.Session() as s:
                # store all uids (if provided by events)
                uids = [e.get('uid') for e in events if e.get('uid')]
                return _post_and_store(s, payload, event_uids=uids)

        # single event: build detailed body and include its uid when storing
        body = _build_body_for_event(events[0], tz, today, tomorrow)
        payload = {"title": title, "body": body, "url": events[0].get('htmlLink', f'/dashboard?id={events[0].get("uid", "")}'), "endpoint": sub_endpoint}
        uid = events[0].get('uid')
        with requests.Session() as s:
            return _post_and_store(s, payload, event_uids=[uid] if uid else None)

    else:

        # Last Minute / immediate: send each event individually using a single Session
        with requests.Session() as s:
            for ev in events:
                title = "Nuova variazione dell'orario!"
                body = _build_body_for_event(ev, tz, today, tomorrow)
                payload = {"title": title, "body": body, "url": ev.get('htmlLink', f'/dashboard?id={ev.get('uid', '')}'), "endpoint": sub_endpoint}
                uid = ev.get('uid')
                _post_and_store(s, payload, event_uids=[uid] if uid else None)
        return True