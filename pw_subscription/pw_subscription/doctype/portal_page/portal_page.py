import os

import frappe
from frappe.model.document import Document


class PortalPage(Document):
    pass


@frappe.whitelist()
def sync_pages_from_www():
    """Scan every app's www/ folder for .html files and create missing Portal Page records."""
    created = 0
    skipped = 0

    for app in frappe.get_installed_apps():
        www_path = frappe.get_app_path(app, "www")
        if not os.path.isdir(www_path):
            continue

        for root, _dirs, files in os.walk(www_path):
            for fname in files:
                if not fname.endswith(".html"):
                    continue

                rel = os.path.relpath(os.path.join(root, fname), www_path)
                # derive route and name from file path
                route_part = rel[:-5]                          # strip .html
                route = "/" + route_part.replace(os.sep, "/")

                # prettify: subscription-portal → Subscription Portal
                raw_name = os.path.basename(route_part)
                page_name = raw_name.replace("-", " ").replace("_", " ").title()

                if frappe.db.exists("Portal Page", page_name):
                    skipped += 1
                    continue

                frappe.get_doc({
                    "doctype": "Portal Page",
                    "page_name": page_name,
                    "route": route,
                }).insert(ignore_permissions=True)
                created += 1

    frappe.db.commit()
    return {"created": created, "skipped": skipped}
