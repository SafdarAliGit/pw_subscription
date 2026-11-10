# PW Subscription

**SaaS Subscription Management for CoreLogics** — a Frappe app that runs the full subscription lifecycle for a multi-site clinic platform: self-service clinic registration with OTP verification, automated site provisioning, trial/paid/grace-period management, manual payment-proof review, site suspension, and an admin "Control Room" for operating every customer site from one place.

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Frappe](https://img.shields.io/badge/Frappe-v15-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)

## Features

- **Subscription lifecycle** — Trial → Active → Grace Period → Expired, transitioned automatically by a daily scheduler, with a complete audit trail (PW Subscription Log).
- **Self-service registration portal** — clinics register on the website, verify by email OTP and/or phone OTP (MSG91), and watch their site being provisioned live.
- **Automated site provisioning** — creates the customer site, installs apps, applies branding/settings, and reports progress step-by-step (with retry on failure).
- **Payment proof workflow** — customers upload payment screenshots; admins approve or reject from the Control Room, which activates/extends the subscription and emails the customer.
- **Control Room** — one dashboard for all customer sites: live server stats, site ping, suspend/unsuspend (via `maintenance_mode`), backup & restore, app install/uninstall, and migrations — all with realtime progress.
- **Enforcement** — expired or suspended sites are blocked at login (`on_session_creation`), with subscription info in every session via `boot_session`.
- **Renewal reminders** — configurable reminder emails (default 7, 3, 1 days before expiry) and optional auto-suspension on trial/subscription expiry.

## DocTypes

| DocType | Purpose |
|---|---|
| PW Subscription | One record per customer site: status, dates, suspension, payment reference |
| PW Subscription Settings | Single: pricing, trial/grace days, OTP toggles, MSG91 keys, bank details, enforcement switches |
| PW Subscription Plan | Plan catalogue (also editable as a child table in Settings) |
| PW Subscription Log | Immutable audit trail of every lifecycle action |
| Payment Proof | Customer-submitted payment screenshots awaiting review |
| Site Provisioning Request | Tracks each site-creation job, its progress log and retries |
| Plans / Portal Page / Carousel / Carousel Item / City | Website & portal content (landing pages, sliders, registration city list) |

## Installation

Requires a Frappe **v15** bench (Python 3.10+).

```bash
cd ~/frappe-bench
bench get-app https://github.com/SafdarAliGit/pw_subscription
bench --site <your-site> install-app pw_subscription
bench --site <your-site> migrate
```

On install, the app seeds **PW Subscription Settings** with sensible defaults and starts a trial subscription for the current site.

## Configuration

Open **PW Subscription Settings** and set:

- `monthly_fee`, `trial_days`, `grace_period_days` — commercial terms
- `bank_details`, `contact_email`, `contact_phone` — shown to customers for manual payment
- `enable_email_otp` / `enable_phone_otp` (+ MSG91 auth key, template & sender IDs) — registration verification
- `enforce_subscription` — block logins on expired/suspended sites
- `auto_suspend_on_trial_expiry` / `auto_suspend_on_subscription_expiry` — automatic suspension
- `enable_renewal_reminders`, `reminder_days` — renewal email schedule

Grant the **PW Admin** role (or System Manager) to staff who should operate the Control Room — every admin API enforces it.

## Scheduled Jobs

| Frequency | Job | Purpose |
|---|---|---|
| Every tick | `api.push_server_stats_realtime` | Live server stats to the Control Room |
| Daily | `subscription_check.update_subscription_statuses` | Trial/Active/Grace → Expired transitions + auto-suspend |
| Daily | `subscription_check.send_renewal_reminders` | Renewal reminder emails |
| Daily | `subscription_check.auto_suspend_expired_sites` | Suspend expired sites per settings |

## Security Notes

- Admin/Control Room APIs are restricted to **System Manager** and **PW Admin** roles (`_require_portal_access`).
- Guest endpoints exist only where the public portal needs them (plans, OTP, registration, payment-proof submission validated against the subscription's email) and OTP/registration endpoints are **rate-limited**.
- Site operations (backup/restore/install/migrate) run through bench commands executed server-side; app names are validated against a strict pattern before use.

## Development

```bash
pip install ruff pre-commit
pre-commit install        # ruff + basic checks on every commit
ruff check pw_subscription
```

CI (GitHub Actions) runs Ruff, a full Python syntax pass, and JSON validation for all DocTypes on every push and pull request.

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 Safdar Ali.
