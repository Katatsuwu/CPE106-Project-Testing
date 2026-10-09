# Cardinal Queue Website

Static kiosk and live queue pages for GitHub Pages. `index.html` is the kiosk; `queue.html` is the TV display and private ticket lookup. Supabase provides the shared queue database and API.

## Publish

Enable GitHub Pages for the `main` branch and repository root. Keep these relative paths intact: `css/`, `js/`, and `assets/`.

The frontend only contains Supabase's public anon key. Never add `admin_config.json`, service-role keys, passwords, or other secrets to this static site.

## Backend source

The complete Python admin app, schema, and Supabase Edge Function source are in the separate `cardinal-queue-source.zip` package.