frappe.ui.form.on("PW Subscription Settings", {
    refresh(frm) {
        frm.add_custom_button("View Subscriptions", () => {
            frappe.set_route("List", "PW Subscription");
        });
        frm.add_custom_button("Subscription Portal", () => {
            window.open("/subscription-portal", "_blank");
        });
    }
});
