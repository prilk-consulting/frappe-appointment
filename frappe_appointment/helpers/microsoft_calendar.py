"""Microsoft Calendar support through the microsoft_integrations app.

microsoft_integrations is to Microsoft 365 what Frappe core's Google Calendar integration is to
Google: it owns the Microsoft Calendar doctype, the Graph login, and pushes Events to Outlook
(with a Teams link when Event.add_video_conferencing is set). This module only does what
frappe_appointment does with Google Calendar: link calendars, read busy time and pick the organiser.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from frappe_appointment.helpers.utils import convert_timezone_to_utc, get_today_min_max_time

MICROSOFT_CALENDAR = "Microsoft Calendar"


def is_microsoft_calendar_installed() -> bool:
    return bool(frappe.db.exists("DocType", MICROSOFT_CALENDAR))


def setup_microsoft_fields():
    """Add Microsoft Calendar links next to the Google Calendar ones, if microsoft_integrations is installed."""
    if not is_microsoft_calendar_installed():
        return
    create_custom_fields(
        {
            "User Appointment Availability": [
                {
                    "fieldname": "microsoft_calendar",
                    "fieldtype": "Link",
                    "label": "Microsoft Calendar",
                    "options": MICROSOFT_CALENDAR,
                    "insert_after": "google_calendar",
                }
            ],
            "Appointment Group": [
                {
                    "fieldname": "microsoft_calendar",
                    "fieldtype": "Link",
                    "label": "Microsoft Calendar (Event Creator)",
                    "options": MICROSOFT_CALENDAR,
                    "insert_after": "event_creator",
                    "description": "Used instead of a Google Calendar event creator.",
                }
            ],
        }
    )


def get_busy_slots(calendar_name: str, date, starttime, endtime) -> list:
    """Busy periods of a Microsoft Calendar on *date*, shaped like Google Calendar events."""
    from frappe_appointment.frappe_appointment.doctype.appointment_time_slot.appointment_time_slot import (
        check_if_datetime_in_range,
    )

    calendar = frappe.get_doc(MICROSOFT_CALENDAR, calendar_name)
    time_max, time_min = get_today_min_max_time(date)
    busy_slots = []
    for start, end in calendar.get_busy_times(time_min.rstrip("Z"), time_max.rstrip("Z")):
        # Graph returns naive UTC datetimes; make the offset explicit before converting.
        slot = {
            "start": {"dateTime": start.split(".")[0] + "+00:00", "timeZone": "UTC"},
            "end": {"dateTime": end.split(".")[0] + "+00:00", "timeZone": "UTC"},
        }
        if check_if_datetime_in_range(
            convert_timezone_to_utc(slot["start"]["dateTime"], "UTC"),
            convert_timezone_to_utc(slot["end"]["dateTime"], "UTC"),
            starttime,
            endtime,
        ):
            busy_slots.append(slot)
    return busy_slots


def get_event_fields(calendar_name: str, add_video_conferencing: bool) -> dict:
    """Event fields that make microsoft_integrations push the booking to Outlook (and add Teams)."""
    return {
        "sync_with_microsoft_calendar": 1,
        "microsoft_calendar": calendar_name,
        "pulled_from_microsoft_calendar": 0,
        "add_video_conferencing": 1 if add_video_conferencing else 0,
    }
