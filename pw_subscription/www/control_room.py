import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/control-room"
        raise frappe.Redirect

    if "System Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw("Access denied. System Manager role required.", frappe.PermissionError)

    context.no_cache = 1
    context.title = "Control Room"

    try:
        settings = frappe.get_single("PW Subscription Settings")
        context.app_name = settings.app_name or "CureDesk"
        context.enable_site_ping = bool(settings.enable_site_ping)
        context.ping_timeout = settings.ping_timeout or 5
        context.phone_otp_enabled = bool(settings.get("enable_phone_otp"))
        context.email_otp_enabled = bool(settings.get("enable_email_otp"))
    except Exception:
        context.app_name = "CureDesk"
        context.enable_site_ping = True
        context.ping_timeout = 5
        context.phone_otp_enabled = False
        context.email_otp_enabled = False

    return context
