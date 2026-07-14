# IDC Query Gateway Contract

The bundled `idc-query` plugin intentionally does not connect directly to
production CRM, monitoring, billing, ticketing, or database systems. It calls a
normalized HTTP gateway so credentials, tenant isolation, and source-specific
logic remain outside the chat bot process.

## Authentication and identity headers

When `IDC_QUERY_API_TOKEN` is configured, every request includes:

```http
Authorization: Bearer <service-token>
X-QQ-Group-ID: <group-openid>
X-QQ-User-ID: <member-openid>
X-IDC-Member-ID: <bound-member-id>
X-Request-ID: <qq-message-id>
```

`X-IDC-Member-ID` is omitted during initial binding verification. The gateway
must independently enforce member ownership for every IP and account query. It
must not trust an IP merely because the plugin supplied it.

The current LangBot Plugin Runtime launches all installed plugins under the same
container user and filesystem. When a gateway token is configured, install only
trusted plugins in that runtime. A later production-hardening phase should move
the IDC connector into a dedicated service identity or isolated runtime.

## LangBot configuration

Administrators configure the gateway under **Settings > IDC Query**. The
settings endpoint requires a user login token and deliberately rejects API-key
and MCP authentication. Reading settings returns only `token_configured`; the
service token itself is never returned. Configuration is atomically written to
`data/idc-query/config.env` with owner-only permissions, and the plugin detects
file replacement before processing the next query.

The same page provides a connection diagnostic. It sends a non-mutating `HEAD`
request to the configured gateway base URL with redirects disabled and reports
only categorized DNS, connection, TLS, timeout, HTTP, and authentication
results. It never calls a binding or query endpoint, returns a response body,
or exposes the URL, token, or low-level exception. A non-401/403 response proves
network reachability but does not prove that the token is authorized for a
specific customer query; that remains the gateway's responsibility on the
first real business request. The diagnostic endpoint accepts user-login
authentication only and is intentionally unavailable to API keys and MCP.

The settings page also exposes a separate QQ callback status view. It reports
the stable callback URL, enabled connection mode, App ID conflicts, and
content-free request, validation, accepted-event, duplicate, and rejection
counters. It never returns App Secrets, tokens, message bodies, group IDs, or
member IDs. These runtime counters reset when the QQ bot process restarts. The
status endpoint accepts user-login authentication only and is intentionally
unavailable to API keys and MCP.

The **Overview** tab aggregates fixed, secret-free readiness codes for the QQ
bot, event transport, Plugin Runtime, bundled IDC plugin, gateway settings,
TLS, optional service token, and recent activity. This check reads local state
only: it does not contact the gateway or invoke any binding or query endpoint.
Its response omits the gateway URL, App ID, credentials, internal paths,
runtime errors, message content, and QQ identities. The readiness endpoint
also requires a user login token and is intentionally unavailable to API keys
and MCP.

The Overview toolbar can copy a fixed-schema support report from
`/api/v1/system/idc-query/diagnostics`. The report contains the application
version/revision, readiness codes, aggregate QQ callback counters, gateway
configuration booleans/limits, and categorical audit counts. It never includes
individual bot names, UUIDs or App IDs, callback/gateway URLs, credentials,
exception text, QQ identities, member IDs, request IDs, messages, IP arguments,
or gateway responses. Unknown audit values are collapsed to `unknown` rather
than copied. This endpoint also requires a user login token and rejects API-key
and MCP authentication.

The configuration page also controls bot-side per-member limits for normal
queries and binding attempts. These limits protect the bot and gateway from a
single noisy QQ member; they are defense in depth and do not replace
gateway-side distributed limits or one-time verification-code controls.

Recent operation outcomes are read from a rotating owner-only JSONL audit log.
The log stores only command category, categorical outcome/reason, QQ group and
user identifiers, bound member identifier, request ID, timestamp, and duration.
It does not store chat text, verification codes, IP arguments, service tokens,
gateway error messages, or response payloads.

The **Group bindings** tab reads a bounded, validated snapshot of active local
bindings. It is deliberately read-only: an administrative deletion that did
not call the gateway would leave the two authorization states inconsistent.
Binding state and its committed recovery copy are atomically written with
owner-only permissions. Both the bindings and audit endpoints require a user
login token and reject API-key or MCP authentication.

The one-click script also accepts `IDC_QUERY_API_BASE_URL`,
`IDC_QUERY_API_TOKEN`, `IDC_QUERY_TIMEOUT_SECONDS`, and
`IDC_QUERY_VERIFY_TLS`, `IDC_QUERY_REQUESTS_PER_MINUTE`, and
`IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES` for unattended initial provisioning.

## Response envelope

Successful responses use:

```json
{
  "ok": true,
  "data": {},
  "message": "optional human-readable message",
  "trace_id": "optional gateway trace id"
}
```

Errors use an appropriate HTTP status and a short, non-sensitive message:

```json
{
  "ok": false,
  "error": {
    "code": "FORBIDDEN"
  },
  "message": "optional operator-safe diagnostic",
  "trace_id": "gateway trace id"
}
```

Stable `error.code` values allow the bot to return useful fixed text without
trusting an upstream message. Supported codes include
`INVALID_VERIFICATION_CODE`, `BINDING_VERIFICATION_FAILED`,
`MEMBER_NOT_FOUND`, `AUTHENTICATION_FAILED`, `SERVICE_TOKEN_INVALID`,
`UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, and
`UPSTREAM_UNAVAILABLE`. Unknown codes receive a generic operation-specific
message. The bot never displays the gateway's free-form `message` or error
body, so keep those fields for gateway-side operators and logs only.
The `ok` field is mandatory and must be a JSON boolean for binding and query
responses. An empty successful response is accepted only for unbinding, where
HTTP `204` is allowed.

Do not return stack traces, access tokens, SQL, internal hosts, or upstream
credentials. The plugin also removes common secret fields from generic output.

## Transport and response limits

- Every business request disables redirects. The gateway base URL must be the
  final HTTP or HTTPS endpoint; redirect responses are rejected so service
  credentials and QQ identity headers cannot be forwarded to another target.
- The client ignores environment proxy variables and connects directly to the
  configured gateway URL.
- A JSON response must be at most 512 KiB after content decoding. Response
  structures are limited to 16 container levels and 4,096 aggregate object or
  array items.
- Responses must be UTF-8 JSON objects. Non-standard constants such as `NaN`
  and `Infinity` are rejected.
- HTTP errors are classified before their response bodies are read. `401`
  means the gateway service token is invalid, while `403` means the bound
  member is not authorized.
- QQ group, QQ user, bound-member, request, gateway-token, and base-URL values
  are validated before network access. Control, surrogate, and invisible
  formatting characters are rejected from security identifiers. Identity and
  Bearer-token values must use visible ASCII characters.

## Binding endpoints

### Verify and create a binding

```http
POST /v1/bindings/verify
Content-Type: application/json

{
  "group_id": "group-openid",
  "user_id": "member-openid",
  "member_id": "10086",
  "verification_code": "938421"
}
```

Expected data:

```json
{
  "ok": true,
  "data": {
    "member_id": "10086",
    "member_name": "Example IDC Customer"
  }
}
```

The verification code must be one-time, expire quickly, and be rate limited.

### Remove a binding

```http
DELETE /v1/bindings/{group_id}
```

The gateway should keep an audit record even after deletion.

## Query endpoints

| Command | Endpoint |
|---|---|
| `查IP <IP>` | `GET /v1/ip/{ip}/summary` |
| `查防护 <IP>` | `GET /v1/ip/{ip}/protection` |
| `查封禁 <IP>` | `GET /v1/ip/{ip}/block-status` |
| `查流量 <IP>` | `GET /v1/ip/{ip}/traffic` |
| `查业务` | `GET /v1/account/businesses` |
| `查工单` | `GET /v1/account/tickets` |
| `查余额` | `GET /v1/account/balance` |

The gateway may return a preformatted `data.text`, a `data.fields` list, or a
plain object/list. Structured data is preferred because the plugin can apply
consistent labels and output limits. `data.text` must be a string; objects are
never converted to text. Operator-facing output is bounded to 32 lines and
1,800 characters, removes invisible formatting controls, ignores top-level
envelope metadata, and filters sensitive keys across names, keys, and labels.

Example IP response:

```json
{
  "ok": true,
  "data": {
    "ip": "1.1.1.1",
    "asset_name": "Web node 01",
    "room": "Shanghai A",
    "line": "BGP",
    "business_name": "Protected hosting",
    "protection_status": "Normal",
    "scrubbing_status": "Inactive",
    "blackhole_status": "Inactive",
    "block_status": "Not blocked",
    "current_traffic": "128 Mbps",
    "peak_traffic": "390 Mbps",
    "abnormal_status": "Normal",
    "updated_at": "2026-07-11T12:00:00+08:00"
  },
  "trace_id": "query-01"
}
```

## Operational requirements

- Use a read-only service identity for all query sources.
- Enforce tenant/member ownership at the gateway and again at each source when possible.
- Apply gateway-side request timeouts, per-member rate limits, and audit logging;
  bot-side limits and audit records are an additional layer, not a replacement.
- Deduplicate mutating requests with `X-Request-ID`.
- Redact balances, ticket details, personal information, and infrastructure metadata according to role.
- Return partial data with explicit source status when one upstream system is unavailable.
