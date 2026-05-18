"""Background job: create a video-meeting link for an already-saved Event.

Triggered when an Appointment Group has `defer_meeting_creation=1`. Lets the
booking endpoint return instantly while a worker calls the (potentially slow)
provider API (Zoom, Microsoft Teams). When the link is ready, the existing
confirmation email is re-triggered so the customer receives it with the link.
"""
import json

import frappe
from frappe.utils import get_datetime, now

from frappe_appointment.constants import APPOINTMENT_GROUP, USER_APPOINTMENT_AVAILABILITY


def create_meeting_for_event(event_name: str):
	"""Worker entry point — called via frappe.enqueue."""
	event = frappe.get_doc("Event", event_name)
	provider = event.custom_meeting_provider

	try:
		if provider == "Microsoft Teams":
			_create_teams(event)
		elif provider == "Zoom":
			_create_zoom(event)
		else:
			return  # nothing to do for Custom / Google Meet (Google Meet links are created by Google Calendar itself)
	except Exception as exc:
		frappe.log_error(
			title=f"{provider} async meeting creation failed — booking preserved",
			message=f"event={event_name} starts_on={event.starts_on} err={exc!r}",
		)
		_mark_failed(event_name, provider, exc)
		return

	_send_meet_link_email(event_name)


# ---------------------------------------------------------------------------
# Provider-specific creation
# ---------------------------------------------------------------------------
def _create_teams(event):
	from frappe_appointment.helpers.teams import create_meeting as create_teams_meeting

	if event.custom_appointment_group:
		ag = frappe.get_doc(APPOINTMENT_GROUP, event.custom_appointment_group)
		members = ag.members or []
		host_member = next((m for m in members if m.is_mandatory), members[0] if members else None)
		host_upn, host_oid = frappe.db.get_value(
			"User Appointment Availability", host_member.user,
			["teams_user_email", "teams_user_object_id"],
		) or (None, None)
		subject = event.subject or ag.group_name
	else:
		uaa = frappe.get_doc(USER_APPOINTMENT_AVAILABILITY, event.custom_user_calendar)
		host_upn = uaa.teams_user_email
		host_oid = uaa.teams_user_object_id
		subject = event.subject or uaa.user

	teams_meeting = create_teams_meeting(
		user_object_id=host_oid,
		user_upn=host_upn,
		subject=subject,
		start_iso=get_datetime(event.starts_on).isoformat(),
		end_iso=get_datetime(event.ends_on).isoformat(),
	)
	_persist_meet_data(event.name, teams_meeting.get("joinUrl", ""), teams_meeting)


def _create_zoom(event):
	from frappe_appointment.helpers.zoom import create_meeting as create_zoom_meeting

	if event.custom_appointment_group:
		ag = frappe.get_doc(APPOINTMENT_GROUP, event.custom_appointment_group)
		creator = ag.event_creator
		duration = ag.duration_for_event // 60
	else:
		uaa = frappe.get_doc(USER_APPOINTMENT_AVAILABILITY, event.custom_user_calendar)
		creator = uaa.google_calendar
		duration = max(
			(frappe.utils.time_diff(event.ends_on, event.starts_on).seconds // 60) or 30,
			1,
		)

	meet_url, meet_data = create_zoom_meeting(
		creator, event.subject, event.starts_on, duration, event.description,
	)
	_persist_meet_data(event.name, meet_url, meet_data)


# ---------------------------------------------------------------------------
# Shared persistence
# ---------------------------------------------------------------------------
def _persist_meet_data(event_name: str, meet_url: str, meet_data: dict):
	current_desc = frappe.db.get_value("Event", event_name, "description") or ""
	# Replace any "[link will follow…]" placeholder from the pending state.
	clean_desc = "\n".join(
		line for line in current_desc.splitlines()
		if "could not be created automatically" not in line and "link will follow" not in line.lower()
	).rstrip()
	new_desc = f"{clean_desc}\nMeet Link: {meet_url}" if meet_url else clean_desc

	frappe.db.set_value(
		"Event", event_name,
		{
			"custom_meet_link": meet_url,
			"custom_meet_data": json.dumps(meet_data, indent=4),
			"description": new_desc,
		},
		update_modified=False,
	)
	frappe.db.commit()


def _mark_failed(event_name: str, provider: str, exc: Exception):
	frappe.db.set_value(
		"Event", event_name,
		{
			"custom_meet_data": json.dumps({
				"creation_failed": True,
				"provider": provider,
				"error": str(exc),
				"failed_at": now(),
				"via": "async_job",
			}, indent=2),
		},
		update_modified=False,
	)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def _send_meet_link_email(event_name: str):
	"""Re-fire the confirmation email now that custom_meet_link is populated.

	Reuses the existing send_meet_email() so the upstream template is honoured.

	Note: send_meet_email -> add_ics_file_in_attachment relies on a runtime-only
	`appointment_group` attribute that upstream's before_save sets on the Event
	doc. We're loading the Event fresh here, so we have to mirror that setup
	before handing the doc to send_meet_email — otherwise it AttributeErrors.
	"""
	from frappe_appointment.overrides.event_override import send_meet_email

	event = frappe.get_doc("Event", event_name)
	if not event.custom_meet_link:
		return  # nothing to mail; failure path leaves this empty

	appointment_group = (
		frappe.get_doc(APPOINTMENT_GROUP, event.custom_appointment_group)
		if event.custom_appointment_group else None
	)
	user_calendar = (
		frappe.get_doc(USER_APPOINTMENT_AVAILABILITY, event.custom_user_calendar)
		if event.custom_user_calendar else None
	)
	# Set the runtime attributes upstream's before_save would have set
	event.appointment_group = appointment_group
	event.user_calendar = user_calendar

	metadata = event.event_info if hasattr(event, "event_info") else {}
	send_meet_email(
		doc=event,
		appointment_group=appointment_group,
		user_calendar=user_calendar,
		metadata=metadata,
	)
