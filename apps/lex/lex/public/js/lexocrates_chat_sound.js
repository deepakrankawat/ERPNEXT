(() => {
	"use strict";

	if (window.lexocratesChatSound) return;

	const STORAGE_KEY = "lex_chat_sound_muted";
	const CHANGE_EVENT = "lex-chat-sound-change";
	const recentSounds = new Map();
	let audioContext = null;

	function isMuted() {
		try {
			return window.localStorage.getItem(STORAGE_KEY) === "1";
		} catch (_) {
			return false;
		}
	}

	function setMuted(muted) {
		const next = Boolean(muted);
		try {
			window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
		} catch (_) {
			// The in-memory event still keeps all chat surfaces synchronized.
		}
		window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: { muted: next } }));
		return next;
	}

	function getContext() {
		if (audioContext) return audioContext;
		const AudioContextClass = window.AudioContext || window.webkitAudioContext;
		if (!AudioContextClass) return null;
		audioContext = new AudioContextClass();
		return audioContext;
	}

	async function unlock() {
		if (isMuted()) return false;
		try {
			const context = getContext();
			if (!context) return false;
			if (context.state === "suspended") await context.resume();
			return context.state === "running";
		} catch (_) {
			return false;
		}
	}

	function tone(context, frequency, startAt, duration, volume, type = "sine", endFrequency = null) {
		const oscillator = context.createOscillator();
		const gain = context.createGain();
		oscillator.type = type;
		oscillator.frequency.setValueAtTime(frequency, startAt);
		if (endFrequency) {
			oscillator.frequency.exponentialRampToValueAtTime(endFrequency, startAt + duration);
		}
		gain.gain.setValueAtTime(0.0001, startAt);
		gain.gain.exponentialRampToValueAtTime(volume, startAt + 0.018);
		gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
		oscillator.connect(gain);
		gain.connect(context.destination);
		oscillator.start(startAt);
		oscillator.stop(startAt + duration + 0.015);
	}

	function wasRecentlyPlayed(key) {
		if (!key) return false;
		const now = Date.now();
		for (const [savedKey, timestamp] of recentSounds) {
			if (now - timestamp > 10000) recentSounds.delete(savedKey);
		}
		if (recentSounds.has(key)) return true;
		recentSounds.set(key, now);
		return false;
	}

	async function play(kind = "incoming", key = null) {
		if (isMuted() || wasRecentlyPlayed(key)) return false;
		if (!(await unlock())) return false;
		try {
			const now = audioContext.currentTime + 0.01;
			if (kind === "sent") {
				// A restrained, short confirmation: distinct from an incoming alert.
				tone(audioContext, 493.88, now, 0.13, 0.035, "sine", 659.25);
			} else {
				// Two gentle notes make an incoming message noticeable without sounding harsh.
				tone(audioContext, 659.25, now, 0.16, 0.045, "sine");
				tone(audioContext, 783.99, now + 0.11, 0.19, 0.04, "sine");
			}
			return true;
		} catch (_) {
			return false;
		}
	}

	window.lexocratesChatSound = Object.freeze({
		CHANGE_EVENT,
		isMuted,
		setMuted,
		unlock,
		play,
	});
})();
