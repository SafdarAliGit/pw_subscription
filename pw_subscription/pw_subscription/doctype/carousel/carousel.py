import frappe
from frappe.model.document import Document


class Carousel(Document):
    def validate(self):
        existing = frappe.db.get_value(
            "Carousel",
            {"portal_page": self.portal_page, "name": ("!=", self.name)},
            "name",
        )
        if existing:
            frappe.throw(
                f"A Carousel for <strong>{self.portal_page}</strong> already exists: {existing}. "
                "Only one carousel is allowed per portal page."
            )
