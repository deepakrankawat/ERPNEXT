# ADR-001: Native Frappe collaboration

- Status: Accepted by product direction
- Date: 2026-08-14
- Decision owner: Lexocrates product owner

## Context

The earlier SRS referenced Mattermost and n8n for collaboration. The product
owner subsequently required communication to remain native to Frappe, secure,
auditable, role-based, record-centric, and real-time.

## Decision

Use `Lexocrates Chat Channel`, `Lexocrates Chat Member`, and
`Lexocrates Chat Message` with Frappe Redis/Socket.IO realtime events. Do not
send legal conversations to Mattermost, Slack, n8n, or another collaboration
processor. Contextual channels enforce the referenced Matter/Job permission on
each read and write.

## Consequences

- One authorization and audit boundary remains inside Frappe.
- Matter, Job, QA, compliance, and AI events can publish deterministic system
  messages without copying client content to another platform.
- Native chat availability now depends on the Frappe Redis/Socket.IO stack and
  must be included in availability, load, backup, and recovery tests.
- Any future external collaboration connector requires a new ADR, security and
  privacy review, tenant-isolation tests, retention mapping, and product-owner
  approval before activation.
