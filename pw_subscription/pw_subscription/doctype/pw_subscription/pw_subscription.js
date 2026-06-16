frappe.ui.form.on("PW Subscription", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button("Activate / Renew", () => {
                const d = new frappe.ui.Dialog({
                    title: "Activate Subscription",
                    fields: [
                        {label: "Subscription End Date", fieldname: "end_date", fieldtype: "Date", reqd: 1},
                        {label: "Payment Reference", fieldname: "payment_reference", fieldtype: "Data"},
                        {label: "Notes", fieldname: "notes", fieldtype: "Small Text"},
                    ],
                    primary_action_label: "Activate",
                    primary_action(values) {
                        frappe.call({
                            method: "pw_subscription.api.activate_subscription",
                            args: {
                                end_date: values.end_date,
                                payment_reference: values.payment_reference,
                                notes: values.notes,
                            },
                            callback(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({ message: "Subscription activated!", indicator: "green" });
                                    frm.reload_doc();
                                }
                            }
                        });
                        d.hide();
                    }
                });
                d.show();
            }, "Actions");

            frm.add_custom_button("Extend Trial", () => {
                frappe.prompt(
                    [{label: "Extra Days", fieldname: "days", fieldtype: "Int", default: 7}],
                    (values) => {
                        frappe.call({
                            method: "pw_subscription.api.extend_trial",
                            args: { extra_days: values.days },
                            callback(r) {
                                if (r.message) {
                                    frappe.show_alert({ message: `Trial extended to ${r.message.new_end}`, indicator: "green" });
                                    frm.reload_doc();
                                }
                            }
                        });
                    },
                    "Extend Trial Period",
                    "Extend"
                );
            }, "Actions");
        }

        const statusColors = {
            "Trial": "blue",
            "Active": "green",
            "Grace Period": "orange",
            "Expired": "red",
            "Cancelled": "gray"
        };
        const color = statusColors[frm.doc.status] || "gray";
        frm.dashboard.set_headline(`<span class="indicator ${color}">${frm.doc.status}</span>`);
    }
});
