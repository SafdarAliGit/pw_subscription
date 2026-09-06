import frappe
from frappe.utils import today, date_diff


def get_context(context):
    context.no_cache = 1
    context.title = "My Subscription"

    user = frappe.session.user or "Guest"
    context.is_guest = (user == "Guest")
    context.session_user = "" if context.is_guest else user

    try:
        settings = frappe.get_single("PW Subscription Settings")
        context.app_name = settings.app_name or "CoreLogics"
        context.bank_details = settings.bank_details or ""
        context.contact_email = settings.contact_email or ""
        context.contact_phone = settings.contact_phone or ""
        context.monthly_fee = settings.monthly_fee or 0
        context.enable_site_ping = bool(settings.enable_site_ping)
        context.ping_timeout = settings.ping_timeout or 5
        context.base_domain = settings.base_domain or ""
        context.phone_otp_enabled = bool(settings.get("enable_phone_otp"))
        context.email_otp_enabled = bool(settings.get("enable_email_otp"))
        context.trial_days = settings.trial_days or 7
        # Build plans list
        context.subscription_plans = []
        for p in (settings.subscription_plans or []):
            if p.is_active:
                context.subscription_plans.append({
                    "plan_label": p.plan_label,
                    "duration_months": p.duration_months,
                    "price": p.price,
                })
        # Compute per-month rate and savings vs monthly plan
        monthly_base = next(
            (p["price"] for p in context.subscription_plans if p["duration_months"] == 1), 0
        )
        best_savings = 0
        for plan in context.subscription_plans:
            plan["monthly_equiv"] = int(plan["price"] / plan["duration_months"]) if plan["duration_months"] else 0
            if monthly_base > 0 and plan["duration_months"] > 1:
                full_cost = monthly_base * plan["duration_months"]
                plan["savings_pct"] = int((full_cost - plan["price"]) / full_cost * 100) if full_cost > 0 else 0
            else:
                plan["savings_pct"] = 0
            if plan["savings_pct"] > best_savings:
                best_savings = plan["savings_pct"]
        for plan in context.subscription_plans:
            if best_savings > 0 and plan["savings_pct"] == best_savings:
                plan["badge"] = "best"
            elif plan["duration_months"] == 3:
                plan["badge"] = "popular"
            else:
                plan["badge"] = ""
    except Exception:
        frappe.log_error(frappe.get_traceback(), "subscription-portal get_context")
        context.app_name = "CoreLogics"
        context.bank_details = ""
        context.contact_email = ""
        context.contact_phone = ""
        context.monthly_fee = 0
        context.enable_site_ping = False
        context.ping_timeout = 5
        context.base_domain = ""
        context.phone_otp_enabled = False
        context.email_otp_enabled = False
        context.trial_days = 7
        context.subscription_plans = []

    # Guest: no subscription pre-loaded — portal uses JS email lookup
    context.subscription = None
    context.status = None
    context.days_remaining = 0
    context.end_date = None
    context.logs = []
    context.payment_proofs = []

    return context
