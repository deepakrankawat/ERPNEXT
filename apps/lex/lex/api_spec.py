from __future__ import annotations

import uuid
import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_openapi_specification() -> dict:
	"""Generate OpenAPI 3.0 contract specification for Lexocrates APIs (API-001)."""
	return {
		"openapi": "3.0.3",
		"info": {
			"title": "Lexocrates AI-Native Legal Operations API",
			"version": "1.0.0",
			"description": "Authoritative REST API specification per LEX-SRS-001 baseline.",
		},
		"paths": {
			"/api/method/lex.client_portal.get_portal_dashboard": {
				"get": {
					"summary": "Get authenticated Client Portal dashboard data",
					"responses": {"200": {"description": "Dashboard metadata and metrics"}},
				}
			},
			"/api/method/lex.work_intake.request_cost_estimate": {
				"post": {
					"summary": "Request a governed Work Intake cost estimate",
					"description": "Client-safe endpoint. It does not expose legal AI chat, prompts, models, reasoning, or raw AI output.",
					"responses": {"200": {"description": "Sanitized quote and workflow status"}},
				}
			},
			"/api/method/lex.wallet_statement.generate_wallet_statement_data": {
				"get": {
					"summary": "Get reconciled LexPoint ledger statement",
					"responses": {"200": {"description": "Wallet statement"}},
				}
			},
		},
		"components": {
			"securitySchemes": {
				"ApiKeyAuth": {
					"type": "apiKey",
					"in": "header",
					"name": "Authorization",
				}
			}
		},
	}


def ensure_correlation_id():
	"""Middleware helper ensuring correlation ID header is attached to request state (API-001)."""
	if not hasattr(frappe.flags, "correlation_id") or not frappe.flags.correlation_id:
		req_id = frappe.request.headers.get("X-Correlation-ID") if hasattr(frappe, "request") and frappe.request else None
		frappe.flags.correlation_id = req_id or f"AEV-{uuid.uuid4()}"
	return frappe.flags.correlation_id
