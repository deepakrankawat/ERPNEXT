frappe.provide("lex.chat");

(() => {
	if (window.lexocratesReliableChat) return;

	const API_ROOT = "lex.lex.page.lexocrates_chat.lexocrates_chat";
	const RECONCILE_MS = 20000;
	const MAX_SEEN_EVENTS = 2500;

	class ReliableChatTransport {
		constructor() {
			this.channels = new Map();
			this.connected = Boolean(frappe.realtime?.socket?.connected);
			this.socketBound = false;
			this.bindRetry = null;
			this._bindSocket();
			this.timer = window.setInterval(() => this.recoverAll("reconcile"), RECONCILE_MS);
			window.addEventListener("online", () => this.recoverAll("online"));
			document.addEventListener("visibilitychange", () => {
				if (!document.hidden) this.recoverAll("visible");
			});
		}

		_bindSocket() {
			if (this.socketBound) return;
			if (!frappe.realtime?.socket) {
				window.clearTimeout(this.bindRetry);
				this.bindRetry = window.setTimeout(() => this._bindSocket(), 100);
				return;
			}
			this.socketBound = true;
			this.connected = Boolean(frappe.realtime.socket?.connected);
			frappe.realtime.on("new_chat_message", (message) => this._receive(message, "socket"));
			frappe.realtime.on("connect", () => {
				this.connected = true;
				for (const channel of this.channels.keys()) this._join(channel);
				this.recoverAll("reconnect");
			});
			frappe.realtime.on("disconnect", () => {
				this.connected = false;
				for (const entry of this.channels.values()) this._state(entry, "offline");
			});
			frappe.realtime.on("connect_error", () => {
				for (const entry of this.channels.values()) this._state(entry, "reconnecting");
			});
		}

		makeClientMessageId() {
			if (window.crypto?.randomUUID) return window.crypto.randomUUID();
			return `web:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 14)}`;
		}

		subscribe(channel, options = {}) {
			if (!channel) throw new Error("A chat channel is required");
			this._bindSocket();
			let entry = this.channels.get(channel);
			if (!entry) {
				entry = { channel, highWater: 0, listeners: new Map(), seen: new Map(), pending: new Map(), recovering: null };
				this.channels.set(channel, entry);
			}
			const initial = typeof options.afterSequence === "function" ? options.afterSequence() : options.afterSequence;
			entry.highWater = Math.max(entry.highWater, Number(initial || 0));
			const token = Symbol(channel);
			entry.listeners.set(token, options);
			this._join(channel);
			this._state(entry, this.connected ? "recovering" : "offline");
			this.recover(channel, "subscribe");
			return () => this.unsubscribe(channel, token);
		}

		unsubscribe(channel, token) {
			const entry = this.channels.get(channel);
			if (!entry) return;
			entry.listeners.delete(token);
			if (entry.listeners.size) return;
			frappe.realtime?.emit("doc_unsubscribe", "Lexocrates Chat Channel", channel);
			this.channels.delete(channel);
		}

		_join(channel) {
			// Frappe's open_docs cache survives reconnect while Socket.IO rooms do not.
			// A raw emit restores the room; the server still runs its permission check.
			frappe.realtime?.emit("doc_subscribe", "Lexocrates Chat Channel", channel);
		}

		getHighWater(channel) {
			return Number(this.channels.get(channel)?.highWater || 0);
		}

		async recoverAll(reason = "manual") {
			if (navigator.onLine === false) return;
			await Promise.allSettled([...this.channels.keys()].map((channel) => this.recover(channel, reason)));
		}

		async recover(channel, reason = "manual") {
			const entry = this.channels.get(channel);
			if (!entry) return;
			if (entry.recovering) return entry.recovering;
			entry.recovering = this._recover(entry, reason).finally(() => { entry.recovering = null; });
			return entry.recovering;
		}

		async _recover(entry, reason) {
			this._state(entry, "recovering", reason);
			let hasMore = true;
			let pages = 0;
			try {
				while (hasMore && pages < 20) {
					const response = await frappe.call({
						method: `${API_ROOT}.sync_messages`,
						args: { channel: entry.channel, after_sequence: entry.highWater, limit: 200 },
						freeze: false,
					});
					const data = response.message || {};
					for (const message of data.messages || []) this._receive(message, "recovery");
					hasMore = Boolean(data.has_more);
					pages += 1;
					if (!data.messages?.length) break;
				}
				this._flush(entry);
				this._state(entry, this.connected ? "live" : "offline", reason);
			} catch (error) {
				this._state(entry, this.connected ? "degraded" : "offline", reason, error);
				throw error;
			}
		}

		_receive(message, source) {
			if (!message?.channel || !message?.name) return;
			const entry = this.channels.get(message.channel);
			if (!entry) return;
			const key = message.event_id || message.name;
			if (entry.seen.has(key) || entry.seen.has(message.name)) return;
			const sequence = Number(message.channel_sequence || 0);
			if (sequence && sequence <= entry.highWater) {
				this._remember(entry, key, message.name);
				return;
			}
			if (sequence && sequence > entry.highWater + 1) {
				entry.pending.set(sequence, { message, source });
				this.recover(entry.channel, "gap");
				return;
			}
			this._deliver(entry, message, source);
			this._flush(entry);
		}

		_deliver(entry, message, source) {
			const sequence = Number(message.channel_sequence || 0);
			if (sequence) entry.highWater = Math.max(entry.highWater, sequence);
			this._remember(entry, message.event_id || message.name, message.name);
			for (const listener of entry.listeners.values()) {
				try { listener.onMessage?.(message, { source }); } catch (error) { console.error(error); }
			}
		}

		_flush(entry) {
			while (entry.pending.has(entry.highWater + 1)) {
				const item = entry.pending.get(entry.highWater + 1);
				entry.pending.delete(entry.highWater + 1);
				this._deliver(entry, item.message, item.source);
			}
		}

		_remember(entry, ...keys) {
			for (const key of keys.filter(Boolean)) entry.seen.set(key, Date.now());
			while (entry.seen.size > MAX_SEEN_EVENTS) entry.seen.delete(entry.seen.keys().next().value);
		}

		_state(entry, state, reason = null, error = null) {
			for (const listener of entry.listeners.values()) {
				try { listener.onState?.({ channel: entry.channel, state, reason, error }); } catch (e) { console.error(e); }
			}
		}

		async send({ method = `${API_ROOT}.send_message`, args = {}, retries = 3 } = {}) {
			const clientMessageId = args.client_message_id || this.makeClientMessageId();
			const requestArgs = { ...args, client_message_id: clientMessageId };
			let lastError;
			for (let attempt = 0; attempt < Math.max(1, retries); attempt += 1) {
				try {
					const response = await frappe.call({ method, args: requestArgs, freeze: false });
					return response.message;
				} catch (error) {
					lastError = error;
					if (!this._retryable(error) || attempt + 1 >= retries) break;
					await new Promise((resolve) => setTimeout(resolve, 500 * (2 ** attempt) + Math.random() * 250));
				}
			}
			if (lastError && typeof lastError === "object") lastError.client_message_id = clientMessageId;
			throw lastError;
		}

		_retryable(error) {
			const status = Number(error?.httpStatus || error?.status || error?.xhr?.status || 0);
			return !status || [408, 425, 429, 502, 503, 504].includes(status);
		}
	}

	window.lexocratesReliableChat = new ReliableChatTransport();
	lex.chat.realtime = window.lexocratesReliableChat;
})();
