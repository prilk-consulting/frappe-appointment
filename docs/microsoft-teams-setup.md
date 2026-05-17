# Microsoft Teams setup for Frappe Appointment

This guide walks through every step needed to use **Microsoft Teams** as the meeting provider for bookings made through Frappe Appointment. After completing it, every booking on an Appointment Group whose `meet_provider` is set to *Microsoft Teams* automatically gets a real Teams meeting URL.

Estimated time: **20 minutes**, of which ~10 minutes is waiting for Microsoft to propagate a tenant policy.

---

## What this gives you

- Customer picks a slot on your public booking page
- Frappe creates an online Teams meeting on the host's calendar via Microsoft Graph
- The booking confirmation email + Frappe Calendar Event both include the Teams **join URL**
- The meeting appears in the host's Outlook / Teams Calendar automatically (Graph creates it under their user)

No Google Calendar required for this path — only Microsoft 365.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Microsoft 365 tenant with Teams licenses for bookable users | The Graph API creates meetings on a user's own Teams calendar; users without a Teams license can't host. |
| **Global Admin** or **Teams Administrator** role on the tenant | Required to consent app permissions in Azure and to grant the Teams application access policy via PowerShell. |
| Frappe Appointment app installed and running on a Frappe site | This guide assumes the app is already installed (the Settings, UAA and Appointment Group doctypes exist). |
| Local PowerShell (Mac/Linux/Windows) **or** Azure Cloud Shell | One short PowerShell session is required (~5 minutes). |

---

## Step 1 — Register an application in Microsoft Entra ID

The app represents Frappe Appointment to Microsoft. It needs permission to call the Graph API on behalf of your bookable users.

1. Sign in to [portal.azure.com](https://portal.azure.com) with a Global Admin account.
2. Top search bar → type **Microsoft Entra ID** → click the result.
3. Left sidebar → **App registrations** → **+ New registration**.
4. Fill in:
   - **Name**: `Frappe Appointment` (or whatever you'd like to see in audit logs)
   - **Supported account types**: **Accounts in this organizational directory only — Single tenant** (unless you specifically need multi-tenant)
   - **Redirect URI**: leave blank (this app uses client-credentials flow, no redirect)
5. Click **Register**.

You're taken to the app's **Overview** page. Note these two values from the right column — you'll need them in Step 4:

- **Application (client) ID** — looks like `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`
- **Directory (tenant) ID** — another UUID

---

## Step 2 — Create a client secret

The client secret is the password your Frappe site uses to prove it is the registered app.

1. Still on the app, left sidebar → **Certificates & secrets** → **Client secrets** tab → **+ New client secret**.
2. **Description**: e.g. `frappe-appointment-prod`
3. **Expires**: choose a sensible lifetime (Azure allows up to 24 months). Set a calendar reminder to rotate before it expires.
4. Click **Add**.
5. **Copy the Value column immediately.** Azure shows the value exactly once; if you navigate away you'll have to delete the secret and create a new one.

Save the secret somewhere secure (a password manager, or your internal credentials store). You'll paste it into Frappe in Step 5.

> The **Secret ID** column (a UUID next to the value) is *not* the value — it's just Azure's internal identifier for the secret entry. Ignore it.

---

## Step 3 — Grant the Graph API permission

The app needs permission to create online meetings.

1. Same app, left sidebar → **API permissions** → **+ Add a permission**.
2. **Microsoft Graph** → **Application permissions** (NOT *Delegated permissions*).
3. Search for `OnlineMeetings.ReadWrite.All`. Tick the box. **Add permissions**.
4. Back on the API permissions list, you'll see the new permission with **Status** = "Not granted".
5. Click **Grant admin consent for [your tenant]** at the top of the table. Confirm.
6. The Status column should now show a green ✓.

---

## Step 4 — Grant tenant policy (PowerShell)

Even with the permission granted in Step 3, Microsoft requires one more security gate before an app can create Teams meetings: an **application access policy**. There's no Azure portal UI for this — only PowerShell. This is the most commonly missed step.

### Why this exists

`OnlineMeetings.ReadWrite.All` is broad — without further scoping it could create meetings for anyone in the tenant (including senior leadership). Microsoft made it so admins must explicitly authorize *which users* the app may act on behalf of. For most deployments you want **tenant-wide** (every user). For tighter scope you can grant per-user.

### Option A — Local PowerShell on Mac/Linux

```bash
brew install --cask powershell        # Mac (one time)
# Linux: see https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-linux
pwsh                                  # starts PowerShell
```

### Option B — Azure Cloud Shell

1. portal.azure.com → click the **>_** icon in the top toolbar.
2. Pick **PowerShell** when prompted.
3. Accept storage account creation prompt if shown.

> Cloud Shell connects to MicrosoftTeams as the managed identity (`MSI@...`), not your admin account. After step 4.2 below, use `Connect-MicrosoftTeams -UseDeviceAuthentication` instead of plain `Connect-MicrosoftTeams`.

### 4.1 Install the MicrosoftTeams module (one-time)

```powershell
Install-Module -Name MicrosoftTeams -Force -Scope CurrentUser
```

### 4.2 Connect as a Teams Admin

```powershell
# Local PowerShell — pops up a browser:
Connect-MicrosoftTeams

# OR Cloud Shell / non-interactive — device code flow:
Connect-MicrosoftTeams -UseDeviceAuthentication
```

The output should show your admin account in the **Account** column (e.g. `admin@contoso.com`), NOT `MSI@…`.

### 4.3 Create the application access policy

```powershell
New-CsApplicationAccessPolicy `
    -Identity "FrappeAppointmentPolicy" `
    -AppIds "<your client id from Step 1>" `
    -Description "Allow Frappe Appointment to create Teams meetings"
```

`-Identity` is just a label, choose any name. `-AppIds` must be your **Application (client) ID** from Step 1.

Expected output (returned silently or with the policy summary):

```
Identity    : Tag:FrappeAppointmentPolicy
AppIds      : {aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}
Description : Allow Frappe Appointment to create Teams meetings
```

### 4.4 Grant the policy tenant-wide

```powershell
Grant-CsApplicationAccessPolicy `
    -PolicyName "FrappeAppointmentPolicy" `
    -Global
```

`-Global` means *every user in the tenant* — both today and any future hires. Returns silently on success.

For tighter scope (only specific users), use `-Identity user@tenant.com` instead of `-Global`. Repeat the command per user.

### 4.5 Verify

```powershell
Get-CsApplicationAccessPolicy -Identity "FrappeAppointmentPolicy"
```

Should print the policy details with your client ID.

### 4.6 Wait for propagation

**The grant takes about 10 minutes to propagate** through Microsoft's infrastructure. If you test Step 6 before propagation completes you'll get HTTP 403. Just wait and retry.

---

## Step 5 — Configure Frappe

On your Frappe site, in the desk:

### 5.1 Appointment Settings (single doctype)

Open `/app/appointment-settings` → scroll to the **Microsoft Teams Settings** section:

| Field | Value |
|---|---|
| **Enable Microsoft Teams** | ✓ tick |
| **Tenant ID** | Your **Directory (tenant) ID** from Step 1 |
| **Client ID** | Your **Application (client) ID** from Step 1 |
| **Client Secret** | The secret **value** from Step 2 (stored encrypted at rest) |

Save.

### 5.2 User Appointment Availability — per bookable user

For each person who'll host bookings, open `/app/user-appointment-availability/<their-name>`:

- **Teams User Email**: their Microsoft 365 UPN (the email they sign in to Outlook / Teams with).

The UPN is the address that owns the calendar where meetings will appear. It must match a real user in your tenant who has a Teams license.

### 5.3 Appointment Group

For each Appointment Group whose bookings should be Teams meetings, open `/app/appointment-group/<group-name>`:

- **Meet Provider**: **Microsoft Teams**

Save. (The validate logic will check that each member has a `Teams User Email` set on their UAA and that the Settings credentials are complete; it will block save with a clear error if anything is missing.)

---

## Step 6 — Test a booking

Open the group's public URL in an incognito browser:

```
https://<your-site>/schedule/gr/<appointment-group-name>
```

Pick a day, pick a slot, fill in your name and email, click **Schedule**. The confirmation should include the Teams meeting join URL. The same URL is on the resulting Calendar Event in Frappe (`/app/event/<event-name>`) — both in the description and in the `custom_meet_link` field.

To verify on the Microsoft side, sign in to https://outlook.office.com/calendar as the host user. The meeting should appear on their calendar with a "Join Microsoft Teams Meeting" link.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| HTTP 400 from token endpoint | Tenant ID is wrong, or client secret is mistyped | Double-check both values in Appointment Settings. Tenant ID must be the UUID, not the tenant name. |
| HTTP 401 on token | Client secret expired or was invalidated | Create a new secret in Step 2, paste into Appointment Settings, save. |
| HTTP 403 when creating meeting | App access policy hasn't propagated yet, OR the user isn't covered by the policy | Wait 10 minutes after `Grant-CsApplicationAccessPolicy`. If using per-user scope (not `-Global`), confirm the host's UPN was granted. |
| `User not found` / 404 | `Teams User Email` on the UAA doesn't match a real M365 UPN | Sign in to admin.microsoft.com as admin → Users → confirm the exact UPN. Some tenants use `@onmicrosoft.com` suffix instead of the vanity domain. |
| Validate blocks save with "credentials not configured" | Settings missing one of Tenant ID / Client ID / Client Secret | Open Appointment Settings, fill in the missing field, save. |
| Meeting created in Frappe but no join URL in response | Graph returned an unexpected payload shape | Check Frappe's Error Log (`/app/error-log`) for the captured response. |

---

## Rotating the client secret

Azure caps client secrets at 24 months. To rotate without downtime:

1. Azure: create a new secret in **Certificates & secrets** alongside the existing one.
2. Frappe: open **Appointment Settings**, paste the new secret value, save.
3. Frappe: clear the cached token — `bench --site <site> execute frappe.db.set_value --kwargs '{"doctype":"Appointment Settings","filters":null,"fieldname":"teams_access_token","value":""}'` (or just edit the hidden field to blank via the UI).
4. Test a booking — the next API call uses the new secret.
5. Azure: delete the old secret once you've confirmed bookings still work.

---

## Architecture (for developers)

```
Booker → /schedule/gr/<group> → POST /api/method/.../book_time_slot
            ↓
        EventOverride.before_insert
            ↓ (meet_provider == "Microsoft Teams")
        helpers/teams.py
            ↓
        get_access_token()    →  POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
                                  (client_credentials, scope=Graph .default)
                                  → token cached on Appointment Settings.teams_access_token
            ↓
        create_meeting()       →  POST https://graph.microsoft.com/v1.0/users/{upn}/onlineMeetings
                                  → response.joinUrl
            ↓
        Event.custom_meet_link = joinUrl
        Event.description     += "\nMeet Link: {joinUrl}"
```

Files involved:

- `frappe_appointment/helpers/teams.py` — Graph API wrapper
- `frappe_appointment/overrides/event_override.py` — `before_insert` branches on `meet_provider`
- `frappe_appointment/frappe_appointment/doctype/appointment_settings/appointment_settings.json` — Teams credentials
- `frappe_appointment/frappe_appointment/doctype/user_appointment_availability/user_appointment_availability.json` — per-user `teams_user_email`
- `frappe_appointment/frappe_appointment/doctype/appointment_group/appointment_group.json` — `meet_provider` Select option

---

## See also

- [Microsoft Graph: Create onlineMeeting](https://learn.microsoft.com/graph/api/application-post-onlinemeetings)
- [Application access policy reference](https://learn.microsoft.com/graph/cloud-communication-online-meeting-application-access-policy)
- Frappe Appointment README
