---
title: Production Security
---

# Production Security

## Security Architecture

AINRF uses a three-layer defense-in-depth architecture:

1. **IP Allowlist** — Reject requests from unknown networks before they reach the application. Configured via `AINRF_ALLOWED_CIDRS`.
2. **Request Size Limit** — Block oversized payloads. Default: 50 MB, configurable via `AINRF_MAX_REQUEST_BODY_BYTES`.
3. **JWT Authentication** — All non-exempt routes require a valid JWT token. Production mode tightens exemptions.

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `AINRF_PRODUCTION` | `false` | Enables production mode |
| `AINRF_ALLOWED_CIDRS` | _(empty)_ | Comma-separated CIDRs allowed to connect |
| `AINRF_TRUSTED_PROXY_CIDRS` | _(empty)_ | CIDRs of trusted reverse proxies |
| `AINRF_PUBLIC_REGISTRATION_ENABLED` | `true` | Allow public user registration |
| `AINRF_LOGIN_MAX_FAILURES` | `10` | Failed logins before lockout |
| `AINRF_LOGIN_LOCKOUT_HOURS` | `24` | Lockout duration |
| `AINRF_MAX_REQUEST_BODY_BYTES` | `52428800` | Max request body (50 MB) |
| `AINRF_MAX_CONCURRENT_REQUESTS` | `0` | Max in-flight requests (0 = unlimited) |
| `AINRF_METRICS_ENABLED` | `false` | Enable Prometheus `/metrics` endpoint |

## Production Deployment Checklist

- [ ] Set `AINRF_PRODUCTION=true`
- [ ] Configure `AINRF_ALLOWED_CIDRS` to your network ranges
- [ ] Set `AINRF_TRUSTED_PROXY_CIDRS` to your reverse proxy IP(s)
- [ ] Disable public registration: `AINRF_PUBLIC_REGISTRATION_ENABLED=false`
- [ ] Run behind a reverse proxy (Caddy/Nginx) with TLS
- [ ] Bind to `127.0.0.1` only — never expose the backend directly
- [ ] Generate a strong API key: `openssl rand -hex 32`
- [ ] Set appropriate `AINRF_LOGIN_MAX_FAILURES` and lockout duration
- [ ] Enable metrics: `AINRF_METRICS_ENABLED=true`
- [ ] Configure log rotation for `<state_root>/logs/`

## Log Locations

- **Application logs**: `<state_root>/logs/backend-YYYYMMDD.log`
- **Audit events**: Same file, filtered by `component=audit`
- **Nginx/Caddy access logs**: Standard reverse proxy logs

## Audit Events

See [[observability]] for the complete audit event catalog.

## Sensitive Path Detection

The following path patterns trigger `files.sensitive_path_access` audit events at severity `high`:

| Pattern | Example |
|---|---|
| `.env` files | `.env`, `.env.production` |
| Certificate files | `*.pem`, `*.key` |
| SSH keys | `id_rsa`, `id_ed25519`, `authorized_keys` |
| Database files | `*.sqlite`, `*.db` |
| System files | `/etc/passwd`, `/etc/shadow` |
| SSH directories | `~/.ssh/*` |
| Privileged paths | `/root/*`, `/proc/*` |
| Admin secrets | `admin_initial_password.txt` |

## Trusted Proxy Configuration

When running behind a reverse proxy, `X-Forwarded-For` headers allow the application to see the real client IP. However, this must be explicitly configured to prevent IP spoofing:

```
# Only trust the local reverse proxy
AINRF_TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

Without `AINRF_TRUSTED_PROXY_CIDRS`, the application trusts `X-Forwarded-For` from any source (dev mode behavior).

## Token Security

- Access tokens are short-lived JWTs
- Refresh tokens allow renewal without re-authentication
- **Neither is ever logged** — the redaction layer strips `Authorization` headers, `api_key` parameters, and `token` query strings from all log output
- The audit log records only the fact that authentication occurred, never the credential itself

## Incident Response

When investigating a security incident, search the audit log:

```bash
# All authentication events
grep '"component":"audit"' logs/backend-*.log | grep '"event":"auth.'

# Sensitive file access
grep '"event":"files.sensitive_path_access"' logs/backend-*.log

# Terminal sessions
grep '"event":"terminal.' logs/backend-*.log

# SSH configuration changes
grep '"event":"environment.ssh_field_changed"' logs/backend-*.log

# All high/critical severity events
grep '"severity":"high\|"severity":"critical"' logs/backend-*.log
```

Correlate events using the `request_id` field — it links all log lines within a single HTTP request or WebSocket session.
