app_name = "pw_subscription"
app_title = "PW Subscription"
app_publisher = "Safdar Ali"
app_description = "SaaS Subscription Management for CoreLogics"
app_email = "safdar211@gmail.com"
app_license = "MIT"
app_logo_url = "/assets/pw_subscription/images/logo.png"

# ──────────────────────────────────────────────────────────────────
# WEBSITE ROUTE RULES
# Map custom URL patterns to web page routes.
# ──────────────────────────────────────────────────────────────────
# website_route_rules = [
#     {"from_route": "/control-room",        "to_route": "control-room"},
#     {"from_route": "/subscription-portal", "to_route": "subscription-portal"},
#     {"from_route": "/subscription-invoice","to_route": "subscription-invoice"},
# ]

# ──────────────────────────────────────────────────────────────────
# APP SCREEN
# Registers the app on the Frappe home/apps screen.
# has_permission must return True for the user to see the tile.
# ──────────────────────────────────────────────────────────────────
add_to_apps_screen = [
    {
        "name": "pw_subscription",
        "logo": "/assets/pw_subscription/images/logo.png",
        "title": "PW Subscription",
        "route": "/control-room",
        "has_permission": "pw_subscription.api.has_app_permission",
    }
]

# ──────────────────────────────────────────────────────────────────
# ASSET INCLUDES
# Inject JS / CSS into the desk (app_include_*) or into public
# web/portal pages (web_include_*).
# ──────────────────────────────────────────────────────────────────
# app_include_js = ["/assets/pw_subscription/js/pw_subscription.js"]
# app_include_css = ["/assets/pw_subscription/css/pw_subscription.css"]

# web_include_js = ["/assets/pw_subscription/js/portal.js"]
# web_include_css = ["/assets/pw_subscription/css/portal.css"]

# ──────────────────────────────────────────────────────────────────
# DOCTYPE JS / LIST JS
# Load extra JS on specific Doctype form or list views.
# ──────────────────────────────────────────────────────────────────
# doctype_js = {
#     "PW Subscription Plan": "public/js/subscription_plan.js",
# }
# doctype_list_js = {
#     "PW Subscription Plan": "public/js/subscription_plan_list.js",
# }

# ──────────────────────────────────────────────────────────────────
# INSTALLATION & MIGRATION
# after_install  — runs once when the app is installed on a site.
# after_migrate  — runs after every `bench migrate`.
# before_uninstall — cleanup before the app is removed.
# ──────────────────────────────────────────────────────────────────
after_install = "pw_subscription.install.after_install"
# after_migrate    = "pw_subscription.install.after_migrate"
# before_uninstall = "pw_subscription.install.before_uninstall"

# ──────────────────────────────────────────────────────────────────
# FIXTURES
# Exported with `bench export-fixtures` and imported on install.
# NOTE: Only City is exported. Subscription Plans and Tiers are
# seeded by install.py to avoid conflicts with site-specific config.
# ──────────────────────────────────────────────────────────────────
fixtures = [
    {"dt": "City"}
    # {"dt": "Role", "filters": [["role_name", "in", ["PW Subscription Admin"]]]},
    # {"dt": "Custom Field", "filters": [["dt", "in", ["PW Subscription Plan"]]]},
    # {"dt": "Property Setter"},
    # {"dt": "Print Format"},
    # {"dt": "Notification"},
]

# ──────────────────────────────────────────────────────────────────
# BOOT SESSION
# Called once per login; return value is merged into frappe.boot
# so the client can access it via frappe.boot.* without an extra API call.
# ──────────────────────────────────────────────────────────────────
boot_session = "pw_subscription.subscription_check.add_subscription_to_boot"

# ──────────────────────────────────────────────────────────────────
# SESSION CREATION
# Fired right after a new session is created (login).
# Used here to validate subscription status and block suspended sites.
# ──────────────────────────────────────────────────────────────────
on_session_creation = "pw_subscription.subscription_check.on_session_creation"

# ──────────────────────────────────────────────────────────────────
# DOC EVENTS
# Hook into standard Frappe document lifecycle events.
# Keys are Doctype names; values are dicts of event → dotted path.
# Common events: before_insert, after_insert, validate, on_update,
#                on_submit, on_cancel, on_trash, after_delete
# ──────────────────────────────────────────────────────────────────
# doc_events = {
#     "PW Subscription Plan": {
#         "on_update": "pw_subscription.subscription_check.on_plan_update",
#     },
#     "PW Subscribed Site": {
#         "validate":  "pw_subscription.subscription_check.validate_site",
#         "on_update": "pw_subscription.subscription_check.on_site_update",
#         "on_trash":  "pw_subscription.subscription_check.on_site_delete",
#     },
# }

# ──────────────────────────────────────────────────────────────────
# OVERRIDE DOCTYPE CLASS
# Replace Frappe / ERPNext doctype controllers with custom subclasses.
# ──────────────────────────────────────────────────────────────────
# override_doctype_class = {
#     "PW Subscription Plan": "pw_subscription.overrides.CustomSubscriptionPlan",
# }

# ──────────────────────────────────────────────────────────────────
# OVERRIDE WHITELISTED METHODS
# Swap out a core whitelisted API with a custom implementation.
# ──────────────────────────────────────────────────────────────────
# override_whitelisted_methods = {
#     "frappe.client.get": "pw_subscription.api.custom_get",
# }

# ──────────────────────────────────────────────────────────────────
# PERMISSION QUERY CONDITIONS
# Append extra WHERE conditions to list queries for row-level security.
# Return a SQL fragment string, e.g. "`tabDoctype`.owner = 'Administrator'"
# ──────────────────────────────────────────────────────────────────
# permission_query_conditions = {
#     "PW Subscribed Site": "pw_subscription.api.get_site_permission_query",
# }

# ──────────────────────────────────────────────────────────────────
# HAS PERMISSION
# Fine-grained document-level access control.
# Function receives (doc, ptype, user) and returns True/False.
# ──────────────────────────────────────────────────────────────────
# has_permission = {
#     "PW Subscribed Site": "pw_subscription.api.has_site_permission",
# }

# ──────────────────────────────────────────────────────────────────
# NOTIFICATION CONFIG
# Define badge-count notifications shown on the desk bell icon.
# ──────────────────────────────────────────────────────────────────
# notification_config = "pw_subscription.notifications.get_notification_config"

# ──────────────────────────────────────────────────────────────────
# JINJA CUSTOMIZATION
# Expose Python helpers to Jinja print-format / web templates.
# ──────────────────────────────────────────────────────────────────
# jinja = {
#     "methods": [
#         "pw_subscription.utils.format_subscription_date",
#         "pw_subscription.utils.get_plan_label",
#     ],
#     "filters": [
#         "pw_subscription.utils.currency_filter",
#     ],
# }

# ──────────────────────────────────────────────────────────────────
# TESTING
# before_tests — seed data or configuration needed before the test suite runs.
# ──────────────────────────────────────────────────────────────────
# before_tests = "pw_subscription.tests.setup.before_tests"

# ──────────────────────────────────────────────────────────────────
# SCHEDULED JOBS
# "all"     — every scheduler tick (~5 min by default)
# "hourly"  — once per hour
# "daily"   — once per day  (recommended for subscription lifecycle)
# "weekly"  — once per week
# "monthly" — once per month
# "cron"    — standard cron expression for fine-grained control
#               e.g. "0 9 * * 1-5" = 09:00 Mon–Fri
# ──────────────────────────────────────────────────────────────────
scheduler_events = {
    # Runs on every scheduler tick — pushes live server stats to Control Room via realtime
    "all": [
        "pw_subscription.api.push_server_stats_realtime",
    ],
    # "hourly": [
    #     "pw_subscription.subscription_check.hourly_sync",
    # ],
    # Runs once per day — handles full subscription lifecycle management
    "daily": [
        "pw_subscription.subscription_check.update_subscription_statuses",   # mark expired / active
        "pw_subscription.subscription_check.send_renewal_reminders",         # email alerts before expiry
        "pw_subscription.subscription_check.auto_suspend_expired_sites",     # suspend overdue sites
    ],
    # "weekly": [
    #     "pw_subscription.subscription_check.weekly_report",
    # ],
    # "monthly": [
    #     "pw_subscription.subscription_check.generate_monthly_invoices",
    # ],
    # "cron": {
    #     "0 8 * * *": [
    #         "pw_subscription.subscription_check.morning_health_check",
    #     ],
    # },
}
