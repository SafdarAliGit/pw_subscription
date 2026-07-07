app_name = "pw_subscription"
app_title = "PW Subscription"
app_publisher = "Safdar Ali"
app_description = "SaaS Subscription Management for CureDesk"
app_email = "safdar211@gmail.com"
app_license = "MIT"

add_to_apps_screen = [
    {
        "name": "pw_subscription",
        "title": "PW Subscription",
        "route": "/control-room",
        "has_permission": "pw_subscription.api.has_app_permission",
    }
]

after_install = "pw_subscription.install.after_install"

fixtures = [
    {"dt": "City"}
]

boot_session = "pw_subscription.subscription_check.add_subscription_to_boot"

on_session_creation = "pw_subscription.subscription_check.on_session_creation"

scheduler_events = {
    "all": [
        "pw_subscription.api.push_server_stats_realtime",
    ],
    "daily": [
        "pw_subscription.subscription_check.update_subscription_statuses",
        "pw_subscription.subscription_check.send_renewal_reminders",
        "pw_subscription.subscription_check.auto_suspend_expired_sites",
    ]
}
