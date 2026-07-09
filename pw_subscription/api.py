import frappe
from frappe.utils import today, add_days, add_months, now, date_diff, now_datetime


# ── helpers ──────────────────────────────────────────────────────────────────

def has_app_permission():
    """Return True if the current user may see PW Subscription on the apps screen."""
    if frappe.session.user == "Guest":
        return False
    return bool(set(frappe.get_roles(frappe.session.user)) & {"System Manager", "PW Admin"})


def _get_settings():
    return frappe.get_single("PW Subscription Settings")


def _require_portal_access():
    """Allow System Manager or PW Admin; throw for everyone else."""
    if frappe.session.user == "Guest":
        frappe.throw("Please log in.", frappe.AuthenticationError)
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles & {"System Manager", "PW Admin"}:
        frappe.throw("Not permitted.", frappe.PermissionError)


def _ensure_website_user(email, full_name, password):
    """Create (or update) a Website User on the master site for portal login."""
    from frappe.utils.password import update_password as _upd
    name_parts = (full_name or "").strip().split(None, 1)
    first_name = name_parts[0] if name_parts else "Doctor"
    last_name  = name_parts[1] if len(name_parts) > 1 else ""

    if not frappe.db.exists("User", email):
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "send_welcome_email": 0,
            "user_type": "Website User",
        })
        user_doc.flags.ignore_password_policy = True
        user_doc.insert(ignore_permissions=True)
    else:
        user_doc = frappe.get_doc("User", email)
        if user_doc.user_type != "Website User" or not user_doc.enabled:
            user_doc.user_type = "Website User"
            user_doc.enabled = 1
            user_doc.flags.ignore_password_policy = True
            user_doc.save(ignore_permissions=True)

    frappe.flags.in_import = True
    try:
        _upd(email, password)
    finally:
        frappe.flags.in_import = False
    frappe.db.commit()


def _days_remaining(sub):
    today_date = today()
    if sub.status == "Trial" and sub.trial_end:
        return max(0, date_diff(sub.trial_end, today_date))
    if sub.status == "Active" and sub.subscription_end:
        return max(0, date_diff(sub.subscription_end, today_date))
    if sub.status == "Grace Period" and sub.grace_end:
        return max(0, date_diff(sub.grace_end, today_date))
    return 0


def _log_action(subscription_name, action, notes="", actor=None):
    frappe.get_doc({
        "doctype": "PW Subscription Log",
        "subscription": subscription_name,
        "action": action,
        "action_date": now(),
        "action_by": actor or frappe.session.user,
        "notes": notes,
    }).insert(ignore_permissions=True)


def _publish_sub_changed(sub):
    try:
        frappe.publish_realtime("pw_sub_changed", {
            "name": sub.name,
            "clinic_name": sub.clinic_name,
            "status": sub.status,
            "is_suspended": bool(sub.is_suspended),
            "trial_end": str(sub.trial_end) if sub.trial_end else "",
            "subscription_end": str(sub.subscription_end) if sub.subscription_end else "",
            "grace_end": str(sub.grace_end) if sub.grace_end else "",
            "days_remaining": _days_remaining(sub),
        })
    except Exception:
        pass


def _publish_proof_done(proof):
    try:
        frappe.publish_realtime("pw_proof_done", {
            "proof_name": proof.name,
            "subscription": proof.subscription,
            "status": proof.status,
        })
    except Exception:
        pass


# ── public read-only APIs ─────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def get_public_info():
    try:
        s = _get_settings()
        return {
            "app_name":        s.app_name or "CureDesk",
            "tagline":         s.tagline or "",
            "monthly_fee":     s.monthly_fee or 0,
            "trial_days":      s.trial_days or 7,
            "contact_email":   s.contact_email or "",
            "contact_phone":   s.contact_phone or "",
            "phone_otp_enabled": bool(s.get("enable_phone_otp")),
        }
    except Exception:
        return {"app_name": "CureDesk", "tagline": "", "monthly_fee": 0,
                "trial_days": 7, "contact_email": "", "contact_phone": "",
                "phone_otp_enabled": False}


@frappe.whitelist(allow_guest=True)
def get_subscription_plans():
    """Return all active subscription plans for the portal plan selector."""
    try:
        s = _get_settings()
        plans = []
        for p in (s.subscription_plans or []):
            if p.is_active:
                plans.append({
                    "plan_label": p.plan_label,
                    "duration_months": p.duration_months,
                    "price": p.price,
                })
        return {"plans": plans, "monthly_fee": s.monthly_fee or 0}
    except Exception:
        return {"plans": [], "monthly_fee": 0}


@frappe.whitelist(allow_guest=True)
def get_subscription_by_email(email):
    """Find a subscription by contact email — used by the customer portal."""
    if not email:
        frappe.throw("Email is required.")
    email = (email or "").strip().lower()
    subs = frappe.get_all(
        "PW Subscription",
        filters={"contact_email": email},
        fields=["name", "clinic_name", "physician_name", "site_name", "status",
                "trial_start", "trial_end", "subscription_start", "subscription_end",
                "grace_end", "is_suspended", "payment_reference"],
        order_by="creation desc",
        limit=1,
    )
    if not subs:
        frappe.throw("No subscription found for this email address.")
    sub = subs[0]
    days = _days_remaining(frappe._dict(sub))
    return {"subscription": sub, "days_remaining": days}


@frappe.whitelist(allow_guest=True)
def get_payment_history_by_email(email):
    """Return payment proof history for a customer by email."""
    if not email:
        frappe.throw("Email is required.")
    email = (email or "").strip().lower()
    subs = frappe.get_all("PW Subscription", filters={"contact_email": email},
                          fields=["name"], limit=1)
    if not subs:
        return {"proofs": []}
    proofs = frappe.get_all(
        "Payment Proof",
        filters={"subscription": subs[0].name},
        fields=["name", "selected_plan", "duration_months", "amount_paid",
                "status", "submitted_on", "admin_notes"],
        order_by="submitted_on desc",
        limit=20,
    )
    return {"proofs": proofs}


@frappe.whitelist(allow_guest=True)
def get_subscription_logs_by_email(email):
    """Return recent activity log for a subscription, looked up by customer email."""
    if not email:
        return {"logs": []}
    email = (email or "").strip().lower()
    subs = frappe.get_all("PW Subscription", filters={"contact_email": email},
                          fields=["name"], limit=1)
    if not subs:
        return {"logs": []}
    logs = frappe.get_all(
        "PW Subscription Log",
        filters={"subscription": subs[0].name},
        fields=["action", "action_date", "notes"],
        order_by="action_date desc",
        limit=10,
    )
    return {"logs": logs}


@frappe.whitelist()
def get_my_subscription():
    """Return subscription for the currently logged-in portal user."""
    email = (frappe.session.user or "").lower()
    if not email or email == "guest":
        frappe.throw("Not authenticated.", frappe.AuthenticationError)
    subs = frappe.get_all(
        "PW Subscription",
        filters={"contact_email": email},
        fields=["name", "clinic_name", "physician_name", "site_name", "status",
                "trial_start", "trial_end", "subscription_start", "subscription_end",
                "grace_end", "is_suspended", "payment_reference"],
        order_by="creation desc",
        limit=1,
        ignore_permissions=True,
    )
    if not subs:
        frappe.throw("No subscription found for your account.")
    sub = subs[0]
    days = _days_remaining(frappe._dict(sub))
    return {"subscription": sub, "days_remaining": days, "email": email}


@frappe.whitelist(allow_guest=True)
def submit_payment_proof(email, subscription_name, plan_label, duration_months,
                         amount_paid, screenshot, notes=None):
    """Customer submits a payment proof screenshot. Validated by email."""
    email = (email or "").strip().lower()
    if not email or not subscription_name or not screenshot:
        frappe.throw("Email, subscription, and screenshot are required.")

    sub = frappe.db.get_value(
        "PW Subscription", subscription_name,
        ["name", "clinic_name", "physician_name", "contact_email", "site_name", "status"],
        as_dict=True,
    )
    if not sub:
        frappe.throw("Subscription not found.")
    if (sub.contact_email or "").strip().lower() != email:
        frappe.throw("Email does not match the subscription record.")
    if sub.status == "Cancelled":
        frappe.throw("This subscription is cancelled. Please contact support.")

    # Check for already-pending proof
    existing = frappe.db.count("Payment Proof", {
        "subscription": subscription_name, "status": "Pending"
    })
    if existing:
        frappe.throw("You already have a pending payment proof under review. "
                     "Please wait for it to be processed before submitting another.")

    proof = frappe.get_doc({
        "doctype": "Payment Proof",
        "subscription": subscription_name,
        "clinic_name": sub.clinic_name,
        "physician_name": sub.physician_name,
        "contact_email": sub.contact_email,
        "site_name": sub.site_name,
        "selected_plan": plan_label,
        "duration_months": int(duration_months or 0),
        "amount_paid": float(amount_paid or 0),
        "screenshot": screenshot,
        "notes": notes or "",
        "status": "Pending",
        "submitted_on": now(),
    })
    proof.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        frappe.publish_realtime("pw_new_proof", {
            "name": proof.name,
            "subscription": subscription_name,
            "clinic_name": sub.clinic_name,
            "physician_name": sub.physician_name or "",
            "site_name": sub.site_name or "",
            "contact_email": sub.contact_email or "",
            "selected_plan": plan_label,
            "duration_months": int(duration_months or 0),
            "amount_paid": float(amount_paid or 0),
            "screenshot": screenshot,
            "notes": notes or "",
            "submitted_on": str(proof.submitted_on),
            "status": "Pending",
        })
    except Exception:
        pass

    return {"success": True, "proof_name": proof.name,
            "message": "Payment proof submitted successfully. We will review and activate your subscription within a few hours."}


@frappe.whitelist(allow_guest=True)
def get_countries():
    """Return all countries for the registration form country picker."""
    countries = frappe.get_list(
        "Country",
        fields=["name"],
        order_by="name asc",
        limit=0,
        ignore_permissions=True,
    )
    return [c.name for c in countries]


@frappe.whitelist(allow_guest=True)
def get_cities_by_country(country):
    """Return cities for a given country, used by the registration form city picker."""
    if not country:
        return []
    cities = frappe.get_list(
        "City",
        filters={"country": country},
        fields=["city_name", "state_province"],
        order_by="city_name asc",
        limit=0,
        ignore_permissions=True,
    )
    return cities


@frappe.whitelist(allow_guest=True)
def send_email_otp(email):
    import random, re
    email = (email or "").strip().lower()
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        frappe.throw("Invalid email address.")

    s = _get_settings()
    if not s.get("enable_email_otp"):
        frappe.throw("Email OTP verification is not enabled.")

    otp = str(random.randint(100000, 999999))
    cache_key = f"email_otp_{email}"
    frappe.cache.set(cache_key, otp)
    frappe.cache.expire(cache_key, 600)  # 10-minute expiry

    app_name = s.app_name or "CureDesk"
    sender   = s.sender_email or None

    subject = f"{app_name} — Your Email Verification Code"
    body = f"""
<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:2rem;border:1px solid #e2e8f0;border-radius:12px">
  <h2 style="margin:0 0 1rem;color:#1e293b">Verify your email address</h2>
  <p style="color:#475569;margin:0 0 1.5rem">Use the code below to complete your {app_name} registration. It expires in <strong>10 minutes</strong>.</p>
  <div style="background:#f1f5f9;border-radius:8px;padding:1.5rem;text-align:center;font-size:2rem;font-weight:700;letter-spacing:.3em;color:#1d4ed8">{otp}</div>
  <p style="color:#94a3b8;font-size:.85rem;margin:1.5rem 0 0">If you did not request this, please ignore this email.</p>
</div>""".strip()

    try:
        frappe.sendmail(
            recipients=[email],
            sender=sender,
            subject=subject,
            message=body,
            now=True,
        )
    except Exception as e:
        frappe.log_error(f"Email OTP send failed for {email}: {e}", "Email OTP")
        frappe.throw("Could not send verification email. Please check the email address and try again.")

    return {"sent": True}


@frappe.whitelist(allow_guest=True)
def verify_email_otp(email, otp):
    import re
    email = (email or "").strip().lower()
    otp   = (otp or "").strip()

    s = _get_settings()
    if not s.get("enable_email_otp"):
        frappe.throw("Email OTP verification is not enabled.")

    if not otp:
        return {"valid": False, "reason": "mismatch"}

    cache_key = f"email_otp_{email}"
    stored = frappe.safe_decode(frappe.cache.get(cache_key) or b"")
    if not stored:
        return {"valid": False, "reason": "expired"}
    if stored != otp:
        return {"valid": False, "reason": "mismatch"}

    frappe.cache.delete(cache_key)
    verified_key = f"email_verified_{email}"
    frappe.cache.set(verified_key, "1")
    frappe.cache.expire(verified_key, 1800)  # 30-minute window to complete registration
    return {"valid": True}


def _msg91_settings():
    """Return (auth_key, template_id, sender_id) or raise if not configured."""
    s = _get_settings()
    if not s.get("enable_phone_otp"):
        frappe.throw("Phone OTP verification is not enabled.")
    auth_key    = s.get_password("msg91_auth_key") if s.msg91_auth_key else ""
    template_id = (s.msg91_template_id or "").strip()
    sender_id   = (s.msg91_sender_id or "OTPSMS").strip()
    if not auth_key or not template_id:
        frappe.throw("MSG91 is not fully configured. Set Auth Key and Template ID in PW Subscription Settings.")
    return auth_key, template_id, sender_id


def _normalize_phone(phone):
    """Strip formatting and ensure no leading +."""
    import re
    digits = re.sub(r"[\s\-().]", "", (phone or "").strip())
    # MSG91 requires country code without the + prefix
    return digits.lstrip("+")


@frappe.whitelist(allow_guest=True)
def send_phone_otp(phone):
    import re, requests as _req
    phone = (phone or "").strip()
    raw_digits = re.sub(r"[\s\-().]", "", phone)
    if not re.match(r"^\+?[0-9]{7,15}$", raw_digits):
        frappe.throw("Invalid phone number.")

    auth_key, template_id, sender_id = _msg91_settings()
    mobile = _normalize_phone(phone)

    try:
        resp = _req.post(
            "https://control.msg91.com/api/v5/otp",
            headers={"authkey": auth_key, "Content-Type": "application/json"},
            json={
                "mobile":      mobile,
                "template_id": template_id,
                "sender":      sender_id,
                "otp_expiry":  5,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("type") not in ("success", "10"):
            frappe.log_error(f"MSG91 send OTP failed for {mobile}: {data}", "Phone OTP")
            frappe.throw("Could not send verification code. Please check the phone number and try again.")
    except _req.exceptions.RequestException as e:
        frappe.log_error(f"MSG91 request error for {mobile}: {e}", "Phone OTP")
        frappe.throw("Could not reach SMS gateway. Please try again.")

    return {"sent": True}


@frappe.whitelist(allow_guest=True)
def verify_phone_otp(phone, otp):
    import requests as _req
    otp = (otp or "").strip()
    if not otp:
        return {"valid": False, "reason": "mismatch"}

    auth_key, _template_id, _sender_id = _msg91_settings()
    mobile = _normalize_phone(phone)

    try:
        resp = _req.post(
            "https://control.msg91.com/api/v5/otp/verify",
            headers={"authkey": auth_key, "Content-Type": "application/json"},
            json={"mobile": mobile, "otp": otp},
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        frappe.log_error(f"MSG91 verify OTP error for {mobile}: {e}", "Phone OTP")
        return {"valid": False, "reason": "error"}

    if data.get("type") == "success":
        # Store a short-lived token so register_clinic can confirm verification
        verified_key = f"phone_verified_{mobile}"
        frappe.cache.set(verified_key, "1")
        frappe.cache.expire(verified_key, 600)
        return {"valid": True}

    reason = "expired" if "expire" in str(data.get("message", "")).lower() else "mismatch"
    return {"valid": False, "reason": reason}


@frappe.whitelist(allow_guest=True)
def check_clinic_name(clinic_name):
    import re
    clinic_name = (clinic_name or "").strip()

    if not clinic_name:
        return {"available": False, "message": "Clinic name is required"}
    if len(clinic_name) < 3:
        return {"available": False, "message": "Too short — minimum 3 characters"}
    if len(clinic_name) > 63:
        return {"available": False, "message": "Too long — maximum 63 characters"}
    if re.match(r'^[0-9]', clinic_name):
        return {"available": False, "message": "Must start with a letter (a–z), not a number"}
    if clinic_name.startswith('-'):
        return {"available": False, "message": "Cannot start with a hyphen"}
    if clinic_name.endswith('-'):
        return {"available": False, "message": "Cannot end with a hyphen"}
    if '--' in clinic_name:
        return {"available": False, "message": "No consecutive hyphens allowed"}
    if not re.match(r'^[a-z][a-z0-9-]*$', clinic_name):
        return {"available": False, "message": "Only lowercase letters (a–z), numbers (0–9) and hyphens (-) allowed"}

    _reserved = {
        'www','mail','ftp','smtp','imap','pop','ns1','ns2','ns3','vpn','cdn',
        'admin','api','app','portal','support','help','dashboard','status',
        'root','localhost','dev','staging','test','demo','beta','alpha',
        'blog','shop','store','static','assets','media','images','docs',
        'git','webmail','cpanel','ssl','remote',
    }
    if clinic_name in _reserved:
        return {"available": False, "message": f'"{clinic_name}" is a reserved word — please choose another'}

    if frappe.db.exists("PW Subscription", {"clinic_name": clinic_name}):
        suggestions = []
        for suffix in ("2", "clinic", "health", "pk", "care"):
            alt = f"{clinic_name}-{suffix}"
            if not frappe.db.exists("PW Subscription", {"clinic_name": alt}) and len(alt) <= 63:
                suggestions.append(alt)
            if len(suggestions) == 2:
                break
        return {"available": False, "message": "This name is already taken.",
                "suggestions": suggestions}

    return {"available": True, "name": clinic_name}


_BLOCKED_STATUSES = {"Trial", "Active", "Expired", "Suspended"}

@frappe.whitelist(allow_guest=True)
def check_email(email):
    email = (email or "").strip().lower()
    import re
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return {"available": False, "message": "Invalid email address."}
    existing = frappe.db.get_value(
        "PW Subscription", {"contact_email": email},
        ["status"], order_by="creation desc", as_dict=True
    )
    if existing and existing.status in _BLOCKED_STATUSES:
        return {"available": False, "message": "This email is already registered. Please contact support."}
    return {"available": True}


@frappe.whitelist(allow_guest=True)
def register_clinic(clinic_name, email, physician_name, password, contact, address,
                    country=None, city=None):
    import re as _re
    clinic_name    = (clinic_name or "").strip()
    email          = (email or "").strip()
    physician_name = (physician_name or "").strip()
    contact        = (contact or "").strip()
    address        = (address or "").strip()
    country        = (country or "").strip()
    city           = (city or "").strip()

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

    s = _get_settings()
    email_otp_on  = bool(s.get("enable_email_otp"))
    phone_otp_on  = bool(s.get("enable_phone_otp"))
    if email_otp_on or phone_otp_on:
        email_verified = email_otp_on and bool(
            frappe.safe_decode(frappe.cache.get(f"email_verified_{email.lower()}") or b"")
        )
        contact_mobile = _normalize_phone(contact)
        phone_verified = phone_otp_on and bool(
            frappe.safe_decode(frappe.cache.get(f"phone_verified_{contact_mobile}") or b"")
        )
        if not (email_verified or phone_verified):
            if email_otp_on and phone_otp_on:
                frappe.throw("Please verify at least your email address or phone number before registering.")
            elif email_otp_on:
                frappe.throw("Email address not verified. Please verify your email before registering.")
            else:
                frappe.throw("Phone number not verified. Please verify your phone number before registering.")

    existing_email = frappe.db.get_value(
        "PW Subscription", {"contact_email": email.lower()},
        ["status"], order_by="creation desc", as_dict=True
    )
    if existing_email and existing_email.status in _BLOCKED_STATUSES:
        frappe.throw("This email is already registered. Please contact support.")

    if frappe.db.exists("PW Subscription", {"clinic_name": clinic_name}):
        frappe.throw("This clinic name is already registered. Please choose a different name.")

    try:
        settings   = _get_settings()
        trial_days = settings.trial_days or 7
        base_domain = (settings.base_domain or "").strip()
    except Exception:
        trial_days  = 7
        base_domain = ""

    if not base_domain:
        frappe.throw("Base Domain is not configured in PW Subscription Settings. "
                     "Please contact the administrator.")

    subdomain = clinic_name  # already validated as proper subdomain format
    site_name = f"{subdomain}.{base_domain}"

    if frappe.db.exists("Site Provisioning Request", {"site_name": site_name}):
        frappe.throw("A provisioning request for this clinic already exists. "
                     "Please contact support if you need assistance.")

    sub_doc = frappe.get_doc({
        "doctype": "PW Subscription",
        "clinic_name": clinic_name,
        "physician_name": physician_name,
        "contact_email": email,
        "contact_phone": contact,
        "country": country or None,
        "city": city or None,
        "address": address,
        "initial_password": password,
        "site_name": site_name,
        "status": "Trial",
        "trial_start": today(),
        "trial_end": add_days(today(), trial_days),
    })
    sub_doc.insert(ignore_permissions=True)

    # Create Website User on master site now so the customer can log into the
    # portal immediately — don't wait for the background provisioning job.
    _ensure_website_user(email, physician_name, password)

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

    from pw_subscription.site_provisioning import _enqueue_provision
    _enqueue_provision(prov_doc.name)

    try:
        frappe.publish_realtime("pw_new_site", {
            "name": sub_doc.name,
            "clinic_name": clinic_name,
            "physician_name": physician_name,
            "contact_email": email,
            "contact_phone": contact,
            "site_name": site_name,
            "site_url": f"https://{site_name}",
            "status": "Trial",
            "is_suspended": False,
            "days_remaining": trial_days,
            "trial_end": str(sub_doc.trial_end),
            "subscription_end": "",
            "grace_end": "",
            "payment_reference": "",
            "creation": str(sub_doc.creation)[:10] if sub_doc.creation else "",
            "provisioning_status": "Pending",
            "provisioning_request": prov_doc.name,
            "provisioning_url": "",
            "prov_error": "",
        })
    except Exception:
        pass

    return {
        "success": True,
        "name": sub_doc.name,
        "clinic_name": clinic_name,
        "trial_end": str(sub_doc.trial_end),
        "request_name": prov_doc.name,
        "site_name": site_name,
    }


@frappe.whitelist(allow_guest=True)
def get_provisioning_status(request_name):
    if not request_name:
        frappe.throw("request_name is required.")

    result = frappe.db.get_value(
        "Site Provisioning Request",
        request_name,
        ["status", "site_url", "contact_email",
         "physician_name", "error_message", "attempt_count", "progress_log"],
        as_dict=True,
    )
    if not result:
        frappe.throw(f"Provisioning request '{request_name}' not found.")

    try:
        step = frappe.db.get_value("Site Provisioning Request", request_name, "current_step")
        result["current_step"] = int(step or 0)
    except Exception:
        from pw_subscription.site_provisioning import _infer_step_from_log
        result["current_step"] = _infer_step_from_log(result.get("progress_log") or "")

    from pw_subscription.site_provisioning import _last_log_line
    result["last_line"] = _last_log_line(result.get("progress_log") or "")
    result.pop("progress_log", None)
    return result


@frappe.whitelist(allow_guest=True)
def retry_site_creation(request_name):
    if not request_name:
        frappe.throw("request_name is required.")

    status = frappe.db.get_value("Site Provisioning Request", request_name, "status")
    if not status:
        frappe.throw(f"Request '{request_name}' not found.")
    if status == "In Progress":
        frappe.throw("Provisioning is already in progress.")
    if status == "Success":
        frappe.throw("This site was already provisioned successfully.")

    frappe.db.set_value("Site Provisioning Request", request_name, {
        "status": "Pending",
        "error_message": "",
    }, update_modified=False)
    try:
        from pw_subscription.site_provisioning import STEP_STARTING
        frappe.db.set_value("Site Provisioning Request", request_name,
                            "current_step", STEP_STARTING, update_modified=False)
    except Exception:
        pass
    frappe.db.commit()

    from pw_subscription.site_provisioning import _enqueue_provision
    _enqueue_provision(request_name)
    return {"success": True}


# ── System Manager — subscription portal (self-service) ──────────────────────

@frappe.whitelist(allow_guest=False)
def get_status():
    from pw_subscription.subscription_check import get_current_subscription
    sub = get_current_subscription()
    try:
        s = _get_settings()
        bank_details = s.bank_details
        contact_email = s.contact_email
        contact_phone = s.contact_phone
        monthly_fee = s.monthly_fee
        app_name = s.app_name
    except Exception:
        bank_details = contact_email = contact_phone = app_name = ""
        monthly_fee = 0

    if not sub:
        return {"status": "No Subscription", "site": frappe.local.site,
                "bank_details": bank_details, "contact_email": contact_email,
                "contact_phone": contact_phone, "monthly_fee": monthly_fee,
                "app_name": app_name}

    logs = frappe.get_all(
        "PW Subscription Log",
        filters={"subscription": sub.name},
        fields=["action", "action_date", "action_by", "notes"],
        order_by="action_date desc",
        limit=10,
    )
    return {
        "status": sub.status,
        "site": frappe.local.site,
        "days_remaining": _days_remaining(sub),
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


# ── System Manager — Control Room APIs ───────────────────────────────────────

@frappe.whitelist()
def get_control_room_data():
    frappe.only_for("System Manager")

    subs = frappe.get_all(
        "PW Subscription",
        fields=["name", "clinic_name", "physician_name", "contact_email",
                "contact_phone", "site_name", "status", "is_suspended",
                "trial_start", "trial_end", "subscription_start", "subscription_end",
                "grace_end", "payment_reference", "creation"],
        order_by="creation desc",
        limit=0,
        ignore_permissions=True,
    )

    # Get latest provisioning request per subscription
    prov_map = {}
    provs = frappe.get_all(
        "Site Provisioning Request",
        fields=["name", "subscription", "status", "site_url", "attempt_count",
                "last_attempt", "error_message"],
        order_by="creation desc",
        limit=0,
        ignore_permissions=True,
    )
    for p in provs:
        if p.subscription not in prov_map:
            prov_map[p.subscription] = p

    # Pending payment proofs
    pending_proofs = frappe.get_all(
        "Payment Proof",
        filters={"status": "Pending"},
        fields=["name", "subscription", "clinic_name", "physician_name", "site_name",
                "selected_plan", "duration_months", "amount_paid", "screenshot",
                "submitted_on", "notes", "contact_email"],
        order_by="submitted_on asc",
        limit=0,
        ignore_permissions=True,
    )

    try:
        s = _get_settings()
        monthly_fee = s.monthly_fee or 0
    except Exception:
        monthly_fee = 0

    # Build site list with computed fields
    site_list = []
    stats = {"total": 0, "active": 0, "trial": 0, "grace": 0,
             "expired": 0, "cancelled": 0, "suspended": 0, "monthly_revenue": 0.0}

    for sub in subs:
        stats["total"] += 1
        status = sub.status
        if status == "Active":
            stats["active"] += 1
            stats["monthly_revenue"] += monthly_fee
        elif status == "Trial":
            stats["trial"] += 1
        elif status == "Grace Period":
            stats["grace"] += 1
        elif status == "Expired":
            stats["expired"] += 1
        elif status == "Cancelled":
            stats["cancelled"] += 1
        if sub.is_suspended:
            stats["suspended"] += 1

        prov = prov_map.get(sub.name)
        site_list.append({
            "name": sub.name,
            "clinic_name": sub.clinic_name,
            "physician_name": sub.physician_name,
            "contact_email": sub.contact_email,
            "contact_phone": sub.contact_phone,
            "site_name": sub.site_name,
            "site_url": f"https://{sub.site_name}" if sub.site_name else "",
            "status": status,
            "is_suspended": bool(sub.is_suspended),
            "days_remaining": _days_remaining(frappe._dict(sub)),
            "trial_start": str(sub.trial_start) if sub.trial_start else "",
            "trial_end": str(sub.trial_end) if sub.trial_end else "",
            "subscription_start": str(sub.subscription_start) if sub.subscription_start else "",
            "subscription_end": str(sub.subscription_end) if sub.subscription_end else "",
            "grace_end": str(sub.grace_end) if sub.grace_end else "",
            "payment_reference": sub.payment_reference or "",
            "creation": str(sub.creation)[:10] if sub.creation else "",
            "provisioning_status": prov.status if prov else "None",
            "provisioning_request": prov.name if prov else "",
            "provisioning_url": prov.site_url if prov else "",
            "prov_error": (prov.error_message or "")[:200] if prov else "",
        })

    stats["pending_approvals"] = len(pending_proofs)

    return {
        "stats": stats,
        "sites": site_list,
        "pending_proofs": pending_proofs,
        "monthly_fee": monthly_fee,
    }


@frappe.whitelist()
def ping_site(site_url, timeout=None):
    """Check if a site is reachable. Returns online status and response time."""
    _require_portal_access()
    try:
        s = _get_settings()
        ping_enabled = s.enable_site_ping
        default_timeout = s.ping_timeout or 5
    except Exception:
        ping_enabled = True
        default_timeout = 5

    if not ping_enabled:
        return {"online": None, "message": "Ping disabled in settings"}

    t = int(timeout or default_timeout)
    t = max(1, min(t, 30))

    if not site_url or not site_url.startswith("http"):
        return {"online": False, "message": "Invalid URL"}

    import urllib.request
    import time
    start = time.time()
    try:
        req = urllib.request.Request(site_url, method="HEAD")
        req.add_header("User-Agent", "PW-ControlRoom/1.0")
        with urllib.request.urlopen(req, timeout=t) as resp:
            elapsed = round((time.time() - start) * 1000)
            return {"online": True, "response_ms": elapsed, "status_code": resp.status}
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return {"online": False, "response_ms": elapsed, "message": str(e)[:100]}


@frappe.whitelist()
def get_provisioning_log(request_name):
    """Return the full provisioning log for a request — admin use."""
    frappe.only_for("System Manager")
    if not request_name:
        frappe.throw("request_name is required.")
    result = frappe.db.get_value(
        "Site Provisioning Request", request_name,
        ["status", "progress_log", "error_message", "attempt_count",
         "last_attempt", "site_name", "site_url"],
        as_dict=True,
    )
    if not result:
        frappe.throw("Provisioning request not found.")
    return result


@frappe.whitelist()
def approve_payment(proof_name, admin_notes=None):
    """Approve a payment proof and activate the subscription."""
    frappe.only_for("System Manager")
    proof = frappe.get_doc("Payment Proof", proof_name)
    if proof.status != "Pending":
        frappe.throw(f"This proof is already {proof.status}.")

    sub = frappe.get_doc("PW Subscription", proof.subscription)
    old_status = sub.status
    months = proof.duration_months or 1

    # Calculate new end date from today (or extend existing)
    base_date = today()
    if sub.status == "Active" and sub.subscription_end and str(sub.subscription_end) >= base_date:
        base_date = str(sub.subscription_end)

    new_end = add_months(base_date, months)
    sub.status = "Active"
    sub.subscription_start = today()
    sub.subscription_end = new_end
    sub.grace_end = None
    sub.payment_reference = proof.name
    sub.activated_by = frappe.session.user
    sub.activation_date = now()
    sub.save(ignore_permissions=True)

    proof.status = "Approved"
    proof.reviewed_by = frappe.session.user
    proof.reviewed_on = now()
    proof.admin_notes = admin_notes or ""
    proof.save(ignore_permissions=True)

    _log_action(sub.name, "Activated",
                f"Payment approved (Proof: {proof_name}). Plan: {proof.selected_plan or months}mo. "
                f"Valid until {new_end}. Prev: {old_status}.")
    frappe.db.commit()

    _publish_sub_changed(sub)
    _publish_proof_done(proof)

    # Send confirmation email if enabled
    _send_activation_email(sub, new_end)

    return {"success": True, "new_end": str(new_end), "subscription": sub.name}


@frappe.whitelist()
def reject_payment(proof_name, admin_notes=None):
    """Reject a payment proof."""
    frappe.only_for("System Manager")
    proof = frappe.get_doc("Payment Proof", proof_name)
    if proof.status != "Pending":
        frappe.throw(f"This proof is already {proof.status}.")

    proof.status = "Rejected"
    proof.reviewed_by = frappe.session.user
    proof.reviewed_on = now()
    proof.admin_notes = admin_notes or ""
    proof.save(ignore_permissions=True)
    frappe.db.commit()

    _publish_proof_done(proof)
    _send_rejection_email(proof, admin_notes)
    return {"success": True}


@frappe.whitelist()
def activate_subscription(subscription_name=None, end_date=None, payment_reference=None,
                          notes=None, plan_label=None, duration_months=None):
    frappe.only_for("System Manager")

    # Support legacy call (no subscription_name) from old portal
    if not subscription_name:
        from pw_subscription.subscription_check import get_current_subscription
        sub = get_current_subscription()
        if not sub:
            frappe.throw("No subscription record found.")
    else:
        sub = frappe.get_doc("PW Subscription", subscription_name)

    if not end_date:
        if duration_months:
            end_date = str(add_months(today(), int(duration_months)))
        else:
            frappe.throw("Either end_date or duration_months is required.")

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

    plan_info = plan_label or (f"{duration_months} months" if duration_months else "")
    _log_action(sub.name, "Activated",
                f"Activated from {old_status}. Plan: {plan_info}. "
                f"Ref: {payment_reference or 'N/A'}. Until: {end_date}.")
    frappe.db.commit()
    _publish_sub_changed(sub)
    _send_activation_email(sub, end_date)
    return {"success": True, "message": "Subscription activated successfully", "end_date": end_date}


@frappe.whitelist()
def extend_trial(subscription_name=None, extra_days=7):
    frappe.only_for("System Manager")

    if not subscription_name:
        from pw_subscription.subscription_check import get_current_subscription
        sub = get_current_subscription()
        if not sub:
            frappe.throw("No subscription found.")
    else:
        sub = frappe.get_doc("PW Subscription", subscription_name)

    extra_days = int(extra_days)
    new_end = add_days(today(), extra_days)
    old_end = sub.trial_end
    sub.trial_end = new_end
    if sub.status in ["Expired", "Grace Period", "Cancelled"]:
        sub.status = "Trial"
        sub.grace_end = None
    sub.save(ignore_permissions=True)
    _log_action(sub.name, "Extended",
                f"Trial extended from {old_end} to {new_end} ({extra_days} days).")
    frappe.db.commit()
    _publish_sub_changed(sub)
    return {"success": True, "new_end": str(new_end)}


@frappe.whitelist()
def cancel_subscription(subscription_name, notes=None):
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    old_status = sub.status
    sub.status = "Cancelled"
    if notes:
        sub.notes = (sub.notes or "") + f"\n[Cancelled] {notes}"
    sub.save(ignore_permissions=True)
    _log_action(sub.name, "Cancelled",
                f"Cancelled from {old_status}. Reason: {notes or 'N/A'}.")
    frappe.db.commit()
    _publish_sub_changed(sub)
    return {"success": True}


@frappe.whitelist()
def suspend_site(subscription_name, reason=None):
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if sub.is_suspended:
        frappe.throw("Site is already suspended.")

    try:
        s = _get_settings()
        mode = s.suspension_mode or "Soft Block"
    except Exception:
        mode = "Soft Block"

    if mode == "Hard Suspend" and sub.site_name:
        from pw_subscription.site_provisioning import _do_suspend_site
        _do_suspend_site(sub.site_name)

    sub.is_suspended = 1
    sub.suspended_on = now()
    sub.suspension_reason = reason or "Suspended by administrator"
    sub.save(ignore_permissions=True)
    _log_action(sub.name, "Cancelled",
                f"Site suspended ({mode}). Reason: {reason or 'N/A'}.")
    frappe.db.commit()
    _publish_sub_changed(sub)
    return {"success": True, "mode": mode}


@frappe.whitelist()
def unsuspend_site(subscription_name):
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.is_suspended:
        frappe.throw("Site is not suspended.")

    try:
        s = _get_settings()
        mode = s.suspension_mode or "Soft Block"
    except Exception:
        mode = "Soft Block"

    if mode == "Hard Suspend" and sub.site_name:
        from pw_subscription.site_provisioning import _do_unsuspend_site
        _do_unsuspend_site(sub.site_name)

    sub.is_suspended = 0
    sub.suspended_on = None
    sub.suspension_reason = ""
    sub.save(ignore_permissions=True)
    _log_action(sub.name, "Activated",
                f"Site unsuspended ({mode}).")
    frappe.db.commit()
    _publish_sub_changed(sub)
    return {"success": True}


@frappe.whitelist()
def send_reminder_manual(subscription_name):
    """Manually trigger a renewal reminder email for a specific subscription."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    try:
        s = _get_settings()
    except Exception:
        frappe.throw("Settings not configured.")

    days = _days_remaining(sub)
    from pw_subscription.subscription_check import _send_reminder_email
    _send_reminder_email(sub, days, s)
    _log_action(sub.name, "Extended",
                f"Renewal reminder manually sent ({days} days remaining).")
    frappe.db.commit()
    return {"success": True, "message": f"Reminder email sent to {sub.contact_email}"}


@frappe.whitelist()
def delete_site_permanently(subscription_name, confirm_text=None):
    """Drop the site from bench and delete all related records. IRREVERSIBLE."""
    frappe.only_for("System Manager")
    if confirm_text != "DELETE":
        frappe.throw("Type DELETE to confirm permanent deletion.")

    sub = frappe.get_doc("PW Subscription", subscription_name)
    site_name = sub.site_name

    # Drop the actual site if it exists
    if site_name:
        try:
            s = _get_settings()
            db_pass = s.get_password("mariadb_root_password") or ""
            if db_pass:
                from pw_subscription.site_provisioning import _run, _bench_dir
                import os
                site_dir = os.path.join(_bench_dir(), "sites", site_name)
                if os.path.exists(site_dir):
                    _run(["drop-site", site_name, "--mariadb-root-password", db_pass, "--force"],
                         None, "Drop site", timeout=120)
        except Exception as e:
            frappe.log_error(str(e), f"Delete site {site_name} failed")

    # Delete records (logs → proofs → provisioning requests → subscription)
    frappe.db.delete("PW Subscription Log", {"subscription": subscription_name})
    frappe.db.delete("Payment Proof", {"subscription": subscription_name})
    prov_requests = frappe.get_all("Site Provisioning Request",
                                   filters={"subscription": subscription_name},
                                   fields=["name"])
    for pr in prov_requests:
        frappe.delete_doc("Site Provisioning Request", pr.name, ignore_permissions=True)
    frappe.delete_doc("PW Subscription", subscription_name, ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": f"Site {site_name} and all records deleted."}


# ── Backup / Restore ─────────────────────────────────────────────────────────

@frappe.whitelist()
def backup_site(subscription_name):
    """Run bench backup --with-files for a managed site."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    from pw_subscription.site_provisioning import _run
    try:
        _run(["--site", sub.site_name, "backup", "--with-files"],
             None, "Backup site", timeout=300)
        _log_action(sub.name, "Extended", f"Manual backup created for {sub.site_name}.")
        frappe.db.commit()
        return {"success": True, "message": f"Backup created for {sub.site_name}."}
    except Exception as e:
        frappe.throw(str(e))


def _fmt_backup_time(ts_str):
    """Convert 20250625_154230 → 2025-06-25 15:42:30."""
    try:
        return (f"{ts_str[0:4]}-{ts_str[4:6]}-{ts_str[6:8]} "
                f"{ts_str[9:11]}:{ts_str[11:13]}:{ts_str[13:15]}")
    except Exception:
        return ts_str


@frappe.whitelist()
def list_site_backups(subscription_name):
    """List available backup sets for a managed site (newest first, up to 10)."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    from pw_subscription.site_provisioning import _bench_dir
    import os, glob as _glob
    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    if not os.path.exists(backup_dir):
        return {"backups": [], "site_name": sub.site_name}
    db_files = sorted(_glob.glob(os.path.join(backup_dir, "*-database.sql.gz")), reverse=True)
    backups = []
    for db_file in db_files[:10]:
        basename = os.path.basename(db_file)
        prefix = basename.replace("-database.sql.gz", "")
        pub_matches  = _glob.glob(os.path.join(backup_dir, prefix + "-files.tar*"))
        priv_matches = _glob.glob(os.path.join(backup_dir, prefix + "-private-files.tar*"))
        ts_raw = prefix.split("-")[0]
        backups.append({
            "prefix":       prefix,
            "db_file":      basename,
            "pub_file":     os.path.basename(pub_matches[0])  if pub_matches  else "",
            "priv_file":    os.path.basename(priv_matches[0]) if priv_matches else "",
            "db_size_bytes": os.path.getsize(db_file),
            "created":      _fmt_backup_time(ts_raw),
        })
    return {"backups": backups, "site_name": sub.site_name}


@frappe.whitelist()
def download_site_backup(subscription_name, filename):
    """Stream a backup file as a browser download (GET-friendly)."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name for this subscription.")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        frappe.throw("Invalid filename.")
    from pw_subscription.site_provisioning import _bench_dir
    import os
    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    filepath = os.path.join(backup_dir, filename)
    if not os.path.isfile(filepath):
        frappe.throw("Backup file not found.")
    with open(filepath, "rb") as f:
        frappe.local.response.filecontent = f.read()
    frappe.local.response.filename = filename
    frappe.local.response.type = "download"


@frappe.whitelist()
def restore_site_backup(subscription_name, db_file, pub_file=None, priv_file=None):
    """Restore a managed site from a selected backup set. DESTRUCTIVE."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    for fname in [db_file, pub_file, priv_file]:
        if fname and ("/" in fname or "\\" in fname or ".." in fname):
            frappe.throw("Invalid filename.")
    from pw_subscription.site_provisioning import _run, _bench_dir
    import os
    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    db_path = os.path.join(backup_dir, db_file)
    if not os.path.isfile(db_path):
        frappe.throw("Database backup file not found.")
    try:
        s = _get_settings()
        db_pass = s.get_password("mariadb_root_password") or ""
    except Exception:
        db_pass = ""
    cmd = ["--site", sub.site_name, "restore", db_path]
    if pub_file:
        pub_path = os.path.join(backup_dir, pub_file)
        if os.path.isfile(pub_path):
            cmd += ["--with-public-files", pub_path]
    if priv_file:
        priv_path = os.path.join(backup_dir, priv_file)
        if os.path.isfile(priv_path):
            cmd += ["--with-private-files", priv_path]
    if db_pass:
        cmd += ["--mariadb-root-password", db_pass]
    try:
        _run(cmd, None, "Restore site", timeout=600)
        _log_action(sub.name, "Extended", f"Site restored from backup: {db_file}.")
        frappe.db.commit()
        return {"success": True, "message": f"Site {sub.site_name} restored from {db_file}."}
    except Exception as e:
        frappe.throw(str(e))


@frappe.whitelist()
def restore_from_uploaded_backup(subscription_name):
    """Restore a site from user-uploaded backup files. DESTRUCTIVE."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")

    request_files = frappe.local.request.files
    if "db_file" not in request_files or not request_files["db_file"].filename:
        frappe.throw("Database backup file is required.")

    from pw_subscription.site_provisioning import _run, _bench_dir
    import os

    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    os.makedirs(backup_dir, exist_ok=True)

    saved = {}
    try:
        for key in ["db_file", "pub_file", "priv_file"]:
            f = request_files.get(key)
            if f and f.filename:
                safe_name = os.path.basename(f.filename)
                dest = os.path.join(backup_dir, f"ext_{key}_{safe_name}")
                f.save(dest)
                saved[key] = dest

        if "db_file" not in saved:
            frappe.throw("Database backup file could not be saved.")

        try:
            s = _get_settings()
            db_pass = s.get_password("mariadb_root_password") or ""
        except Exception:
            db_pass = ""

        cmd = ["--site", sub.site_name, "restore", saved["db_file"]]
        if "pub_file" in saved:
            cmd += ["--with-public-files", saved["pub_file"]]
        if "priv_file" in saved:
            cmd += ["--with-private-files", saved["priv_file"]]
        if db_pass:
            cmd += ["--mariadb-root-password", db_pass]

        _run(cmd, None, "Restore site from uploaded backup", timeout=600)
        _log_action(sub.name, "Extended", "Site restored from externally uploaded backup.")
        frappe.db.commit()
        return {"success": True, "message": f"Site {sub.site_name} restored from uploaded backup."}
    except Exception as e:
        frappe.throw(str(e))
    finally:
        for path in saved.values():
            try:
                os.remove(path)
            except Exception:
                pass


# ── Streaming progress helpers ───────────────────────────────────────────────

def _emit_progress(job_id, user, status, line="", percent=None):
    """Publish a real-time progress event for a running bench job."""
    try:
        frappe.publish_realtime("pw_job_progress", {
            "job_id":  job_id,
            "status":  status,   # running | success | error
            "line":    line,
            "percent": percent,
        }, user=user, after_commit=False)
    except Exception:
        pass


def _run_streaming(args, job_id, user, timeout=600):
    """Run a bench command and emit each output line via realtime."""
    from pw_subscription.site_provisioning import _find_bench, _bench_dir, _run_env
    import subprocess, time

    bench_exe = _find_bench()
    env = _run_env()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [bench_exe] + args,
        cwd=_bench_dir(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=0,
    )
    all_lines = []
    deadline = time.time() + timeout
    try:
        while True:
            raw = proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            all_lines.append(line)
            _emit_progress(job_id, user, "running", line=line)
            if time.time() > deadline:
                proc.kill()
                raise RuntimeError("Operation timed out.")
    finally:
        proc.stdout.close()
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(all_lines[-40:]) or "Unknown error"
        raise RuntimeError(err)
    return "\n".join(all_lines)


# ── Streaming background jobs ─────────────────────────────────────────────────

@frappe.whitelist()
def start_backup_job(subscription_name):
    """Enqueue a backup and return a job_id for progress tracking."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    import uuid
    job_id = "bkp_" + str(uuid.uuid4())[:8]
    frappe.enqueue(
        "pw_subscription.api._job_backup",
        queue="default", timeout=600,
        subscription_name=subscription_name,
        pw_job_id=job_id, user=frappe.session.user,
    )
    return {"job_id": job_id, "site_name": sub.site_name}


def _job_backup(subscription_name, pw_job_id, user):
    sub = frappe.get_doc("PW Subscription", subscription_name)
    try:
        _emit_progress(pw_job_id, user, "running", line=f"Starting backup for {sub.site_name}…", percent=5)
        _run_streaming(
            ["--site", sub.site_name, "backup", "--with-files"],
            pw_job_id, user, timeout=350,
        )
        _log_action(sub.name, "Extended", f"Manual backup created for {sub.site_name}.")
        frappe.db.commit()
        _emit_progress(pw_job_id, user, "success",
                       line=f"Backup completed successfully for {sub.site_name}.", percent=100)
    except Exception as e:
        _emit_progress(pw_job_id, user, "error", line=str(e)[:600])
        frappe.log_error(str(e), f"Backup job {pw_job_id}")


@frappe.whitelist()
def start_restore_job(subscription_name, db_file, pub_file=None, priv_file=None):
    """Enqueue a restore from existing backup and return a job_id."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured.")
    for fname in [db_file, pub_file, priv_file]:
        if fname and ("/" in fname or "\\" in fname or ".." in fname):
            frappe.throw("Invalid filename.")
    from pw_subscription.site_provisioning import _bench_dir
    import os
    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    if not os.path.isfile(os.path.join(backup_dir, db_file)):
        frappe.throw("Database backup file not found.")
    import uuid
    job_id = "rst_" + str(uuid.uuid4())[:8]
    frappe.enqueue(
        "pw_subscription.api._job_restore",
        queue="default", timeout=900,
        subscription_name=subscription_name,
        db_file=db_file, pub_file=pub_file, priv_file=priv_file,
        pw_job_id=job_id, user=frappe.session.user,
    )
    return {"job_id": job_id, "site_name": sub.site_name}


def _job_restore(subscription_name, db_file, pw_job_id, user, pub_file=None, priv_file=None):
    from pw_subscription.site_provisioning import _bench_dir
    import os
    sub = frappe.get_doc("PW Subscription", subscription_name)
    backup_dir = os.path.join(_bench_dir(), "sites", sub.site_name, "private", "backups")
    try:
        _emit_progress(pw_job_id, user, "running", line="Preparing restore…", percent=5)
        try:
            s = _get_settings()
            db_pass = s.get_password("mariadb_root_password") or ""
        except Exception:
            db_pass = ""
        cmd = ["--site", sub.site_name, "restore", os.path.join(backup_dir, db_file)]
        if pub_file:
            p = os.path.join(backup_dir, pub_file)
            if os.path.isfile(p): cmd += ["--with-public-files", p]
        if priv_file:
            p = os.path.join(backup_dir, priv_file)
            if os.path.isfile(p): cmd += ["--with-private-files", p]
        if db_pass:
            cmd += ["--mariadb-root-password", db_pass]
        _emit_progress(pw_job_id, user, "running",
                       line=f"Restoring {sub.site_name} from {db_file}…", percent=15)
        _run_streaming(cmd, pw_job_id, user, timeout=650)
        _log_action(sub.name, "Extended", f"Site restored from backup: {db_file}.")
        frappe.db.commit()
        _emit_progress(pw_job_id, user, "success",
                       line=f"{sub.site_name} restored successfully.", percent=100)
    except Exception as e:
        _emit_progress(pw_job_id, user, "error", line=str(e)[:600])
        frappe.log_error(str(e), f"Restore job {pw_job_id}")


@frappe.whitelist()
def start_install_job(subscription_name, app_name, repo_url=None, branch=None):
    """Enqueue an app install and return a job_id."""
    frappe.only_for("System Manager")
    import re as _re
    app_name = (app_name or "").strip()
    if not app_name or not _re.match(r'^[a-z][a-z0-9_-]*$', app_name):
        frappe.throw("Invalid app name.")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured.")
    import uuid
    job_id = "inst_" + str(uuid.uuid4())[:8]
    frappe.enqueue(
        "pw_subscription.api._job_install",
        queue="default", timeout=900,
        subscription_name=subscription_name,
        app_name=app_name, repo_url=repo_url, branch=branch,
        job_id=job_id, user=frappe.session.user,
    )
    return {"job_id": job_id, "site_name": sub.site_name, "app_name": app_name}


def _job_install(subscription_name, app_name, job_id, user, repo_url=None, branch=None):
    from pw_subscription.site_provisioning import _bench_dir
    import os
    sub = frappe.get_doc("PW Subscription", subscription_name)
    try:
        app_dir = os.path.join(_bench_dir(), "apps", app_name)
        if not os.path.isdir(app_dir):
            if not repo_url:
                raise RuntimeError(
                    f"App '{app_name}' is not in bench. Provide a repository URL to fetch it.")
            _emit_progress(job_id, user, "running",
                           line=f"Fetching {app_name} from repository…", percent=10)
            get_cmd = ["get-app", repo_url]
            if branch:
                get_cmd += ["--branch", branch]
            _run_streaming(get_cmd, job_id, user, timeout=400)
        _emit_progress(job_id, user, "running",
                       line=f"Installing {app_name} on {sub.site_name}…", percent=65)
        _run_streaming(
            ["--site", sub.site_name, "install-app", app_name],
            job_id, user, timeout=300,
        )
        _log_action(sub.name, "Extended", f"App '{app_name}' installed on {sub.site_name}.")
        frappe.db.commit()
        _emit_progress(job_id, user, "success",
                       line=f"'{app_name}' installed successfully on {sub.site_name}.", percent=100)
    except Exception as e:
        _emit_progress(job_id, user, "error", line=str(e)[:600])
        frappe.log_error(str(e), f"Install job {job_id}")


@frappe.whitelist()
def start_uninstall_job(subscription_name, app_name):
    """Enqueue an app uninstall and return a job_id."""
    frappe.only_for("System Manager")
    app_name = (app_name or "").strip()
    if not app_name or app_name == "frappe":
        frappe.throw("Cannot uninstall 'frappe'.")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured.")
    import uuid
    job_id = "uninst_" + str(uuid.uuid4())[:8]
    frappe.enqueue(
        "pw_subscription.api._job_uninstall",
        queue="default", timeout=600,
        subscription_name=subscription_name,
        app_name=app_name,
        job_id=job_id, user=frappe.session.user,
    )
    return {"job_id": job_id, "site_name": sub.site_name, "app_name": app_name}


def _job_uninstall(subscription_name, app_name, job_id, user):
    sub = frappe.get_doc("PW Subscription", subscription_name)
    try:
        _emit_progress(job_id, user, "running",
                       line=f"Uninstalling {app_name} from {sub.site_name}…", percent=10)
        _run_streaming(
            ["--site", sub.site_name, "uninstall-app", app_name, "--yes", "--no-backup", "--force"],
            job_id, user, timeout=300,
        )
        _log_action(sub.name, "Extended", f"App '{app_name}' uninstalled from {sub.site_name}.")
        frappe.db.commit()
        _emit_progress(job_id, user, "success",
                       line=f"'{app_name}' removed from {sub.site_name}.", percent=100)
    except Exception as e:
        _emit_progress(job_id, user, "error", line=str(e)[:600])
        frappe.log_error(str(e), f"Uninstall job {job_id}")


@frappe.whitelist()
def start_migrate_job(subscription_name):
    """Enqueue a bench migrate and return a job_id."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured.")
    import uuid
    job_id = "mig_" + str(uuid.uuid4())[:8]
    frappe.enqueue(
        "pw_subscription.api._job_migrate",
        queue="default", timeout=900,
        subscription_name=subscription_name,
        job_id=job_id, user=frappe.session.user,
    )
    return {"job_id": job_id, "site_name": sub.site_name}


def _job_migrate(subscription_name, job_id, user):
    sub = frappe.get_doc("PW Subscription", subscription_name)
    try:
        _emit_progress(job_id, user, "running",
                       line=f"Running migrations on {sub.site_name}…", percent=5)
        _run_streaming(
            ["--site", sub.site_name, "migrate"],
            job_id, user, timeout=650,
        )
        _log_action(sub.name, "Extended", f"Site {sub.site_name} migrated successfully.")
        frappe.db.commit()
        _emit_progress(job_id, user, "success",
                       line=f"All migrations completed for {sub.site_name}.", percent=100)
    except Exception as e:
        _emit_progress(job_id, user, "error", line=str(e)[:600])
        frappe.log_error(str(e), f"Migrate job {job_id}")


# ── App Management ──────────────────────────────────────────────────────────

@frappe.whitelist()
def list_site_apps(subscription_name):
    """List apps installed on a managed site using bench list-apps."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    from pw_subscription.site_provisioning import _run
    output = _run(["--site", sub.site_name, "list-apps"], None, "List apps", timeout=30)
    import re as _re
    _valid_name = _re.compile(r'^[a-z][a-z0-9_]*$')
    apps = []
    for line in (output or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if not _valid_name.match(name):
            continue
        version = parts[1] if len(parts) > 1 else ""
        branch  = parts[2] if len(parts) > 2 else ""
        apps.append({"name": name, "version": version, "branch": branch})
    return {"apps": apps, "site_name": sub.site_name}


@frappe.whitelist()
def install_app(subscription_name, app_name, repo_url=None, branch=None):
    """Install a Frappe app on a managed site (fetches from repo if not in bench)."""
    frappe.only_for("System Manager")
    import re as _re
    app_name = (app_name or "").strip()
    if not app_name or not _re.match(r'^[a-z][a-z0-9_-]*$', app_name):
        frappe.throw("Invalid app name. Use lowercase letters, numbers, hyphens and underscores only.")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    from pw_subscription.site_provisioning import _run, _bench_dir
    import os
    app_dir = os.path.join(_bench_dir(), "apps", app_name)
    if not os.path.isdir(app_dir):
        if not repo_url:
            frappe.throw(f"App '{app_name}' is not in bench. Provide a repository URL to fetch it.")
        get_cmd = ["get-app", repo_url]
        if branch:
            get_cmd += ["--branch", branch]
        _run(get_cmd, None, f"Get app {app_name}", timeout=300)
    _run(["--site", sub.site_name, "install-app", app_name],
         None, f"Install app {app_name}", timeout=300)
    _log_action(sub.name, "Extended", f"App '{app_name}' installed on {sub.site_name}.")
    frappe.db.commit()
    return {"success": True, "message": f"App '{app_name}' installed successfully on {sub.site_name}."}


@frappe.whitelist()
def uninstall_app(subscription_name, app_name):
    """Uninstall a Frappe app from a managed site."""
    frappe.only_for("System Manager")
    app_name = (app_name or "").strip()
    if not app_name or app_name == "frappe":
        frappe.throw("Cannot uninstall 'frappe' or invalid app name.")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")

    from pw_subscription.site_provisioning import _find_bench, _bench_dir, _run_env
    import subprocess, re as _re

    bench_exe = _find_bench()
    bd = _bench_dir()
    env = _run_env()

    result = subprocess.run(
        [bench_exe, "--site", sub.site_name, "uninstall-app", app_name, "--yes", "--no-backup"],
        cwd=bd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=env, timeout=300,
    )

    if result.returncode != 0:
        # bench sometimes exits non-zero even when the uninstall succeeded.
        # Verify by checking whether the app is still in the site's app list.
        check = subprocess.run(
            [bench_exe, "--site", sub.site_name, "list-apps"],
            cwd=bd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=env, timeout=30,
        )
        still_installed = any(
            line.split()[0] == app_name
            for line in (check.stdout or "").splitlines()
            if line.strip() and _re.match(r'^[a-z][a-z0-9_]*$', line.split()[0] if line.split() else "")
        )
        if still_installed:
            err = (result.stderr or result.stdout or "Unknown error").strip()
            frappe.throw(f"Uninstall failed: {err[-800:]}")
        # App is gone despite non-zero exit — treat as success

    _log_action(sub.name, "Extended", f"App '{app_name}' uninstalled from {sub.site_name}.")
    frappe.db.commit()
    return {"success": True, "message": f"App '{app_name}' uninstalled from {sub.site_name}."}


@frappe.whitelist()
def migrate_site(subscription_name):
    """Run bench migrate on a managed site."""
    frappe.only_for("System Manager")
    sub = frappe.get_doc("PW Subscription", subscription_name)
    if not sub.site_name:
        frappe.throw("No site name configured for this subscription.")
    from pw_subscription.site_provisioning import _run
    _run(["--site", sub.site_name, "migrate"], None, "Migrate site", timeout=600)
    _log_action(sub.name, "Extended", f"Site {sub.site_name} migrated successfully.")
    frappe.db.commit()
    return {"success": True, "message": f"Site {sub.site_name} migrated successfully."}


# ── Email helpers ─────────────────────────────────────────────────────────────

def _send_activation_email(sub, end_date):
    try:
        s = _get_settings()
        if not s.enable_welcome_email:
            return
        sender = (s.sender_email or "").strip() or None
        app_name = s.app_name or "CureDesk"
        site_url = f"https://{sub.site_name}" if sub.site_name else ""
        subject = f"Your {app_name} subscription has been activated"
        body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#1E293B">
  <h2 style="color:#10B981">{app_name} — Subscription Activated</h2>
  <p>Dear <strong>{sub.physician_name}</strong>,</p>
  <p>Your subscription has been activated successfully.</p>
  <table style="width:100%;border-collapse:collapse;margin:1.5rem 0">
    <tr style="background:#DBEAFE">
      <td style="padding:.75rem;font-weight:700;color:#1E40AF;width:40%">Site URL</td>
      <td style="padding:.75rem"><a href="{site_url}">{site_url}</a></td>
    </tr>
    <tr style="background:#F0FDF4">
      <td style="padding:.75rem;font-weight:700;color:#065F46">Valid Until</td>
      <td style="padding:.75rem">{end_date}</td>
    </tr>
  </table>
  <p>Thank you for choosing {app_name}!</p>
</div>""".strip()
        frappe.sendmail(
            recipients=[sub.contact_email],
            sender=sender,
            subject=subject,
            message=body,
            now=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Activation email failed")


def _send_rejection_email(proof, admin_notes):
    try:
        s = _get_settings()
        if not s.enable_welcome_email:
            return
        sender = (s.sender_email or "").strip() or None
        app_name = s.app_name or "CureDesk"
        subject = f"Your {app_name} payment proof could not be verified"
        reason = admin_notes or "The payment proof submitted could not be verified."
        body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#1E293B">
  <h2 style="color:#EF4444">{app_name} — Payment Not Verified</h2>
  <p>Dear <strong>{proof.physician_name}</strong>,</p>
  <p>Unfortunately, we could not verify your payment proof.</p>
  <p><strong>Reason:</strong> {reason}</p>
  <p>Please re-submit with a clear payment screenshot or contact our support team.</p>
</div>""".strip()
        frappe.sendmail(
            recipients=[proof.contact_email],
            sender=sender,
            subject=subject,
            message=body,
            now=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Rejection email failed")


# ─── Server Stats & Monitoring ──────────────────────────────────────────────────

@frappe.whitelist(allow_guest=False)
def get_server_stats():
    """Collect system metrics and return to caller."""
    frappe.only_for("System Manager")
    stats = _collect_server_stats()
    return stats


def push_server_stats_realtime():
    """Scheduler hook — pushes server stats every minute to open Control Room tabs."""
    try:
        stats = _collect_server_stats()
        frappe.publish_realtime("pw_server_stats", stats, user="Administrator", after_commit=False)
    except Exception:
        pass


def _collect_server_stats():
    import psutil, os, time as _time

    now = _time.time()

    # CPU
    cpu_pct   = psutil.cpu_percent(interval=0.3)
    cpu_count = psutil.cpu_count(logical=True)
    try:
        load1, load5, load15 = os.getloadavg()
    except AttributeError:
        load1 = load5 = load15 = 0.0

    # RAM
    mem = psutil.virtual_memory()

    # Disk
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device":     part.device,
                "mountpoint": part.mountpoint,
                "fstype":     part.fstype,
                "total":      usage.total,
                "used":       usage.used,
                "free":       usage.free,
                "percent":    usage.percent,
            })
        except (PermissionError, OSError):
            continue

    # Network I/O + throughput delta
    net      = psutil.net_io_counters()
    prev_net = frappe.cache().get_value("pws_prev_net") or {}
    prev_ts  = frappe.cache().get_value("pws_prev_ts")  or now
    dt = now - prev_ts
    if dt > 0 and prev_net:
        tx_rate = max(0.0, (net.bytes_sent - prev_net.get("bytes_sent", 0)) / dt)
        rx_rate = max(0.0, (net.bytes_recv - prev_net.get("bytes_recv", 0)) / dt)
    else:
        tx_rate = rx_rate = 0.0
    frappe.cache().set_value(
        "pws_prev_net", {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv},
        expires_in_sec=300
    )
    frappe.cache().set_value("pws_prev_ts", now, expires_in_sec=300)

    # Redis
    redis_data = {"status": "offline"}
    try:
        import redis as _redis
        r = _redis.from_url(frappe.conf.redis_cache)
        info = r.info()
        redis_data = {
            "status":                   "online",
            "version":                  info.get("redis_version", ""),
            "used_memory_human":        info.get("used_memory_human", "N/A"),
            "connected_clients":        info.get("connected_clients", 0),
            "uptime_in_seconds":        info.get("uptime_in_seconds", 0),
            "total_commands_processed": info.get("total_commands_processed", 0),
        }
    except Exception:
        pass

    # MariaDB
    db_data = {"status": "offline"}
    try:
        rows = frappe.db.sql(
            "SHOW GLOBAL STATUS WHERE Variable_name IN "
            "('Threads_connected','Uptime','Questions','Slow_queries','Max_used_connections')",
            as_dict=True
        )
        db_data = {row.Variable_name: row.Value for row in rows}
        db_data["status"] = "online"
        ver = frappe.db.sql("SELECT VERSION() AS v", as_dict=True)
        if ver:
            db_data["version"] = ver[0].v
    except Exception:
        pass

    return {
        "cpu": {
            "percent": cpu_pct,
            "count":   cpu_count,
            "load1":   round(load1, 2),
            "load5":   round(load5, 2),
            "load15":  round(load15, 2),
        },
        "ram": {
            "total":     mem.total,
            "used":      mem.used,
            "available": mem.available,
            "percent":   mem.percent,
        },
        "disk":    disks,
        "network": {
            "bytes_sent":   net.bytes_sent,
            "bytes_recv":   net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
            "tx_rate":      tx_rate,
            "rx_rate":      rx_rate,
        },
        "redis": redis_data,
        "db":    db_data,
        "ts":    now,
    }
