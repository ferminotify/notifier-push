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
    """Return (start_date, start_time, end_date, end_time).
    Each value may be None. Accepts ISO datetimes or already-formatted HH:MM strings;
    also checks start.date / end.date. Keeps parsing defensive and logs on parse failures.
    """
    start_date = None
    start_time = ''
    end_date = None
    end_time = ''

    # start.dateTime or start.date
    sdt = ev.get('start.dateTime')
    if sdt:
        if 'T' in sdt:
            try:
                dt = datetime.fromisoformat(sdt)
                if dt.tzinfo is None:
                    dt = tz.localize(dt)
                dt = dt.astimezone(tz)
                start_time = dt.strftime('%H:%M')
                start_date = dt.date()
            except Exception:
                start_time = sdt
                if _LOGGER:
                    _LOGGER.debug(f"_parse_event_datetime: failed to parse start.dateTime '{sdt}'")
        else:
            # already a time string like 'HH:MM'
            start_time = sdt

    sd = ev.get('start.date')
    if sd:
        try:
            if '-' in sd:
                start_date = datetime.strptime(sd, '%Y-%m-%d').date()
            elif '/' in sd:
                start_date = datetime.strptime(sd, '%d/%m/%Y').date()
        except Exception:
            if _LOGGER:
                _LOGGER.debug(f"_parse_event_datetime: failed to parse start.date '{sd}'")

    # end.dateTime or end.date
    edt = ev.get('end.dateTime')
    if edt:
        if 'T' in edt:
            try:
                dt = datetime.fromisoformat(edt)
                if dt.tzinfo is None:
                    dt = tz.localize(dt)
                dt = dt.astimezone(tz)
                end_time = dt.strftime('%H:%M')
                end_date = dt.date()
            except Exception:
                end_time = edt
                if _LOGGER:
                    _LOGGER.debug(f"_parse_event_datetime: failed to parse end.dateTime '{edt}'")
        else:
            end_time = edt

    ed = ev.get('end.date')
    if ed:
        try:
            if '-' in ed:
                end_date = datetime.strptime(ed, '%Y-%m-%d').date()
            elif '/' in ed:
                end_date = datetime.strptime(ed, '%d/%m/%Y').date()
        except Exception:
            if _LOGGER:
                _LOGGER.debug(f"_parse_event_datetime: failed to parse end.date '{ed}'")

    return start_date, start_time or None, end_date, end_time or None


def _build_body_for_event(ev: dict, tz, today, tomorrow):
    start_date, start_time, end_date, end_time = _parse_event_datetime(ev, tz)

    # Use formatted time if available (from main.py format_event_for_display)
    formatted_start = ev.get('_formatted_time')
    if formatted_start:
        start_time = formatted_start
    # main.py may format end.dateTime as HH:MM; prefer explicit _formatted_end_time if present
    formatted_end = ev.get('_formatted_end_time') or ev.get('end.dateTime')
    if formatted_end and ':' in str(formatted_end):
        end_time = formatted_end

    summary = ev.get('summary', '').strip()

    # Helper to format a date to human DD/MM (no year)
    def _fmt_date_short(d):
        return d.strftime('%d/%m') if d else None

    # Same-day events (or only start date known)
    if start_date and (not end_date or start_date == end_date):
        if start_date == today:
            day_label = 'Oggi'
        elif start_date == tomorrow:
            day_label = 'Domani'
        else:
            day_label = _fmt_date_short(start_date)

        if start_time and end_time:
            return f"{day_label} {start_time} - {end_time}: {summary}"
        if start_time:
            return f"{day_label} {start_time}: {summary}"
        if day_label:
            return f"{day_label}: {summary}"

    # Multi-day events
    if start_date and end_date and start_date != end_date:
        start_str = _fmt_date_short(start_date)
        end_str = _fmt_date_short(end_date)
        # If both have times, include them per day
        if start_time and end_time:
            return f"{start_str} {start_time} - {end_str} {end_time}: {summary}"
        # If only dates, show date range without year
        return f"{start_str} - {end_str}: {summary}"

    # If only end date/time present
    if end_date and not start_date:
        if end_date == today:
            day_label = 'Oggi'
        elif end_date == tomorrow:
            day_label = 'Domani'
        else:
            day_label = _fmt_date_short(end_date)
        if end_time:
            return f"{day_label} {end_time}: {summary}"
        return f"{day_label}: {summary}"

    # Fallbacks: if times exist without dates or nothing parsed
    if start_time and end_time:
        return f"{start_time} - {end_time}: {summary}"
    if start_time:
        return f"{start_time}: {summary}"
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
            status = resp.status_code
            ok = status == 200
            removed = status in (403, 404, 410)
            if not ok and _LOGGER:
                _LOGGER.error(f"[push-notifier] notify POST failed: {status} {resp.text}")
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
            return ok, removed
        except Exception as e:
            if _LOGGER:
                _LOGGER.error(f"[push-notifier] notify request exception: {e}")
            return False, False

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
        results = []
        with requests.Session() as s:
            for ev in events:
                title = "Nuova variazione dell'orario!"
                body = _build_body_for_event(ev, tz, today, tomorrow)
                payload = {"title": title, "body": body, "url": ev.get('htmlLink', f'/dashboard?id={ev.get('uid', '')}'), "endpoint": sub_endpoint}
                uid = ev.get('uid')
                ok, removed = _post_and_store(s, payload, event_uids=[uid] if uid else None)
                results.append(ok)
                if removed:
                    # backend indicated subscription removed (410/404/403) — stop sending further events for this endpoint
                    if _LOGGER:
                        _LOGGER.info(f"[push-notifier] endpoint removed, stopping further sends for endpoint: {sub_endpoint}")
                    break
        return results