import time
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe.utils import get_datetime, get_system_timezone


TOKEN_ENDPOINT = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_MEETING_ENDPOINT = "https://graph.microsoft.com/v1.0/users/{user_id}/onlineMeetings"
TOKEN_TTL_BUFFER = 60  # refresh if less than 60s remain before expiry


def _to_graph_utc_iso(value) -> str:
	"""Normalise *value* to a UTC-anchored ISO string Microsoft Graph accepts.

	Frappe stores Event datetimes as naive timestamps in the system timezone;
	`.isoformat()` of a naive datetime drops the offset entirely, which the
	Graph onlineMeetings API rejects with HTTP 400 'Request payload cannot be
	null.' Localise to system tz, convert to UTC, format with explicit 'Z'.
	"""
	dt = get_datetime(value)
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

# TODO: wire up frappe.integrations.utils.create_request_log once the Zoom path
# adopts Integration Request logging; for now we mirror the Zoom pattern (raw
# requests + frappe.log_error on failure).


def get_access_token() -> str:
	"""Return a valid Graph API access token (client credentials flow).

	The token is cached in two places:
	  - the raw value is stored in Appointment Settings.teams_access_token (Password field)
	  - the expiry timestamp is kept in the Frappe cache so we can check it without
	    a DB round-trip on every booking.
	"""
	settings = frappe.get_single("Appointment Settings")
	appointment_settings_link = frappe.utils.get_link_to_form("Appointment Settings", None, "Appointment Settings")

	if not settings.enable_microsoft_teams:
		frappe.throw(frappe._(f"Microsoft Teams is not enabled. Please enable it from {appointment_settings_link}."))

	tenant_id = settings.teams_tenant_id
	client_id = settings.teams_client_id
	client_secret = settings.get_password("teams_client_secret", raise_exception=False)

	if not (tenant_id and client_id and client_secret):
		frappe.throw(
			frappe._(f"Microsoft Teams credentials are not fully configured. Please set Tenant ID, Client ID and Client Secret in {appointment_settings_link}.")
		)

	# Check cache first: avoid token fetch if we have a valid cached token
	cached_token = settings.get_password("teams_access_token", raise_exception=False)
	expiry = frappe.cache.get_value("frappe_appointment::teams_token_expires_at")
	if cached_token and expiry and (float(expiry) - TOKEN_TTL_BUFFER) > time.time():
		return cached_token

	# Fetch a new token from Azure AD
	resp = requests.post(
		TOKEN_ENDPOINT.format(tenant=tenant_id),
		data={
			"grant_type": "client_credentials",
			"client_id": client_id,
			"client_secret": client_secret,
			"scope": "https://graph.microsoft.com/.default",
		},
		timeout=30,
	)
	resp.raise_for_status()
	payload = resp.json()

	token = payload["access_token"]
	expires_in = int(payload.get("expires_in", 3600))

	# Persist the new token in the Settings doc (without bumping modified)
	settings.db_set("teams_access_token", token, update_modified=False)
	frappe.cache.set_value(
		"frappe_appointment::teams_token_expires_at",
		time.time() + expires_in,
	)

	return token


def create_meeting(
	user_object_id: str,
	subject: str,
	start_iso: str,
	end_iso: str,
	user_upn: str = None,
) -> dict:
	"""Create a Teams online meeting on behalf of the given user.

	Microsoft Graph's Application Access Policy is keyed by user Object ID at the
	service layer — calling the endpoint with the UPN alone returns HTTP 404
	UnknownError even when the policy is correctly assigned. The Object ID is
	therefore required; *user_upn* is accepted only for logging context.

	Args:
	    user_object_id: The user's Entra/Azure AD Object ID (GUID). Required.
	    subject:        Meeting subject / title.
	    start_iso:      ISO-8601 datetime string with timezone offset.
	    end_iso:        ISO-8601 end datetime string with timezone offset.
	    user_upn:       Optional UPN (email), used only for diagnostic logging.

	Returns:
	    The Graph API response dict, which includes at minimum 'joinUrl' and 'id'.

	Raises:
	    frappe.ValidationError: if the API call fails or the Object ID is missing.
	"""
	if not user_object_id:
		frappe.throw(frappe._("Microsoft Teams user Object ID is missing. Set it on the User Appointment Availability record (Entra Admin Center → Users → Object ID)."))

	token = get_access_token()

	payload = {
		"subject": subject,
		"startDateTime": _to_graph_utc_iso(start_iso),
		"endDateTime": _to_graph_utc_iso(end_iso),
	}

	resp = requests.post(
		GRAPH_MEETING_ENDPOINT.format(user_id=user_object_id),
		headers={
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
		},
		json=payload,
		timeout=30,
	)

	if resp.status_code >= 400:
		frappe.log_error(
			title="Microsoft Teams meeting creation failed",
			message=(
				f"object_id={user_object_id} upn={user_upn} "
				f"status={resp.status_code} "
				f"sent_payload={payload} "
				f"sent_body={resp.request.body!r} "
				f"response_body={resp.text[:1500]}"
			),
		)
		frappe.throw(
			frappe._("Could not create Microsoft Teams meeting (HTTP {0}).").format(resp.status_code)
		)

	return resp.json()
