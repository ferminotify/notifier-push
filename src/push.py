import os
from datetime import datetime, timedelta
import pytz
import requests
from src.logger import Logger
logger = Logger()
from src.db import NotifierDB


# try to instantiate a module logger if present; fall back to None
try:
    from src.logger import Logger
    _LOGGER = Logger()
except Exception:
    _LOGGER = None


def _parse_event_datetime(ev: dict, tz):
    """Return (ev_date: date|None, time_str: str|None).
    Accepts ISO datetimes or already-formatted HH:MM strings; also checks start.date.
    """
    ev_date = None
    time_str = ''

    sdt = ev.get('start.dateTime')
    if sdt:
        if 'T' in sdt:
            try:
                dt = datetime.fromisoformat(sdt)
                dt = dt.astimezone(tz)
                time_str = dt.strftime('%H:%M')
                ev_date = dt.date()
            except Exception:
                # keep raw string as fallback
                time_str = sdt
                ev_date = None
        else:
            # assume already HH:MM
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
            pass

    return ev_date, time_str


def _build_body_for_event(ev: dict, tz, today, tomorrow):
    ev_date, time_str = _parse_event_datetime(ev, tz)
    
    # Use formatted time if available (from main.py format_event_for_display)
    formatted_time = ev.get('_formatted_time')
    if formatted_time:
        time_str = formatted_time
    
    when = 'Oggi'
    if ev_date == tomorrow:
        when = 'Domani'
    # default to 'Oggi' if ev_date is today or unknown

    summary = ev.get('summary', '').strip()
    if time_str:
        return f"{when} alle {time_str}: {summary}"
    return summary


def send_push_notification(sub_endpoint, events, notification_type, user_id=None, device_id=None):
    """Send push notifications. For Daily Notification a single summary message is sent
    (or a single-event detailed message). For Last Minute / immediate notifications each
    event is sent as a separate POST to the backend notify endpoint.
    Returns True/False or list of booleans for per-event sends.
    """
    notification_api_key = os.getenv("NOTIFICATION_API_KEY")
    headers = {
        "Authorization": f"Bearer {notification_api_key}",
        "Content-Type": "application/json"
    }

    logger.debug(str(events))

    tz = pytz.timezone("Europe/Rome")
    today = datetime.now(tz).date()
    tomorrow = today + timedelta(days=1)

    if notification_type == "Daily Notification":

        # single notification summarizing the day's events
        title = f"Daily Notification ({len(events)} event{'o' if len(events) == 1 else 'i'})"
        if len(events) > 1:
            body = f"Sono previsti {len(events)} evento{'o' if len(events) == 1 else 'i'}."
            payload = {"title": title, "body": body, "url": "/dashboard", "endpoint": sub_endpoint}
            # Send one notification via backend notify endpoint
            notify_url = os.getenv("BACKEND_URL") + "/user/push/notify"
            try:
                with requests.Session() as s:
                    resp = s.post(notify_url, headers=headers, json=payload, timeout=10)
                    ok = resp.status_code == 200
                    if not ok and _LOGGER:
                        _LOGGER.error(f"[push-notifier] notify POST failed: {resp.status_code} {resp.text}")
                    # If send succeeded and we have subscriber/device info, store all event uids
                    if ok and user_id and device_id:
                        try:
                            db = NotifierDB()
                            for ev in events:
                                uid = ev.get('uid')
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

        else:
            # single event: build detailed body
            body = _build_body_for_event(events[0], tz, today, tomorrow)
            payload = {"title": title, "body": body, "url": events[0].get('htmlLink', f'/dashboard?id={events[0].get("uid", "")}'), "endpoint": sub_endpoint}
            notify_url = os.getenv("BACKEND_URL") + "/user/push/notify"
            try:
                with requests.Session() as s:
                    resp = s.post(notify_url, headers=headers, json=payload, timeout=10)
                    ok = resp.status_code == 200
                    if not ok and _LOGGER:
                        _LOGGER.error(f"[push-notifier] notify POST failed: {resp.status_code} {resp.text}")
                    else:
                        # successful single-event send: store push_sent if subscriber info provided
                        if ok and user_id and device_id:
                            try:
                                db = NotifierDB()
                                uid = events[0].get('uid')
                                if uid:
                                    db.store_push_sent(user_id, uid, device_id)
                                db.close_connection()
                            except Exception:
                                if _LOGGER:
                                    _LOGGER.error("[push-notifier] failed to store push_sent entry for single event")
                    return ok
            except Exception as e:
                if _LOGGER:
                    _LOGGER.error(f"[push-notifier] notify request exception: {e}")
                return False

    else:

        # Last Minute / immediate: send each event individually using a single Session
        notify_url = os.getenv("BACKEND_URL") + "/user/push/notify"
        results = []
        # Use a single DB connection for storing multiple per-event sends when possible
        db = None
        if user_id and device_id:
            try:
                db = NotifierDB()
            except Exception:
                db = None

        with requests.Session() as s:
            for ev in events:
                title = "Nuova variazione dell'orario!"
                body = _build_body_for_event(ev, tz, today, tomorrow)
                payload = {"title": title, "body": body, "url": ev.get('htmlLink', f'/dashboard?id={ev.get("uid", "")}'), "endpoint": sub_endpoint}
                try:
                    resp = s.post(notify_url, headers=headers, json=payload, timeout=10)
                    ok = resp.status_code == 200
                    if not ok and _LOGGER:
                        _LOGGER.error(f"[push-notifier] notify POST failed: {resp.status_code} {resp.text}")
                    results.append(ok)
                    _LOGGER.debug(f"[push-notifier] notify POST succeeded for event {ev.get('uid', '')}.")
                    if ok and db and user_id and device_id:
                        try:
                            uid = ev.get('uid')
                            if uid:
                                db.store_push_sent(user_id, uid, device_id)
                        except Exception:
                            if _LOGGER:
                                _LOGGER.error(f"[push-notifier] failed to store push_sent for event {ev.get('uid', '')}")
                except Exception as e:
                    results.append(False)
                    if _LOGGER:
                        _LOGGER.error(f"[push-notifier] notify request exception: {e}")
                    # continue to next event instead of returning immediately
                    continue

        if db:
            try:
                db.close_connection()
            except Exception:
                pass

        return results