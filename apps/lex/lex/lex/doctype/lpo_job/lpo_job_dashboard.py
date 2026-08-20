from frappe import _


def get_data():
	return {
		"fieldname": "job",
		"non_standard_fieldnames": {"LPO Channel": "reference_name"},
		"transactions": [
			{"label": _("Quality and Governance"), "items": ["LPO QA Review", "LPO Compliance Log"]},
			{"label": _("Communication"), "items": ["LPO Channel"]},
		],
	}
