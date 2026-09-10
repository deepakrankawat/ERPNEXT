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

	if (window.location.pathname === '/login' || window.location.pathname === '/client-login') {
		enforceLoginLightTheme();
	}

	function initLoginEnhancements() {
		const isLoginPage = window.location.pathname === '/login' ||
			window.location.pathname === '/client-login' ||
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

			// If this is a generic Frappe Desk login page without client navigation, add client helper link
			if (window.location.pathname === '/login' && !document.querySelector('.lex-client-helper-banner') && !document.querySelector('.btn-to-client')) {
				const helperHtml = `
					<div class="lex-client-helper-banner" style="margin-top: 16px; padding: 12px 16px; background: #eff6ff; border: 1px solid #bae6fd; border-radius: 10px; display: flex; align-items: center; justify-content: space-between; gap: 12px;">
						<div>
							<h4 style="margin: 0 0 2px 0; font-size: 12px; font-weight: 700; color: #0369a1;">Client Organization?</h4>
							<p style="margin: 0; font-size: 11px; color: #0c4a6e;">Sign in to review quotes, matters &amp; LexPack<sup class="lex-tm">TM</sup>s.</p>
						</div>
						<a href="/client-login" class="btn btn-sm" style="white-space: nowrap; background: #0284c7; color: #ffffff !important; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 6px; text-decoration: none;">
							Client Login →
						</a>
					</div>
				`;
				const form = pageCard.querySelector('form');
				if (form) {
					form.insertAdjacentHTML('afterend', helperHtml);
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

	document.addEventListener('DOMContentLoaded', initLoginEnhancements);
	setTimeout(initLoginEnhancements, 300);
})();
