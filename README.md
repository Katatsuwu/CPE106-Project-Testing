# Cardinal Queue Website

Static kiosk and live queue pages for GitHub Pages. `index.html` is the kiosk; `queue.html` is the TV display and private ticket lookup. Supabase provides the shared queue database and API.

## Live site

- Kiosk: <https://katatsuwu.github.io/CPE106-Project-Testing/>
- Live queue and ticket lookup: <https://katatsuwu.github.io/CPE106-Project-Testing/queue.html>
- Staff invitation setup: <https://katatsuwu.github.io/CPE106-Project-Testing/staff-setup.html>
- Source: <https://github.com/Katatsuwu/CPE106-Project-Testing>

GitHub Pages serves the `main` branch repository root. Keep these relative paths intact: `css/`, `js/`, and `assets/`.

The frontend only contains Supabase's public anon key. Never add `admin_config.json`, service-role keys, passwords, or other secrets to this static site.

The Supabase API and starter service list are live. Staff invitations and password recovery links should redirect to `staff-setup.html` to set a password; reset requests are initiated from the Python staff console. The web page does not provide staff management. Email alerts are not configured and are not sent yet.

## Backend source

The complete Python admin app, schema, and Supabase Edge Function source are in the separate `cardinal-queue-source.zip` package.
