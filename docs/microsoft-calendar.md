# Microsoft 365 calendars and Microsoft Teams

Frappe Appointment works with Microsoft 365 the way it works with Google Calendar. The Microsoft side is provided by the [microsoft_integrations](https://github.com/prilk-consulting/microsoft_integrations) app, which is to Microsoft 365 what Frappe's built-in Google Calendar integration is to Google.

| | Google | Microsoft 365 |
|---|---|---|
| Calendar record | Google Calendar (Frappe) | Microsoft Calendar (microsoft_integrations) |
| Busy time for bookable slots | Member's Google Calendar | Member's Microsoft Calendar |
| Booking in the host's calendar | Event synced to Google Calendar | Event synced to Outlook |
| Video meeting | Google Meet | Microsoft Teams |
| Reschedule / cancel | Moves / deletes the Google event | Moves / deletes the Outlook event |

## Setup

1. Install and set up **microsoft_integrations** (Microsoft Settings, then a **Microsoft Calendar** per person, with *Push to Microsoft Calendar* enabled). Run `bench migrate` afterwards: Frappe Appointment then adds a **Microsoft Calendar** field to *User Appointment Availability* and *Appointment Group*.
2. **User Appointment Availability**: set **Microsoft Calendar** instead of *Google Calendar*. Busy time in that calendar blocks booking slots.
3. **Appointment Group**: set **Microsoft Calendar (Event Creator)** instead of *Event Creator*, and **Meet Provider** to **Microsoft Teams** for Teams meetings.

A member or group needs either a Google Calendar or a Microsoft Calendar. Google Meet and Zoom need a Google Calendar; Microsoft Teams needs a Microsoft Calendar.

The Teams link is created by microsoft_integrations when the booking is pushed to Outlook and is used in the confirmation email like a Google Meet link.
