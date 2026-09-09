import frappe
from frappe.model.document import Document


class Plans(Document):
    def validate(self):
        existing = frappe.db.get_value(
            "Plans",
            {"portal_page": self.portal_page, "name": ("!=", self.name)},
            "name",
        )
        if existing:
            frappe.throw(
                f"A Plans record for <strong>{self.portal_page}</strong> already exists: {existing}. "
                "Only one Plans record is allowed per portal page."
            )
