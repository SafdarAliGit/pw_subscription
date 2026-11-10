import frappe
from frappe.utils import add_days, today


def after_install():
    frappe.clear_cache()
    create_settings()
    create_initial_subscription()
    frappe.db.commit()
    print("[✓] PW Subscription installed successfully.")


def create_settings():
    try:
        doc = frappe.get_single("PW Subscription Settings")
        if not doc.app_name:
            doc.app_name = "CoreLogics"
            doc.tagline = "The smartest prescription writing platform for modern clinics"
            doc.monthly_fee = 2000
            doc.trial_days = 7
            doc.grace_period_days = 3
            doc.contact_email = "safdar211@gmail.com"
            doc.contact_phone = "+92-XXX-XXXXXXX"
            doc.bank_details = (
                "Bank: [Your Bank Name]\n"
                "Account Title: [Your Name]\n"
                "Account No: [XXXXXXXXXX]\n"
                "IBAN: PK00XXXX0000000000000000\n"
                "Branch: [Branch Name]"
            )
            doc.enforce_subscription = 1
            doc.save(ignore_permissions=True)
        print("  [✓] Subscription settings created")
    except Exception as e:
        print(f"  [!] Could not create settings: {e}")


def create_initial_subscription():
    try:
        if frappe.db.count("PW Subscription") == 0:
            settings = frappe.get_single("PW Subscription Settings")
            trial_days = settings.trial_days or 7
            doc = frappe.get_doc({
                "doctype": "PW Subscription",
                "site_name": frappe.local.site,
                "status": "Trial",
                "trial_start": today(),
                "trial_end": add_days(today(), trial_days),
            })
            doc.insert(ignore_permissions=True)
            frappe.get_doc({
                "doctype": "PW Subscription Log",
                "subscription": doc.name,
                "action": "Trial Started",
                "action_date": frappe.utils.now(),
                "action_by": "Administrator",
                "notes": f"Trial started for {frappe.local.site}. Ends on {doc.trial_end}."
            }).insert(ignore_permissions=True)
        print("  [✓] Initial subscription created")
    except Exception as e:
        print(f"  [!] Could not create initial subscription: {e}")
