from frappe import _


def get_data():
	return {
		"fieldname": "engagement",
		"transactions": [
			{
				"label": _("Operational Work"),
				"items": ["LPO Job", "LPO QA Review", "LPO Compliance Log"],
			}
		],
	}
