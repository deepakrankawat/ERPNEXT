const cookie = require("cookie");
const request = require("superagent");
const { get_url } = require("../utils");

const { get_conf } = require("../../node_utils");
const conf = get_conf();

function authenticate_with_frappe(socket, next) {
	let namespace = socket.nsp.name;
	namespace = namespace.slice(1, namespace.length); // remove leading `/`

	let site_name = get_site_name(socket);
	if (namespace && site_name && namespace !== site_name) {
		next(new Error("Invalid namespace"));
		return;
	}

	const host_name = get_hostname(socket.request.headers.host);
	const origin_name = get_hostname(socket.request.headers.origin);
	if (origin_name && host_name && origin_name !== host_name && host_name !== "127.0.0.1" && host_name !== "localhost") {
		next(new Error("Invalid origin"));
		return;
	}

	if (!socket.request.headers.cookie && !socket.request.headers.authorization) {
		next(
			new Error(
				"Missing cookie and authorization header. Either one needed for authentication."
			)
		);
		return;
	}

	let cookies = cookie.parse(socket.request.headers.cookie || "");
	let authorization_header = socket.request.headers.authorization;

	if (!cookies.sid && !authorization_header) {
		next(new Error("No authentication method used. Use cookie or authorization header."));
		return;
	}

	let auth_req = request
		.get(get_url(socket, "/api/method/frappe.realtime.get_user_info"))
		.set("Host", site_name || socket.request.headers.host || "")
		.set("X-Frappe-Site-Name", site_name || "");

	if (authorization_header) {
		auth_req = auth_req.set("Authorization", authorization_header);
	} else if (cookies.sid) {
		auth_req = auth_req.query({ sid: cookies.sid });
	}

	auth_req
		.type("form")
		.then((res) => {
			socket.user = res.body.message.user;
			socket.user_type = res.body.message.user_type;
			socket.sid = cookies.sid;
			socket.authorization_header = authorization_header;
			socket.site_name = site_name;
			next();
		})
		.catch((e) => {
			next(new Error(`Unauthorized: ${e}`));
		});
}

function get_site_name(socket) {
	if (socket.site_name) {
		return socket.site_name;
	} else if (socket.request.headers["x-frappe-site-name"]) {
		socket.site_name = get_hostname(socket.request.headers["x-frappe-site-name"]);
	} else if (socket.request.headers.origin && get_hostname(socket.request.headers.origin) !== "localhost" && get_hostname(socket.request.headers.origin) !== "127.0.0.1") {
		socket.site_name = get_hostname(socket.request.headers.origin);
	} else if (
		conf.default_site &&
		["localhost", "127.0.0.1"].indexOf(get_hostname(socket.request.headers.host)) !== -1
	) {
		socket.site_name = conf.default_site;
	} else if (socket.request.headers.origin) {
		socket.site_name = get_hostname(socket.request.headers.origin);
	} else {
		socket.site_name = get_hostname(socket.request.headers.host);
	}
	return socket.site_name;
}

function get_hostname(url) {
	if (!url) return undefined;
	if (url.indexOf("://") > -1) {
		url = url.split("/")[2];
	}
	return url.match(/:/g) ? url.slice(0, url.indexOf(":")) : url;
}

module.exports = authenticate_with_frappe;
