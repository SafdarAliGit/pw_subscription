import frappe
from frappe.utils import today, add_days, date_diff


def get_current_subscription():
    try:
        subs = frappe.get_all(
            "PW Subscription",
            fields=["name", "status", "trial_start", "trial_end",
                    "subscription_start", "subscription_end", "grace_end", "site_name"],
            order_by="creation desc",
            limit=1
        )
        return frappe.get_doc("PW Subscription", subs[0].name) if subs else None
    except Exception:
        return None


def update_subscription_statuses():
    today_date = today()
    subs = frappe.get_all(
        "PW Subscription",
        filters={"status": ["in", ["Trial", "Active", "Grace Period"]]},
        fields=["name", "status", "trial_end", "subscription_end", "grace_end"]
    )
    try:
        settings = frappe.get_single("PW Subscription Settings")
        grace_days = settings.grace_period_days or 3
    except Exception:
        grace_days = 3

    for s in subs:
        new_status = None
        grace_end_date = None

        if s.status == "Trial" and s.trial_end and str(s.trial_end) < today_date:
            new_status = "Expired"
        elif s.status == "Active" and s.subscription_end and str(s.subscription_end) < today_date:
            new_status = "Grace Period"
            grace_end_date = add_days(s.subscription_end, grace_days)
        elif s.status == "Grace Period" and s.grace_end and str(s.grace_end) < today_date:
            new_status = "Expired"

        if new_status:
            doc = frappe.get_doc("PW Subscription", s.name)
            old_status = doc.status
            doc.status = new_status
            if grace_end_date:
                doc.grace_end = grace_end_date
            doc.save(ignore_permissions=True)
            frappe.get_doc({
                "doctype": "PW Subscription Log",
                "subscription": s.name,
                "action": new_status,
                "action_date": frappe.utils.now(),
                "action_by": "Administrator",
                "notes": f"Auto-updated from {old_status} to {new_status} by scheduler."
            }).insert(ignore_permissions=True)

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
            "trial_end": str(sub.trial_end) if sub.trial_end else None,
            "subscription_end": str(sub.subscription_end) if sub.subscription_end else None,
            "grace_end": str(sub.grace_end) if sub.grace_end else None,
        }
    except Exception:
        bootinfo.pw_subscription = {"status": "Unknown"}


def on_session_creation(login_manager):
    try:
        settings = frappe.get_single("PW Subscription Settings")
        if not settings.enforce_subscription:
            return
        sub = get_current_subscription()
        if sub and sub.status == "Expired":
            frappe.throw(
                "Your subscription has expired. Please contact support to renew your plan.",
                frappe.AuthenticationError
            )
    except frappe.AuthenticationError:
        raise
    except Exception:
        pass
