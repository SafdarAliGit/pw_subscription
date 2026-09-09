
import frappe
from frappe.utils import today, date_diff


def get_context(context):
    context.no_cache = 1
    context.title = ""

    user = frappe.session.user or "Guest"
    context.is_guest = (user == "Guest")
    context.session_user = "" if context.is_guest else user

    try:
        settings = frappe.get_single("PW Subscription Settings")
        context.company_logo = settings.company_logo or ""
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
        from pw_subscription.www.healthcare import get_plans_for_page
        context.plan_features, context.subscription_plans = get_plans_for_page("Subscription Portal")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "subscription-portal get_context")
        context.company_logo = ""
        context.app_name = "CoreLogics"
        context.bank_details = ""
        context.contact_email = ""
        context.contact_phone = ""
        context.monthly_fee = 0
        context.enable_site_ping = False
        context.ping_timeout = 5
        context.base_domain = ""
        context.trial_days         = 7
        context.plan_features      = []
        context.subscription_plans = []

    return context
