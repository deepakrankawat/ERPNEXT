const assert = require("node:assert/strict");
const path = require("node:path");

const handlers = new Map();
const emitted = [];
let serverMessages = [];

global.window = global;
Object.defineProperty(global, "navigator", { value: { onLine: true }, configurable: true });
global.document = { hidden: false, addEventListener() {} };
global.addEventListener = () => {};
global.setInterval = () => 0;
global.lex = { chat: {} };
global.frappe = {
	provide() {},
	realtime: {
		socket: { connected: true },
		on(event, callback) {
			if (!handlers.has(event)) handlers.set(event, []);
			handlers.get(event).push(callback);
		},
		emit(...args) { emitted.push(args); },
	},
	async call({ method, args }) {
		assert.match(method, /sync_messages$/);
		const messages = serverMessages.filter((message) => message.channel_sequence > Number(args.after_sequence || 0));
		return {
			message: {
				protocol_version: 1,
				messages,
				has_more: false,
				high_watermark: serverMessages.at(-1)?.channel_sequence || 0,
			},
		};
	},
};

const transportPath = path.resolve(__dirname, "../../public/js/lexocrates_realtime_transport.js");
require(transportPath);

const fire = (event, payload) => {
	for (const callback of handlers.get(event) || []) callback(payload);
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));
const message = (sequence) => ({
	protocol_version: 1,
	event_id: `chat-message:LCM-${sequence}:created`,
	name: `LCM-${sequence}`,
	channel: "LCC-TEST",
	channel_sequence: sequence,
	message_text: `Message ${sequence}`,
});

(async () => {
	serverMessages = [message(1), message(2)];
	const delivered = [];
	window.lexocratesReliableChat.subscribe("LCC-TEST", {
		afterSequence: 0,
		onMessage(value) { delivered.push(value.channel_sequence); },
	});
	await settle();
	assert.deepEqual(delivered, [1, 2], "initial recovery must deliver ordered history");

	fire("new_chat_message", message(2));
	assert.deepEqual(delivered, [1, 2], "duplicate Socket.IO delivery must be ignored");

	serverMessages = [message(1), message(2), message(3)];
	fire("disconnect");
	fire("connect");
	await settle();
	assert.deepEqual(delivered, [1, 2, 3], "reconnect must recover the missed sequence");
	assert.ok(
		emitted.filter((args) => args[0] === "doc_subscribe" && args[2] === "LCC-TEST").length >= 2,
		"document room must be restored after reconnect",
	);

	serverMessages = [message(1), message(2), message(3), message(4), message(5)];
	fire("new_chat_message", message(5));
	await settle();
	assert.deepEqual(delivered, [1, 2, 3, 4, 5], "a sequence gap must be repaired before delivery");

	let attempts = 0;
	const deliveryKeys = [];
	frappe.call = async ({ args }) => {
		attempts += 1;
		deliveryKeys.push(args.client_message_id);
		if (attempts === 1) throw { status: 503 };
		return { message: message(6) };
	};
	const sent = await window.lexocratesReliableChat.send({
		args: { channel: "LCC-TEST", message_text: "Retry safely" },
	});
	assert.equal(sent.channel_sequence, 6);
	assert.equal(attempts, 2);
	assert.equal(deliveryKeys[0], deliveryKeys[1], "all retries must reuse one idempotency key");

	console.log("Reliable chat transport tests passed");
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
