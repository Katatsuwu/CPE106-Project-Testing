# Cardinal Queue

Touch-friendly kiosk, live queue display, ticket lookup, and Python staff console. The active backend is Supabase (Postgres, Auth, Realtime, and Edge Functions).

## Included

- `index.html` — kiosk registration, ticket, and QR handoff.
- `queue.html` — public live queue and private ticket lookup.
- `staff-setup.html` — invitation landing page for setting an initial staff password.
- `admin_app.py` — Tkinter staff console for queue actions, records, reports, service settings, staff roles, and audit logs.
- `apps-script/` — Gmail relay source for signed queue alert requests.
- `supabase/migrations/0001_cardinal_queue.sql` — schema, starter services, RLS, realtime publication, and atomic queue RPCs.
- `supabase/functions/api/index.ts` — public queue actions and authenticated staff API.
- `assets/` — supplied Cardinal Queue logos and backgrounds, including `header_bg.png` and the transparent `admin_logo.png` used together in the administrator header.

The kiosk keeps the original prototype's four red pill buttons and Mapúa background. Its logo and buttons scale together for iPad (8th generation) and smaller screens. The queue monitor keeps its existing layout and adapts its panels for mobile. The Python staff console sign-in uses the administrator logo and screenshot layout, with a full-screen Mapúa background. After sign-in, the header layers the supplied `assets/admin_logo.png` with its transparency intact over `assets/header_bg.png`, and scales with the console window.

## Supabase setup

The Supabase Free project for Cardinal Queue is created in Singapore. The SQL migration has been applied, and the `api` Edge Function is deployed. To rebuild the backend, use the SQL editor to run `supabase/migrations/0001_cardinal_queue.sql`; it enables Realtime for `queue_public`.

The project URL and public legacy `anon` key are already in `js/supabase-config.js` and `admin_config.example.json`. The anon key is safe to ship; RLS limits its database access. The API Edge Function disables the gateway JWT check because it validates sessions with Supabase Auth `getUser(token)` inside the handler and checks active staff roles before every staff action. Public kiosk actions remain intentionally public. Never put the service-role key in the website, desktop config, or source control.

The deployed `api` Edge Function uses Supabase's server-only `SUPABASE_SERVICE_ROLE_KEY`, which bypasses RLS. It is never included in this package. Function-level staff checks validate each session and active staff role.

The initial administrator role is assigned. Send invitations with the staff setup URL as the redirect so invitees can accept the link and set a password on `staff-setup.html`. The Python console's **Forgot password?** action requests a Supabase recovery email; staff verify through the secure link, set a new password on that page, then return to the Python console. The web page does not provide staff management. For later staff, invite the user under **Authentication → Users**, then assign their role from the Staff Accounts tab. A user must already exist in Supabase Authentication before assigning a role.



## Live website

- Kiosk: <https://katatsuwu.github.io/Cardinal-Queue/>
- Live queue and ticket lookup: <https://katatsuwu.github.io/Cardinal-Queue/queue.html>
- Staff invitation setup: <https://katatsuwu.github.io/Cardinal-Queue/staff-setup.html>
- Public source repository: <https://github.com/Katatsuwu/Cardinal-Queue>

GitHub Pages serves the static frontend from the repository's `main` branch. The Supabase backend is deployed and the starter service list is active. Invitation links should redirect to `staff-setup.html` so staff can set their own password before using the console. The full source ZIP includes the Python staff console and setup files.

## Run locally

Serve this folder over HTTP (ES modules do not work reliably from `file://`) using any static web server. Open `index.html` for the kiosk or `queue.html` for the queue monitor.

Python 3 with Tkinter is required for the staff console. The console loads the included `admin_config.example.json` automatically; no config copy is needed for the supplied Supabase project. To use another project, create `admin_config.json` beside `admin_app.py` with its URL and public anon key. Never use a service-role key here.

### Sample staff sign-in

The console leaves the email field blank so staff must enter their sign-in address:

- Email: `cardinalqueue.noreply@gmail.com`
- Password: `mapuaadmin`

These are the supplied demonstration credentials. Change the password before using this account outside a classroom demo. The included Supabase project settings are already configured; do not edit or create a config file.

For a Windows computer without Python installed, [download the Cardinal Queue Staff Console (Portable)](downloads/Cardinal%20Queue%20Staff%20Console%20(Portable).zip), extract it, then double-click `Start Cardinal Queue Console.bat`. It includes its own Python runtime and uses the included public project configuration; no Python or Supabase setup is required. Internet access is required.

The staff console refreshes its Supabase session before access tokens expire and retries once after an expired-token response. If the refresh session itself has expired or been revoked, sign in again.

In **Queue Management**, **Call next** only selects waiting requests assigned to the chosen window; choose **Any** to call the oldest waiting request across windows. Completed requests leave this active list and remain available in **Records**.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" admin_app.py
```

## Data protection and behavior

Private queue records and staff data have row-level security enabled with no direct client access. The Edge Function uses its server-only service key and checks staff role/active state for every administrative request. Public clients can read only `queue_public`, which contains ticket number, service, window, status, creation time, and local date. The personal monitor requires the queue number and a random ticket code; only its SHA-256 hash is stored.

Queue numbering and window rotation run in a database transaction. Daily counters use `Asia/Manila`; timestamps are UTC. Queue statuses are `Waiting`, `Serving`, and `Completed`. Transitions and queue creation update the public projection and transaction record atomically.

Queue alert triggers send email when a ticket moves to fourth in its service/window waiting line and when staff calls it. The Apps Script relay validates signed requests for alert and `ticket_details` messages. Its live deployment has been updated, and the health endpoint returns success. Apps Script's daily email quota applies.

The live site is published in the existing public group repository, so its frontend files, assets, and public Supabase anon key can be viewed publicly. Never commit private configuration or the service-role key. The initial administrator account and role are set up. The desktop console retries Supabase hostname lookup through Cloudflare or Google DNS over HTTPS if Windows DNS fails; TLS certificate validation remains enabled. If a network blocks both regular DNS and direct HTTPS to these resolvers, the console still needs a network that allows Supabase access.

## Cost and availability

The project is prepared for Supabase Free. Free projects can pause after a period of inactivity and have usage limits; check the current plan dashboard before real deployment. No billing upgrade or service-role secret is included in this package.
