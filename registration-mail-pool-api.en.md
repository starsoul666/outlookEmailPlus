# Registration Worker Integration and External API Guide

[中文文档](./注册与邮箱池接口文档.md) | [English Version](./registration-mail-pool-api.en.md)

## Overview

This document describes the `/api/external/*` endpoints currently implemented and exposed for registration workers, scripts, and third-party integrations.

Service goals:

- mailbox pool claim, release, and completion callbacks
- verification-code, verification-link, message-reading, and wait-for-message capabilities
- service health, capability discovery, and account readability checks

Current contract:

- the current version uses `/api/external/*`
- the old anonymous `/api/pool/*` endpoints have been removed
- real registration flows usually need more than `/api/external/pool/*`; they also use the verification and mail-reading endpoints

---

## Authentication and Access Rules

All `/api/external/*` endpoints require:

```text
X-API-Key: YOUR_API_KEY
```

Two key models are supported:

1. legacy single key: `settings.external_api_key`
2. enabled keys from `external_api_keys`

Additional rules:

- mail-reading endpoints are scoped by `email`. If the current key has `allowed_emails`, only those mailboxes may be accessed.
- `/api/external/pool/*` requires both:
  `pool_external_enabled=true` and the current key having `pool_access=true`
- in public mode, endpoints may also be limited by IP allowlist, rate limiting, and feature switches
- the current public-mode switches can disable:
  `raw_content`, `wait_message`, `pool_claim_random`, `pool_claim_release`, `pool_claim_complete`, `pool_stats`
- no browser session, cookies, or CSRF token is required

---

## Standard Response Format

Success response:

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

Failure response:

```json
{
  "success": false,
  "code": "ERROR_CODE",
  "message": "Error description",
  "data": null
}
```

Time fields use ISO 8601, for example:

```text
2026-03-26T12:00:00Z
```

---

## Endpoint Summary

### System and Discovery

| Endpoint | Purpose | Recommended |
| --- | --- | --- |
| `GET /api/external/health` | service health check | Yes |
| `GET /api/external/capabilities` | inspect currently available capabilities | Yes |
| `GET /api/external/account-status` | inspect account existence and readability | Optional |

### Mail Reading and Verification

| Endpoint | Purpose | Recommended |
| --- | --- | --- |
| `GET /api/external/messages` | list message summaries | Optional |
| `GET /api/external/messages/latest` | get the latest matching message | Yes |
| `GET /api/external/messages/{message_id}` | get message details | Optional |
| `GET /api/external/messages/{message_id}/raw` | get raw message content | Optional for debugging |
| `GET /api/external/verification-code` | extract a verification code | Common |
| `GET /api/external/verification-link` | extract a verification link | Common |
| `GET /api/external/wait-message` | wait for a new message | Common |
| `GET /api/external/probe/{probe_id}` | query async wait status | Needed for `mode=async` |

### Mail Pool

| Endpoint | Purpose | Recommended |
| --- | --- | --- |
| `POST /api/external/pool/claim-random` | claim a mailbox | Common |
| `POST /api/external/pool/claim-release` | release a mailbox | Common |
| `POST /api/external/pool/claim-complete` | submit the task result | Common |
| `GET /api/external/pool/stats` | inspect pool counts | Optional |

---

## Recommended Integration Flow

1. `GET /api/external/health`
2. `GET /api/external/capabilities`
3. `POST /api/external/pool/claim-random`
4. read the returned `email`
5. call `verification-code` / `verification-link` / `wait-message`
6. call `claim-complete` on success
7. call `claim-release` if the task is abandoned

---

## System and Discovery Endpoints

### `GET /api/external/health`

Purpose: inspect service, database, and instance-level upstream probe status.

Request example:

```bash
curl -X GET https://api.example.com/api/external/health \
  -H "X-API-Key: YOUR_API_KEY"
```

Important response fields:

- `status`
- `service`
- `version`
- `server_time_utc`
- `database`
- `upstream_probe_ok`
- `last_probe_at`
- `last_probe_error`

### `GET /api/external/capabilities`

Purpose: inspect currently available capabilities.

Response fields:

- `public_mode`
- `features`
- `restricted_features`

The current `features` list focuses on mail-reading capabilities:

- `message_list`
- `message_detail`
- `raw_content`
- `verification_code`
- `verification_link`
- `wait_message`

### `GET /api/external/account-status`

Query parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | Yes | mailbox address to inspect |

Important response fields:

- `exists`
- `account_type`
- `provider`
- `group_id`
- `status`
- `last_refresh_at`
- `preferred_method`
- `can_read`
- `upstream_probe_ok`
- `probe_method`
- `last_probe_at`
- `last_probe_error`

---

## Shared Mail Query Parameters

These parameters apply to most mail-reading endpoints:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | Yes | mailbox address |
| `folder` | string | No | `inbox` / `junkemail` / `deleteditems`, default `inbox` |
| `skip` | integer | No | default `0` |
| `top` | integer | No | range `1-50`, default `20` |
| `from_contains` | string | No | fuzzy match against sender |
| `subject_contains` | string | No | fuzzy match against subject |
| `since_minutes` | integer | No | only search mail from the last N minutes, must be greater than 0 |

Notes:

- if the mailbox came from the pool, use the `email` returned by `claim-random`
- the current external read API is email-based, not claim-based

---

## Mail and Verification Endpoints

### `GET /api/external/messages`

Purpose: return message summaries.

Response fields:

- `emails`
- `count`
- `has_more`

### `GET /api/external/messages/latest`

Purpose: return the latest matching message summary.

### `GET /api/external/messages/{message_id}`

Purpose: return message details.

Important response fields:

- `id`
- `email_address`
- `from_address`
- `to_address`
- `subject`
- `content`
- `html_content`
- `raw_content`
- `timestamp`
- `created_at`
- `has_html`
- `method`

### `GET /api/external/messages/{message_id}/raw`

Purpose: return raw message content.

Notes:

- mainly for debugging, custom parsing, and special-site compatibility
- may be disabled in public mode

### `GET /api/external/verification-code`

Purpose: extract a verification code from matching mail.

Additional parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `code_length` | string | No | restrict expected code length |
| `code_regex` | string | No | custom regex |
| `code_source` | string | No | `subject` / `content` / `html` / `all`, default `all` |

Notes:

- if `since_minutes` is omitted, the current implementation defaults to the last `10` minutes
- only high-confidence codes are returned as successful results

### `GET /api/external/verification-link`

Purpose: extract a verification link from matching mail.

Notes:

- if `since_minutes` is omitted, the current implementation defaults to the last `10` minutes
- only high-confidence links are returned as successful results

### `GET /api/external/wait-message`

Purpose: wait for a matching message that appears after the request begins.

Additional parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `timeout_seconds` | integer | No | range `1-120`, default `30` |
| `poll_interval` | integer | No | must be greater than `0` and not exceed `timeout_seconds`, default `5` |
| `mode` | string | No | `sync` or `async`, default `sync` |

Behavior:

- `mode=sync`: block until a new matching message is found, then return the message summary
- `mode=async`: return `probe_id` and HTTP `202`
- For high-concurrency or bulk registration flows, prefer `mode=async`; sync mode holds a request thread until a match or timeout

### `GET /api/external/probe/{probe_id}`

Purpose: query a probe created by `wait-message?mode=async`.

Statuses:

- `pending`
- `matched`
- `timeout`
- `error`

---

## Pool Endpoints

### `POST /api/external/pool/claim-random`

Request body:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `caller_id` | string | Yes | caller instance, node, or worker identity |
| `task_id` | string | Yes | unique task ID |
| `provider` | string | No | provider filter: `outlook` / `imap` / `custom` / `cloudflare_temp_mail` |

Current implementation notes:

- the current pool API supports filtering only by `provider`
- `outlook.com`, `hotmail.com`, `live.com`, and `live.cn` all map to `provider=outlook`
- the current external pool API does not support extra filtering by domain, group, or tags
- when `provider=cloudflare_temp_mail` and no eligible mailbox exists in pool, the service dynamically creates a CF temp mailbox and returns it as claimed

Success response fields:

- `account_id`
- `email`
- `email_domain`
- `claim_token`
- `claimed_at`
- `lease_expires_at`

When no mailbox is available, the current implementation returns:

- HTTP `200`
- response body with `success=false`
- `code=no_available_account`

#### Copy-paste Example (CF pool: claim-random)

```bash
curl -X POST https://api.example.com/api/external/pool/claim-random \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "caller_id": "reg-worker-001",
    "task_id": "task-20260409-0001",
    "provider": "cloudflare_temp_mail",
    "project_key": "project-A",
    "email_domain": "zerodotsix.top"
  }'
```

Success response example:

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {
    "account_id": 123,
    "email": "abc123@zerodotsix.top",
    "email_domain": "zerodotsix.top",
    "claim_token": "clm_xxx",
    "claimed_at": "2026-04-09T05:38:26.123Z",
    "lease_expires_at": "2026-04-09T05:48:26.123Z"
  }
}
```

No-available response example:

```json
{
  "success": false,
  "code": "no_available_account",
  "message": "No eligible mailbox available in pool",
  "data": null
}
```

### `POST /api/external/pool/claim-release`

Request body:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `account_id` | integer | Yes | account ID returned by the claim operation |
| `claim_token` | string | Yes | token returned by the claim operation |
| `caller_id` | string | Yes | must exactly match the claim request |
| `task_id` | string | Yes | must exactly match the claim request |
| `reason` | string | No | release reason |

### `POST /api/external/pool/claim-complete`

Request body:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `account_id` | integer | Yes | account ID returned by the claim operation |
| `claim_token` | string | Yes | token returned by the claim operation |
| `caller_id` | string | Yes | must exactly match the claim request |
| `task_id` | string | Yes | must exactly match the claim request |
| `result` | string | Yes | result enum, see table below |
| `detail` | string | No | extra detail |

`result` to pool-state mapping:

| `result` | Meaning | Final `pool_status` |
| --- | --- | --- |
| `success` | registration succeeded; project-reuse claims return to pool, legacy paths stay consumed | `available` or `used` |
| `verification_timeout` | no verification code arrived in time | `cooldown` |
| `provider_blocked` | provider-side block or restriction | `frozen` |
| `credential_invalid` | invalid credentials | `retired` |
| `network_error` | temporary network issue, safe to retry quickly | `available` |

Current implementation notes:

- the `claim-complete` request shape has **not changed**; whether project reuse applies is derived entirely from the claim context already bound during `claim-random`
- for long-lived mailboxes, when `claim-random` used a non-empty `project_key` and the callback keeps the original `caller_id / task_id`:
  - future claims in the same project are blocked by recorded success history
  - `claim-complete(result=success)` returns `pool_status=available`
  - the mailbox can be immediately claimed again by other projects
- when `project_key` is missing/blank, or for `provider=cloudflare_temp_mail` / temp-mail accounts, `success` keeps the legacy `used` behavior
- `/api/external/pool/stats` still aggregates only `accounts.pool_status`; there is no separate project-success counter in the response
- for `provider=cloudflare_temp_mail`:
  - `result in ('success','credential_invalid')` triggers a best-effort remote mailbox deletion
  - deletion failure is non-blocking and does not break `claim-complete` success response

#### Copy-paste Example (task success callback: claim-complete)

```bash
curl -X POST https://api.example.com/api/external/pool/claim-complete \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 123,
    "claim_token": "clm_xxx",
    "caller_id": "reg-worker-001",
    "task_id": "task-20260409-0001",
    "result": "success",
    "detail": "registration succeeded"
  }'
```

Success response example:

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {
    "account_id": 123,
    "pool_status": "available"
  }
}
```

Note: if the original claim did not enter the long-lived mailbox project-reuse path, the same `result=success` callback can still return `pool_status="used"`.

#### Copy-paste Example (abort task: claim-release)

```bash
curl -X POST https://api.example.com/api/external/pool/claim-release \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 123,
    "claim_token": "clm_xxx",
    "caller_id": "reg-worker-001",
    "task_id": "task-20260409-0001",
    "reason": "upstream registration API is temporarily unavailable"
  }'
```

### `GET /api/external/pool/stats`

Purpose: return counts for each pool state.

Response fields:

- `pool_counts.available`
- `pool_counts.claimed`
- `pool_counts.used`
- `pool_counts.cooldown`
- `pool_counts.frozen`
- `pool_counts.retired`

---

## Important Behavioral Notes

### Lease Expiration

In the current implementation, an expired claim does not immediately return to `available`.

Actual behavior:

1. the mailbox first moves from `claimed` to `cooldown`
2. a background maintenance task later restores it from `cooldown` to `available`

Default values:

- `pool_default_lease_seconds = 600`
- `pool_cooldown_seconds = 86400`

### Callback Parameters Must Match Exactly

For `claim-release` and `claim-complete`, the following fields must exactly match the original claim:

- `account_id`
- `claim_token`
- `caller_id`
- `task_id`

### `wait-message` Only Returns New Mail

The sync `wait-message` endpoint returns only a matching message that appears after the request begins. Older matching messages are not treated as new arrivals.

---

## Common Error Codes

| Error Code | Typical Meaning |
| --- | --- |
| `UNAUTHORIZED` | missing or invalid API key |
| `API_KEY_NOT_CONFIGURED` | no usable API key is configured on the server |
| `EMAIL_SCOPE_FORBIDDEN` | the current key cannot access this mailbox |
| `FORBIDDEN` | the current key cannot access the pool |
| `FEATURE_DISABLED` | the capability is disabled in public mode |
| `IP_NOT_ALLOWED` | the current IP is not in the allowlist |
| `RATE_LIMIT_EXCEEDED` | the current IP exceeded the rate limit |
| `INVALID_PARAM` | invalid request parameter |
| `ACCOUNT_NOT_FOUND` | mailbox account does not exist |
| `ACCOUNT_ACCESS_FORBIDDEN` | mailbox exists but cannot currently be read |
| `MAIL_NOT_FOUND` | no matching mail was found |
| `VERIFICATION_CODE_NOT_FOUND` | no high-confidence verification code was extracted |
| `VERIFICATION_LINK_NOT_FOUND` | no high-confidence verification link was extracted |
| `UPSTREAM_READ_FAILED` | Graph / IMAP read failed |
| `PROXY_ERROR` | proxy connection failed |
| `no_available_account` | no eligible mailbox is currently available in the pool |
| `TOKEN_MISMATCH` | `claim_token` does not match |
| `CALLER_MISMATCH` | `caller_id` or `task_id` does not match the claim record |
| `NOT_CLAIMED` | the mailbox is not currently in `claimed` state |

---

## FAQ

### Q1: Why is the pool API alone not enough for a registration project?

Because most registration projects also need:

- `verification-code`
- `verification-link`
- `wait-message`

### Q2: Can `provider=outlook` distinguish `hotmail.com` from `outlook.com`?

No. In the current implementation, those Microsoft domains all map to the same `provider=outlook`.

### Q3: What happens if I claim a mailbox and never send a callback?

The mailbox stays `claimed`, then moves to `cooldown` after lease expiration, and later returns to `available` after the cooldown window.

### Q4: Can the same mailbox be reused in another project after `success`?

Yes, but only on the long-lived mailbox project-reuse path: the original claim must include a non-empty `project_key`, and the callback must keep the same `caller_id / task_id`. In that case, `success` returns the mailbox to `available`, blocks the same project by recorded success history, and allows immediate reuse by other projects. Claims without `project_key` and temp-mail paths still end in `used`.

### Q5: Why does `no_available_account` still use HTTP 200?

That is the current implementation behavior. Integrators must check `success` and `code`, not only the HTTP status.

---

## Migration Notes

If you still use older scripts, migrate as follows:

1. move old `/api/pool/*` calls to `/api/external/pool/*`
2. send `X-API-Key` for all external requests
3. add mail-reading calls to the registration flow:
   `verification-code` / `verification-link` / `wait-message`
4. explicitly handle `403`, `429`, and `no_available_account`
5. if you need CF temp mail from pool, send `provider=cloudflare_temp_mail` in `claim-random`

---

## Version Note

This document describes the external API behavior already implemented in the current repository, not future planned APIs.
