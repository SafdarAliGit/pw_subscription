import os
import shutil

import frappe
from frappe.utils import get_url


def _public_image_url(file_path):
    """Return an absolute, publicly accessible URL for an uploaded image."""
    if not file_path:
        return None

    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path

    try:
        filename = os.path.basename(file_path)
        private_path = frappe.get_site_path("private", "files", filename)
        public_path = frappe.get_site_path("public", "files", filename)

        if file_path.startswith("/private/"):
            # Update DB record to point to public path
            public_url = "/files/" + filename
            frappe.db.set_value("File", {"file_url": file_path}, "is_private", 0)
            frappe.db.set_value("File", {"file_url": file_path}, "file_url", public_url)
            frappe.db.commit()
            file_path = public_url

        # Ensure the file physically exists in the public directory
        if not os.path.exists(public_path) and os.path.exists(private_path):
            shutil.copy2(private_path, public_path)
    except Exception:
        pass

    return get_url(file_path)


def get_context(context):
    context.no_cache = 1
    context.title = "CureDesk — Subscription Plans"
    try:
        settings = frappe.get_single("PW Subscription Settings")
        context.app_name = settings.app_name or "CureDesk"
        context.tagline = settings.tagline or "The smartest prescription writing platform"
        context.monthly_fee = settings.monthly_fee or 0
        context.trial_days = settings.trial_days or 7
        context.contact_email = settings.contact_email or ""
        context.contact_phone = settings.contact_phone or ""
        context.bank_details = settings.bank_details or ""
        context.grace_period = f"{settings.grace_period_days or 3} days"
    except Exception:
        context.app_name = "CureDesk"
        context.tagline = "The smartest prescription writing platform"
        context.monthly_fee = 0
        context.trial_days = 7
        context.contact_email = ""
        context.contact_phone = ""
        context.bank_details = ""
        context.grace_period = "3 days"

    try:
        carousel = frappe.get_single("Carousel")
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
    except Exception:
        context.carousel_delay = 4000
        context.carousel_items = []

    return context
