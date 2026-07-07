import frappe
import json
import os
import glob
import subprocess
from frappe.utils import now_datetime


STEP_STARTING   = 0
STEP_BACKUP     = 1
STEP_CREATE     = 2
STEP_RESTORE    = 3
STEP_PASSWORD   = 4
STEP_EMAIL      = 5
STEP_DONE       = 6
STEP_FAILED     = -1


# ── Environment helpers ──────────────────────────────────────────────────────

def _bench_dir():
    return os.path.abspath(os.path.join(frappe.get_site_path(), "..", ".."))


def _find_bench():
    bd = _bench_dir()
    candidates = [
        bd.rstrip("/") + "_env/bin/bench",
        os.path.join(bd, "env", "bin", "bench"),
        os.path.expanduser("~/.local/bin/bench"),
        "/usr/local/bin/bench",
        "/usr/bin/bench",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "bench"


def _run_env():
    bd = _bench_dir()
    env = os.environ.copy()
    bench_exe = _find_bench()
    bench_bin_dir = os.path.dirname(bench_exe)
    extra = [d for d in [bench_bin_dir, os.path.join(bd, "env", "bin")] if d]
    env["PATH"] = ":".join(extra) + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def _log(request_name, message):
    if not request_name:
        return
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
    if not request_name:
        return
    frappe.db.set_value(
        "Site Provisioning Request", request_name,
        "current_step", step,
        update_modified=False,
    )
    frappe.db.commit()


def _run(args, request_name, step_label, timeout=600):
    bench_exe = _find_bench()
    result = subprocess.run(
        [bench_exe] + args,
        cwd=_bench_dir(),
        stdin=subprocess.DEVNULL,
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


# ── Site suspension / unsuspension ──────────────────────────────────────────

def _do_suspend_site(site_name):
    """Put a site into maintenance mode (hard suspend)."""
    _run(
        ["--site", site_name, "set-config", "maintenance_mode", "1"],
        None, f"Suspend {site_name}", timeout=30,
    )


def _do_unsuspend_site(site_name):
    """Remove maintenance mode from a site."""
    _run(
        ["--site", site_name, "set-config", "maintenance_mode", "0"],
        None, f"Unsuspend {site_name}", timeout=30,
    )


# ── Background provisioning job ──────────────────────────────────────────────

def _provision_site(request_name):
    """
    Long-running background job:
      1. Fresh backup of master site
      2. Create new site
      3. Restore master backup
      4. Reset admin password
      5. Send welcome email (if enabled)
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
    _publish_prov(request_name, "In Progress")

    _log(request_name, f"=== Attempt {attempt} started ===")

    try:
        settings     = frappe.get_single("PW Subscription Settings")
        master_site  = (settings.master_site_name or "").strip()
        db_root_pass = settings.get_password("mariadb_root_password") or ""

        if not master_site:
            raise ValueError("Master Site Name is not configured in PW Subscription Settings.")
        if not db_root_pass:
            raise ValueError("MariaDB Root Password is not configured in PW Subscription Settings.")

        doc            = frappe.get_doc("Site Provisioning Request", request_name)
        site_name      = doc.site_name
        sub_doc        = frappe.get_doc("PW Subscription", doc.subscription)
        admin_pass     = (sub_doc.initial_password or "").strip()
        contact_email  = (doc.contact_email or "").strip().lower()
        physician_name = (doc.physician_name or "").strip()
        _name_parts    = physician_name.split(None, 1)
        first_name     = _name_parts[0] if _name_parts else "Doctor"
        last_name      = _name_parts[1] if len(_name_parts) > 1 else ""

        if not admin_pass:
            raise ValueError("Admin password not found in the subscription record.")

        _log(request_name, f"Provisioning: {site_name}")

        # ── Step 1: Backup master site ───────────────────────────────────────
        _set_step(request_name, STEP_BACKUP)
        _log(request_name, "Creating backup of master site...")
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
            _log(request_name, f"Site {site_name} already exists — dropping before recreating...")
            _run(
                ["drop-site", site_name, "--mariadb-root-password", db_root_pass, "--force"],
                request_name, "Drop existing site", timeout=120,
            )
            _log(request_name, "✓ Existing site dropped.")
        _log(request_name, f"Creating site {site_name}...")
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
        _log(request_name, "Restoring master data to new site...")
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

        _log(request_name, "Applying database migrations...")
        _run(
            ["--site", site_name, "migrate"],
            request_name, "Migrate", timeout=300,
        )
        _log(request_name, "✓ Migrations applied.")

        # ── Step 3b: Ensure portal login user exists on master site ─────────────
        _log(request_name, f"Ensuring portal account on master site ({frappe.local.site})...")
        try:
            from frappe.utils.password import update_password as _upd
            if not frappe.db.exists("User", contact_email):
                u = frappe.get_doc({
                    "doctype": "User",
                    "email": contact_email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "user_type": "Website User",
                    "new_password": admin_pass,
                })
                u.flags.ignore_password_policy = True
                u.insert(ignore_permissions=True)
            else:
                u = frappe.get_doc("User", contact_email)
                if u.user_type != "Website User" or not u.enabled:
                    u.user_type = "Website User"
                    u.enabled = 1
                    u.flags.ignore_password_policy = True
                    u.save(ignore_permissions=True)
            # Always explicitly set password to guarantee it's stored
            frappe.flags.in_import = True
            try:
                _upd(contact_email, admin_pass)
            finally:
                frappe.flags.in_import = False
            frappe.db.commit()
            _log(request_name, f"✓ Portal account ready: {contact_email}")
        except Exception as portal_exc:
            frappe.log_error(frappe.get_traceback(), f"Portal user creation failed [{request_name}]")
            _log(request_name, f"⚠ Portal user creation failed: {str(portal_exc)[:300]}")

        # ── Step 4: Create PW Admin user on new site + set admin password ────────
        _set_step(request_name, STEP_PASSWORD)
        _log(request_name, "Configuring your account...")

        # Create the customer's user with PW Admin role on the new clinic site
        if contact_email:
            _log(request_name, f"Creating clinic login account ({contact_email})...")
            try:
                _run(
                    [
                        "--site", site_name, "execute",
                        "frappe.get_attr('pw_subscription.site_provisioning._setup_site_user')",
                        "--kwargs", json.dumps({
                            "email": contact_email,
                            "first_name": first_name,
                            "last_name": last_name,
                            "password": admin_pass,
                        }),
                    ],
                    request_name, "Create clinic user", timeout=120,
                )
                _log(request_name, f"✓ Clinic account ready: {contact_email}")
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Clinic user creation failed [{request_name}]")
                _log(request_name, "⚠ Clinic user setup skipped (non-fatal).")

        # Also set the built-in Administrator password as a fallback
        _log(request_name, "Setting administrator password...")
        _run(
            ["--site", site_name, "set-admin-password", admin_pass],
            request_name, "Set password", timeout=60,
        )
        _log(request_name, "✓ Account configured.")

        # ── Step 5: Production setup ──────────────────────────────────────────
        _log(request_name, "Enabling scheduler...")
        try:
            _run(
                ["--site", site_name, "enable-scheduler"],
                request_name, "Enable scheduler", timeout=60,
            )
            _log(request_name, "✓ Scheduler enabled.")
        except Exception as _prod_exc:
            _log(request_name, f"⚠ enable-scheduler skipped: {str(_prod_exc)[:200]}")

        _log(request_name, "Disabling maintenance mode...")
        try:
            _run(
                ["--site", site_name, "set-config", "maintenance_mode", "0"],
                request_name, "Disable maintenance mode", timeout=30,
            )
            _log(request_name, "✓ Maintenance mode disabled.")
        except Exception as _prod_exc:
            _log(request_name, f"⚠ maintenance mode step skipped: {str(_prod_exc)[:200]}")

        _log(request_name, "Updating nginx config...")
        try:
            _run(
                ["setup", "nginx", "--yes"],
                request_name, "Setup nginx", timeout=120,
            )
            _log(request_name, "✓ Nginx configured.")
        except Exception as _prod_exc:
            _log(request_name, f"⚠ bench setup nginx skipped: {str(_prod_exc)[:200]}")

        # ── Step 6: Send welcome email ────────────────────────────────────────
        _set_step(request_name, STEP_EMAIL)
        site_url = f"https://{site_name}"
        _log(request_name, f"Sending welcome email to {doc.contact_email}...")
        _send_welcome_email(doc, site_url, admin_pass, settings)

        # ── Done ──────────────────────────────────────────────────────────────
        _log(request_name, f"✓ Site is live: {site_url}")
        frappe.db.set_value("Site Provisioning Request", request_name, {
            "status": "Success",
            "site_url": site_url,
            "error_message": "",
            "current_step": STEP_DONE,
        }, update_modified=False)

        # Clear stored plain-text password
        try:
            frappe.db.set_value(
                "PW Subscription", doc.subscription,
                "initial_password", "", update_modified=False,
            )
        except Exception:
            pass
        frappe.db.commit()
        _publish_prov(request_name, "Success", site_url=site_url,
                      subscription=doc.subscription)

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
        _publish_prov(request_name, "Failed")


def _send_welcome_email(doc, site_url, admin_password, settings):
    """Send welcome email. Only runs when enable_welcome_email is on."""
    try:
        if not settings.enable_welcome_email:
            return
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
      <td style="padding:.75rem 1rem;font-weight:700;color:#065F46">Login Email</td>
      <td style="padding:.75rem 1rem">{doc.contact_email}</td>
    </tr>
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem 1rem;font-weight:700;color:#1E40AF">Password</td>
      <td style="padding:.75rem 1rem;font-family:monospace">{admin_password}</td>
    </tr>
  </table>
  <p style="color:#DC2626;font-weight:600">Please change your password after your first login.</p>
  <hr style="border:none;border-top:1px solid #E2E8F0;margin:2rem 0">
  <p style="color:#94A3B8;font-size:.8rem">{app_name} — Professional Clinic Management</p>
</div>""".strip()
        frappe.sendmail(
            recipients=[doc.contact_email],
            sender=sender,
            subject=subject,
            message=body,
            now=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Welcome email failed for {doc.site_name}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _infer_step_from_log(log):
    if not log:
        return 0
    lo = log.lower()
    if "site is live" in lo or "welcome email" in lo:
        return STEP_DONE
    if "sending welcome" in lo or "sending" in lo:
        return STEP_EMAIL
    if "admin password" in lo or "securing" in lo or "set-admin-password" in lo:
        return STEP_PASSWORD
    if "restoring" in lo or "restore" in lo or "migration" in lo:
        return STEP_RESTORE
    if "creating site" in lo or "new-site" in lo:
        return STEP_CREATE
    if "backup" in lo or "backing up" in lo:
        return STEP_BACKUP
    return STEP_STARTING


def _last_log_line(log):
    if not log:
        return ""
    lines = [l.strip() for l in log.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _publish_prov(request_name, status, site_url="", subscription=""):
    try:
        frappe.publish_realtime("pw_prov_updated", {
            "request_name": request_name,
            "subscription": subscription,
            "status": status,
            "site_url": site_url,
        })
    except Exception:
        pass


def _setup_site_user(email, first_name, last_name, password):
    """
    Called via `bench --site <new_site> execute` in the new clinic site's context.
    Creates (or updates) the customer's user with PW Admin role and sets their password.
    """
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        if "PW Admin" not in [r.role for r in user.roles]:
            user.append("roles", {"role": "PW Admin"})
            user.flags.ignore_password_policy = True
            user.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name or "Doctor",
            "last_name": last_name or "",
            "enabled": 1,
            "send_welcome_email": 0,
            "user_type": "System User",
            "roles": [{"role": "PW Admin"}],
        })
        doc.flags.ignore_password_policy = True
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
    from frappe.utils.password import update_password
    frappe.flags.in_import = True
    try:
        update_password(email, password)
        frappe.db.commit()
    finally:
        frappe.flags.in_import = False


def _enqueue_provision(request_name):
    kwargs = dict(
        method="pw_subscription.site_provisioning._provision_site",
        request_name=request_name,
        timeout=1800,
    )
    try:
        frappe.enqueue(queue="long", **kwargs)
    except Exception:
        frappe.enqueue(queue="default", **kwargs)
