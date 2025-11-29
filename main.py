'''
    Main for Push Notifier application.
'''
from src.db import NotifierDB
from src.events import get_events, filter_events_kw, remove_sent_events
from src.logger import Logger
from src.push import send_push_notification
from datetime import datetime, timedelta
import time
import pytz

logger = Logger()

if __name__ == "__main__":
    logger.info("Starting Push Notifier application.")

    errors = 0
    notifications = 0

    # Constants to avoid repeated lookups/allocations
    tz_rome = pytz.timezone("Europe/Rome")
    now_rome = datetime.now(tz_rome)
    today_start = now_rome.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    def event_start_dt(event):
        """Return aware datetime for start if present, else None.
        Prefer `start.dateTime` (ISO-8601), fallback to `start.date` at midnight Rome.
        """
        dt_str = event.get("start.dateTime")
        if dt_str:
            try:
                # fromisoformat may return naive if no timezone; assume Rome
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = tz_rome.localize(dt)
                return dt.astimezone(tz_rome)
            except Exception:
                return None
        d_str = event.get("start.date")
        if d_str:
            try:
                d = datetime.strptime(d_str, "%Y-%m-%d")
                return tz_rome.localize(d.replace(hour=0, minute=0, second=0, microsecond=0))
            except Exception:
                return None
        return None

    def in_day(event, day_start):
        """Check if event occurs within the 24h window starting at day_start (Rome)."""
        dt = event_start_dt(event)
        if not dt:
            return False
        return day_start <= dt < (day_start + timedelta(days=1))

    def format_event_for_display(event):
        """Produce a shallow copy with human-friendly date/time fields for sending."""
        e = dict(event)
        try:
            # Preserve original ISO dates for date comparison in utils.py
            if e.get('start.date'):
                original_date = e['start.date']
                e['start.date'] = datetime.strptime(original_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            if e.get('end.date'):
                original_date = e['end.date']
                e['end.date'] = datetime.strptime(original_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            if e.get('start.dateTime'):
                original_dt = e['start.dateTime']
                dt = datetime.fromisoformat(original_dt)
                if dt.tzinfo is None:
                    dt = tz_rome.localize(dt)
                # Keep original ISO datetime for date comparison, format time separately
                e['start.dateTime'] = original_dt
                e['_formatted_time'] = dt.astimezone(tz_rome).strftime('%H:%M')
            if e.get('end.dateTime'):
                dt = datetime.fromisoformat(e['end.dateTime'])
                if dt.tzinfo is None:
                    dt = tz_rome.localize(dt)
                e['end.dateTime'] = dt.astimezone(tz_rome).strftime('%H:%M')
        except Exception:
            # If formatting fails, fall back to original values
            pass
        return e

    try:
        db = NotifierDB()
        subs = db.get_subscribers_push()

        events = get_events()

        for sub in subs:
            logger.info(f"Subscriber ID: {sub['id']}, Device: {sub['device_id']}, Keywords: {sub['keywords']}")
            # GET USER push_sent for this specific device
            sent_push_ids = db.get_all_sent_push_id(sub['id'], sub['device_id'])
            events_filtered = filter_events_kw(events, sub['keywords'])
            events_filtered = remove_sent_events(events_filtered, sent_push_ids)
            logger.info(f"Found {len(events_filtered)} new events for subscriber ID {sub['id']} after filtering.")
            logger.debug(f"Events to send: {events_filtered}")
            # Do not mutate events before time-based filtering; format only before sending
            
            '''
            events left are to be sent
            '''

            # check if user has send_push_with_notifications = True
            if sub['send_push_with_notifications']:
                '''
                Send with email / telegram notification
                '''

                # Split events in today and tomorrow
                today_rome = today_start
                tomorrow_rome = tomorrow_start

                events_today = [e for e in events_filtered if in_day(e, today_rome)]
                events_tomorrow = [e for e in events_filtered if in_day(e, tomorrow_rome)]

                # Check if it's time for Daily Notification
                daily_notification_datetime_end = datetime.combine(now_rome.date(), sub["notification_time"]) + timedelta(minutes=15)

                try:
                    if sub["notification_time"] <= now_rome.time() <= daily_notification_datetime_end.time(): # Daily Notification
                        if sub["notification_day_before"]:
                            # Send the notification for today (usually empty - rare case new event added right now and not yet sent as last min) and tomorrow
                            payload = [format_event_for_display(e) for e in (events_today + events_tomorrow)]
                            send_push_notification(sub["endpoint"], payload, "Daily Notification", sub['id'], sub['device_id'])
                            logger.info(f"[>] Sent Daily Notification ({len(events_today + events_tomorrow)}) to {sub['email']}.")
                            notifications += 1
                        else:
                            if events_today:
                                # Send the notification for today
                                payload = [format_event_for_display(e) for e in events_today]
                                send_push_notification(sub["endpoint"], payload, "Daily Notification", sub['id'], sub['device_id'])
                                logger.info(f"[>] Sent Daily Notification ({len(events_today)}) to {sub['email']}.")
                                notifications += 1
                    else: # Last Minute Notification
                        if sub["notification_day_before"]: # if user wants the Daily Notification the day before send today notifications as Last Minute
                            # if it's after the Daily Notification time send Last Minute Notification
                            if now_rome.time() > daily_notification_datetime_end.time():
                                payload = [format_event_for_display(e) for e in (events_today + events_tomorrow)]
                                send_push_notification(sub["endpoint"], payload, "Last Minute Notification", sub['id'], sub['device_id'])
                                logger.info(f"[>] Sent Last Minute Notification ({len(events_today + events_tomorrow)}) to {sub['email']}.")
                                notifications += 1
                            else: # if it's before the Daily Notification time send only today notifications as Last Minute (if not already sent)
                                if events_today:
                                    payload = [format_event_for_display(e) for e in events_today]
                                    send_push_notification(sub["endpoint"], payload, "Last Minute Notification", sub['id'], sub['device_id'])
                                    logger.info(f"[>] Sent Last Minute Notification ({len(events_today)}) to {sub['email']}.")
                                    notifications += 1
                        else: # if it's after the Daily Notification time and user doesn't want the Daily Notification the day before send only today notifications as Last Minute
                            if events_today:
                                if now_rome.time() > daily_notification_datetime_end.time():
                                    payload = [format_event_for_display(e) for e in events_today]
                                    send_push_notification(sub["endpoint"], payload, "Last Minute Notification", sub['id'], sub['device_id'])
                                    logger.info(f"[>] Sent Last Minute Notification ({len(events_today)}) to {sub['email']}.")
                                    notifications += 1

                except Exception as e:
                    logger.error(f"[X] Error sending notification to {sub['email']}: {e}")
                    errors += 1
            
            else:
                '''
                send push notification
                '''
                # check event if it's today or tomorrow
                today_rome = today_start
                tomorrow_rome = tomorrow_start

                events_today = [e for e in events_filtered if in_day(e, today_rome)]
                events_tomorrow = [e for e in events_filtered if in_day(e, tomorrow_rome)]

                try:
                    if events_today or events_tomorrow:
                        payload = [format_event_for_display(e) for e in (events_today + events_tomorrow)]
                        send_push_notification(sub["endpoint"], payload, "Last Minute Notification", sub['id'], sub['device_id'])
                        logger.info(f"[>] Sent Push Notification ({len(events_today) + len(events_tomorrow)}) to {sub['email']}.")
                        notifications += 1
                    else:
                        logger.info(f"[i] No events to send push notification to {sub['email']}.")
                except Exception as e:
                    logger.error(f"[X] Error sending push notification to {sub['email']}: {e}")
                    errors += 1
            
        db.close_connection()
    except Exception as e:
        logger.error(f"An error occurred in main: {e}")
        time.sleep(10)  # Wait before retrying