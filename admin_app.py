"""Cardinal Queue desktop staff console. Uses Supabase Auth and Edge Functions."""
from __future__ import annotations

import csv
import http.client
import ipaddress
import io
import json
import os
import re
import socket
import ssl
import time
from fractions import Fraction
from urllib.parse import quote, urlencode, urlsplit
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "admin_config.json"
EXAMPLE_CONFIG_PATH = ROOT / "admin_config.example.json"
AUTH_URL = "{}/auth/v1/token?grant_type=password"
REFRESH_URL = "{}/auth/v1/token?grant_type=refresh_token"
RECOVER_URL = "{}/auth/v1/recover?redirect_to={}"
PASSWORD_SETUP_URL = "https://katatsuwu.github.io/Cardinal-Queue/staff-setup.html"
SAMPLE_ACCOUNT_EMAIL = "cardinalqueue.noreply@gmail.com"
DEFAULT_SERVICE_WINDOWS = {
    "Enrollment": (1, 2),
    "Payment": (3, 4),
    "Form 137": (1,),
    "SF9": (1,),
    "Other": (1, 2, 3, 4),
}
_DNS_CACHE = {}


def _dns_failure(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, socket.gaierror) or getattr(reason, "winerror", None) == 11001 or getattr(reason, "errno", None) == 11001


def _https_request_to_ip(host, ip, path, *, method="GET", body=None, headers=None, timeout=12):
    """Connect to a known IP while validating TLS for the requested hostname."""
    context = ssl.create_default_context()
    raw_socket = socket.create_connection((ip, 443), timeout=timeout)
    try:
        tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
    except Exception:
        raw_socket.close()
        raise
    connection = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
    connection.sock = tls_socket
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        status, reason, response_headers = response.status, response.reason, response.headers
        if status >= 400:
            raise HTTPError(f"https://{host}{path}", status, reason, response_headers, io.BytesIO(payload))
        return io.BytesIO(payload)
    finally:
        connection.close()


def _resolve_supabase_with_doh(host, timeout=12):
    now = time.monotonic()
    cached = _DNS_CACHE.get(host)
    if cached and cached[0] > now:
        return cached[1]

    query = urlencode({"name": host, "type": "A"})
    resolvers = (
        ("cloudflare-dns.com", "1.1.1.1", f"/dns-query?{query}"),
        ("dns.google", "8.8.8.8", f"/resolve?{query}"),
    )
    failures = []
    for resolver_host, resolver_ip, path in resolvers:
        try:
            response = _https_request_to_ip(
                resolver_host, resolver_ip, path,
                headers={"Accept": "application/dns-json", "User-Agent": "CardinalQueue/1.0"},
                timeout=timeout,
            )
            result = json.loads(response.read().decode("utf-8"))
            addresses = []
            for answer in result.get("Answer", []):
                if answer.get("type") == 1:
                    try:
                        address = str(ipaddress.IPv4Address(answer.get("data", "")))
                    except ipaddress.AddressValueError:
                        continue
                    if address not in addresses:
                        addresses.append(address)
            if addresses:
                _DNS_CACHE[host] = (now + 300, addresses)
                return addresses
            failures.append(f"{resolver_host} returned no IPv4 address")
        except Exception as exc:
            failures.append(f"{resolver_host}: {exc}")
    raise RuntimeError("Secure DNS fallback could not resolve the Supabase address. Check that this network allows HTTPS to Supabase and public DNS providers.") from RuntimeError("; ".join(failures))


def _supabase_doh_open(request, timeout=20):
    parsed = urlsplit(request.full_url)
    host = (parsed.hostname or "").lower()
    if not host.endswith(".supabase.co"):
        raise RuntimeError("Secure DNS fallback is available only for the configured Supabase project.")
    addresses = _resolve_supabase_with_doh(host, timeout=min(timeout, 12))
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = dict(request.header_items())
    headers["Host"] = host
    errors = []
    for address in addresses:
        try:
            return _https_request_to_ip(
                host, address, path, method=request.get_method(), body=request.data,
                headers=headers, timeout=timeout,
            )
        except HTTPError:
            raise
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("Secure DNS found Supabase, but the project server could not be reached. Check this network's firewall or VPN settings.") from RuntimeError("; ".join(errors))


def read_config():
    # The distributable source ZIP intentionally omits the local config file.
    # Its example contains only the public project URL and anon key, so it is
    # safe to use as the default and lets the console run immediately.
    for config_path in (CONFIG_PATH, EXAMPLE_CONFIG_PATH):
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("url") and config.get("anonKey"):
                return config
    return {
        "url": os.environ.get("CARDINAL_SUPABASE_URL", ""),
        "anonKey": os.environ.get("CARDINAL_SUPABASE_ANON_KEY", ""),
    }


def post_json(url, body, token=None, anon_key=None):
    headers = {"Content-Type": "application/json"}
    if anon_key:
        headers["apikey"] = anon_key
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        try:
            response_context = urlopen(request, timeout=20)
        except URLError as exc:
            if not _dns_failure(exc):
                raise
            try:
                response_context = _supabase_doh_open(request, timeout=20)
            except Exception as fallback_error:
                raise RuntimeError(str(fallback_error)) from exc
        with response_context as response:
            result = response.read().decode()
            return json.loads(result) if result else {}
    except HTTPError as exc:
        try:
            error = json.loads(exc.read().decode())
            nested = error.get("error") if isinstance(error, dict) else None
            text = (error.get("msg") or error.get("message") or error.get("error_description") or (nested.get("message") if isinstance(nested, dict) else nested) or str(exc)) if isinstance(error, dict) else str(exc)
        except Exception:
            text = str(exc)
        raise RuntimeError(text) from exc
    except URLError as exc:
        reason = exc.reason
        if _dns_failure(exc):
            detail = "Windows DNS and secure DNS fallback could not reach Supabase. Check that this network allows HTTPS access and that a VPN, firewall, or DNS filter is not blocking it."
        else:
            detail = f"Could not reach Supabase: {reason}"
        raise RuntimeError(detail) from exc


class CardinalAdmin:
    def __init__(self, root):
        self.root = root
        self.root.title("Cardinal Queue · Staff Console")
        self.root.geometry("1440x900")
        self.root.minsize(1080, 700)
        self.root.configure(bg="#f4f5f7")
        self.cfg = read_config()
        self.token = None
        self.refresh_token = None
        self.refresh_after = 0.0
        self.email = ""
        self.display_name = ""
        self.role = ""
        self.queues = []
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#f5f6f8")
        self.style.configure("Card.TFrame", background="white")
        self.style.configure("TLabel", background="#f5f6f8", foreground="#182238", font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8), background="#f1eeee", foreground="#263248", borderwidth=0)
        self.style.map("TButton", background=[("active", "#e7e8ed"), ("pressed", "#dadce3")])
        self.style.configure("Primary.TButton", background="#bd101b", foreground="white", font=("Segoe UI", 10, "bold"), padding=(15, 9))
        self.style.map("Primary.TButton", background=[("active", "#a10d19"), ("pressed", "#850a14")])
        self.style.configure("Success.TButton", background="#ffc83d", foreground="#251a00", font=("Segoe UI", 10, "bold"), padding=(15, 9))
        self.style.map("Success.TButton", background=[("active", "#efb723"), ("pressed", "#dba411")])
        self.style.configure("Treeview", rowheight=35, font=("Segoe UI", 10), background="white", fieldbackground="white", foreground="#263248", borderwidth=0)
        self.style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#eef0f3", foreground="#202c42", padding=9)
        self.style.map("Treeview", background=[("selected", "#ffe1e1")], foreground=[("selected", "#8c101c")])
        self.login_view()

    def load_asset(self, filename, factor=1):
        """Load a bundled PNG asset with Tk's built-in image support."""
        path = ROOT / "assets" / filename
        if not path.is_file():
            return None
        try:
            image = tk.PhotoImage(file=str(path))
            return image.subsample(factor, factor) if factor > 1 else image
        except tk.TclError:
            return None

    def clear(self):
        for child in self.root.winfo_children():
            child.destroy()

    def login_view(self):
        self.clear()
        self.login_canvas = tk.Canvas(self.root, bg="#640710", highlightthickness=0)
        self.login_canvas.pack(fill="both", expand=True)

        self.login_background = self.load_asset("background.png")
        if self.login_background:
            self.login_bg_item = self.login_canvas.create_image(0, 0, image=self.login_background, anchor="center")
        else:
            self.login_bg_item = None

        self.admin_logo_source = self.load_asset("admin_logo.png")
        self.admin_logo_image = self.admin_logo_source.zoom(2, 2).subsample(6, 6) if self.admin_logo_source else None
        self.login_logo_item = (
            self.login_canvas.create_image(0, 0, image=self.admin_logo_image, anchor="center")
            if self.admin_logo_image else None
        )

        self.login_field_width = 350
        self.login_field_height = 62
        self.email_pill = self._create_pill_parts()
        self.password_pill = self._create_pill_parts()
        self.email_entry = tk.Entry(
            self.login_canvas, relief="flat", bd=0, highlightthickness=0,
            bg="#f5f5f5", fg="#bcbcbc", insertbackground="#333333",
            font=("Arial", 14, "italic"),
        )
        self.email_entry.insert(0, "Email address")
        self.email_placeholder = True
        self.email_window = self.login_canvas.create_window(0, 0, window=self.email_entry, width=300, height=38)
        self.email_entry.bind("<FocusIn>", self._clear_email_placeholder)
        self.email_entry.bind("<FocusOut>", self._restore_email_placeholder)
        self.email_entry.bind("<Return>", lambda _event: self.password_entry.focus_set())

        self.password_entry = tk.Entry(
            self.login_canvas, relief="flat", bd=0, highlightthickness=0,
            bg="#f5f5f5", fg="#bcbcbc", insertbackground="#333333",
            font=("Arial", 14, "italic"),
        )
        self.password_entry.insert(0, "Password")
        self.password_placeholder = True
        self.password_window = self.login_canvas.create_window(0, 0, window=self.password_entry, width=300, height=38)
        self.password_entry.bind("<FocusIn>", self._clear_password_placeholder)
        self.password_entry.bind("<FocusOut>", self._restore_password_placeholder)
        self.password_entry.bind("<Return>", lambda _event: self.login())

        self.login_button_pill = self._create_pill_parts()
        self.login_button_text = self.login_canvas.create_text(
            0, 0, text="LOGIN", fill="white", font=("Arial", 14, "bold"),
        )
        for item in self.login_button_pill:
            self.login_canvas.tag_bind(item, "<Button-1>", lambda _event: self.login())
            self.login_canvas.tag_bind(item, "<Enter>", lambda _event: self.login_canvas.configure(cursor="hand2"))
            self.login_canvas.tag_bind(item, "<Leave>", lambda _event: self.login_canvas.configure(cursor=""))
        self.login_canvas.tag_bind(self.login_button_text, "<Button-1>", lambda _event: self.login())
        self.login_canvas.tag_bind(self.login_button_text, "<Enter>", lambda _event: self.login_canvas.configure(cursor="hand2"))
        self.login_canvas.tag_bind(self.login_button_text, "<Leave>", lambda _event: self.login_canvas.configure(cursor=""))

        self.forgot_password_text = self.login_canvas.create_text(
            0, 0, text="Forgot password?", fill="#fff4e8", font=("Arial", 10), anchor="e",
        )
        self.login_canvas.tag_bind(self.forgot_password_text, "<Button-1>", lambda _event: self.request_password_reset())
        self.login_canvas.tag_bind(self.forgot_password_text, "<Enter>", lambda _event: self.login_canvas.configure(cursor="hand2"))
        self.login_canvas.tag_bind(self.forgot_password_text, "<Leave>", lambda _event: self.login_canvas.configure(cursor=""))
        self.login_canvas.bind("<Configure>", self._layout_login)

        if not self.cfg.get("url") or not self.cfg.get("anonKey") or "REPLACE_" in str(self.cfg):
            self.setup_notice = self.login_canvas.create_text(
                0, 0,
                text="Supabase setup is required. Add your project URL and publishable key to admin_config.json.",
                fill="#fff4cc", width=520, font=("Arial", 10), justify="center",
            )
        else:
            self.setup_notice = None

    def _create_pill_parts(self):
        canvas = self.login_canvas
        return [
            canvas.create_oval(0, 0, 1, 1, fill="#8b8b8b", outline=""),
            canvas.create_oval(0, 0, 1, 1, fill="#8b8b8b", outline=""),
            canvas.create_rectangle(0, 0, 1, 1, fill="#8b8b8b", outline=""),
            canvas.create_oval(0, 0, 1, 1, fill="#f5f5f5", outline=""),
            canvas.create_oval(0, 0, 1, 1, fill="#f5f5f5", outline=""),
            canvas.create_rectangle(0, 0, 1, 1, fill="#f5f5f5", outline=""),
        ]

    def _set_pill_parts(self, items, x, y, width, height, border=4, fill="#f5f5f5"):
        canvas = self.login_canvas
        x1, x2 = x - width / 2, x + width / 2
        y1, y2 = y - height / 2, y + height / 2
        radius = height / 2
        coordinates = [
            (x1, y1, x1 + height, y2), (x2 - height, y1, x2, y2),
            (x1 + radius, y1, x2 - radius, y2),
            (x1 + border, y1 + border, x1 + border + height - 2 * border, y2 - border),
            (x2 - border - height + 2 * border, y1 + border, x2 - border, y2 - border),
            (x1 + radius, y1 + border, x2 - radius, y2 - border),
        ]
        for item, coords in zip(items, coordinates):
            canvas.coords(item, *coords)
        for item in items[3:]:
            canvas.itemconfigure(item, fill=fill)

    def _layout_login(self, _event=None):
        canvas = self.login_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        center_x = width / 2
        if self.login_bg_item:
            canvas.coords(self.login_bg_item, center_x, height / 2)
        if self.login_logo_item:
            canvas.coords(self.login_logo_item, center_x, height * 0.22)

        field_width = min(self.login_field_width, width * 0.82)
        field_height = min(self.login_field_height, max(52, height * 0.09))
        first_y, second_y = height * 0.50, height * 0.625
        self._set_pill_parts(self.email_pill, center_x, first_y, field_width, field_height)
        self._set_pill_parts(self.password_pill, center_x, second_y, field_width, field_height)
        entry_width = max(120, field_width - 42)
        canvas.coords(self.email_window, center_x, first_y)
        canvas.coords(self.password_window, center_x, second_y)
        canvas.itemconfigure(self.email_window, width=entry_width, height=max(36, field_height - 18))
        canvas.itemconfigure(self.password_window, width=entry_width, height=max(36, field_height - 18))

        button_width = min(138, width * 0.55)
        button_height = min(54, max(46, height * 0.075))
        button_y = height * 0.75
        self._set_pill_parts(self.login_button_pill, center_x, button_y, button_width, button_height, border=0, fill="#c90000")
        for item in self.login_button_pill:
            self.login_canvas.itemconfigure(item, fill="#c90000")
        canvas.coords(self.login_button_text, center_x, button_y)
        canvas.coords(self.forgot_password_text, center_x + field_width / 2 - 2, second_y + field_height / 2 + 17)
        if self.setup_notice:
            canvas.coords(self.setup_notice, center_x, height * 0.97)

    def _clear_email_placeholder(self, _event=None):
        if self.email_placeholder:
            self.email_entry.delete(0, "end")
            self.email_entry.configure(fg="#333333", font=("Arial", 14))
            self.email_placeholder = False

    def _restore_email_placeholder(self, _event=None):
        if not self.email_entry.get().strip():
            self.email_entry.insert(0, "Email address")
            self.email_entry.configure(fg="#bcbcbc", font=("Arial", 14, "italic"))
            self.email_placeholder = True

    def _clear_password_placeholder(self, _event=None):
        if self.password_placeholder:
            self.password_entry.delete(0, "end")
            self.password_entry.configure(fg="#333333", font=("Arial", 14), show="•")
            self.password_placeholder = False

    def _restore_password_placeholder(self, _event=None):
        if not self.password_entry.get():
            self.password_entry.configure(show="")
            self.password_entry.insert(0, "Password")
            self.password_entry.configure(fg="#bcbcbc", font=("Arial", 14, "italic"))
            self.password_placeholder = True
    def request_password_reset(self):
        email = self.email_entry.get().strip()
        if not email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            messagebox.showerror("Enter your staff email", "Type the email address for your staff account, then choose Forgot password again.")
            return
        if not self.cfg.get("url") or not self.cfg.get("anonKey") or "REPLACE_" in str(self.cfg):
            messagebox.showerror("Setup required", "Configure Supabase in admin_config.json first.")
            return
        try:
            recover_url = RECOVER_URL.format(
                self.cfg["url"].rstrip("/"), quote(PASSWORD_SETUP_URL, safe="")
            )
            post_json(recover_url, {"email": email}, anon_key=self.cfg["anonKey"])
            messagebox.showinfo(
                "Check your email",
                "If this address belongs to a staff account, Supabase will send a secure password reset link. "
                "Open it to choose a new password, then sign in here.",
            )
        except Exception as exc:
            messagebox.showerror("Could not request reset", str(exc))

    def login(self):
        if self.email_placeholder or self.password_placeholder:
            messagebox.showerror("Missing sign-in details", "Enter your staff email and password to continue.")
            return
        if not self.cfg.get("url") or not self.cfg.get("anonKey") or "REPLACE_" in str(self.cfg):
            messagebox.showerror("Setup required", "Configure Supabase in admin_config.json first.")
            return
        try:
            payload = post_json(AUTH_URL.format(self.cfg["url"].rstrip("/")), {
                "email": "" if self.email_placeholder else self.email_entry.get().strip(),
                "password": "" if self.password_placeholder else self.password_entry.get(),
            }, anon_key=self.cfg["anonKey"])
            self._store_session(payload)
            self.email = payload.get("user", {}).get("email", "")
            profile = self.invoke("profile")
            self.role = profile.get("role", "")
            self.display_name = profile.get("name") or self.email.split("@")[0].replace(".", " ").replace("_", " ").title()
            if self.role not in ("staff", "system_admin"):
                raise RuntimeError("This account is not assigned an active staff role.")
            self.main_view()
        except Exception as exc:
            messagebox.showerror("Sign in failed", str(exc))

    def invoke(self, name, data=None):
        base = f"{self.cfg['url'].rstrip('/')}/functions/v1/api"
        payload = {"action": name, **(data or {})}
        self._refresh_session_if_needed()
        try:
            return post_json(base, payload, self.token, self.cfg["anonKey"])
        except RuntimeError as exc:
            if "invalid jwt" not in str(exc).casefold() and "jwt expired" not in str(exc).casefold():
                raise
            self._refresh_session_if_needed(force=True)
            return post_json(base, payload, self.token, self.cfg["anonKey"])

    def _store_session(self, payload):
        self.token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        expires_in = max(1, int(payload.get("expires_in", 3600)))
        self.refresh_after = time.monotonic() + max(1, expires_in - 120)

    def _refresh_session_if_needed(self, force=False):
        if not self.token or (not force and time.monotonic() < self.refresh_after):
            return
        if not self.refresh_token:
            self.logout()
            raise RuntimeError("Your sign-in session expired. Please sign in again.")
        try:
            refreshed = post_json(
                REFRESH_URL.format(self.cfg["url"].rstrip("/")),
                {"refresh_token": self.refresh_token},
                anon_key=self.cfg["anonKey"],
            )
            self._store_session(refreshed)
        except Exception as exc:
            self.logout()
            raise RuntimeError("Your sign-in session expired. Please sign in again.") from exc

    def _queue_header_resize(self, _event=None):
        if hasattr(self, "header_resize_after"):
            self.root.after_cancel(self.header_resize_after)
        self.header_resize_after = self.root.after(60, self._resize_admin_header)

    def _resize_admin_header(self):
        if not hasattr(self, "header_canvas") or not self.header_source:
            return
        width = max(self.header_canvas.winfo_width(), 1)
        if width < 10:
            return
        source_width = self.header_source.width()
        ratio = Fraction(width, source_width).limit_denominator(16)
        numerator, denominator = ratio.numerator, ratio.denominator
        scale = (numerator, denominator)
        if scale not in self.header_images:
            self.header_images[scale] = self.header_source.zoom(numerator, numerator).subsample(denominator, denominator)
        self.header_photo = self.header_images[scale]
        self.header_canvas.configure(height=self.header_photo.height())
        self.header_canvas.coords(self.header_background_id, width // 2, self.header_photo.height() // 2)
        self.header_canvas.itemconfigure(self.header_background_id, image=self.header_photo)
        if self.header_logo_source:
            if scale not in self.header_logo_images:
                self.header_logo_images[scale] = self.header_logo_source.zoom(numerator, numerator).subsample(denominator, denominator)
            self.header_logo_photo = self.header_logo_images[scale]
            self.header_canvas.coords(self.header_logo_id, max(18, int(width * 0.018)), self.header_photo.height() // 2)
            self.header_canvas.itemconfigure(self.header_logo_id, image=self.header_logo_photo)

    def main_view(self):
        self.clear()
        self.header_canvas = tk.Canvas(self.root, bg="#6d0d1d", height=187, highlightthickness=0, bd=0)
        self.header_canvas.pack(fill="x")
        self.header_source = self.load_asset("header_bg.png")
        self.header_images = {}
        self.header_logo_source = self.load_asset("admin_logo.png")
        if self.header_logo_source:
            # Preserve PNG transparency so the background artwork remains visible.
            self.header_logo_source = self.header_logo_source.zoom(4, 4).subsample(19, 19)
        self.header_logo_images = {}
        self.header_background_id = self.header_canvas.create_image(0, 0, anchor="center")
        self.header_logo_id = self.header_canvas.create_image(0, 0, anchor="w")
        self.header_canvas.bind("<Configure>", self._queue_header_resize)
        self._queue_header_resize()
        shell = tk.Frame(self.root, bg="#f5f6f8")
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg="#bf252a", width=240)
        self.sidebar = sidebar
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="STAFF CONSOLE", bg="#bf252a", fg="#ffe26c", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=22, pady=(24, 12))
        self.pages = {}
        self.nav_buttons = {}
        self.content = tk.Frame(shell, bg="#f5f6f8", padx=22, pady=20)
        self.content.pack(side="left", fill="both", expand=True)
        self.dashboard_tab = self.add_page("Dashboard", "◆  Dashboard", sidebar)
        self.queue_tab = self.add_page("Queue management", "♟  Queue Management", sidebar)
        self.records_tab = self.add_page("Records", "▤  Records", sidebar)
        self.reports_tab = self.add_page("Reports", "▥  Reports", sidebar)
        self.build_dashboard()
        self.build_queue_tab()
        self.build_records_tab()
        self.build_reports_tab()
        if self.role == "system_admin":
            self.build_admin_tabs()
        tk.Frame(sidebar, bg="#e98f8c", height=1).pack(fill="x", padx=20, pady=(16, 9))
        self.profile_tab = self.add_page("Profile", "●  Profile", sidebar)
        self.build_profile()
        logout = tk.Button(sidebar, text="↪  Logout", anchor="w", bd=0, padx=22, pady=13,
                           bg="#bf252a", fg="white", activebackground="#d73c3c",
                           activeforeground="white", font=("Segoe UI", 10, "bold"), command=self.logout)
        logout.pack(fill="x", padx=8, pady=2, side="bottom")
        self.show_page("Dashboard")
        self.refresh_queues()
        self.schedule_refresh()

    def add_page(self, name, nav_label, sidebar):
        button = tk.Button(sidebar, text=nav_label, anchor="w", bd=0, padx=18, pady=12,
                           bg="#bf252a", fg="white", activebackground="#d73c3c",
                           activeforeground="white", font=("Segoe UI", 10, "bold"),
                           command=lambda page=name: self.show_page(page))
        button.pack(fill="x", padx=9, pady=2)
        self.nav_buttons[name] = button
        page = tk.Frame(self.content, bg="#f5f6f8")
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages[name] = page
        return page

    def show_page(self, name):
        self.pages[name].tkraise()
        for page, button in self.nav_buttons.items():
            selected = page == name
            button.configure(bg="#ffe1df" if selected else "#bf252a", fg="#95131d" if selected else "white")

    def page_header(self, page, title, subtitle):
        head = tk.Frame(page, bg="#f5f6f8")
        head.pack(fill="x", pady=(0, 17))
        title_box = tk.Frame(head, bg="#f5f6f8")
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text=title, bg="#f5f6f8", fg="#111a2b", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(title_box, text=subtitle, bg="#f5f6f8", fg="#727986", font=("Segoe UI", 10)).pack(anchor="w", pady=(1, 0))
        stamp = tk.Frame(head, bg="white", highlightbackground="#dfe2e8", highlightthickness=1, padx=12, pady=8)
        stamp.pack(side="right", padx=(10, 0))
        tk.Label(stamp, text="▣   " + datetime.now().strftime("%B %d, %Y"), bg="white", fg="#1d2940", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(stamp, text=datetime.now().strftime("%A, %I:%M %p"), bg="white", fg="#697181", font=("Segoe UI", 9)).pack(anchor="w", padx=(22, 0))
        return head

    def panel(self, parent, title=None, **pack_options):
        frame = tk.Frame(parent, bg="white", highlightbackground="#e1e4e9", highlightthickness=1, padx=14, pady=12)
        if title:
            tk.Label(frame, text=title, bg="white", fg="#172238", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 9))
        if pack_options:
            frame.pack(**pack_options)
        return frame

    def pill_button(self, parent, text, command, color="#bb101b", foreground="white", **kwargs):
        return tk.Button(parent, text=text, command=command, bg=color, fg=foreground,
                         activebackground="#a00e18" if color == "#bb101b" else color,
                         activeforeground=foreground, bd=0, padx=14, pady=9,
                         font=("Segoe UI", 9, "bold"), cursor="hand2", **kwargs)

    def logout(self):
        self.token = None
        self.refresh_token = None
        self.refresh_after = 0.0
        self.email = ""
        self.display_name = ""
        self.role = ""
        self.login_view()

    def build_profile(self):
        self.page_header(self.profile_tab, "User Profile", "View your account details and update your password.")
        body = tk.Frame(self.profile_tab, bg="#f5f6f8")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=9, uniform="profile")
        body.grid_columnconfigure(1, weight=12, uniform="profile")
        body.grid_columnconfigure(2, weight=11, uniform="profile")
        body.grid_rowconfigure(0, weight=1)

        identity = self.panel(body)
        identity.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        avatar = tk.Canvas(identity, width=126, height=126, bg="white", highlightthickness=0)
        avatar.pack(pady=(12, 8))
        avatar.create_oval(8, 8, 118, 118, fill="#ffe2e3", outline="")
        avatar.create_oval(48, 29, 79, 60, fill="#bb101b", outline="")
        avatar.create_oval(32, 62, 95, 116, fill="#bb101b", outline="")
        self.profile_name_label = tk.Label(identity, text=self.display_name or self.email.split("@")[0].replace(".", " ").title(), bg="white", fg="#172238", font=("Segoe UI", 16, "bold"))
        self.profile_name_label.pack()
        tk.Label(identity, text="System Administrator" if self.role == "system_admin" else "Administrative Staff", bg="white", fg="#697181", font=("Segoe UI", 10)).pack(pady=(3, 12))
        tk.Label(identity, text="●  Active Account", bg="#dff6e9", fg="#087341", padx=12, pady=6, font=("Segoe UI", 9, "bold")).pack()
        tk.Frame(identity, bg="#e5e7eb", height=1).pack(fill="x", pady=16)
        for symbol, value, caption in (("✉", self.email, "Email address"), ("◆", self.role.replace("_", " ").title(), "Role")):
            row = tk.Frame(identity, bg="white")
            row.pack(fill="x", pady=7)
            tk.Label(row, text=symbol, bg="white", fg="#172238", font=("Segoe UI", 15, "bold"), width=3).pack(side="left", anchor="n")
            words = tk.Frame(row, bg="white")
            words.pack(side="left", fill="x", expand=True)
            tk.Label(words, text=value or "—", bg="white", fg="#172238", font=("Segoe UI", 9, "bold"), wraplength=210, justify="left").pack(anchor="w")
            tk.Label(words, text=caption, bg="white", fg="#7a8290", font=("Segoe UI", 9)).pack(anchor="w")

        account = self.panel(body, "♟  Account Information")
        account.grid(row=0, column=1, sticky="nsew", padx=8)
        self._profile_field(account, "Full Name", self.display_name or self.email.split("@")[0].replace(".", " ").title())
        self._profile_field(account, "Email Address", self.email)
        self._profile_field(account, "Role", self.role.replace("_", " ").title())
        self._profile_field(account, "Account Status", "Active")

        actions = tk.Frame(body, bg="#f5f6f8")
        actions.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        password = self.panel(actions, "▣  Change Password")
        password.pack(fill="x", expand=True, pady=(0, 9))
        self.current_password_var = tk.StringVar()
        self.new_password_var = tk.StringVar()
        self.confirm_password_var = tk.StringVar()
        for label, variable, show in (("Current Password", self.current_password_var, "●"), ("New Password", self.new_password_var, "●"), ("Confirm New Password", self.confirm_password_var, "●")):
            tk.Label(password, text=label, bg="white", fg="#263248", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(7, 4))
            entry = tk.Entry(password, textvariable=variable, show=show, relief="solid", bd=1, highlightthickness=0, font=("Segoe UI", 10))
            entry.pack(fill="x", ipady=8)
        self.pill_button(password, "Update Password", self.change_password).pack(fill="x", pady=(14, 2))
        account_actions = self.panel(actions, "⚙  Account Actions")
        account_actions.pack(fill="x")
        self.pill_button(account_actions, "↪  Logout from Account", self.logout, color="white", foreground="#a10d19", highlightthickness=1, highlightbackground="#bd101b").pack(fill="x")

    def _profile_field(self, parent, label, value):
        tk.Label(parent, text=label, bg="white", fg="#263248", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 4))
        field = tk.Label(parent, text=value or "—", anchor="w", bg="#f0f1f4", fg="#374151", padx=10, pady=9, font=("Segoe UI", 10), wraplength=300)
        field.pack(fill="x")

    def change_password(self):
        current = self.current_password_var.get()
        new = self.new_password_var.get()
        confirm = self.confirm_password_var.get()
        if not current or not new or not confirm:
            messagebox.showerror("Complete all password fields", "Enter your current password and the new password twice.")
            return
        if len(new) < 8:
            messagebox.showerror("Password is too short", "Use at least 8 characters for the new password.")
            return
        if new != confirm:
            messagebox.showerror("Passwords do not match", "The new password and confirmation must match.")
            return
        try:
            session = post_json(AUTH_URL.format(self.cfg["url"].rstrip("/")), {"email": self.email, "password": current}, anon_key=self.cfg["anonKey"])
            request = Request(
                f"{self.cfg['url'].rstrip('/')}/auth/v1/user",
                data=json.dumps({"password": new}).encode(),
                headers={"Content-Type": "application/json", "apikey": self.cfg["anonKey"], "Authorization": f"Bearer {session['access_token']}"},
                method="PUT",
            )
            with urlopen(request, timeout=20) as response:
                response.read()
            self._store_session(session)
            self.current_password_var.set("")
            self.new_password_var.set("")
            self.confirm_password_var.set("")
            messagebox.showinfo("Password updated", "Your password has been changed.")
        except Exception as exc:
            messagebox.showerror("Could not update password", str(exc))

    def build_dashboard(self):
        self.page_header(self.dashboard_tab, "Administrative Dashboard", "Overview of current queues, service windows, and system activity.")
        cards = tk.Frame(self.dashboard_tab, bg="#f5f6f8")
        cards.pack(fill="x", pady=(0, 14))
        self.summary_labels = {}
        summaries = (("Waiting", "▣", "#bd101b", "#fff0f0"), ("Serving", "♟", "#e6a000", "#fff8e8"), ("Completed", "✓", "#14734e", "#eaf8f0"), ("Windows in Use", "▦", "#1552a0", "#edf5ff"))
        for index, (key, icon, color, soft) in enumerate(summaries):
            card = tk.Frame(cards, bg="white", highlightbackground="#e5e7eb", highlightthickness=1, padx=13, pady=11)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            cards.columnconfigure(index, weight=1, uniform="summary")
            circle = tk.Label(card, text=icon, bg=soft, fg=color, font=("Segoe UI", 17, "bold"), width=3, height=1)
            circle.pack(side="left", padx=(0, 10))
            labels = tk.Frame(card, bg="white")
            labels.pack(side="left", fill="x", expand=True)
            tk.Label(labels, text=key, bg="white", fg="#27334a", font=("Segoe UI", 9, "bold")).pack(anchor="w")
            label = tk.Label(labels, text="—", bg="white", fg=color, font=("Segoe UI", 21, "bold"))
            label.pack(anchor="w", pady=(0, 0))
            self.summary_labels[key] = label

        lower = tk.Frame(self.dashboard_tab, bg="#f5f6f8")
        lower.pack(fill="both", expand=True)
        lower.grid_columnconfigure(0, weight=6, uniform="dashboard")
        lower.grid_columnconfigure(1, weight=5, uniform="dashboard")
        lower.grid_rowconfigure(0, weight=1)
        queue_panel = self.panel(lower, "♟  Current Queue")
        queue_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.dashboard_tree = self.make_tree(queue_panel, [("number", "Queue No.", 95), ("name", "Name", 150), ("service", "Service", 110), ("window", "Window", 75), ("status", "Status", 85)])
        self.dashboard_tree.bind("<Double-1>", lambda _event: self.show_page("Queue management"))
        right = tk.Frame(lower, bg="#f5f6f8")
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        windows = self.panel(right, "▣  Service Windows")
        windows.pack(fill="both", expand=True, pady=(0, 8))
        self.window_cards = tk.Frame(windows, bg="white")
        self.window_cards.pack(fill="both", expand=True)
        recent = self.panel(right, "◷  Recent Activity")
        recent.pack(fill="both", expand=True)
        self.activity_tree = self.make_tree(recent, [("time", "Time", 85), ("number", "Queue No.", 90), ("activity", "Activity", 110)])
        self.pill_button(self.dashboard_tab, "Refresh dashboard", self.refresh_queues, color="#ffffff", foreground="#a10d19", highlightthickness=1, highlightbackground="#e1e4e9").pack(anchor="e", pady=(9, 0))

    def make_tree(self, parent, columns):
        column_ids = [key for key, _label, _width in columns]
        tree = ttk.Treeview(parent, columns=column_ids, show="headings", selectmode="browse")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=55, anchor="w", stretch=True)
        tree.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        return tree

    def _queue_values(self, q):
        created = str(q.get("createdAt", ""))
        return (q.get("queueNumber", ""), q.get("fullName", ""), q.get("service", ""), f"Window {q.get('window')}" if q.get("window") else "—", q.get("status", ""))

    def _refresh_dashboard_widgets(self):
        statuses = {status: sum(1 for q in self.queues if q.get("status") == status) for status in ("Waiting", "Serving", "Completed")}
        serving = [q for q in self.queues if q.get("status") == "Serving"]
        in_use = len({str(q.get("window")) for q in serving if q.get("window")})
        values = {"Waiting": statuses["Waiting"], "Serving": statuses["Serving"], "Completed": statuses["Completed"], "Windows in Use": in_use}
        for name, label in getattr(self, "summary_labels", {}).items():
            label.configure(text=str(values.get(name, 0)))
        if hasattr(self, "dashboard_tree"):
            self.dashboard_tree.delete(*self.dashboard_tree.get_children())
            current = [q for q in self.queues if q.get("status") in ("Serving", "Waiting")]
            for q in current[:10]:
                self.dashboard_tree.insert("", "end", iid=f"dash-{q['id']}", values=self._queue_values(q))
        if hasattr(self, "window_cards"):
            for child in self.window_cards.winfo_children(): child.destroy()
            window_ids = sorted({int(q.get("window")) for q in self.queues if q.get("window") and str(q.get("window")).isdigit()}) or [1, 2, 3]
            for index, window in enumerate(window_ids):
                active = next((q for q in serving if str(q.get("window")) == str(window)), None)
                card = tk.Frame(self.window_cards, bg="#fbfbfc", highlightbackground="#e6e8ed", highlightthickness=1, padx=10, pady=8)
                card.pack(fill="x", pady=(0, 5))
                tk.Label(card, text=f"Window {window}", bg="#fbfbfc", fg="#a3121d", font=("Segoe UI", 10, "bold")).pack(side="left")
                tk.Label(card, text="●  Serving" if active else "●  No active queue", bg="#fbfbfc", fg="#14804e" if active else "#9298a3", font=("Segoe UI", 9, "bold")).pack(side="right")
                if active:
                    tk.Label(card, text=f"{active.get('service')}  ·  {active.get('queueNumber')}", bg="#fbfbfc", fg="#5e6674", font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        if hasattr(self, "activity_tree"):
            self.activity_tree.delete(*self.activity_tree.get_children())
            recent = sorted(self.queues, key=lambda q: str(q.get("createdAt", "")), reverse=True)
            for i, q in enumerate(recent[:8]):
                stamp = str(q.get("createdAt", ""))
                try: stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().strftime("%I:%M %p")
                except Exception: stamp = stamp[11:16]
                self.activity_tree.insert("", "end", iid=f"activity-{i}", values=(stamp, q.get("queueNumber"), q.get("status")))

    def build_queue_tab(self):
        self.page_header(self.queue_tab, "Queue Management", "Manage active queues, call users, and monitor service windows.")
        top = tk.Frame(self.queue_tab, bg="#f5f6f8")
        top.pack(fill="x", pady=(0, 11))
        top.grid_columnconfigure(0, weight=6, uniform="queue_top")
        top.grid_columnconfigure(1, weight=5, uniform="queue_top")
        current = self.panel(top, "♟  Currently Serving")
        current.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.current_number = tk.Label(current, text="—", bg="white", fg="#a6101b", font=("Segoe UI", 28, "bold"))
        self.current_number.pack(anchor="w", pady=(3, 0))
        self.current_name = tk.Label(current, text="No queue is being served", bg="white", fg="#172238", font=("Segoe UI", 12, "bold"))
        self.current_name.pack(anchor="w")
        self.current_service = tk.Label(current, text="", bg="white", fg="#697181", font=("Segoe UI", 10))
        self.current_service.pack(anchor="w", pady=(0, 10))
        controls = tk.Frame(current, bg="white")
        controls.pack(fill="x")
        self.window_var = tk.StringVar(value="Any")
        ttk.Label(controls, text="Window").pack(side="left", padx=(0, 4))
        ttk.Combobox(controls, textvariable=self.window_var, values=["Any", "1", "2", "3", "4", "5"], width=7, state="readonly").pack(side="left", padx=(0, 9))
        self.pill_button(controls, "▶  Call Next", self.call_next).pack(side="left", padx=(0, 6))
        self.pill_button(controls, "✓  Complete", self.complete_selected, color="#ffc83d", foreground="#251a00").pack(side="left", padx=(0, 6))
        self.pill_button(controls, "↶  Return to Waiting", self.return_selected, color="#f1f2f5", foreground="#303b50").pack(side="left")
        windows = self.panel(top, "▣  Service Windows")
        windows.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.queue_window_cards = tk.Frame(windows, bg="white")
        self.queue_window_cards.pack(fill="both", expand=True)

        lower = tk.Frame(self.queue_tab, bg="#f5f6f8")
        lower.pack(fill="both", expand=True)
        lower.grid_columnconfigure(0, weight=7, uniform="queue_lower")
        lower.grid_columnconfigure(1, weight=4, uniform="queue_lower")
        lower.grid_rowconfigure(0, weight=1)
        list_panel = self.panel(lower, "♟  Queue List")
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        filters = tk.Frame(list_panel, bg="white")
        filters.pack(fill="x", pady=(0, 8))
        self.queue_service_filter = tk.StringVar(value="All Services")
        self.queue_status_filter = tk.StringVar(value="All Statuses")
        ttk.Combobox(filters, textvariable=self.queue_service_filter, values=["All Services", "Enrollment", "Payment", "Form 137", "SF9", "Other"], state="readonly", width=15).pack(side="left", padx=(0, 6))
        ttk.Combobox(filters, textvariable=self.queue_status_filter, values=["All Statuses", "Waiting", "Serving"], state="readonly", width=13).pack(side="left", padx=(0, 6))
        self.queue_search = tk.StringVar()
        search = ttk.Entry(filters, textvariable=self.queue_search)
        search.pack(side="left", fill="x", expand=True)
        self.pill_button(filters, "Refresh", self.refresh_queues, color="#f1f2f5", foreground="#303b50").pack(side="left", padx=(7, 0))
        self.queue_tree = self.make_tree(list_panel, [("number", "Queue No.", 85), ("name", "Name", 135), ("service", "Service", 95), ("window", "Window", 80), ("status", "Status", 85), ("created", "Time Joined", 105)])
        self.queue_tree.bind("<<TreeviewSelect>>", self.show_queue_details)
        self.queue_search.trace_add("write", lambda *_: self.filter_queue_rows())
        self.queue_service_filter.trace_add("write", lambda *_: self.filter_queue_rows())
        self.queue_status_filter.trace_add("write", lambda *_: self.filter_queue_rows())
        detail = self.panel(lower, "▤  Queue Details")
        detail.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.queue_detail_labels = {}
        for key in ("Queue No.", "Name", "Service", "Window", "Status", "Time Joined", "Email", "Education Level"):
            row = tk.Frame(detail, bg="white")
            row.pack(fill="x", pady=5)
            tk.Label(row, text=key, bg="white", fg="#697181", font=("Segoe UI", 9), width=15, anchor="w").pack(side="left")
            value = tk.Label(row, text="—", bg="white", fg="#172238", font=("Segoe UI", 9, "bold"), anchor="w", wraplength=190, justify="left")
            value.pack(side="left", fill="x", expand=True)
            self.queue_detail_labels[key] = value
        self.queue_empty_notice = tk.Label(self.queue_tab, text="Completed requests remain available in Records.", bg="#fff2d0", fg="#7b4a00", padx=10, pady=7, font=("Segoe UI", 9))
        self.queue_empty_notice.pack(fill="x", pady=(8, 0))

    def filter_queue_rows(self):
        if not hasattr(self, "queue_tree"): return
        selected = self.queue_tree.selection()
        query = self.queue_search.get().strip().casefold()
        service = self.queue_service_filter.get()
        status = self.queue_status_filter.get()
        self.queue_tree.delete(*self.queue_tree.get_children())
        for q in self.queues:
            if q.get("status") not in ("Waiting", "Serving"): continue
            if service != "All Services" and q.get("service") != service: continue
            if status != "All Statuses" and q.get("status") != status: continue
            searchable = " ".join(str(q.get(k, "")) for k in ("queueNumber", "fullName", "service", "window", "status")).casefold()
            if query and query not in searchable: continue
            created = str(q.get("createdAt", ""))
            try: created = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone().strftime("%I:%M %p")
            except Exception: created = created[11:16]
            self.queue_tree.insert("", "end", iid=q["id"], values=(q.get("queueNumber"), q.get("fullName"), q.get("service"), f"Window {q.get('window')}" if q.get("window") else "—", q.get("status"), created))
        if selected and self.queue_tree.exists(selected[0]): self.queue_tree.selection_set(selected[0])
        if not self.queue_tree.get_children():
            self.queue_empty_notice.configure(text="No active queues match these filters. Completed requests remain in Records.")
        else:
            self.queue_empty_notice.configure(text="Completed requests remain available in Records.")

    def show_queue_details(self, _event=None):
        selection = self.queue_tree.selection() if hasattr(self, "queue_tree") else ()
        q = next((item for item in self.queues if selection and item.get("id") == selection[0]), None)
        if not q: return
        values = {"Queue No.": q.get("queueNumber"), "Name": q.get("fullName"), "Service": q.get("service"), "Window": f"Window {q.get('window')}" if q.get("window") else "—", "Status": q.get("status"), "Time Joined": q.get("createdAt"), "Email": q.get("email"), "Education Level": q.get("education")}
        for key, label in getattr(self, "queue_detail_labels", {}).items(): label.configure(text=values.get(key) or "—")

    def refresh_queues(self, quiet=False):
        try:
            result = self.invoke("listQueues", {"quiet": quiet})
            self.queues = result.get("queues", [])
            self._refresh_dashboard_widgets()
            self.filter_queue_rows()
            self._refresh_queue_management_cards()
            if hasattr(self, "record_filter") and getattr(self, "records_loaded", False):
                self.filter_records()
            if hasattr(self, "report_filter_vars") and getattr(self, "report_has_data", False):
                self.render_report()
        except Exception as exc:
            if not quiet:
                messagebox.showerror("Queue refresh failed", str(exc))

    def _refresh_queue_management_cards(self):
        serving = next((q for q in self.queues if q.get("status") == "Serving"), None)
        if hasattr(self, "current_number"):
            self.current_number.configure(text=serving.get("queueNumber") if serving else "—")
            self.current_name.configure(text=serving.get("fullName") if serving else "No queue is being served")
            self.current_service.configure(text=f"{serving.get('service')}  ·  Window {serving.get('window')}" if serving else "Call next to begin serving.")
        if hasattr(self, "queue_window_cards"):
            for child in self.queue_window_cards.winfo_children(): child.destroy()
            window_ids = sorted({int(q.get("window")) for q in self.queues if q.get("window") and str(q.get("window")).isdigit()}) or [1, 2, 3]
            for window in window_ids:
                active = next((q for q in self.queues if q.get("status") == "Serving" and str(q.get("window")) == str(window)), None)
                box = tk.Frame(self.queue_window_cards, bg="#fafbfc", highlightbackground="#e4e6eb", highlightthickness=1, padx=9, pady=7)
                box.pack(side="left", fill="both", expand=True, padx=(0, 5))
                tk.Label(box, text=f"Window {window}", bg="#fafbfc", fg="#a10d19", font=("Segoe UI", 9, "bold")).pack(anchor="w")
                tk.Label(box, text="● Active" if active else "● Available", bg="#fafbfc", fg="#12804d" if active else "#767e8b", font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(3, 0))
                if active:
                    tk.Label(box, text=active.get("queueNumber", ""), bg="#fafbfc", fg="#263248", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 0))

    def schedule_refresh(self):
        if not self.root.winfo_exists():
            return
        self.root.after(5000, self.poll_queues)

    def poll_queues(self):
        if self.token:
            self.refresh_queues(quiet=True)
            self.schedule_refresh()

    def call_next(self):
        try:
            selected = self.window_var.get()
            self.refresh_queues(quiet=True)
            waiting = [q for q in self.queues if q.get("status") == "Waiting"]
            if selected != "Any" and not any(str(q.get("window")) == selected for q in waiting):
                messagebox.showinfo(
                    "No waiting queue",
                    f"There are no waiting requests assigned to Window {selected}. "
                    "Choose another window or select Any.",
                )
                return
            if selected == "Any" and not waiting:
                messagebox.showinfo("No waiting queue", "There are no waiting requests to call.")
                return
            result = self.invoke("transitionQueue", {"queueAction": "callNext", **({"window": int(selected)} if selected != "Any" else {})})
            messagebox.showinfo("Queue called", f"Now serving {result['queue']['queueNumber']} at Window {result['queue']['window']}.")
            self.refresh_queues()
        except Exception as exc:
            messagebox.showerror("Could not call next", str(exc))

    def complete_selected(self):
        selected = self.queue_tree.selection()
        if not selected:
            messagebox.showinfo("Select a queue", "Choose a serving request first.")
            return
        queue = next((q for q in self.queues if q.get("id") == selected[0]), None)
        if not queue or queue.get("status") != "Serving":
            messagebox.showinfo("Queue is not being served", "Only a serving request can be completed.")
            return
        try:
            result = self.invoke("transitionQueue", {"queueAction": "complete", "queueId": selected[0]})
            self.refresh_queues()
            number = result.get("queue", {}).get("queueNumber", "The request")
            messagebox.showinfo("Request completed", f"{number} was removed from Queue Management. Its record remains under Records.")
        except Exception as exc:
            messagebox.showerror("Could not complete queue", str(exc))

    def return_selected(self):
        selected = self.queue_tree.selection()
        if not selected:
            messagebox.showinfo("Select a queue", "Choose a serving queue first.")
            return
        try:
            self.invoke("transitionQueue", {"queueAction": "returnToWaiting", "queueId": selected[0]})
            self.refresh_queues()
        except Exception as exc:
            messagebox.showerror("Could not update queue", str(exc))

    def build_records_tab(self):
        self.page_header(self.records_tab, "Records Management", "Search and review queue and transaction records.")
        controls = tk.Frame(self.records_tab, bg="white", highlightbackground="#e1e4e9", highlightthickness=1, padx=12, pady=10)
        controls.pack(fill="x", pady=(0, 10))
        tk.Label(controls, text="Date", bg="white", fg="#29364b", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 5))
        self.record_date = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(controls, textvariable=self.record_date, width=13).pack(side="left", padx=(0, 9))
        self.record_filter = tk.StringVar()
        ttk.Entry(controls, textvariable=self.record_filter, width=25).pack(side="left", fill="x", expand=True, padx=(0, 7))
        self.pill_button(controls, "Search", self.filter_records, color="#f1f2f5", foreground="#303b50").pack(side="left", padx=(0, 7))
        self.pill_button(controls, "Load Records", self.load_records).pack(side="left", padx=(0, 7))
        self.pill_button(controls, "Export CSV", self.export_records, color="#ffffff", foreground="#a10d19", highlightthickness=1, highlightbackground="#e1e4e9").pack(side="left")
        body = tk.Frame(self.records_tab, bg="#f5f6f8")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=7, uniform="records")
        body.grid_columnconfigure(1, weight=3, uniform="records")
        body.grid_rowconfigure(0, weight=1)
        table = self.panel(body, "▤  Queue Records")
        table.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.records_tree = self.make_tree(table, [("number", "Queue No.", 90), ("name", "Name", 145), ("email", "Email", 175), ("service", "Service", 100), ("window", "Window", 75), ("status", "Status", 85), ("time", "Created", 115)])
        self.records_tree.bind("<<TreeviewSelect>>", self.show_record_details)
        detail = self.panel(body, "▣  Record Details")
        detail.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.record_detail_labels = {}
        for key in ("Queue No.", "Name", "Email", "Education", "Service", "Window", "Status", "Created", "Served", "Completed"):
            row = tk.Frame(detail, bg="white")
            row.pack(fill="x", pady=4)
            tk.Label(row, text=key, bg="white", fg="#697181", font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
            value = tk.Label(row, text="—", bg="white", fg="#172238", font=("Segoe UI", 9, "bold"), anchor="w", wraplength=170, justify="left")
            value.pack(side="left", fill="x", expand=True)
            self.record_detail_labels[key] = value

    def load_records(self):
        try:
            day = self.record_date.get().strip() or date.today().isoformat()
            self.records = self.invoke("getRecords", {"dateKey": day}).get("records", [])
            self.records_loaded = True
            self.filter_records()
        except Exception as exc:
            messagebox.showerror("Records unavailable", str(exc))

    def filter_records(self):
        query = self.record_filter.get().strip().casefold()
        self.records_tree.delete(*self.records_tree.get_children())
        for q in getattr(self, "records", []):
            searchable = " ".join(str(q.get(field, "")) for field in ("queueNumber", "fullName", "email", "service", "window", "status")).casefold()
            if query and query not in searchable:
                continue
            self.records_tree.insert("", "end", iid=q["id"], values=(q.get("queueNumber"), q.get("fullName"), q.get("email"), q.get("service"), f"Window {q.get('window')}" if q.get("window") else "—", q.get("status"), str(q.get("createdAt", ""))[:19].replace("T", " ")))

    def show_record_details(self, _event=None):
        selected = self.records_tree.selection() if hasattr(self, "records_tree") else ()
        q = next((item for item in getattr(self, "records", []) if selected and item.get("id") == selected[0]), None)
        if not q: return
        values = {"Queue No.": q.get("queueNumber"), "Name": q.get("fullName"), "Email": q.get("email"), "Education": q.get("education"), "Service": q.get("service"), "Window": q.get("window"), "Status": q.get("status"), "Created": q.get("createdAt"), "Served": q.get("serviceTime"), "Completed": q.get("completionTime")}
        for key, label in getattr(self, "record_detail_labels", {}).items(): label.configure(text=values.get(key) or "—")

    def export_records(self):
        if not getattr(self, "records_loaded", False):
            self.load_records()
        query = self.record_filter.get().strip().casefold()
        rows = [q for q in getattr(self, "records", []) if not query or query in " ".join(str(q.get(field, "")) for field in ("queueNumber", "fullName", "email", "service", "window", "status")).casefold()]
        if not rows:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"cardinal-queue-{date.today().isoformat()}.csv")
        if not path: return
        fields = ["queueNumber", "fullName", "education", "email", "service", "window", "status", "createdAt", "serviceTime", "completionTime"]
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        messagebox.showinfo("Export complete", f"Saved {len(rows)} records.")

    def build_reports_tab(self):
        self.page_header(self.reports_tab, "Reports", "View queue transaction summaries and generate reports.")
        controls = tk.Frame(self.reports_tab, bg="white", highlightbackground="#e1e4e9", highlightthickness=1, padx=12, pady=10)
        controls.pack(fill="x", pady=(0, 10))
        self.report_date = tk.StringVar(value=date.today().isoformat())
        self.report_service = tk.StringVar(value="All Services")
        self.report_window = tk.StringVar(value="All Windows")
        self.report_status = tk.StringVar(value="All Statuses")
        for title, variable, choices in (("Date", self.report_date, None), ("Service", self.report_service, ["All Services", "Enrollment", "Payment", "Form 137", "SF9", "Other"]), ("Service Window", self.report_window, ["All Windows", "1", "2", "3", "4", "5"]), ("Status", self.report_status, ["All Statuses", "Waiting", "Serving", "Completed"])):
            group = tk.Frame(controls, bg="white")
            group.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(group, text=title, bg="white", fg="#263248", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
            if choices:
                ttk.Combobox(group, textvariable=variable, values=choices, state="readonly").pack(fill="x")
            else:
                ttk.Entry(group, textvariable=variable).pack(fill="x")
        self.pill_button(controls, "▥  Generate Report", self.report).pack(side="left", padx=(4, 6), pady=(15, 0))
        self.pill_button(controls, "⇩  Export CSV", self.export_report, color="#ffffff", foreground="#172238", highlightthickness=1, highlightbackground="#e1e4e9").pack(side="left", pady=(15, 0))
        self.report_body = tk.Frame(self.reports_tab, bg="#f5f6f8")
        self.report_body.pack(fill="both", expand=True)
        self.report_cards = tk.Frame(self.report_body, bg="#f5f6f8")
        self.report_cards.pack(fill="x", pady=(0, 10))
        self.report_visuals = tk.Frame(self.report_body, bg="#f5f6f8")
        self.report_visuals.pack(fill="both", expand=True)
        self.report_has_data = False

    def report(self):
        try:
            selected_day = self.report_date.get().strip() or date.today().isoformat()
            self.report_records = self.invoke("getRecords", {"dateKey": selected_day}).get("records", [])
            self.report_filter_vars = True
            self.report_has_data = True
            self.render_report()
        except Exception as exc:
            messagebox.showerror("Report unavailable", str(exc))

    def render_report(self):
        service = self.report_service.get()
        window = self.report_window.get()
        status = self.report_status.get()
        rows = [q for q in getattr(self, "report_records", [])
                if (service == "All Services" or q.get("service") == service)
                and (window == "All Windows" or str(q.get("window")) == window)
                and (status == "All Statuses" or q.get("status") == status)]
        for frame in (self.report_cards, self.report_visuals):
            for child in frame.winfo_children(): child.destroy()
        completed = sum(q.get("status") == "Completed" for q in rows)
        waiting = sum(q.get("status") == "Waiting" for q in rows)
        serving = sum(q.get("status") == "Serving" for q in rows)
        wait_minutes = []
        for q in rows:
            try:
                created = datetime.fromisoformat(str(q.get("createdAt")).replace("Z", "+00:00"))
                called = datetime.fromisoformat(str(q.get("serviceTime")).replace("Z", "+00:00"))
                wait_minutes.append(max(0, (called - created).total_seconds() / 60))
            except Exception: pass
        average = f"{sum(wait_minutes) / len(wait_minutes):.0f} min" if wait_minutes else "—"
        summaries = (("Total Transactions", len(rows), "#bd101b", "#fff0f0"), ("Completed", completed, "#14734e", "#eaf8f0"), ("Average Wait", average, "#d78b00", "#fff8e8"), ("In Progress", waiting + serving, "#1552a0", "#edf5ff"))
        for index, (name, value, color, soft) in enumerate(summaries):
            card = tk.Frame(self.report_cards, bg="white", highlightbackground="#e5e7eb", highlightthickness=1, padx=12, pady=10)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            self.report_cards.grid_columnconfigure(index, weight=1, uniform="report")
            tk.Label(card, text=name, bg="white", fg="#263248", font=("Segoe UI", 9, "bold")).pack(anchor="w")
            tk.Label(card, text=str(value), bg="white", fg=color, font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(4, 0))
        left = self.panel(self.report_visuals, "▥  Transactions per Service")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        chart = tk.Canvas(left, bg="white", highlightthickness=0, height=210)
        chart.pack(fill="both", expand=True)
        service_totals = {}
        for q in rows: service_totals[q.get("service", "Other")] = service_totals.get(q.get("service", "Other"), 0) + 1
        maximum = max(service_totals.values(), default=1)
        chart.update_idletasks()
        width = max(chart.winfo_width(), 320)
        height = max(chart.winfo_height(), 200)
        colors = ["#d54a52", "#5097e9", "#f4c345", "#40a981", "#8f65c5"]
        count = max(1, len(service_totals))
        slot = width / count
        for idx, (name, total) in enumerate(sorted(service_totals.items())):
            x0 = idx * slot + slot * .23
            x1 = (idx + 1) * slot - slot * .23
            bar_h = (height - 50) * total / maximum
            chart.create_rectangle(x0, height - 28 - bar_h, x1, height - 28, fill=colors[idx % len(colors)], outline="")
            chart.create_text((x0+x1)/2, height - 38 - bar_h, text=str(total), fill="#263248", font=("Segoe UI", 9, "bold"))
            chart.create_text((x0+x1)/2, height - 12, text=name, fill="#3f4a5e", font=("Segoe UI", 8))
        right = self.panel(self.report_visuals, "◷  Transaction Status")
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        for label, amount, color in (("Completed", completed, "#32a775"), ("Waiting", waiting, "#f4bb35"), ("Serving", serving, "#5097e9")):
            row = tk.Frame(right, bg="white")
            row.pack(fill="x", pady=9)
            tk.Label(row, text="●", bg="white", fg=color, font=("Segoe UI", 14, "bold")).pack(side="left", padx=(0, 7))
            tk.Label(row, text=label, bg="white", fg="#263248", font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, text=f"{amount}  ({(amount/len(rows)*100 if rows else 0):.1f}%)", bg="white", fg="#263248", font=("Segoe UI", 10, "bold")).pack(side="right")
        tk.Label(right, text=f"Date: {self.report_date.get()}   ·   {len(rows)} records", bg="white", fg="#697181", font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 0))

    def export_report(self):
        rows = getattr(self, "report_records", [])
        if not rows:
            messagebox.showinfo("No report data", "Generate a report before exporting it.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"cardinal-queue-report-{self.report_date.get()}.csv")
        if not path: return
        fields = ["queueNumber", "fullName", "education", "email", "service", "window", "status", "createdAt", "serviceTime", "completionTime"]
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        messagebox.showinfo("Export complete", f"Saved {len(rows)} report records.")

    def build_admin_tabs(self):
        self.services_tab = self.add_page("Services & windows", "⚙  Services & windows", self.sidebar)
        self.staff_tab = self.add_page("Staff accounts", "♙  Staff accounts", self.sidebar)
        self.logs_tab = self.add_page("System logs", "▧  System logs", self.sidebar)
        self.build_services()
        self.build_staff()
        self.build_logs()

    def build_services(self):
        self.page_header(self.services_tab, "Services & Windows", "Manage the services and windows available for queue registration.")
        card = self.panel(self.services_tab, "⚙  Service Configuration")
        card.pack(fill="x", anchor="n")
        form = tk.Frame(card, bg="white")
        form.pack(fill="x")
        ttk.Label(form, text="Service").grid(row=0, column=0, sticky="w", pady=6)
        self.service_name = tk.StringVar(value="Enrollment")
        service_selector = ttk.Combobox(form, textvariable=self.service_name, values=list(DEFAULT_SERVICE_WINDOWS), state="readonly", width=24)
        service_selector.grid(row=0, column=1, sticky="w")
        service_selector.bind("<<ComboboxSelected>>", self.load_service_window_defaults)
        ttk.Label(form, text="Available windows (comma separated)").grid(row=1, column=0, sticky="w", pady=6)
        self.service_windows = ttk.Entry(form, width=35)
        self.load_service_window_defaults()
        self.service_windows.grid(row=1, column=1, sticky="w")
        self.service_active = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Service is available", variable=self.service_active).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Button(form, text="Save service", command=self.save_service, style="Primary.TButton").grid(row=3, column=1, sticky="w", pady=10)
        defaults_summary = " · ".join(f"{name} {','.join(map(str, windows))}" for name, windows in DEFAULT_SERVICE_WINDOWS.items())
        ttk.Label(form, text=f"Default windows: {defaults_summary}", wraplength=660).grid(row=4, column=0, columnspan=2, sticky="w", pady=15)

    def load_service_window_defaults(self, _event=None):
        windows = DEFAULT_SERVICE_WINDOWS.get(self.service_name.get(), (1, 2))
        self.service_windows.delete(0, "end")
        self.service_windows.insert(0, ",".join(map(str, windows)))

    def save_service(self):
        try:
            windows = [int(x.strip()) for x in self.service_windows.get().split(",") if x.strip()]
            self.invoke("saveService", {"name": self.service_name.get(), "windows": windows, "active": self.service_active.get()})
            messagebox.showinfo("Saved", "Service availability and windows updated.")
        except Exception as exc:
            messagebox.showerror("Could not save service", str(exc))

    def build_staff(self):
        self.page_header(self.staff_tab, "Staff Accounts", "Manage authorized users and their access roles.")
        card = self.panel(self.staff_tab, "♙  Authorized Staff")
        card.pack(fill="both", expand=True)
        bar = tk.Frame(card, bg="white")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Load staff accounts", command=self.load_staff).pack(side="left")
        self.staff_tree_frame = tk.Frame(card, bg="white")
        self.staff_tree_frame.pack(fill="both", expand=False, pady=(0, 8))
        self.staff_tree = self.make_tree(self.staff_tree_frame, [("name", "Name", 150), ("email", "Email", 220), ("role", "Role", 130), ("active", "Active", 75), ("uid", "UID", 280)])
        self.staff_tree.configure(height=5)
        form = tk.Frame(card, bg="white")
        form.pack(fill="x")
        ttk.Label(form, text="Supabase Auth user ID").grid(row=0, column=0, sticky="w", pady=5)
        self.staff_uid = ttk.Entry(form, width=50); self.staff_uid.grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="Display name").grid(row=1, column=0, sticky="w", pady=5)
        self.staff_name = ttk.Entry(form, width=50); self.staff_name.grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Role").grid(row=2, column=0, sticky="w", pady=5)
        self.staff_role = tk.StringVar(value="staff")
        ttk.Combobox(form, textvariable=self.staff_role, values=["staff", "system_admin", "disabled"], state="readonly", width=18).grid(row=2, column=1, sticky="w")
        ttk.Button(form, text="Set staff role", command=self.save_staff, style="Primary.TButton").grid(row=3, column=1, sticky="w", pady=12)
        ttk.Label(form, text="Create or invite the user in Supabase Authentication first. Then enter their user ID to assign a staff role.", wraplength=650).grid(row=4, column=0, columnspan=2, sticky="w", pady=10)

    def load_staff(self):
        try:
            staff = self.invoke("listStaff").get("staff", [])
            self.staff_tree.delete(*self.staff_tree.get_children())
            for member in staff:
                self.staff_tree.insert("", "end", iid=member["id"], values=(member.get("name"), member.get("email"), member.get("role"), "Yes" if member.get("active") else "No", member.get("staffId")))
        except Exception as exc:
            messagebox.showerror("Staff accounts unavailable", str(exc))

    def save_staff(self):
        try:
            self.invoke("setStaffRole", {"uid": self.staff_uid.get().strip(), "name": self.staff_name.get().strip(), "role": self.staff_role.get()})
            messagebox.showinfo("Saved", "Staff role updated. They may need to sign in again for the new role to take effect.")
        except Exception as exc:
            messagebox.showerror("Could not update staff", str(exc))

    def build_logs(self):
        self.page_header(self.logs_tab, "System Logs", "Review recent administrative activity and system events.")
        card = self.panel(self.logs_tab, "◷  Audit Activity")
        card.pack(fill="both", expand=True)
        ttk.Button(card, text="Load latest logs", command=self.load_logs).pack(anchor="w", pady=(0, 10))
        self.logs_tree = self.make_tree(card, [("time", "Time", 200), ("action", "Action", 220), ("staff", "Staff UID", 200), ("record", "Record", 250)])

    def load_logs(self):
        try:
            logs = self.invoke("listLogs").get("logs", [])
            self.logs_tree.delete(*self.logs_tree.get_children())
            for log in logs:
                self.logs_tree.insert("", "end", iid=log["id"], values=(str(log.get("createdAt", ""))[:19].replace("T", " "), log.get("action"), log.get("staffUid"), log.get("recordId")))
        except Exception as exc:
            messagebox.showerror("Logs unavailable", str(exc))


if __name__ == "__main__":
    window = tk.Tk()
    CardinalAdmin(window)
    window.mainloop()
