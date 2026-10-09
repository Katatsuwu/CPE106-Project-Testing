# Cardinal Queue

A touch-friendly Mapúa kiosk, live queue display, personal ticket lookup, and shared Supabase backend.

## Live website

- Kiosk: https://katatsuwu.github.io/Cardinal-Queue/
- Queue monitor and ticket lookup: https://katatsuwu.github.io/Cardinal-Queue/queue.html
- Staff invitation and password setup: https://katatsuwu.github.io/Cardinal-Queue/staff-setup.html

The kiosk keeps the design from the original project prototype. The queue monitor uses the proposal-based layout and adapts for phone screens. The separate Python staff console is distributed in the project source package.

## Project source

This public repository contains the GitHub Pages frontend, including its kiosk, queue monitor, scripts, and image assets. The complete Python console, Supabase schema and Edge Function source, and Gmail relay source are included in the Cardinal Queue source package.

## Backend and privacy

Supabase provides authentication, the queue database, and the API. Public pages use the Supabase anon key with row-level security. Never put a service-role key, staff password, or private configuration in this repository. The Python console uses its local admin_config.json file for the project URL and anon key.

New kiosk registrations receive a copy of their ticket details and private queue link by email. Email alerts are sent when a ticket is about three positions away and when it is called; delivery depends on the configured relay and Supabase secrets.

GitHub Pages publishes the main branch. Page files use relative paths for CSS, JavaScript, and images.
