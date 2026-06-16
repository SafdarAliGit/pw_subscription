import frappe
from frappe.model.document import Document


class SiteProvisioningRequest(Document):
    def validate(self):
        if not self.site_name:
            frappe.throw("Site Name is required.")
        if not self.clinic_name:
            frappe.throw("Clinic Name is required.")

    def before_insert(self):
        self.status = "Pending"
        self.attempt_count = 0
