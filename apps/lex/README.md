### LPO Operation

Native legal-operations hierarchy and contextual, real-time communications for Lexocrates.

The operational model is:

`Customer -> LPO Matter -> LPO Job -> AI / QA / Compliance activity`

The client-facing model is deliberately direct:

`Customer (Client organization) -> Lexocrates Portal User -> explicit Matter authorization`

`Contact` is not part of client authorization. Legacy Contact links are migrated
once into `Lexocrates Portal User`; empty Contacts automatically created by
Frappe for new Portal Users are removed, while Contacts with genuine ERP links
are retained as historical business data.

`LPO Matter` is shown to users as a client matter: the strategic and
contractual container for a customer, legal scope, jurisdiction, SLA, manager,
and confidentiality policy. `LPO Job` is the individual production task. Every
job requires one parent matter and inherits its customer, practice area,
jurisdiction, and confidentiality context.

The `Lex` tab provides the production communication model:

- `Lexocrates Chat Channel` supports public, private, and ERP-record-contextual
  channels. Contextual channels use a Link plus Dynamic Link pair and re-check
  the referenced document permission on every access.
- `Lexocrates Chat Member` records Owner, Moderator, Member, or Read Only access,
  with explicit posting and member-management capabilities.
- `Lexocrates Chat Message` stores sanitized message HTML, threads, normalized
  mentions, audited attachment URLs, automation sources, sender, and server time.

The dedicated Desk page at `/app/lexocrates-chat` uses Frappe's authenticated
Redis/Socket.IO bridge. It subscribes to the selected channel's document room and
listens for `new_chat_message`, `chat_message_updated`, and `chat_mention` events.
The same contextual conversation is embedded on LPO Matter and LPO Job forms.

The default public channels are `#legal-research`, `#qa-review`, and
`#compliance-alerts`. Hooks publish system messages for new LPO Jobs, failed QA
reviews, compliance actions, optional AI Job Requests, and hourly SLA breaches.

#### Governance

| Role | Chat Channel | Chat Message |
| --- | --- | --- |
| `LPO_Admin` | Global access; create and manage | Post and read |
| `LPO_Manager` | Global access; create and manage | Post and read |
| `LPO_Analyst` | Public channels plus authorized private/contextual membership | Post unless Read Only |
| `System Manager` | Global access; create and manage | Post and read |

Sender and timestamp are authoritative server values. User messages have a
15-minute correction window whose changes are recorded by Frappe Versioning;
system messages are immediately immutable, and no message can be physically
deleted. Realtime delivery is deferred until the database transaction commits.

The embedded form UI uses the `chat_interface_html` field on `LPO Matter` and
`LPO Job`. Existing `LPO Channel` and `LPO Message` records are retained for
backward compatibility and copied idempotently into the production audit model
after migration.

### Client Portal

The authenticated website route `/client-portal` provides a responsive,
permission-personalized client UI. `/client-registration` uses a controlled
three-stage lifecycle: email verification, staff KYC/conflict/sanctions and
commercial review, then a separate time-limited activation link. A Customer,
User, Portal User, and Wallet are created only after every approval gate passes.

Eight client roles are supported: Client Administrator, Partner / General
Counsel, Legal, Operations, Finance, Procurement, Compliance, and Read Only.
Role defaults are independently constrained by explicit function permissions
and the `Lexocrates Matter Authorization` table on each LPO Matter.

Client Administrators can issue time-limited invitations, lock/suspend/disable
users, grant expiring delegated administration, change
function permissions, and assign Matter-level view, upload, comment, approve,
and billing access without obtaining internal ERP administration rights.

`Lexocrates Client Wallet` is unique per Client and has no expiry field.
Purchases, top-ups, reservations, releases, consumption, and linked one-time
reversals are posted only through the immutable `Lexocrates Wallet Transaction` ledger. Portal lifecycle,
permission, Matter-access, login, and financial events are appended to
`Lexocrates Portal Audit Event`; audit events cannot be edited or deleted and
are linked by a persisted SHA-256 chain that can be independently verified.

Matter activation is server-gated by an approved quote or a successful LexPoint
reservation. Operational Jobs require pinned Published Workflow and Effective
SOP versions. Source, evidence, and delivery Files remain quarantined until
their content signature matches and ClamAV returns clean; document checksums,
versions, SOP evidence, exceptions, and delivery acknowledgements are retained.

### Required production security configuration

Add these settings to the site's `site_config.json` or environment-managed
configuration. Never commit live secrets:

```json
{
  "lexocrates_wallet_webhook_secret": "managed-secret-value",
  "lexocrates_clamscan_path": "/usr/bin/clamscan",
  "lexocrates_ai_providers": {
    "OpenAI": {
      "endpoint": "https://your-controlled-ai-gateway.example/v1/execute",
      "api_key": "managed-secret-value",
      "timeout_seconds": 60
    }
  }
}
```

Payment webhooks must send `X-Lexocrates-Signature: sha256=<hex digest>`
calculated over the exact request body and include a signed ISO timestamp no
more than five minutes old. When ClamAV is missing or unavailable, uploads stay
in `Scanner Unavailable` quarantine and are not released for processing. AI
calls fail closed when no provider gateway is configured; provider kill switches
and circuit-breaker state are durable database records.

Run the complete regression suite with:

```bash
bench --site development.localhost run-tests --app lex
```

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app lex
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/lex
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
