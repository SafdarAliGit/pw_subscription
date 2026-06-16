import frappe
import os
import glob
import subprocess
from frappe.utils import now_datetime


# Step constants (stored in current_step field, polled by frontend)
STEP_STARTING   = 0
STEP_BACKUP     = 1
STEP_CREATE     = 2
STEP_RESTORE    = 3
STEP_PASSWORD   = 4
STEP_EMAIL      = 5
STEP_DONE       = 6
STEP_FAILED     = -1


# ── Internal helpers ────────────────────────────────────────────────────────

def _bench_dir():
    """Return the frappe-bench root directory."""
    return os.path.abspath(os.path.join(frappe.get_site_path(), "..", ".."))


def _find_bench():
    """
    Return the path to a working bench executable.
    Checks the bench-specific virtualenv first (e.g. bench15_env),
    then the standard frappe env, then common system locations.
    """
    bd = _bench_dir()
    candidates = [
        # Bench virtualenv sits next to the bench dir: bench15 → bench15_env
        bd.rstrip("/") + "_env/bin/bench",
        # Standard Frappe bench layout: env/ inside the bench dir
        os.path.join(bd, "env", "bin", "bench"),
        # User-local pip install
        os.path.expanduser("~/.local/bin/bench"),
        # System installs
        "/usr/local/bin/bench",
        "/usr/bin/bench",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "bench"  # last resort


def _run_env():
    """Return an environment dict suitable for running bench."""
    bd = _bench_dir()
    env = os.environ.copy()
    bench_exe = _find_bench()
    bench_bin_dir = os.path.dirname(bench_exe)
    # Prepend bench dirs to the existing PATH (don't drop system entries)
    extra = [d for d in [bench_bin_dir, os.path.join(bd, "env", "bin")] if d]
    env["PATH"] = ":".join(extra) + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def _log(request_name, message):
    """Append a timestamped line to the request's progress log."""
    ts = now_datetime().strftime("%H:%M:%S")
    line = f"[{ts}] {message}\n"
    existing = frappe.db.get_value("Site Provisioning Request", request_name, "progress_log") or ""
    frappe.db.set_value(
        "Site Provisioning Request", request_name,
        "progress_log", existing + line,
        update_modified=False,
    )
    frappe.db.commit()


def _set_step(request_name, step):
    """Update the current_step field so the frontend can show friendly progress."""
    frappe.db.set_value(
        "Site Provisioning Request", request_name,
        "current_step", step,
        update_modified=False,
    )
    frappe.db.commit()


def _run(args, request_name, step_label, timeout=600):
    """
    Run a bench command, log start/end, raise on non-zero exit.
    Returns stdout string.
    """
    bench_exe = _find_bench()
    result = subprocess.run(
        [bench_exe] + args,
        cwd=_bench_dir(),
        capture_output=True,
        text=True,
        env=_run_env(),
        timeout=timeout,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "Unknown error").strip()
        if len(err) > 1000:
            err = "…" + err[-1000:]
        raise RuntimeError(f"{step_label} failed:\n{err}")
    return result.stdout


def _latest_backup_files(site_name):
    """
    Return (db_file, pub_file, priv_file) for the most recent backup.
    pub_file and priv_file may be None if absent.
    """
    backup_dir = os.path.join(_bench_dir(), "sites", site_name, "private", "backups")
    db_files   = sorted(glob.glob(os.path.join(backup_dir, "*-database.sql.gz")))
    pub_files  = sorted(glob.glob(os.path.join(backup_dir, "*-files.tar")))
    priv_files = sorted(glob.glob(os.path.join(backup_dir, "*-private-files.tar")))

    if not db_files:
        raise FileNotFoundError(f"No database backup found in {backup_dir}")

    return (
        db_files[-1],
        pub_files[-1] if pub_files else None,
        priv_files[-1] if priv_files else None,
    )


# ── Background job ───────────────────────────────────────────────────────────

def _provision_site(request_name):
    """
    Long-running background job:
      1. Fresh backup of master site
      2. Create new site
      3. Restore master backup
      4. Reset admin password
      5. Send welcome email
    """
    frappe.set_user("Administrator")

    attempt = (frappe.db.get_value("Site Provisioning Request", request_name, "attempt_count") or 0) + 1
    frappe.db.set_value("Site Provisioning Request", request_name, {
        "status": "In Progress",
        "attempt_count": attempt,
        "last_attempt": now_datetime(),
        "error_message": "",
        "current_step": STEP_STARTING,
    }, update_modified=False)
    frappe.db.commit()

    _log(request_name, f"=== Attempt {attempt} started ===")

    try:
        # ── Load settings ────────────────────────────────────────────────────
        settings     = frappe.get_single("PW Subscription Settings")
        master_site  = (settings.master_site_name or "").strip()
        db_root_pass = settings.get_password("mariadb_root_password") or ""

        if not master_site:
            raise ValueError("Master Site Name is not configured in PW Subscription Settings.")
        if not db_root_pass:
            raise ValueError("MariaDB Root Password is not configured in PW Subscription Settings.")

        doc          = frappe.get_doc("Site Provisioning Request", request_name)
        site_name    = doc.site_name
        sub_doc      = frappe.get_doc("PW Subscription", doc.subscription)
        admin_pass   = (sub_doc.initial_password or "").strip()

        if not admin_pass:
            raise ValueError("Admin password not found in the subscription record.")

        _log(request_name, f"Provisioning: {site_name}")

        # ── Step 1: Backup master site ───────────────────────────────────────
        _set_step(request_name, STEP_BACKUP)
        _log(request_name, "Creating Backup...")
        _run(
            ["--site", master_site, "backup", "--with-files"],
            request_name, "Master backup", timeout=300,
        )
        db_file, pub_file, priv_file = _latest_backup_files(master_site)
        _log(request_name, f"✓ Backup ready: {os.path.basename(db_file)}")

        # ── Step 2: Create new site ──────────────────────────────────────────
        _set_step(request_name, STEP_CREATE)
        site_dir = os.path.join(_bench_dir(), "sites", site_name)
        if os.path.exists(site_dir):
            _log(request_name, f"Site {site_name} already exists — dropping before recreating…")
            _run(
                ["drop-site", site_name, "--mariadb-root-password", db_root_pass, "--force"],
                request_name, "Drop existing site", timeout=120,
            )
            _log(request_name, f"✓ Existing site dropped.")
        _log(request_name, f"Creating site {site_name}…")
        _run(
            [
                "new-site", site_name,
                "--admin-password", admin_pass,
                "--mariadb-root-password", db_root_pass,
                "--install-app", "frappe",
            ],
            request_name, "New site", timeout=300,
        )
        _log(request_name, f"✓ Site {site_name} created.")

        # ── Step 3: Restore backup ───────────────────────────────────────────
        _set_step(request_name, STEP_RESTORE)
        _log(request_name, "Restoring master data to new site…")
        restore_args = [
            "--site", site_name, "restore", db_file,
            "--mariadb-root-password", db_root_pass,
            "--admin-password", admin_pass,
        ]
        if pub_file:
            restore_args += ["--with-public-files", pub_file]
        if priv_file:
            restore_args += ["--with-private-files", priv_file]
        _run(restore_args, request_name, "Restore", timeout=600)
        _log(request_name, "✓ Data restored successfully.")

        # Apply any pending schema migrations so the new site is fully up-to-date
        _log(request_name, "Applying database migrations…")
        _run(
            ["--site", site_name, "migrate"],
            request_name, "Migrate", timeout=300,
        )
        _log(request_name, "✓ Migrations applied.")

        # ── Step 4: Reset admin password (restore overwrites it) ─────────────
        _set_step(request_name, STEP_PASSWORD)
        _log(request_name, "Securing your account…")
        _run(
            ["--site", site_name, "set-admin-password", admin_pass],
            request_name, "Set password", timeout=60,
        )
        _log(request_name, "✓ Admin password configured.")

        # ── Step 5: Send welcome email ────────────────────────────────────────
        _set_step(request_name, STEP_EMAIL)
        site_url = f"https://{site_name}"
        _log(request_name, f"Sending welcome email to {doc.contact_email}…")
        _send_welcome_email(doc, site_url, admin_pass, settings)
        _log(request_name, "✓ Welcome email sent.")

        # ── Done ──────────────────────────────────────────────────────────────
        _log(request_name, f"✓ Site is live: {site_url}")
        frappe.db.set_value("Site Provisioning Request", request_name, {
            "status": "Success",
            "site_url": site_url,
            "error_message": "",
            "current_step": STEP_DONE,
        }, update_modified=False)
        # Clear stored plain-text password now that provisioning is complete
        try:
            frappe.db.set_value(
                "PW Subscription", doc.subscription,
                "initial_password", "", update_modified=False,
            )
        except Exception:
            pass
        frappe.db.commit()

    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), f"Site Provisioning Failed [{request_name}]")
        err_text = str(exc)
        _log(request_name, f"✗ {err_text}")
        frappe.db.set_value("Site Provisioning Request", request_name, {
            "status": "Failed",
            "error_message": err_text,
            "current_step": STEP_FAILED,
        }, update_modified=False)
        frappe.db.commit()


def _send_welcome_email(doc, site_url, admin_password, settings):
    settings = frappe.get_single("PW Subscription Settings")
    sender   = (settings.sender_email or "").strip() or None
    app_name = settings.app_name or "CureDesk"
    subject  = f"Your {app_name} clinic is ready — {doc.site_name}"
    body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#1E293B">
  <h2 style="color:#2563EB">{app_name} — Clinic Setup Complete</h2>
  <p>Dear <strong>{doc.physician_name}</strong>,</p>
  <p>Your clinic site is now live. Use the credentials below to log in:</p>
  <table style="width:100%;border-collapse:collapse;margin:1.5rem 0;border-radius:8px;overflow:hidden">
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem 1rem;font-weight:700;color:#1E40AF;width:40%">Site URL</td>
      <td style="padding:.75rem 1rem"><a href="{site_url}" style="color:#2563EB">{site_url}</a></td>
    </tr>
    <tr style="background:#F0FDF4">
      <td style="padding:.75rem 1rem;font-weight:700;color:#065F46">User ID</td>
      <td style="padding:.75rem 1rem">Administrator</td>
    </tr>
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem 1rem;font-weight:700;color:#1E40AF">Password</td>
      <td style="padding:.75rem 1rem;font-family:monospace">{admin_password}</td>
    </tr>
  </table>
  <p style="color:#DC2626;font-weight:600">Please change your password after your first login.</p>
  <hr style="border:none;border-top:1px solid #E2E8F0;margin:2rem 0">
  <p style="color:#94A3B8;font-size:.8rem">{app_name} — Professional Clinic Management</p>
</div>
""".strip()
    # frappe.sendmail(
    #     recipients=[doc.contact_email],
    #     sender=sender,
    #     subject=subject,
    #     message=body,
    #     now=True,
    # )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _infer_step_from_log(log):
    """
    Derive the current step number from progress_log text.
    Used as a fallback when the current_step column does not yet exist in the DB.
    """
    if not log:
        return 0
    lo = log.lower()
    if "site is live" in lo or "welcome email sent" in lo:
        return STEP_DONE
    if "welcome email" in lo or "sending" in lo:
        return STEP_EMAIL
    if "admin password" in lo or "securing" in lo or "set-admin-password" in lo:
        return STEP_PASSWORD
    if "restoring" in lo or "restore" in lo:
        return STEP_RESTORE
    if "creating site" in lo or "new-site" in lo or f"site {'' if True else ''}" in lo:
        return STEP_CREATE
    if "backup" in lo or "backing up" in lo:
        return STEP_BACKUP
    return STEP_STARTING


def _last_log_line(log):
    """Return the last non-empty line from the progress log."""
    if not log:
        return ""
    lines = [l.strip() for l in log.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _enqueue_provision(request_name):
    """Enqueue the provisioning job. Tries long queue first, falls back to default."""
    kwargs = dict(
        method="pw_subscription.site_provisioning._provision_site",
        request_name=request_name,
        timeout=1800,
    )
    try:
        frappe.enqueue(queue="long", **kwargs)
    except Exception:
        frappe.enqueue(queue="default", **kwargs)


# ── Public API ───────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def get_provisioning_status(request_name):
    """
    Poll endpoint — returns status, step, last log line, and error for a request.
    Resilient to missing current_step column (runs before bench migrate).
    """
    if not request_name:
        frappe.throw("request_name is required.")

    # Always fetch these safe fields
    result = frappe.db.get_value(
        "Site Provisioning Request",
        request_name,
        ["status", "site_url", "contact_email",
         "physician_name", "error_message", "attempt_count", "progress_log"],
        as_dict=True,
    )
    if not result:
        frappe.throw(f"Provisioning request '{request_name}' not found.")

    # Try to get current_step — may not exist if bench migrate hasn't been run
    try:
        step = frappe.db.get_value("Site Provisioning Request", request_name, "current_step")
        result["current_step"] = int(step or 0)
    except Exception:
        result["current_step"] = _infer_step_from_log(result.get("progress_log") or "")

    result["last_line"] = _last_log_line(result.get("progress_log") or "")
    # Don't send full log to frontend (it's for admin use only)
    result.pop("progress_log", None)
    return result


@frappe.whitelist(allow_guest=True)
def retry_site_creation(request_name):
    """Re-queue a failed or pending provisioning request."""
    if not request_name:
        frappe.throw("request_name is required.")

    status = frappe.db.get_value("Site Provisioning Request", request_name, "status")
    if not status:
        frappe.throw(f"Request '{request_name}' not found.")
    if status == "In Progress":
        frappe.throw("Provisioning is already in progress.")
    if status == "Success":
        frappe.throw("This site was already provisioned successfully.")

    frappe.db.set_value("Site Provisioning Request", request_name, {
        "status": "Pending",
        "error_message": "",
    }, update_modified=False)
    # Try to reset current_step if column exists
    try:
        frappe.db.set_value("Site Provisioning Request", request_name,
                            "current_step", STEP_STARTING, update_modified=False)
    except Exception:
        pass
    frappe.db.commit()

    _enqueue_provision(request_name)
    return {"success": True}
