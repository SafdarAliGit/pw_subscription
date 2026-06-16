frappe.ui.form.on("Site Provisioning Request", {
    refresh(frm) {
        frm.disable_save();

        if (frm.doc.status === "Failed" || frm.doc.status === "Pending") {
            frm.add_custom_button("Retry Site Creation", () => {
                frappe.confirm(
                    `Retry provisioning for <b>${frm.doc.site_name}</b>?`,
                    () => {
                        frappe.call({
                            method: "pw_subscription.site_provisioning.retry_site_creation",
                            args: { request_name: frm.doc.name },
                            freeze: true,
                            freeze_message: "Queuing retry…",
                            callback(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({ message: "Retry queued. Refreshing…", indicator: "blue" });
                                    setTimeout(() => frm.reload_doc(), 2000);
                                }
                            }
                        });
                    }
                );
            }, "Actions").addClass("btn-primary");
        }

        if (frm.doc.status === "In Progress") {
            frm.add_custom_button("Refresh Progress", () => frm.reload_doc(), "Actions");
            // Auto-refresh every 5 seconds while in progress
            if (!frm._auto_refresh) {
                frm._auto_refresh = setInterval(() => {
                    if (frm.doc.status === "In Progress") {
                        frm.reload_doc();
                    } else {
                        clearInterval(frm._auto_refresh);
                        frm._auto_refresh = null;
                    }
                }, 5000);
            }
        }

        if (frm.doc.status === "Success" && frm.doc.site_url) {
            frm.add_custom_button("Open Site", () => {
                window.open(frm.doc.site_url, "_blank");
            }, "Actions").addClass("btn-success");
        }

        // Color-code status indicator
        const color_map = {
            "Pending": "orange",
            "In Progress": "blue",
            "Success": "green",
            "Failed": "red"
        };
        frm.set_indicator_formatter("status", () => color_map[frm.doc.status] || "grey");
    },

    onload(frm) {
        // Clear auto-refresh when form is closed
        frm.events.refresh(frm);
    }
});
