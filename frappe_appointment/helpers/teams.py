import time

import frappe
import requests


TOKEN_ENDPOINT = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_MEETING_ENDPOINT = "https://graph.microsoft.com/v1.0/users/{upn}/onlineMeetings"
TOKEN_TTL_BUFFER = 60  # refresh if less than 60s remain before expiry

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


def create_meeting(user_upn: str, subject: str, start_iso: str, end_iso: str) -> dict:
	"""Create a Teams online meeting on behalf of *user_upn*.

	Args:
	    user_upn: The Microsoft 365 UPN (email) of the organiser user.
	    subject:   Meeting subject / title.
	    start_iso: ISO-8601 datetime string with timezone offset, e.g. '2026-07-16T10:00:00+00:00'.
	    end_iso:   ISO-8601 end datetime string with timezone offset.

	Returns:
	    The Graph API response dict, which includes at minimum 'joinUrl' and 'id'.

	Raises:
	    frappe.ValidationError: if the API call fails.
	"""
	if not user_upn:
		frappe.throw(frappe._("Microsoft Teams user email (UPN) is missing for this member."))

	token = get_access_token()

	resp = requests.post(
		GRAPH_MEETING_ENDPOINT.format(upn=user_upn),
		headers={
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
		},
		json={
			"subject": subject,
			"startDateTime": start_iso,
			"endDateTime": end_iso,
		},
		timeout=30,
	)

	if resp.status_code >= 400:
		frappe.log_error(
			title="Microsoft Teams meeting creation failed",
			message=f"upn={user_upn} status={resp.status_code} body={resp.text[:1500]}",
		)
		frappe.throw(
			frappe._("Could not create Microsoft Teams meeting (HTTP {0}).").format(resp.status_code)
		)

	return resp.json()
