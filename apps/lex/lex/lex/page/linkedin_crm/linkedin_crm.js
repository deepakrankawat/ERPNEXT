frappe.pages["linkedin-crm"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "LinkedIn CRM & Social Engagement",
		single_column: true,
	});
	wrapper.linkedin_crm = new LinkedInCRMPage(page);
};

class LinkedInCRMPage {
	constructor(page) {
		this.page = page;
		this.currentTab = "inbox"; // Default directly to the requested Live Messages & Inbox Tab!
		this.data = null;
		this.status = null;
		this.inboxConversations = [];
		this.activeConvId = "conv_1";
		this.init();
	}

	init() {
		this.page.set_primary_action(__("Sync Live Data"), () => this.refreshCurrent(), "octicon octicon-sync");
		this.page.add_button(__("Configure .env"), () => this.showConfigDialog());
		this.loadInitialData();
	}

	refreshCurrent() {
		if (this.currentTab === "inbox") {
			this.loadInboxData(true);
		} else {
			this.loadOverviewData(true);
		}
	}

	loadInitialData() {
		frappe.show_progress(__("Loading LinkedIn Module"), 20, 100);
		frappe.call({
			method: "lex.linkedin_crm.get_linkedin_status",
			callback: (r) => {
				this.status = r.message || {};
				frappe.show_progress(__("Connecting to LinkedIn Messages"), 50, 100);
				this.loadInboxData(false, () => {
					this.loadOverviewData(false, () => {
						frappe.hide_progress();
						this.render();
					});
				});
			}
		});
	}

	loadInboxData(reRender = true, done = null) {
		frappe.call({
			method: "lex.linkedin_crm.get_linkedin_inbox",
			callback: (res) => {
				const d = res.message || {};
				this.inboxConversations = d.conversations || [];
				if (this.inboxConversations.length && !this.activeConvId) {
					this.activeConvId = this.inboxConversations[0].id;
				}
				if (reRender) {
					this.render();
				}
				if (done) done();
			},
			error: () => {
				if (done) done();
			}
		});
	}

	loadOverviewData(reRender = true, done = null) {
		frappe.call({
			method: "lex.linkedin_crm.get_linkedin_analytics",
			args: { period: "monthly" },
			callback: (res) => {
				this.data = res.message || {};
				if (reRender) {
					this.render();
				}
				if (done) done();
			},
			error: () => {
				if (done) done();
			}
		});
	}

	esc(v) {
		return frappe.utils.escape_html(v == null ? "" : String(v));
	}

	render() {
		const st = this.status || {};
		const isLive = Boolean(st.is_configured);
		const totalUnread = this.inboxConversations.reduce((sum, c) => sum + (c.unread_count || 0), 0);

		const html = `
			<div class="linkedin-crm-page">
				<!-- Header Status Card -->
				<div class="linkedin-header-card">
					<div class="linkedin-brand-badge">
						<div class="linkedin-logo-icon">in</div>
						<div>
							<h4 style="margin: 0; font-size: 18px; font-weight: 700; color: #111827;">
								Company Page Social CRM
							</h4>
							<p style="margin: 4px 0 0 0; font-size: 13px; color: #6b7280;">
								Real-time LinkedIn Direct Messages, live prospect chats & CRM lead conversion.
							</p>
						</div>
					</div>
					<div>
						<span class="linkedin-status-badge ${isLive ? 'live' : 'demo'}">
							<span style="font-size: 10px;">●</span>
							${isLive ? `Live Connected (Org ID: ${this.esc(st.organization_id)})` : `Demo/Sandbox Mode (Read from .env)`}
						</span>
					</div>
				</div>

				<!-- Tab Navigation -->
				<div class="linkedin-tabs-nav">
					<button class="linkedin-tab-btn ${this.currentTab === 'inbox' ? 'active' : ''}" data-tab="inbox">
						💬 LinkedIn Live Messages & Inbox
						${totalUnread > 0 ? `<span class="tab-badge">${totalUnread}</span>` : ""}
					</button>
					<button class="linkedin-tab-btn ${this.currentTab === 'overview' ? 'active' : ''}" data-tab="overview">
						📊 Overview & Social Engagement
					</button>
				</div>

				<!-- Tab 1: LIVE MESSAGES & INBOX -->
				<div id="tab-inbox-view" style="${this.currentTab === 'inbox' ? 'display:block;' : 'display:none;'}">
					${this.renderInboxHTML()}
				</div>

				<!-- Tab 2: OVERVIEW & POSTS -->
				<div id="tab-overview-view" style="${this.currentTab === 'overview' ? 'display:block;' : 'display:none;'}">
					${this.renderOverviewHTML()}
				</div>
			</div>
		`;

		this.page.body.html(html);
		this.attachEvents();
		this.scrollChatToBottom();
	}

	renderInboxHTML() {
		const convs = this.inboxConversations || [];
		const activeConv = convs.find(c => c.id === this.activeConvId) || convs[0] || {};
		const messages = activeConv.messages || [];

		return `
			<div class="linkedin-inbox-container">
				<!-- Left Conversation Sidebar -->
				<div class="inbox-sidebar">
					<div class="inbox-search-header">
						<input type="text" class="inbox-search-input" id="inbox-search" placeholder="🔍 Search prospect or company..." />
					</div>
					<div class="conversation-list" id="conv-list-container">
						${convs.map(c => `
							<div class="conversation-item ${c.id === this.activeConvId ? 'active' : ''}" data-conv-id="${this.esc(c.id)}">
								<div class="conv-avatar-wrap">
									<img class="conv-avatar" src="${this.esc(c.avatar)}" alt="${this.esc(c.prospect_name)}" onerror="this.src='/assets/frappe/images/default-avatar/avatar_1.png'" />
									${c.online_status && c.online_status.includes("Active") ? '<span class="online-dot"></span>' : ''}
								</div>
								<div class="conv-details">
									<div class="conv-top-row">
										<span class="conv-name">${this.esc(c.prospect_name)}</span>
										<span class="conv-time">${this.esc(c.last_time)}</span>
									</div>
									<div class="conv-headline">${this.esc(c.headline || 'Prospect')}</div>
									<div class="conv-snippet-row">
										<span class="conv-snippet">${this.esc(c.last_message || '')}</span>
										${c.unread_count > 0 ? `<span class="conv-unread-badge">${c.unread_count}</span>` : ''}
									</div>
								</div>
							</div>
						`).join("")}
					</div>
				</div>

				<!-- Right Chat View -->
				<div class="inbox-chat-panel">
					${activeConv.id ? `
						<div class="chat-header">
							<div class="chat-prospect-info">
								<img class="conv-avatar" src="${this.esc(activeConv.avatar)}" alt="${this.esc(activeConv.prospect_name)}" onerror="this.src='/assets/frappe/images/default-avatar/avatar_1.png'" />
								<div>
									<h5 class="chat-prospect-name">${this.esc(activeConv.prospect_name)}</h5>
									<p class="chat-prospect-sub">${this.esc(activeConv.headline)} · <span style="color:#10b981;">${this.esc(activeConv.online_status)}</span></p>
								</div>
							</div>
							<div style="display: flex; gap: 8px;">
								<button class="btn btn-xs btn-default open-linkedin-profile-btn" data-name="${this.esc(activeConv.prospect_name)}">
									🔗 LinkedIn Profile
								</button>
								<button class="btn btn-xs btn-primary convert-inbox-lead-btn" 
									data-name="${this.esc(activeConv.prospect_name)}" 
									data-headline="${this.esc(activeConv.headline)}"
									data-last-msg="${this.esc(activeConv.last_message)}">
									➕ Convert to CRM Lead
								</button>
							</div>
						</div>

						<!-- Messages Stream -->
						<div class="chat-messages-stream" id="chat-messages-stream">
							${messages.map(m => `
								<div class="chat-bubble-row ${m.is_self ? 'outbound' : 'inbound'}">
									<div class="chat-bubble">${this.esc(m.text)}</div>
									<div class="chat-bubble-meta">
										${this.esc(m.sender)} · ${this.esc(m.timestamp)} ${m.status ? `· <span style="color:#059669;">✔ ${this.esc(m.status)}</span>` : ''}
									</div>
								</div>
							`).join("")}
						</div>

						<!-- Chat Input Bar -->
						<div class="chat-input-bar">
							<textarea class="chat-textarea" id="inbox-chat-input" placeholder="Type a message to ${this.esc(activeConv.prospect_name)}... (Press Enter to Send)" rows="1"></textarea>
							<button class="chat-send-btn" id="inbox-send-btn">
								<span>Send</span>
								<span>✈</span>
							</button>
						</div>
					` : `
						<div class="text-muted text-center p-5" style="margin: auto;">
							Select a conversation from the left to start messaging.
						</div>
					`}
				</div>
			</div>
		`;
	}

	renderOverviewHTML() {
		const d = this.data || {};
		const reactions = d.likes_reactions || {};
		const impClicks = d.impressions_clicks || {};
		const followers = d.followers_growth || {};
		const posts = d.posts || [];

		return `
			<!-- Top 6 KPI Metric Cards Grid -->
			<div class="linkedin-kpi-grid">
				<div class="linkedin-kpi-card posts">
					<div class="kpi-title">
						<span>Total Posts Count</span>
						<span class="kpi-badge">Frequency</span>
					</div>
					<div class="kpi-value">${this.esc(d.total_posts || 0)}</div>
					<div class="kpi-subtitle">
						<strong>${this.esc(d.posts_this_month || 0)}</strong> this month (${this.esc(d.posts_this_week || 0)} this week)
					</div>
				</div>

				<div class="linkedin-kpi-card comments">
					<div class="kpi-title">
						<span>Comments Count</span>
						<span class="kpi-badge">Engagement</span>
					</div>
					<div class="kpi-value">${this.esc(d.comments_count || 0)}</div>
					<div class="kpi-subtitle">Across all company publications</div>
				</div>

				<div class="linkedin-kpi-card reactions">
					<div class="kpi-title">
						<span>Likes / Reactions</span>
						<span class="kpi-badge">Sentiment</span>
					</div>
					<div class="kpi-value">${this.esc(reactions.total || 0)}</div>
					<div class="kpi-subtitle">
						👍 ${this.esc(reactions.like || 0)} · 👏 ${this.esc(reactions.celebrate || 0)} · 💡 ${this.esc(reactions.insightful || 0)}
					</div>
				</div>

				<div class="linkedin-kpi-card shares">
					<div class="kpi-title">
						<span>Shares / Reposts</span>
						<span class="kpi-badge">Reach</span>
					</div>
					<div class="kpi-value">${this.esc(d.shares_reposts || 0)}</div>
					<div class="kpi-subtitle">Viral reach & shares</div>
				</div>

				<div class="linkedin-kpi-card impressions">
					<div class="kpi-title">
						<span>Impressions & Clicks</span>
						<span class="kpi-badge">Leads Potential</span>
					</div>
					<div class="kpi-value">${this.esc(impClicks.impressions || 0)}</div>
					<div class="kpi-subtitle">
						<strong>${this.esc(impClicks.clicks || 0)}</strong> clicks · <strong>${this.esc(impClicks.ctr || "0%")}</strong> CTR
					</div>
				</div>

				<div class="linkedin-kpi-card followers">
					<div class="kpi-title">
						<span>Followers Growth</span>
						<span class="kpi-badge">Brand Reach</span>
					</div>
					<div class="kpi-value">${this.esc(followers.total_followers || 0)}</div>
					<div class="kpi-subtitle">
						<span style="color: #059669; font-weight: 700;">${this.esc(followers.growth_rate || "+0%")}</span> (+${this.esc(followers.gained_this_month || 0)} this month)
					</div>
				</div>
			</div>

			<!-- Posts Feed -->
			<div class="linkedin-section-title">
				<span>Recent Company Posts & Comments Stream</span>
			</div>

			<div class="linkedin-posts-container">
				${posts.map(p => this.renderPostCard(p)).join("")}
			</div>
		`;
	}

	renderPostCard(post) {
		const comments = post.comments_list || [];
		return `
			<div class="linkedin-post-card" data-post-urn="${this.esc(post.urn)}">
				<div class="post-header">
					<img class="post-author-avatar" src="/assets/lex/images/lexocrates-mark-dark.png" alt="Company Logo" onerror="this.src='/assets/frappe/images/default-avatar/avatar_1.png'" />
					<div class="post-meta">
						<h6>Lexocrates Legal Operations</h6>
						<span>Published on ${this.esc(post.published_on)}</span>
					</div>
				</div>

				<div class="post-body">${this.esc(post.full_text || post.title)}</div>

				<div class="post-metrics-bar">
					<div class="metric-pill">👍 <span>${this.esc(post.likes)} Likes</span></div>
					<div class="metric-pill">💬 <span>${this.esc(post.comments)} Comments</span></div>
					<div class="metric-pill">🔁 <span>${this.esc(post.shares)} Reposts</span></div>
					<div class="metric-pill">👁️ <span>${this.esc(post.impressions)} Impressions</span></div>
				</div>

				<div class="comments-accordion">
					<div class="comments-title">
						<span>💬 Comments & Threaded Discussions (${comments.length})</span>
					</div>
					<div class="comments-list">
						${comments.map(c => `
							<div class="comment-item">
								<div class="comment-author-row">
									<div>
										<span class="comment-author-name">${this.esc(c.author_name)}</span>
										<div class="comment-author-headline">${this.esc(c.author_headline || "LinkedIn Member")}</div>
									</div>
									<span class="text-muted small">${this.esc(c.time_ago)}</span>
								</div>
								<div class="comment-text">"${this.esc(c.text)}"</div>
								<div class="comment-actions">
									<button class="btn btn-xs btn-primary reply-btn" 
										data-post-urn="${this.esc(post.urn)}" 
										data-comment-id="${this.esc(c.id)}"
										data-author-name="${this.esc(c.author_name)}">
										💬 Reply to Comment
									</button>
									<button class="btn btn-xs btn-info dm-btn"
										data-author-name="${this.esc(c.author_name)}"
										data-headline="${this.esc(c.author_headline || '')}">
										✉️ Direct Message (DM)
									</button>
									<button class="btn btn-xs btn-default convert-lead-btn"
										data-commenter-name="${this.esc(c.author_name)}"
										data-headline="${this.esc(c.author_headline || '')}"
										data-comment-text="${this.esc(c.text)}">
										➕ Convert to Lead
									</button>
								</div>
							</div>
						`).join("")}
					</div>
				</div>
			</div>
		`;
	}

	attachEvents() {
		// Tab Switching
		this.page.body.find(".linkedin-tab-btn").on("click", (e) => {
			const targetTab = $(e.currentTarget).data("tab");
			this.currentTab = targetTab;
			this.page.body.find(".linkedin-tab-btn").removeClass("active");
			$(e.currentTarget).addClass("active");

			if (targetTab === "inbox") {
				$("#tab-inbox-view").show();
				$("#tab-overview-view").hide();
				this.scrollChatToBottom();
			} else {
				$("#tab-inbox-view").hide();
				$("#tab-overview-view").show();
			}
		});

		// Conversation Selection in Inbox
		this.page.body.find(".conversation-item").on("click", (e) => {
			const convId = $(e.currentTarget).data("conv-id");
			this.activeConvId = convId;
			// Mark unread as 0 locally
			const conv = this.inboxConversations.find(c => c.id === convId);
			if (conv) conv.unread_count = 0;
			this.render();
		});

		// Search Inbox Conversations
		this.page.body.find("#inbox-search").on("input", (e) => {
			const q = $(e.target).val().toLowerCase();
			this.page.body.find(".conversation-item").each(function () {
				const text = $(this).text().toLowerCase();
				$(this).toggle(text.includes(q));
			});
		});

		// Send message button in Chat View
		this.page.body.find("#inbox-send-btn").on("click", () => this.sendChatMessage());

		// Send on Enter in Textarea
		this.page.body.find("#inbox-chat-input").on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.sendChatMessage();
			}
		});

		// Convert Inbox Prospect to Lead button
		this.page.body.find(".convert-inbox-lead-btn").on("click", (e) => {
			const btn = $(e.currentTarget);
			const name = btn.data("name");
			const headline = btn.data("headline");
			const lastMsg = btn.data("last-msg");
			this.convertToLead(name, headline, `Inbound LinkedIn Chat: "${lastMsg}"`, btn);
		});

		// Open LinkedIn Profile search
		this.page.body.find(".open-linkedin-profile-btn").on("click", (e) => {
			const name = $(e.currentTarget).data("name");
			window.open(`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(name)}`, "_blank");
		});

		// Post Comment Reply button
		this.page.body.find(".reply-btn").on("click", (e) => {
			const btn = $(e.currentTarget);
			this.openReplyDialog(btn.data("post-urn"), btn.data("comment-id"), btn.data("author-name"));
		});

		// DM Modal button
		this.page.body.find(".dm-btn").on("click", (e) => {
			const btn = $(e.currentTarget);
			this.openDirectMessageDialog(btn.data("author-name"), btn.data("headline"));
		});

		// Post Convert Lead button
		this.page.body.find(".convert-lead-btn").on("click", (e) => {
			const btn = $(e.currentTarget);
			this.convertToLead(btn.data("commenter-name"), btn.data("headline"), btn.data("comment-text"), btn);
		});
	}

	sendChatMessage() {
		const input = this.page.body.find("#inbox-chat-input");
		const text = input.val().trim();
		if (!text) return;

		input.val("");
		const stream = this.page.body.find("#chat-messages-stream");

		// Optimistic append
		const tempId = "temp_" + Date.now();
		stream.append(`
			<div class="chat-bubble-row outbound" id="${tempId}">
				<div class="chat-bubble">${this.esc(text)}</div>
				<div class="chat-bubble-meta">
					Lexocrates Legal Ops (You) · Just now · <span style="color:#059669;">✔ Sending...</span>
				</div>
			</div>
		`);
		this.scrollChatToBottom();

		frappe.call({
			method: "lex.linkedin_crm.send_linkedin_inbox_message",
			args: {
				conversation_id: this.activeConvId,
				message_text: text,
			},
			callback: (r) => {
				if (r.message && r.message.status === "success") {
					$(`#${tempId} .chat-bubble-meta`).html("Lexocrates Legal Ops (You) · Just now · <span style='color:#059669;'>✔ Delivered</span>");
				}
			}
		});
	}

	scrollChatToBottom() {
		const el = document.getElementById("chat-messages-stream");
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	}

	convertToLead(commenterName, headline, commentText, btn) {
		frappe.confirm(
			__("Create a new CRM Lead for <strong>{0}</strong>?", [commenterName]),
			() => {
				btn.prop("disabled", true).text(__("Creating Lead..."));
				frappe.call({
					method: "lex.linkedin_crm.convert_to_lead",
					args: {
						commenter_name: commenterName,
						headline: headline,
						comment_text: commentText,
					},
					callback: (r) => {
						btn.prop("disabled", false).text(__("✔ Lead Created")).removeClass("btn-default").addClass("btn-success");
						frappe.show_alert({
							message: `<a href="/app/lead/${encodeURIComponent(r.message.lead_id)}" style="color: white; text-decoration: underline; font-weight: bold;">✔ Lead ${frappe.utils.escape_html(r.message.lead_id)} created! Click to open in CRM.</a>`,
							indicator: "green",
						}, 7);
					},
					error: () => {
						btn.prop("disabled", false).text(__("➕ Convert to Lead"));
					}
				});
			}
		);
	}

	openDirectMessageDialog(authorName, headline) {
		const searchUrl = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(authorName)}`;
		const d = new frappe.ui.Dialog({
			title: __("Send 1-to-1 Message to {0}", [authorName]),
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<div class="alert alert-info" style="font-size: 13px;">
							<strong>Target Prospect:</strong> ${this.esc(authorName)} <br>
							<strong>Headline:</strong> ${this.esc(headline || "Professional")}
						</div>
					`
				},
				{
					fieldname: "custom_note",
					fieldtype: "Small Text",
					label: __("Copy-Ready Outreach Message"),
					default: `Hi ${authorName}, saw your comment on our LinkedIn post regarding legal operations. Would love to share our pricing deck with you directly.`,
				}
			],
			primary_action_label: __("Open LinkedIn Chat"),
			primary_action: () => {
				window.open(searchUrl, "_blank");
				d.hide();
			},
			secondary_action_label: __("Switch to Live Inbox Tab"),
			secondary_action: () => {
				d.hide();
				this.page.body.find(".linkedin-tab-btn[data-tab='inbox']").trigger("click");
			}
		});
		d.show();
	}

	openReplyDialog(postUrn, commentId, authorName) {
		const d = new frappe.ui.Dialog({
			title: __("Reply to {0} on LinkedIn", [authorName]),
			fields: [
				{
					fieldname: "reply_text",
					fieldtype: "Small Text",
					label: __("Your Reply Message"),
					reqd: 1,
				}
			],
			primary_action_label: __("Send Reply via LinkedIn API"),
			primary_action: (values) => {
				frappe.show_progress(__("Publishing reply to LinkedIn"), 50, 100);
				frappe.call({
					method: "lex.linkedin_crm.reply_to_comment",
					args: {
						post_urn: postUrn,
						comment_id: commentId,
						reply_text: values.reply_text,
					},
					callback: (r) => {
						frappe.hide_progress();
						d.hide();
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								message: __("Reply successfully posted to LinkedIn!"),
								indicator: "green",
							});
						}
					},
					error: () => frappe.hide_progress(),
				});
			}
		});
		d.show();
	}

	showConfigDialog() {
		const st = this.status || {};
		const d = new frappe.ui.Dialog({
			title: __("LinkedIn API Environment Configuration"),
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<div class="alert alert-info">
							Credentials are read directly from <code>.env</code> file:
							<br>• <strong>LINKEDIN_ORGANIZATION_ID</strong>: Your Company Page ID
							<br>• <strong>LINKEDIN_ACCESS_TOKEN</strong>: OAuth 2.0 Access Token
							<br>• <strong>LINKEDIN_CLIENT_ID</strong>: Client ID from Developer Portal
						</div>
						<table class="table table-bordered table-sm">
							<tr><th>Variable</th><th>Status</th></tr>
							<tr><td>LINKEDIN_ORGANIZATION_ID</td><td><code>${this.esc(st.organization_id)}</code></td></tr>
							<tr><td>LINKEDIN_ACCESS_TOKEN</td><td><code>${this.esc(st.masked_token)}</code></td></tr>
							<tr><td>Configuration Source</td><td><code>${this.esc(st.source)}</code></td></tr>
						</table>
					`
				}
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});
		d.show();
	}
}
