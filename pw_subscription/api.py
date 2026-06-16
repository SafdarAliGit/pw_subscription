import frappe
from frappe.utils import today, add_days, now
from pw_subscription.subscription_check import get_current_subscription


@frappe.whitelist(allow_guest=False)
def get_status():
    sub = get_current_subscription()
    try:
        settings = frappe.get_single("PW Subscription Settings")
        bank_details = settings.bank_details
        contact_email = settings.contact_email
        contact_phone = settings.contact_phone
        monthly_fee = settings.monthly_fee
        app_name = settings.app_name
    except Exception:
        bank_details = contact_email = contact_phone = app_name = ""
        monthly_fee = 0

    if not sub:
        return {
            "status": "No Subscription",
            "site": frappe.local.site,
            "bank_details": bank_details,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "monthly_fee": monthly_fee,
            "app_name": app_name,
        }

    from frappe.utils import date_diff
    today_date = today()
    days_remaining = 0
    if sub.status == "Trial" and sub.trial_end:
        days_remaining = max(0, date_diff(sub.trial_end, today_date))
    elif sub.status == "Active" and sub.subscription_end:
        days_remaining = max(0, date_diff(sub.subscription_end, today_date))
    elif sub.status == "Grace Period" and sub.grace_end:
        days_remaining = max(0, date_diff(sub.grace_end, today_date))

    logs = frappe.get_all(
        "PW Subscription Log",
        filters={"subscription": sub.name},
        fields=["action", "action_date", "action_by", "notes"],
        order_by="action_date desc",
        limit=10
    )

    return {
        "status": sub.status,
        "site": frappe.local.site,
        "days_remaining": days_remaining,
        "trial_start": str(sub.trial_start) if sub.trial_start else None,
        "trial_end": str(sub.trial_end) if sub.trial_end else None,
        "subscription_start": str(sub.subscription_start) if sub.subscription_start else None,
        "subscription_end": str(sub.subscription_end) if sub.subscription_end else None,
        "grace_end": str(sub.grace_end) if sub.grace_end else None,
        "bank_details": bank_details,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "monthly_fee": monthly_fee,
        "app_name": app_name,
        "logs": logs,
    }


@frappe.whitelist()
def activate_subscription(end_date, payment_reference=None, notes=None):
    frappe.only_for("System Manager")
    sub = get_current_subscription()
    if not sub:
        frappe.throw("No subscription record found.")
    old_status = sub.status
    sub.status = "Active"
    sub.subscription_start = today()
    sub.subscription_end = end_date
    sub.grace_end = None
    if payment_reference:
        sub.payment_reference = payment_reference
    sub.activated_by = frappe.session.user
    sub.activation_date = now()
    if notes:
        sub.notes = notes
    sub.save(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "PW Subscription Log",
        "subscription": sub.name,
        "action": "Activated",
        "action_date": now(),
        "action_by": frappe.session.user,
        "notes": f"Activated from {old_status}. Ref: {payment_reference or 'N/A'}"
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Subscription activated successfully", "end_date": end_date}


@frappe.whitelist()
def extend_trial(extra_days=7):
    frappe.only_for("System Manager")
    sub = get_current_subscription()
    if not sub:
        frappe.throw("No subscription found.")
    new_end = add_days(today(), int(extra_days))
    old_end = sub.trial_end
    sub.trial_end = new_end
    if sub.status in ["Expired", "Grace Period"]:
        sub.status = "Trial"
        sub.grace_end = None
    sub.save(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "PW Subscription Log",
        "subscription": sub.name,
        "action": "Extended",
        "action_date": now(),
        "action_by": frappe.session.user,
        "notes": f"Trial extended from {old_end} to {new_end}"
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "new_end": str(new_end)}


@frappe.whitelist(allow_guest=True)
def check_clinic_name(clinic_name):
    import re
    clinic_name = (clinic_name or "").strip()
    if not clinic_name:
        return {"available": False, "message": "Clinic name is required"}
    if len(clinic_name) < 3:
        return {"available": False, "message": "Name must be at least 3 characters"}

    exists = frappe.db.exists("PW Subscription", {"clinic_name": clinic_name})
    if exists:
        suggestions = []
        for suffix in ("Clinic", "Medical", "Health Center", "2"):
            alt = f"{clinic_name} {suffix}"
            if not frappe.db.exists("PW Subscription", {"clinic_name": alt}):
                suggestions.append(alt)
            if len(suggestions) == 2:
                break
        return {"available": False, "message": "This clinic name is already registered.", "suggestions": suggestions}

    base = re.sub(r"[^a-z0-9]+", "-", clinic_name.lower()).strip("-")
    count = frappe.db.count("PW Subscription", {"name": ["like", f"{base}-%"]})
    doc_name = f"{base}-{str(count + 1).zfill(5)}"
    return {"available": True, "name": doc_name}


@frappe.whitelist(allow_guest=True)
def register_clinic(clinic_name, email, physician_name, password, contact, address):
    import re as _re
    clinic_name    = (clinic_name or "").strip()
    email          = (email or "").strip()
    physician_name = (physician_name or "").strip()
    contact        = (contact or "").strip()
    address        = (address or "").strip()

    missing = [f for f, v in [
        ("Clinic Name", clinic_name), ("Email", email),
        ("Physician Name", physician_name), ("Password", password),
        ("Contact", contact), ("Address", address)
    ] if not v]
    if missing:
        frappe.throw(f"Missing required fields: {', '.join(missing)}")

    if not _re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        frappe.throw("Invalid email address.")
    if len(password) < 8:
        frappe.throw("Password must be at least 8 characters.")

    if frappe.db.exists("PW Subscription", {"clinic_name": clinic_name}):
        frappe.throw("This clinic name is already registered. Please choose a different name.")

    try:
        settings   = frappe.get_single("PW Subscription Settings")
        trial_days = settings.trial_days or 7
        base_domain = (settings.base_domain or "").strip()
    except Exception:
        trial_days  = 7
        base_domain = ""

    if not base_domain:
        frappe.throw("Base Domain is not configured in PW Subscription Settings. Please contact the administrator.")

    # Derive subdomain: lowercase, replace non-alphanumeric runs with hyphens
    subdomain = _re.sub(r"[^a-z0-9]+", "-", clinic_name.lower()).strip("-")
    site_name = f"{subdomain}.{base_domain}"

    if frappe.db.exists("Site Provisioning Request", {"site_name": site_name}):
        frappe.throw(
            "A provisioning request for this clinic already exists. "
            "Please contact support if you need assistance."
        )

    # Create subscription record
    sub_doc = frappe.get_doc({
        "doctype": "PW Subscription",
        "clinic_name": clinic_name,
        "physician_name": physician_name,
        "contact_email": email,
        "contact_phone": contact,
        "address": address,
        "initial_password": password,
        "site_name": site_name,
        "status": "Trial",
        "trial_start": today(),
        "trial_end": add_days(today(), trial_days),
    })
    sub_doc.insert(ignore_permissions=True)

    # Create provisioning request
    prov_doc = frappe.get_doc({
        "doctype": "Site Provisioning Request",
        "clinic_name": clinic_name,
        "physician_name": physician_name,
        "contact_email": email,
        "contact_phone": contact,
        "site_name": site_name,
        "subscription": sub_doc.name,
        "status": "Pending",
    })
    prov_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    # Enqueue background provisioning job
    from pw_subscription.site_provisioning import _enqueue_provision
    _enqueue_provision(prov_doc.name)

    return {
        "success": True,
        "name": sub_doc.name,
        "clinic_name": clinic_name,
        "trial_end": str(sub_doc.trial_end),
        "request_name": prov_doc.name,
        "site_name": site_name,
    }


@frappe.whitelist(allow_guest=True)
def get_public_info():
    try:
        settings = frappe.get_single("PW Subscription Settings")
        return {
            "app_name": settings.app_name or "CureDesk",
            "tagline": settings.tagline or "The smartest prescription writing platform",
            "monthly_fee": settings.monthly_fee or 0,
            "trial_days": settings.trial_days or 7,
            "contact_email": settings.contact_email or "",
            "contact_phone": settings.contact_phone or "",
        }
    except Exception:
        return {
            "app_name": "CureDesk",
            "tagline": "The smartest prescription writing platform",
            "monthly_fee": 0,
            "trial_days": 7,
            "contact_email": "",
            "contact_phone": "",
        }
