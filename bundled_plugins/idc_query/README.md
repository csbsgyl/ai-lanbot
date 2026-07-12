# IDC Query Plugin

This bundled LangBot plugin implements deterministic IDC self-service commands
for QQ Official group bots. It handles member binding, access checks, duplicate
message suppression, IP validation, gateway calls, and plain-text responses
without sending commands to an LLM.

The plugin is installed automatically by `scripts/one-click-deploy.sh`.

## Gateway configuration

After deployment, sign in as an administrator and open **Settings > IDC Query**
to set the gateway URL, service token, request timeout, and TLS verification.
The token is never returned by the settings API, and the plugin loads saved
changes on the next query without a container restart.

For unattended first-time provisioning, set these variables before running the
deployment script:

```bash
export IDC_QUERY_API_BASE_URL=https://query.example.com
export IDC_QUERY_API_TOKEN=replace-with-a-service-token
```

Do not commit the service token or place it in public plugin configuration. The
WebUI and one-click script store the values in
`docker/data/idc-query/config.env` with owner-only permissions, and the plugin
reads that mounted file because the Plugin Runtime launches plugin processes
with a clean environment.

See the
[IDC query gateway contract](https://github.com/csbsgyl/ai-lanbot/blob/main/docs/IDC_QUERY_GATEWAY.md)
for the normalized HTTP interface.
