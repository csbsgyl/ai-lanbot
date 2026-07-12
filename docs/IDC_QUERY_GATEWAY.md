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
  "message": "No permission or resource does not exist",
  "trace_id": "gateway trace id"
}
```

Do not return stack traces, access tokens, SQL, internal hosts, or upstream
credentials. The plugin also removes common secret fields from generic output.

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
consistent labels and output limits.

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
- Apply request timeouts, per-member rate limits, and audit logging.
- Deduplicate mutating requests with `X-Request-ID`.
- Redact balances, ticket details, personal information, and infrastructure metadata according to role.
- Return partial data with explicit source status when one upstream system is unavailable.
