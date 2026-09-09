import os
import shutil

import frappe
from frappe.utils import get_url


def _public_image_url(file_path):
    if not file_path:
        return None
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    try:
        filename = os.path.basename(file_path)
        private_path = frappe.get_site_path("private", "files", filename)
        public_path = frappe.get_site_path("public", "files", filename)
        if file_path.startswith("/private/"):
            public_url = "/files/" + filename
            frappe.db.set_value("File", {"file_url": file_path}, "is_private", 0)
            frappe.db.set_value("File", {"file_url": file_path}, "file_url", public_url)
            frappe.db.commit()
            file_path = public_url
        if not os.path.exists(public_path) and os.path.exists(private_path):
            shutil.copy2(private_path, public_path)
    except Exception:
        pass
    return get_url(file_path)


def get_plans_for_page(portal_page):
    """Return (plan_features_list, subscription_plans_list) for the given portal page."""
    plans_name = frappe.db.get_value("Plans", {"portal_page": portal_page}, "name")
    if not plans_name:
        return [], []

    plans_doc = frappe.get_doc("Plans", plans_name)
    raw_features = (plans_doc.plan_features or "")
    global_features = [f.strip() for f in raw_features.splitlines() if f.strip()]

    plans = []
    for p in (plans_doc.subscription_plans or []):
        if not getattr(p, "is_active", 1):
            continue
        months = p.duration_months or 1
        label = getattr(p, "plan_label", "") or f"{months} Month{'s' if months > 1 else ''}"
        raw_plan_features = getattr(p, "plan_features", "") or ""
        per_plan_features = [f.strip() for f in raw_plan_features.splitlines() if f.strip()]
        plans.append({
            "plan_label":      label,
            "duration_months": months,
            "price":           p.price or 0,
            "badge":           getattr(p, "badge", "") or "",
            "savings_pct":     getattr(p, "savings_pct", 0) or 0,
            "monthly_equiv":   getattr(p, "monthly_equiv", "") or "",
            "plan_features":   per_plan_features if per_plan_features else global_features,
        })

    return global_features, plans


def get_context(context):
    context.no_cache = 1
    context.title = ""

    try:
        s = frappe.get_single("PW Subscription Settings")
        context.company_logo   = s.company_logo or ""
        context.company_name   = s.company_name or "CoreLogics"
        context.app_name       = s.app_name or "CoreLogics"
        context.tagline        = s.tagline or "Business Software Built Right"
        context.founder_name   = s.founder_name or "Safdar Ali"
        context.contact_email  = s.contact_email or ""
        context.contact_phone  = s.contact_phone or ""
        context.base_domain    = s.base_domain or ""
        context.trial_days     = s.trial_days or 7
        context.bank_details   = getattr(s, "bank_details", "") or ""
        context.allow_application_creation = bool(getattr(s, "allow_application_creation_by_website_user", 0))
        context.email_otp_enabled          = bool(getattr(s, "enable_email_otp", 0))
        context.phone_otp_enabled          = bool(getattr(s, "enable_phone_otp", 0))
    except Exception:
        context.company_logo       = ""
        context.company_name       = "CoreLogics"
        context.app_name           = "CoreLogics"
        context.tagline            = "Business Software Built Right"
        context.founder_name       = "Safdar Ali"
        context.contact_email      = ""
        context.contact_phone      = ""
        context.base_domain        = ""
        context.trial_days         = 7
        context.bank_details       = ""
        context.allow_application_creation = False
        context.email_otp_enabled          = False
        context.phone_otp_enabled          = False

    try:
        context.plan_features, context.subscription_plans = get_plans_for_page("Healthcare")
    except Exception:
        context.plan_features      = []
        context.subscription_plans = []

    try:
        carousel_name = frappe.db.get_value("Carousel", {"portal_page": "Healthcare"}, "name")
        if carousel_name:
            carousel = frappe.get_doc("Carousel", carousel_name)
            context.carousel_delay = (carousel.delay_time or 4) * 1000
            context.carousel_items = [
                {
                    "image": _public_image_url(item.image),
                    "title": item.title,
                    "subtitle": item.subtitle or "",
                }
                for item in (carousel.carousel_items or [])
                if item.image and item.title
            ]
        else:
            context.carousel_delay = 4000
            context.carousel_items = []
    except Exception:
        context.carousel_delay = 4000
        context.carousel_items = []

    return context
