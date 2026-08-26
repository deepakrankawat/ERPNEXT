const request = require("superagent");
const { get_conf } = require("../node_utils");
const conf = get_conf();

function get_url(socket, path) {
	if (!path) {
		path = "";
	}
	const web_port = conf.webserver_port || 8000;
	return `http://127.0.0.1:${web_port}${path}`;
}

// Authenticates a partial request created using superagent
function frappe_request(path, socket) {
	const site_name = socket.site_name || socket.nsp?.name?.replace(/^\//, "") || "";
	const partial_req = request
		.get(get_url(socket, path))
		.set("Host", site_name || socket.request.headers.host || "")
		.set("X-Frappe-Site-Name", site_name || "");

	if (socket.authorization_header) {
		return partial_req.set("Authorization", socket.authorization_header);
	} else if (socket.sid) {
		return partial_req.query({ sid: socket.sid });
	}
	return partial_req;
}

module.exports = {
	get_url,
	frappe_request,
};
