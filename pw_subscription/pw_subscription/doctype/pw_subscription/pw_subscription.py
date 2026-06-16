import re

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import today, add_days, now


class PWSubscription(Document):
    def autoname(self):
        if self.clinic_name:
            base = re.sub(r"[^a-z0-9]+", "-", self.clinic_name.strip().lower()).strip("-")
            count = frappe.db.count("PW Subscription", {"name": ["like", f"{base}-%"]})
            self.name = f"{base}-{str(count + 1).zfill(5)}"
        else:
            self.name = make_autoname("SUB-.YYYY.-.#####", "PW Subscription")

    def before_save(self):
        if not self.site_name and frappe.session.user not in ("Guest",):
            self.site_name = frappe.local.site
        if self.status == "Active" and not self.subscription_start:
            self.subscription_start = today()
        if self.status == "Grace Period" and not self.grace_end:
            try:
                settings = frappe.get_single("PW Subscription Settings")
                grace_days = settings.grace_period_days or 3
            except Exception:
                grace_days = 3
            if self.subscription_end:
                self.grace_end = add_days(self.subscription_end, grace_days)
