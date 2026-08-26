import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const storage = new Map();
const events = [];
const oscillators = [];

class MockAudioParam {
	setValueAtTime() {}
	exponentialRampToValueAtTime() {}
}

class MockOscillator {
	constructor() {
		this.frequency = new MockAudioParam();
		this.type = "sine";
		oscillators.push(this);
	}
	connect() {}
	start() {}
	stop() {}
}

class MockGain {
	constructor() {
		this.gain = new MockAudioParam();
	}
	connect() {}
}

class MockAudioContext {
	constructor() {
		this.currentTime = 1;
		this.destination = {};
		this.state = "running";
	}
	createOscillator() { return new MockOscillator(); }
	createGain() { return new MockGain(); }
	async resume() { this.state = "running"; }
}

class MockCustomEvent {
	constructor(type, init = {}) {
		this.type = type;
		this.detail = init.detail;
	}
}

const window = {
	AudioContext: MockAudioContext,
	localStorage: {
		getItem: (key) => storage.get(key) ?? null,
		setItem: (key, value) => storage.set(key, String(value)),
	},
	dispatchEvent: (event) => events.push(event),
};

const source = fs.readFileSync(
	new URL("../lex/public/js/lexocrates_chat_sound.js", import.meta.url),
	"utf8",
);
vm.runInNewContext(source, { window, CustomEvent: MockCustomEvent, Date, Map, Object, Boolean });

const sound = window.lexocratesChatSound;
assert.ok(sound, "shared sound controller is installed");
assert.equal(sound.isMuted(), false);

sound.setMuted(true);
assert.equal(sound.isMuted(), true);
assert.equal(events.at(-1).detail.muted, true);
assert.equal(await sound.play("incoming", "message:muted"), false);
assert.equal(oscillators.length, 0, "muted messages must not create a tone");

sound.setMuted(false);
assert.equal(await sound.play("incoming", "message:one"), true);
assert.equal(oscillators.length, 2, "incoming sound uses two soft notes");
assert.equal(await sound.play("incoming", "message:one"), false);
assert.equal(oscillators.length, 2, "the same realtime event is de-duplicated");

assert.equal(await sound.play("sent", "message:sent"), true);
assert.equal(oscillators.length, 3, "sent confirmation uses one short note");

console.log("chat sound controller: OK");
