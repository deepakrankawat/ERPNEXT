// Lexocrates Login Page Enhancer
(function () {
	'use strict';
	let loginThemeObserver = null;

	function enforceLoginLightTheme() {
		const root = document.documentElement;
		if (root.getAttribute('data-theme') !== 'light') root.setAttribute('data-theme', 'light');
		root.style.colorScheme = 'light';
		if (!loginThemeObserver) {
			loginThemeObserver = new MutationObserver(() => {
				if (root.getAttribute('data-theme') !== 'light') root.setAttribute('data-theme', 'light');
			});
			loginThemeObserver.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
		}
	}

	if (window.location.pathname === '/login') enforceLoginLightTheme();

	function initLoginEnhancements() {
		const isLoginPage = window.location.pathname === '/login' ||
			document.querySelector('.for-login') ||
			document.querySelector('form[action*="login"]') ||
			document.querySelector('#page-login');

		if (!isLoginPage) return;
		enforceLoginLightTheme();

		// Ensure body has login class
		document.body.classList.add('for-login', 'lex-custom-login');

		// 1. Enhance login card container if present and not yet enhanced
		const pageCard = document.querySelector('.page-card, .login-content, .frappe-card, .form-signin');
		if (pageCard && !pageCard.dataset.lexEnhanced) {
			pageCard.dataset.lexEnhanced = 'true';

			// Inject custom tabs, register banner, and footer if not present
			if (!document.querySelector('.lex-login-tabs')) {
				const tabsHtml = `
					<div class="lex-login-tabs" role="tablist" style="display: grid; grid-template-columns: 1fr 1fr 1fr; background: #f1f5f9; padding: 4px; border-radius: 10px; margin-bottom: 20px; gap: 4px;">
						<button id="tab-client" class="lex-login-tab active" type="button" onclick="window.lexSwitchLogin('client')" style="border:none; background:#fff; padding:9px 8px; font-size:12px; font-weight:600; color:#0f172a; border-radius:8px; cursor:pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
							Client
						</button>
						<button id="tab-email" class="lex-login-tab" type="button" onclick="window.lexSwitchLogin('email')" style="border:none; background:transparent; padding:9px 8px; font-size:12px; font-weight:600; color:#64748b; border-radius:8px; cursor:pointer;">
							Email Link
						</button>
						<button id="tab-system" class="lex-login-tab" type="button" onclick="window.lexSwitchLogin('system')" style="border:none; background:transparent; padding:9px 8px; font-size:12px; font-weight:600; color:#64748b; border-radius:8px; cursor:pointer;">
							Staff
						</button>
					</div>
					<div class="lex-register-banner" id="register-banner" style="background: linear-gradient(135deg, #eff6ff 0%, #e0f2fe 100%); border: 1px solid #bae6fd; border-radius: 12px; padding: 14px 16px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px;">
						<div class="lex-register-text">
							<h4 style="margin: 0 0 2px 0; font-size: 13px; font-weight: 700; color: #0369a1;">New Client Organization?</h4>
							<p style="margin: 0; font-size: 11px; color: #0c4a6e;">Register to submit matters, review quotes &amp; LexPacks.</p>
						</div>
						<a href="/client-registration" class="btn btn-register" style="white-space: nowrap; background: #0284c7; color: #ffffff !important; font-weight: 600; font-size: 12px; padding: 6px 14px; border-radius: 8px; text-decoration: none;">
							Register Client →
						</a>
					</div>
				`;

				const form = pageCard.querySelector('form');
				if (form) {
					form.insertAdjacentHTML('beforebegin', tabsHtml);
				}
			}

			// Inject or Update Footer inside login card
			let footer = pageCard.querySelector('.lex-login-footer');
			if (!footer) {
				footer = document.createElement('div');
				footer.className = 'lex-login-footer';
				footer.style.cssText = 'margin-top: 24px; text-align: center; font-size: 12px; color: #94a3b8;';
				pageCard.appendChild(footer);
			}
			footer.innerHTML = `
				Protected by Lexocrates Enterprise Zero-Trust Authorization &amp; Cryptographic Audit.
				<div style="margin-top: 8px; font-weight: 600; color: #475569; font-size: 12px;">
					Powered by <a href="https://www.linkedin.com/in/deepak-rankawat-658b0a259/" target="_blank" rel="noopener noreferrer" style="color: #0284c7; text-decoration: underline;">Deepak Rankawat</a>
				</div>
			`;
		}

		// 2. Always replace bottom right page footer links (e.g. Powered by ERPNext)
		const bottomFooterLinks = document.querySelectorAll('a[href*="erpnext"], .footer-powered, footer .text-right, .web-footer-right, .web-footer a');
		bottomFooterLinks.forEach((el) => {
			if (el.tagName === 'A' && (el.href.includes('erpnext') || el.textContent.includes('ERPNext'))) {
				el.href = 'https://www.linkedin.com/in/deepak-rankawat-658b0a259/';
				el.target = '_blank';
				el.rel = 'noopener noreferrer';
				el.innerHTML = 'Powered by Deepak Rankawat';
				el.style.color = '#0284c7';
				el.style.fontWeight = '600';
				el.style.textDecoration = 'underline';
			} else if (!el.dataset.lexPoweredUpdated && el.textContent.includes('ERPNext')) {
				el.dataset.lexPoweredUpdated = 'true';
				el.innerHTML = `Powered by <a href="https://www.linkedin.com/in/deepak-rankawat-658b0a259/" target="_blank" rel="noopener noreferrer" style="color: #0284c7; text-decoration: underline; font-weight: 600;">Deepak Rankawat</a>`;
			}
		});

		// 3. Password visibility toggle (seen/unseen) enhancement for login password inputs
		const pwdInputs = document.querySelectorAll('input[type="password"], input[name="pwd"], input[name="password"]');
		pwdInputs.forEach((pwdInput) => {
			if (!pwdInput.dataset.lexToggleAdded && !pwdInput.parentElement.querySelector('.btn-toggle-password, .toggle-password')) {
				pwdInput.dataset.lexToggleAdded = 'true';
				
				const parent = pwdInput.parentElement;
				if (window.getComputedStyle(parent).position === 'static') {
					parent.style.position = 'relative';
				}
				pwdInput.style.paddingRight = '42px';

				const toggleBtn = document.createElement('button');
				toggleBtn.type = 'button';
				toggleBtn.className = 'btn-toggle-password';
				toggleBtn.setAttribute('aria-label', 'Toggle password visibility');
				toggleBtn.title = 'Show / Hide Password';
				toggleBtn.tabIndex = -1;
				toggleBtn.style.cssText = 'position: absolute; right: 6px; top: 50%; transform: translateY(-50%); background: transparent; border: none; padding: 6px 8px; color: #64748b; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; z-index: 10;';
				
				const eyeOpenSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
				const eyeSlashSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

				toggleBtn.innerHTML = eyeOpenSvg;
				toggleBtn.addEventListener('click', function(e) {
					e.preventDefault();
					e.stopPropagation();
					if (pwdInput.type === 'password') {
						pwdInput.type = 'text';
						toggleBtn.innerHTML = eyeSlashSvg;
						toggleBtn.setAttribute('title', 'Hide Password');
					} else {
						pwdInput.type = 'password';
						toggleBtn.innerHTML = eyeOpenSvg;
						toggleBtn.setAttribute('title', 'Show Password');
					}
				});

				parent.appendChild(toggleBtn);
			}
		});
	}

	window.lexSwitchLogin = function (mode) {
		const clientTab = document.getElementById('tab-client');
		const emailTab = document.getElementById('tab-email');
		const systemTab = document.getElementById('tab-system');
		const registerBanner = document.getElementById('register-banner');
		const pwdInput = document.querySelector('input[type="password"]');
		const pwdGroup = pwdInput ? pwdInput.closest('.form-group, .mb-3') : null;
		const submitBtn = document.querySelector('button[type="submit"], .btn-login');

		if (clientTab) {
			clientTab.style.background = mode === 'client' ? '#ffffff' : 'transparent';
			clientTab.style.color = mode === 'client' ? '#0f172a' : '#64748b';
		}
		if (emailTab) {
			emailTab.style.background = mode === 'email' ? '#ffffff' : 'transparent';
			emailTab.style.color = mode === 'email' ? '#0f172a' : '#64748b';
		}
		if (systemTab) {
			systemTab.style.background = mode === 'system' ? '#ffffff' : 'transparent';
			systemTab.style.color = mode === 'system' ? '#0f172a' : '#64748b';
		}

		if (registerBanner) {
			registerBanner.style.display = mode === 'client' ? 'flex' : 'none';
		}

		if (pwdGroup) {
			pwdGroup.style.display = mode === 'email' ? 'none' : 'block';
		}
		if (pwdInput) {
			pwdInput.required = mode !== 'email';
		}

		if (submitBtn) {
			if (mode === 'client') submitBtn.innerHTML = 'Sign in to Client Portal';
			else if (mode === 'email') submitBtn.innerHTML = 'Send Secure Login Link to Email';
			else submitBtn.innerHTML = 'Sign in to Legal Desk (/app)';
		}

		// Store intended redirect
		window.lexIntendedRedirect = mode === 'system' ? '/app' : '/client-portal';
	};

	document.addEventListener('DOMContentLoaded', initLoginEnhancements);
	setTimeout(initLoginEnhancements, 300);
})();
