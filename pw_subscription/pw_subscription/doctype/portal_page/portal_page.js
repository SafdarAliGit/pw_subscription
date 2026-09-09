frappe.listview_settings["Portal Page"] = {
	onload(listview) {
		listview.page.add_action_item(__("Sync Pages from www"), () => {
			frappe.confirm(
				__("Scan the app's <code>www</code> folder and create missing Portal Page records for every <code>.html</code> file found?"),
				() => {
					frappe.call({
						method: "pw_subscription.pw_subscription.doctype.portal_page.portal_page.sync_pages_from_www",
						freeze: true,
						freeze_message: __("Scanning www folder…"),
						callback(r) {
							if (r.message) {
								const { created, skipped } = r.message;
								frappe.msgprint(
									__("{0} page(s) added, {1} already existed.", [created, skipped]),
									__("Sync Complete")
								);
								listview.refresh();
							}
						},
					});
				}
			);
		});
	},
};
