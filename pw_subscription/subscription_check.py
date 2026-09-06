import frappe
from frappe.utils import today, add_days, date_diff, now


def get_current_subscription():
    try:
        subs = frappe.get_all(
            "PW Subscription",
            fields=["name", "status", "trial_start", "trial_end",
                    "subscription_start", "subscription_end", "grace_end",
                    "site_name", "is_suspended"],
            order_by="creation desc",
            limit=1,
        )
        return frappe.get_doc("PW Subscription", subs[0].name) if subs else None
    except Exception:
        return None


def update_subscription_statuses():
    """Daily scheduler: auto-transition subscription statuses and handle suspension."""
    today_date = today()
    subs = frappe.get_all(
        "PW Subscription",
        filters={"status": ["in", ["Trial", "Active", "Grace Period"]]},
        fields=["name", "status", "trial_end", "subscription_end", "grace_end",
                "site_name", "is_suspended"],
    )
    try:
        settings = frappe.get_single("PW Subscription Settings")
        grace_days = settings.grace_period_days or 3
        auto_suspend_trial = settings.auto_suspend_on_trial_expiry
        auto_suspend_sub = settings.auto_suspend_on_subscription_expiry
        suspension_mode = settings.suspension_mode or "Soft Block"
    except Exception:
        grace_days = 3
        auto_suspend_trial = False
        auto_suspend_sub = False
        suspension_mode = "Soft Block"

    for s in subs:
        new_status = None
        grace_end_date = None
        should_suspend = False

        if s.status == "Trial" and s.trial_end and str(s.trial_end) < today_date:
            new_status = "Expired"
            should_suspend = bool(auto_suspend_trial)
        elif s.status == "Active" and s.subscription_end and str(s.subscription_end) < today_date:
            new_status = "Grace Period"
            grace_end_date = add_days(s.subscription_end, grace_days)
        elif s.status == "Grace Period" and s.grace_end and str(s.grace_end) < today_date:
            new_status = "Expired"
            should_suspend = bool(auto_suspend_sub)

        if new_status:
            doc = frappe.get_doc("PW Subscription", s.name)
            old_status = doc.status
            doc.status = new_status
            if grace_end_date:
                doc.grace_end = grace_end_date

            # Auto-suspend if configured and not already suspended
            if should_suspend and not doc.is_suspended:
                if doc.site_name:
                    try:
                        from pw_subscription.site_provisioning import _do_suspend_site
                        _do_suspend_site(doc.site_name)
                    except Exception as e:
                        frappe.log_error(str(e), f"Auto-suspend failed for {doc.site_name}")
                doc.is_suspended = 1
                doc.suspended_on = now()
                doc.suspension_reason = f"Auto-suspended: {new_status}"

            doc.save(ignore_permissions=True)
            frappe.get_doc({
                "doctype": "PW Subscription Log",
                "subscription": s.name,
                "action": new_status if new_status in ["Expired", "Grace Period"] else "Cancelled",
                "action_date": now(),
                "action_by": "Administrator",
                "notes": f"Auto-updated from {old_status} to {new_status} by scheduler."
                         + (" Site auto-suspended." if should_suspend and not s.is_suspended else ""),
            }).insert(ignore_permissions=True)

    frappe.db.commit()


def send_renewal_reminders():
    """Daily scheduler: send renewal reminder emails at configured intervals."""
    try:
        settings = frappe.get_single("PW Subscription Settings")
        if not settings.enable_renewal_reminders:
            return
        if not settings.enable_welcome_email:
            return  # email sending must be enabled
        raw = (settings.reminder_days or "7,3,1").strip()
        reminder_day_list = [int(d.strip()) for d in raw.split(",") if d.strip().isdigit()]
    except Exception:
        return

    today_date = today()
    subs = frappe.get_all(
        "PW Subscription",
        filters={"status": ["in", ["Trial", "Active", "Grace Period"]]},
        fields=["name", "status", "trial_end", "subscription_end", "grace_end",
                "contact_email", "physician_name", "clinic_name", "site_name"],
    )

    for s in subs:
        if not s.contact_email:
            continue

        days_left = 0
        if s.status == "Trial" and s.trial_end:
            days_left = max(0, date_diff(s.trial_end, today_date))
        elif s.status == "Active" and s.subscription_end:
            days_left = max(0, date_diff(s.subscription_end, today_date))
        elif s.status == "Grace Period" and s.grace_end:
            days_left = max(0, date_diff(s.grace_end, today_date))

        if days_left in reminder_day_list:
            sub_doc = frappe._dict(s)
            _send_reminder_email(sub_doc, days_left, settings)

    frappe.db.commit()


def _send_reminder_email(sub, days_left, settings):
    """Send a renewal reminder email to a subscription holder."""
    try:
        sender = (settings.sender_email or "").strip() or None
        app_name = settings.app_name or "CoreLogics"
        contact_email = settings.contact_email or ""
        contact_phone = settings.contact_phone or ""
        monthly_fee = settings.monthly_fee or 0
        bank_details = settings.bank_details or ""
        site_url = f"https://{sub.site_name}" if sub.site_name else ""

        if days_left == 0:
            urgency = "EXPIRED — Immediate Action Required"
            color = "#EF4444"
            msg_line = "Your subscription has expired. Your access may be blocked immediately."
        elif days_left <= 3:
            urgency = f"URGENT — Only {days_left} Day(s) Left"
            color = "#F59E0B"
            msg_line = f"Your subscription expires in <strong>{days_left} day(s)</strong>. Please renew immediately to avoid interruption."
        else:
            urgency = f"Reminder — {days_left} Days Until Expiry"
            color = "#2563EB"
            msg_line = f"Your subscription will expire in <strong>{days_left} day(s)</strong>. Please renew to continue uninterrupted access."

        subject = f"{app_name} Subscription — {urgency}"
        body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#1E293B">
  <h2 style="color:{color}">{app_name} — {urgency}</h2>
  <p>Dear <strong>{sub.physician_name}</strong>,</p>
  <p>{msg_line}</p>
  <table style="width:100%;border-collapse:collapse;margin:1.5rem 0">
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem;font-weight:700;color:#1E40AF;width:40%">Clinic</td>
      <td style="padding:.75rem">{sub.clinic_name}</td>
    </tr>
    <tr style="background:#F8FAFC">
      <td style="padding:.75rem;font-weight:700">Site</td>
      <td style="padding:.75rem"><a href="{site_url}">{site_url}</a></td>
    </tr>
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem;font-weight:700;color:#1E40AF">Renewal Fee</td>
      <td style="padding:.75rem">PKR {int(monthly_fee)} / month</td>
    </tr>
  </table>
  <h3>How to Renew:</h3>
  <ol>
    <li>Transfer the renewal amount to our bank account</li>
    <li>Take a screenshot of your payment confirmation</li>
    <li>Submit your payment proof at your subscription portal</li>
    <li>We will activate your subscription within a few hours</li>
  </ol>
  {f'<pre style="background:#F1F5F9;padding:1rem;border-radius:8px">{bank_details}</pre>' if bank_details else ''}
  <p>Need help? Contact us:</p>
  <ul>
    {f'<li>Email: <a href="mailto:{contact_email}">{contact_email}</a></li>' if contact_email else ''}
    {f'<li>Phone/WhatsApp: {contact_phone}</li>' if contact_phone else ''}
  </ul>
  <hr style="border:none;border-top:1px solid #E2E8F0;margin:2rem 0">
  <p style="color:#94A3B8;font-size:.8rem">{app_name} — Professional Clinic Management</p>
</div>""".strip()

        frappe.sendmail(
            recipients=[sub.contact_email],
            sender=sender,
            subject=subject,
            message=body,
            now=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Reminder email failed for {sub.get('name')}")


def auto_suspend_expired_sites():
    """Daily scheduler: suspend expired sites if auto-suspend is configured."""
    try:
        settings = frappe.get_single("PW Subscription Settings")
        auto_trial = settings.auto_suspend_on_trial_expiry
        auto_sub = settings.auto_suspend_on_subscription_expiry
        mode = settings.suspension_mode or "Soft Block"
    except Exception:
        return

    if not auto_trial and not auto_sub:
        return

    expired = frappe.get_all(
        "PW Subscription",
        filters={"status": "Expired", "is_suspended": 0},
        fields=["name", "site_name"],
    )

    for s in expired:
        try:
            if s.site_name:
                from pw_subscription.site_provisioning import _do_suspend_site
                _do_suspend_site(s.site_name)
            frappe.db.set_value("PW Subscription", s.name, {
                "is_suspended": 1,
                "suspended_on": now(),
                "suspension_reason": "Auto-suspended: expired subscription",
            }, update_modified=False)
            frappe.get_doc({
                "doctype": "PW Subscription Log",
                "subscription": s.name,
                "action": "Cancelled",
                "action_date": now(),
                "action_by": "Administrator",
                "notes": f"Auto-suspended ({mode}): subscription expired.",
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(str(e), f"Auto-suspend failed: {s.name}")

    frappe.db.commit()


def add_subscription_to_boot(bootinfo):
    try:
        sub = get_current_subscription()
        if not sub:
            bootinfo.pw_subscription = {"status": "No Subscription"}
            return
        today_date = today()
        days_remaining = 0
        if sub.status == "Trial" and sub.trial_end:
            days_remaining = max(0, date_diff(sub.trial_end, today_date))
        elif sub.status == "Active" and sub.subscription_end:
            days_remaining = max(0, date_diff(sub.subscription_end, today_date))
        elif sub.status == "Grace Period" and sub.grace_end:
            days_remaining = max(0, date_diff(sub.grace_end, today_date))

        bootinfo.pw_subscription = {
            "status": sub.status,
            "days_remaining": days_remaining,
            "is_suspended": bool(sub.is_suspended),
            "trial_end": str(sub.trial_end) if sub.trial_end else None,
            "subscription_end": str(sub.subscription_end) if sub.subscription_end else None,
            "grace_end": str(sub.grace_end) if sub.grace_end else None,
        }
    except Exception:
        bootinfo.pw_subscription = {"status": "Unknown"}


def on_session_creation(login_manager):
    # Administrator is always allowed — never block the business owner
    if getattr(login_manager, "user", None) == "Administrator":
        return
    try:
        settings = frappe.get_single("PW Subscription Settings")
        if not settings.enforce_subscription:
            return
        sub = get_current_subscription()
        if sub and sub.status == "Expired":
            frappe.throw(
                "Your subscription has expired. Please contact support to renew your plan.",
                frappe.AuthenticationError,
            )
        if sub and sub.is_suspended:
            frappe.throw(
                "Your site has been suspended. Please contact support.",
                frappe.AuthenticationError,
            )
    except frappe.AuthenticationError:
        raise
    except Exception:
        pass
