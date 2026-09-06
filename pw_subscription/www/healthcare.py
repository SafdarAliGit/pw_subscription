import frappe


def get_context(context):
    context.no_cache = 1
    context.title = ""

    try:
        s = frappe.get_single("PW Subscription Settings")
        context.company_name   = s.company_name or "CoreLogics"
        context.app_name       = s.app_name or "CoreLogics"
        context.tagline        = s.tagline or "Business Software Built Right"
        context.founder_name   = s.founder_name or "Safdar Ali"
        context.contact_email  = s.contact_email or ""
        context.contact_phone  = s.contact_phone or ""
        context.base_domain    = s.base_domain or ""
        context.trial_days     = s.trial_days or 7
    except Exception:
        context.company_name  = "CoreLogics"
        context.app_name      = "CoreLogics"
        context.tagline       = "Business Software Built Right"
        context.founder_name  = "Safdar Ali"
        context.contact_email = ""
        context.contact_phone = ""
        context.base_domain   = ""
        context.trial_days    = 7

    return context
