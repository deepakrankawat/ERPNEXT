const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.window = global;
global.document = { hidden: false };
global.frappe = { pages: { "lexocrates-chat": {} } };

const sourcePath = path.resolve(
	__dirname,
	"../../lex/page/lexocrates_chat/lexocrates_chat.js",
);
const source = fs.readFileSync(sourcePath, "utf8");
vm.runInThisContext(
	`${source}\nglobalThis.LexocratesChatPageForTest = LexocratesChatPage;`,
	{ filename: sourcePath },
);

const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

(async () => {
	const calls = [];
	let releaseFirstCall;
	global.frappe.call = async ({ args }) => {
		calls.push(args);
		if (calls.length === 1) {
			await new Promise((resolve) => {
				releaseFirstCall = resolve;
			});
		}
	};

	const page = Object.create(global.LexocratesChatPageForTest.prototype);
	page.api = "lex.lex.page.lexocrates_chat.lexocrates_chat";
	page.read_timer = null;
	page.read_inflight = false;
	page.pending_read_states = new Map();

	page.selected_channel = "CHANNEL-A";
	page.mark_read("MESSAGE-A");
	const firstFlush = page.flush_read_state();
	await Promise.resolve();

	page.selected_channel = "CHANNEL-B";
	page.mark_read("MESSAGE-B");
	releaseFirstCall();
	await firstFlush;
	await settle();

	assert.deepEqual(calls, [
		{ channel: "CHANNEL-A", message_name: "MESSAGE-A" },
		{ channel: "CHANNEL-B", message_name: "MESSAGE-B" },
	]);
	console.log("Chat read marker channel-switch regression test passed");
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
