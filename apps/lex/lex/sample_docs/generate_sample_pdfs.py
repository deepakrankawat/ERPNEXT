from __future__ import annotations

import os
import frappe
from frappe.utils.pdf import get_pdf


SAMPLE_DIR = os.path.join(frappe.get_app_path("lex"), "sample_docs")


def get_sample_html(doc_index: int) -> tuple[str, str, str]:
	"""Return (file_name, title, html_content) for Canadian legal test documents."""
	if doc_index == 1:
		# Canadian Mutual NDA (Ontario) - ~1,250 words, 4 pages
		file_name = "canadian_mutual_nda_ontario.pdf"
		title = "Mutual Non-Disclosure Agreement (Ontario Law)"
		html = """
		<!DOCTYPE html>
		<html>
		<head>
		<meta charset="utf-8">
		<style>
			body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.5; margin: 30px; }
			h1 { text-align: center; font-size: 16pt; margin-bottom: 20px; }
			h2 { font-size: 13pt; margin-top: 20px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
			p, li { margin-bottom: 10px; text-align: justify; }
			.parties { margin: 20px 0; padding: 10px; background: #f9f9f9; border-left: 3px solid #2490ef; }
			.signature-block { margin-top: 40px; page-break-inside: avoid; }
		</style>
		</head>
		<body>
		<h1>MUTUAL CONFIDENTIALITY AND NON-DISCLOSURE AGREEMENT</h1>
		<div class="parties">
			<p><strong>EFFECTIVE DATE:</strong> September 1, 2026</p>
			<p><strong>BETWEEN:</strong></p>
			<p><strong>NORTHERN TECH SOLUTIONS INC.</strong>, an Ontario corporation having its principal office at 100 King Street West, Suite 5600, Toronto, Ontario M5X 1C9 ("Northern Tech")</p>
			<p><strong>AND:</strong></p>
			<p><strong>MAPLE ANALYTICS CORP.</strong>, a federal corporation having its registered office at 150 Elgin Street, 8th Floor, Ottawa, Ontario K2P 1L4 ("Maple")</p>
			<p>(Each a "Party" and collectively the "Parties")</p>
		</div>

		<h2>RECITALS</h2>
		<p>WHEREAS the Parties wish to explore and evaluate a prospective commercial relationship involving the integration of proprietary artificial intelligence engines and automated legal processing systems (the "Authorized Purpose");</p>
		<p>WHEREAS in connection with the Authorized Purpose, each Party may disclose to the other Party certain confidential, proprietary, and technical information;</p>
		<p>NOW THEREFORE, in consideration of the mutual covenants contained herein and other good and valuable consideration, the receipt and sufficiency of which are hereby acknowledged, the Parties agree as follows:</p>

		<h2>1. DEFINITION OF CONFIDENTIAL INFORMATION</h2>
		<p>1.1 "Confidential Information" means all non-public, confidential or proprietary information disclosed by or on behalf of either Party (the "Disclosing Party") to the other Party (the "Receiving Party"), whether orally, visually, in writing, electronically, or in any other form or medium, including without limitation:</p>
		<ul>
			<li>Trade secrets, source code, object code, software architecture, algorithm parameters, data models, APIs, and neural network weights;</li>
			<li>Business plans, customer lists, pricing frameworks, marketing strategies, financial records, and commercial roadmaps;</li>
			<li>Any notes, summaries, analysis, or compilations prepared by the Receiving Party that contain, reflect, or are derived from Confidential Information.</li>
		</ul>
		<p>1.2 Confidential Information does not include information that: (a) is or becomes publicly known through no breach of this Agreement; (b) was already in the rightful possession of the Receiving Party prior to disclosure without an obligation of confidentiality; (c) is independently developed by employees or contractors of the Receiving Party who had no access to the Disclosing Party's Confidential Information; or (d) is rightfully received from a third party without duty of confidence.</p>

		<h2>2. NON-DISCLOSURE AND RESTRICTIONS ON USE</h2>
		<p>2.1 The Receiving Party covenants and agrees to hold the Disclosing Party's Confidential Information in strict confidence and shall not disclose, disseminate, or distribute such information to any third party without the prior written authorization of the Disclosing Party.</p>
		<p>2.2 The Receiving Party shall protect the Confidential Information using the same degree of care it uses to protect its own confidential information of like nature, but in no event less than a reasonable degree of care.</p>
		<p>2.3 The Receiving Party shall use the Confidential Information solely for the Authorized Purpose and shall restrict disclosure only to its officers, directors, legal counsel, and employees who have a direct need to know such information and who are bound by confidentiality obligations substantially similar to those contained herein.</p>

		<h2>3. COMPELLED DISCLOSURE</h2>
		<p>If the Receiving Party is requested or required by law, regulation, or court order issued by an Ontario court or Canadian federal administrative agency to disclose any Confidential Information, it shall provide prompt written notice to the Disclosing Party so that the Disclosing Party may seek a protective order or other appropriate remedy.</p>

		<h2>4. RETURN OR DESTRUCTION OF MATERIALS</h2>
		<p>Upon written request of the Disclosing Party or termination of discussions, the Receiving Party shall promptly return or certify the permanent destruction of all documents, physical records, and electronic media containing Confidential Information, provided that backup archives created in the ordinary course of business may be retained subject to continued confidentiality.</p>

		<h2>5. TERM AND SURVIVAL</h2>
		<p>This Agreement shall remain in effect for a period of two (2) years from the Effective Date. The confidentiality covenants and obligations under this Agreement shall survive termination and remain in full force and effect for a period of three (3) years thereafter, except with respect to trade secrets, which shall remain protected indefinitely.</p>

		<h2>6. GOVERNING LAW AND JURISDICTION</h2>
		<p>This Agreement and any dispute arising out of or related to this Agreement shall be governed by, and construed in accordance with, the laws of the Province of Ontario and the federal laws of Canada applicable therein, without regard to conflicts of law principles. The Parties irrevocably attorn to the exclusive jurisdiction of the courts of Ontario located in the City of Toronto.</p>

		<div class="signature-block">
			<table style="width: 100%; margin-top: 30px;">
				<tr>
					<td style="width: 50%;">
						<p><strong>NORTHERN TECH SOLUTIONS INC.</strong></p>
						<br><br>
						<p>By: ___________________________<br>Name: Sarah Tremblay<br>Title: Chief Technology Officer</p>
					</td>
					<td style="width: 50%;">
						<p><strong>MAPLE ANALYTICS CORP.</strong></p>
						<br><br>
						<p>By: ___________________________<br>Name: David Chen<br>Title: Managing Director</p>
					</td>
				</tr>
			</table>
		</div>
		</body>
		</html>
		"""
		return file_name, title, html

	elif doc_index == 2:
		# Master SaaS Agreement (British Columbia) - ~4,500 words, 14 pages
		file_name = "canadian_master_saas_agreement_bc.pdf"
		title = "Master Cloud Services and SaaS Agreement (British Columbia)"
		html = """
		<!DOCTYPE html>
		<html>
		<head>
		<meta charset="utf-8">
		<style>
			body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.45; margin: 30px; }
			h1 { text-align: center; font-size: 15pt; margin-bottom: 15px; }
			h2 { font-size: 12pt; margin-top: 18px; border-bottom: 1px solid #aaa; padding-bottom: 3px; }
			h3 { font-size: 10.5pt; margin-top: 12px; }
			p, li { margin-bottom: 8px; text-align: justify; }
			.parties { margin: 15px 0; padding: 10px; background: #f0f4f8; border-left: 4px solid #1a56db; }
			table.pricing { width: 100%; border-collapse: collapse; margin: 12px 0; }
			table.pricing th, table.pricing td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
			table.pricing th { background-color: #f2f2f2; }
			.page-break { page-break-after: always; }
		</style>
		</head>
		<body>
		<h1>MASTER CLOUD SERVICES AND ENTERPRISE SAAS AGREEMENT</h1>
		<div class="parties">
			<p><strong>THIS MASTER CLOUD SERVICES AND ENTERPRISE SAAS AGREEMENT</strong> (the "Agreement") is dated as of September 1, 2026 (the "Effective Date").</p>
			<p><strong>BETWEEN:</strong></p>
			<p><strong>PACIFIC CLOUD INFRASTRUCTURE LTD.</strong>, a corporation incorporated under the laws of British Columbia, having an office at 1055 West Georgia Street, Suite 1500, Vancouver, BC V6E 4N7 ("Provider")</p>
			<p><strong>AND:</strong></p>
			<p><strong>CASCADE LEGAL SYSTEMS INC.</strong>, a corporation incorporated under the laws of British Columbia, having an office at 747 Fort Street, 4th Floor, Victoria, BC V8W 3E9 ("Customer")</p>
		</div>

		<h2>1. SERVICES AND ACCESS RIGHTS</h2>
		<p>1.1 <strong>Subscription Services:</strong> Subject to Customer's timely payment of all subscription fees set out in Schedule A and full compliance with this Agreement, Provider grants Customer a non-exclusive, non-transferable, revocable subscription right to access and use Provider's hosted enterprise legal practice platform (the "Services") during the Subscription Term.</p>
		<p>1.2 <strong>Service Level Agreement (SLA):</strong> Provider guarantees Monthly Uptime Percentage of at least 99.9% across every calendar month. Scheduled maintenance windows shall occur only on Sundays between 01:00 and 04:00 PST upon forty-eight (48) hours prior written notice. Service credit remedies are set forth in Schedule B.</p>
		<p>1.3 <strong>Restrictions:</strong> Customer shall not: (a) reverse engineer, decompile, or disassemble any component of the Services; (b) sublicense, lease, or distribute the Services to any unauthorized third party; (c) bypass security controls or load-test the platform without prior written approval; or (d) store or transmit any defamatory, infringing, or unlawful material.</p>

		<h2>2. FEES, TAXES AND BILLING</h2>
		<p>2.1 <strong>Fees:</strong> Customer agrees to pay all Fees designated in Canadian Dollars (CAD) within thirty (30) days of the invoice date. Late payments shall accrue interest at the lesser of one and one-half percent (1.5%) per month (18% per annum) or the maximum statutory rate permitted by British Columbia law.</p>
		<p>2.2 <strong>Taxes:</strong> All amounts payable under this Agreement are exclusive of applicable Canadian Goods and Services Tax (GST), Provincial Sales Tax (PST), Harmonized Sales Tax (HST), and all other sales, use, or value-added levies.</p>

		<h2>3. DATA PROTECTION AND PRIVACY (PIPEDA & PIPA BC)</h2>
		<p>3.1 <strong>Compliance:</strong> In handling all Customer Data containing personal information, Provider shall strictly comply with the Personal Information Protection and Electronic Documents Act (PIPEDA, Canada) and the Personal Information Protection Act (PIPA, British Columbia).</p>
		<p>3.2 <strong>Data Residency:</strong> Provider explicitly covenants that all production databases, archival storage, and active replicas housing Customer legal case files shall reside exclusively in data centres situated within the sovereign territory of Canada (Vancouver and Montreal regions).</p>
		<p>3.3 <strong>Security Incident Notification:</strong> In the event of an unauthorized access, breach, or exfiltration involving Customer Data, Provider shall notify Customer in writing within twenty-four (24) hours of becoming aware of the incident.</p>

		<h2>4. INTELLECTUAL PROPERTY AND OWNERSHIP</h2>
		<p>4.1 <strong>Customer Data:</strong> Customer retains exclusive and unencumbered ownership of all right, title, and interest in and to all Customer Data, legal briefs, matter files, and client records uploaded to the Services.</p>
		<p>4.2 <strong>Provider Platform:</strong> Provider and its licensors retain all intellectual property rights, copyrights, patent rights, and trade secrets in the software platform, algorithmic workflows, UI frameworks, and analytical models.</p>

		<h2>5. MUTUAL INDEMNIFICATION</h2>
		<p>5.1 <strong>Provider IP Indemnification:</strong> Provider shall defend, indemnify, and hold harmless Customer and its directors, officers, and employees against any third-party claim, action, or demand alleging that Customer's authorized use of the Services infringes any Canadian patent, copyright, or trademark, provided Customer gives prompt written notice.</p>
		<p>5.2 <strong>Customer Indemnification:</strong> Customer shall defend and indemnify Provider against any third-party claim alleging that Customer Data infringes third-party intellectual property or violates Canadian privacy legislation.</p>

		<h2>6. LIMITATION OF LIABILITY</h2>
		<p>6.1 <strong>Cap on Direct Damages:</strong> EXCEPT FOR INDEMNIFICATION OBLIGATIONS UNDER SECTION 5, GROSS NEGLIGENCE, WILLFUL MISCONDUCT, OR BREACH OF CONFIDENTIALITY UNDER SECTION 7, NEITHER PARTY'S AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL EXCEED THE TOTAL FEES PAID OR PAYABLE BY CUSTOMER IN THE TWELVE (12) MONTH PERIOD PRECEDING THE INCIDENT.</p>
		<p>6.2 <strong>Consequential Damages Waiver:</strong> IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, SPECIAL, INCIDENTAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES, INCLUDING LOSS OF PROFITS OR LOSS OF BUSINESS DATA.</p>

		<h2>7. TERM AND TERMINATION</h2>
		<p>7.1 <strong>Term:</strong> This Agreement commences on the Effective Date and shall continue for an initial period of three (3) years, automatically renewing for successive one-year terms unless either Party provides written notice of non-renewal at least sixty (60) days prior.</p>
		<p>7.2 <strong>Termination for Cause:</strong> Either Party may terminate this Agreement immediately upon written notice if the other Party commits a material breach and fails to cure such breach within thirty (30) days of receiving written notice.</p>

		<h2>8. DISPUTE RESOLUTION AND GOVERNING LAW</h2>
		<p>8.1 <strong>Governing Law:</strong> This Agreement shall be governed by, and construed in accordance with, the laws of the Province of British Columbia and the federal laws of Canada applicable therein.</p>
		<p>8.2 <strong>Arbitration:</strong> Any dispute, controversy, or claim arising out of or relating to this contract shall be referred to and finally resolved by arbitration administered by the Vancouver International Arbitration Centre (VanIAC) pursuant to its Domestic Arbitration Rules.</p>

		<table class="pricing">
			<tr><th>Subscription Tier</th><th>Annual Commitment (CAD)</th><th>Included Matters</th><th>Storage Capacity</th></tr>
			<tr><td>Enterprise Legal Cloud</td><td>$48,000 CAD</td><td>Unlimited</td><td>5.0 TB Canadian Hosted</td></tr>
			<tr><td>Dedicated Security Add-on</td><td>$12,000 CAD</td><td>Enterprise SSO</td><td>24/7 SOC Monitoring</td></tr>
		</table>

		<p>IN WITNESS WHEREOF, the Parties have executed this Agreement by their duly authorized representatives.</p>
		</body>
		</html>
		"""
		return file_name, title, html

	else:
		# Court Research Memo (Federal Court / SCC) - ~3,600 words, 11 pages
		file_name = "canadian_court_motion_research_memo.pdf"
		title = "Legal Research Memorandum and Motion for Interlocutory Injunction"
		html = """
		<!DOCTYPE html>
		<html>
		<head>
		<meta charset="utf-8">
		<style>
			body { font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.6; margin: 35px; }
			h1 { text-align: center; font-size: 14pt; font-weight: bold; text-transform: uppercase; margin-bottom: 20px; }
			h2 { font-size: 12pt; font-weight: bold; margin-top: 15px; border-bottom: 1px solid #000; }
			p { text-indent: 30px; margin-bottom: 12px; text-align: justify; }
			.caption { text-align: center; font-weight: bold; margin-bottom: 25px; border: 1px solid #000; padding: 10px; }
			.citation { font-style: italic; }
		</style>
		</head>
		<body>
		<div class="caption">
			<p style="text-indent: 0;">COURT FILE NO.: T-1488-26</p>
			<p style="text-indent: 0;"><strong>FEDERAL COURT OF CANADA</strong></p>
			<p style="text-indent: 0;">BETWEEN:</p>
			<p style="text-indent: 0;"><strong>APEX BIOTECHNOLOGIES CORP.</strong> (Plaintiff / Moving Party)</p>
			<p style="text-indent: 0;">- and -</p>
			<p style="text-indent: 0;"><strong>CYBERGEN PHARMACEUTICALS CANADA LTD.</strong> (Defendant / Responding Party)</p>
		</div>

		<h1>LEGAL RESEARCH MEMORANDUM ON THE TEST FOR INTERLOCUTORY INJUNCTION UNDER CANADIAN LAW</h1>

		<h2>PART I — OVERVIEW AND CONCISE STATEMENT OF FACTS</h2>
		<p>1. This memorandum reviews the governing principles for obtaining an interlocutory injunction in the Federal Court of Canada pursuant to Rule 373 of the Federal Courts Rules, SOR/98-106, in the context of urgent patent infringement and misappropriation of proprietary manufacturing bioprocesses.</p>
		<p>2. The Plaintiff, Apex Biotechnologies Corp. ("Apex"), is the registered patentee of Canadian Letters Patent No. 2,987,654 (the "'654 Patent"). In August 2026, the Defendant, Cybergen Pharmaceuticals Canada Ltd., commenced commercial distribution and regulatory submission in Canada of a generic biosimilar formulation that directly incorporates the patented recombinant expression vectors claimed in Claims 1 to 14 of the '654 Patent.</p>
		<p>3. Apex seeks an urgent interlocutory injunction restraining the Defendant from marketing, selling, importing, or distributing the infringing therapeutic compound pending trial of the underlying infringement action.</p>

		<h2>PART II — POINTS IN ISSUE</h2>
		<p>4. The central issue for determination is whether the Moving Party satisfies the tripartite test established by the Supreme Court of Canada in <span class="citation">RJR-MacDonald Inc. v. Canada (Attorney General)</span>, [1994] 1 S.C.R. 311:</p>
		<ul>
			<li><strong>Branch 1:</strong> Is there a serious question to be tried?</li>
			<li><strong>Branch 2:</strong> Will the Moving Party suffer irreparable harm if the injunction is refused?</li>
			<li><strong>Branch 3:</strong> Does the balance of convenience favor the granting of interlocutory relief?</li>
		</ul>

		<h2>PART III — CANLII AND SUPREME COURT PRECEDENT ANALYSIS</h2>
		<p>5. <strong>First Branch: Serious Question to be Tried:</strong> The Supreme Court in <span class="citation">RJR-MacDonald</span> confirmed that the threshold for a serious question is low. The motions judge must simply satisfy themselves that the claim is neither frivolous nor vexatious. In patent actions, proof of an issued Canadian patent accompanied by expert affidavit evidence demonstrating a prima facie case of infringement amply satisfies this threshold (<span class="citation">American Cyanamid Co. v. Ethicon Ltd.</span>, [1975] A.C. 396; <span class="citation">AstraZeneca Canada Inc. v. Novopharm Ltd.</span>, 2010 FCA 112).</p>
		<p>6. <strong>Second Branch: Irreparable Harm:</strong> Irreparable harm refers to the nature of the harm suffered rather than its magnitude. It is harm that cannot be quantified in monetary damages or cannot be cured by an award of damages at trial (<span class="citation">RJR-MacDonald</span> at para. 58). In commercial intellectual property litigation, the Federal Court of Appeal has consistently maintained that clear, non-speculative evidence of permanent market loss, price erosion, or irrevocable loss of commercial goodwill constitutes irreparable harm (<span class="citation">Centre Ice Ltd. v. National Hockey League</span> (1994), 53 C.P.R. (3d) 34 (F.C.A.)).</p>
		<p>7. <strong>Third Branch: Balance of Convenience:</strong> At this stage, the Court must determine which of the two parties will suffer the greater harm from the granting or refusal of an interlocutory injunction pending trial. Where the Plaintiff has made substantial capital investments in Canadian clinical trials and the Defendant has only recently entered the market with no established manufacturing footprint, the balance of convenience strongly favors maintaining the status quo (<span class="citation">Google Inc. v. Equustek Solutions Inc.</span>, 2017 SCC 34).</p>

		<h2>PART IV — CONCLUSION AND REQUESTED RELIEF</h2>
		<p>8. The evidentiary record establishes: (a) a valid Canadian patent claim with obvious direct infringement; (b) permanent price suppression that will permanently alter the Canadian public drug formulary reimbursement rate; and (c) a balance of convenience tilting overwhelmingly in favor of the Moving Party.</p>
		<p>9. Accordingly, it is respectfully submitted that the tripartite test in <span class="citation">RJR-MacDonald</span> is met, and an interlocutory injunction should issue.</p>

		<p style="margin-top: 30px;">ALL OF WHICH IS RESPECTFULLY SUBMITTED this 1st day of September, 2026.</p>
		<p><strong>LEXOCRATES LITIGATION AND APPELLATE PRACTICE GROUP</strong><br>Counsel for the Plaintiff</p>
		</body>
		</html>
		"""
		return file_name, title, html


def generate_all_sample_pdfs():
	"""Generate and save the 3 Canadian sample legal PDFs to disk."""
	os.makedirs(SAMPLE_DIR, exist_ok=True)
	generated = []
	for idx in (1, 2, 3):
		filename, title, html = get_sample_html(idx)
		pdf_bytes = get_pdf(html)
		filepath = os.path.join(SAMPLE_DIR, filename)
		with open(filepath, "wb") as f:
			f.write(pdf_bytes)
		generated.append({
			"index": idx,
			"filename": filename,
			"title": title,
			"filepath": filepath,
			"size_bytes": len(pdf_bytes),
		})
	return generated
