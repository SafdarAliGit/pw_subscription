app_name = "pw_subscription"
app_title = "PW Subscription"
app_publisher = "Safdar Ali"
app_description = "SaaS Subscription Management for CureDesk"
app_email = "safdar211@gmail.com"
app_license = "MIT"

after_install = "pw_subscription.install.after_install"

boot_session = "pw_subscription.subscription_check.add_subscription_to_boot"

on_session_creation = "pw_subscription.subscription_check.on_session_creation"

scheduler_events = {
    "daily": [
        "pw_subscription.subscription_check.update_subscription_statuses",
    ]
}
