import frappe
from frappe.utils import today, date_diff


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/subscription-portal"
        raise frappe.Redirect

    context.no_cache = 1
    context.title = "My Subscription"

    try:
        settings = frappe.get_single("PW Subscription Settings")
        context.bank_details = settings.bank_details or ""
        context.contact_email = settings.contact_email or ""
        context.contact_phone = settings.contact_phone or ""
        context.monthly_fee = settings.monthly_fee or 0
        context.app_name = settings.app_name or "CureDesk"
    except Exception:
        context.bank_details = ""
        context.contact_email = ""
        context.contact_phone = ""
        context.monthly_fee = 0
        context.app_name = "CureDesk"

    try:
        subs = frappe.get_all(
            "PW Subscription",
            fields=["name", "status", "trial_start", "trial_end",
                    "subscription_start", "subscription_end", "grace_end", "site_name"],
            order_by="creation desc",
            limit=1
        )
        if subs:
            sub = subs[0]
            context.subscription = sub
            context.status = sub.status
            today_date = today()
            if sub.status == "Trial" and sub.trial_end:
                context.days_remaining = max(0, date_diff(sub.trial_end, today_date))
                context.end_date = sub.trial_end
            elif sub.status == "Active" and sub.subscription_end:
                context.days_remaining = max(0, date_diff(sub.subscription_end, today_date))
                context.end_date = sub.subscription_end
            elif sub.status == "Grace Period" and sub.grace_end:
                context.days_remaining = max(0, date_diff(sub.grace_end, today_date))
                context.end_date = sub.grace_end
            else:
                context.days_remaining = 0
                context.end_date = None

            context.logs = frappe.get_all(
                "PW Subscription Log",
                filters={"subscription": sub.name},
                fields=["action", "action_date", "notes"],
                order_by="action_date desc",
                limit=10
            )
        else:
            context.subscription = None
            context.status = "No Subscription"
            context.days_remaining = 0
            context.end_date = None
            context.logs = []
    except Exception:
        context.subscription = None
        context.status = "Unknown"
        context.days_remaining = 0
        context.end_date = None
        context.logs = []

    return context
