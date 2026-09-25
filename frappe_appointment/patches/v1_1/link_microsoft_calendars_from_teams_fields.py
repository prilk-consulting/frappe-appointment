import frappe

from frappe_appointment.helpers.microsoft_calendar import is_microsoft_calendar_installed, setup_microsoft_fields

AVAILABILITY = "User Appointment Availability"


def execute():
    """Sites that ran the earlier built-in Teams support kept the host's Microsoft user on the
    availability (teams_user_object_id). Link the Microsoft Calendar of that user instead, and use
    it as event creator for Teams groups that have no calendar yet."""
    if not is_microsoft_calendar_installed() or not frappe.db.has_column(AVAILABILITY, "teams_user_object_id"):
        return

    # Custom fields are normally created after migrate; this patch needs them now.
    setup_microsoft_fields()

    calendars = {
        row.microsoft_user_object_id: row.name
        for row in frappe.get_all("Microsoft Calendar", fields=["name", "microsoft_user_object_id"])
        if row.microsoft_user_object_id
    }
    availabilities = frappe.db.sql(
        f"select name, teams_user_object_id from `tab{AVAILABILITY}` where ifnull(teams_user_object_id, '') != ''",
        as_dict=True,
    )
    for availability in availabilities:
        calendar = calendars.get(availability.teams_user_object_id)
        if calendar and not frappe.db.get_value(AVAILABILITY, availability.name, "microsoft_calendar"):
            frappe.db.set_value(AVAILABILITY, availability.name, "microsoft_calendar", calendar, update_modified=False)

    groups = frappe.get_all(
        "Appointment Group",
        filters={"meet_provider": "Microsoft Teams"},
        fields=["name", "event_creator", "microsoft_calendar"],
    )
    for group in groups:
        if group.event_creator or group.microsoft_calendar:
            continue
        hosts = frappe.get_all(
            "Members",
            filters={"parent": group.name, "parenttype": "Appointment Group", "is_mandatory": 1},
            pluck="user",
            order_by="idx",
        )
        calendar = hosts and frappe.db.get_value(AVAILABILITY, hosts[0], "microsoft_calendar")
        if calendar:
            frappe.db.set_value("Appointment Group", group.name, "microsoft_calendar", calendar, update_modified=False)
