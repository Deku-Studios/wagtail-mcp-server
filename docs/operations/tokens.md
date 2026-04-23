# Token operations

`UserMcpToken` is the per-agent credential. One row per agent
identity, bound to a Django user, label, and (optionally) an
expiry. The plaintext is shown exactly once at issue time and
never again.

## Issuing a token

```bash
python manage.py mcp_issue_token --user alice --label "Claude Desktop"
```

Flags:

* `--user USERNAME` — required. The Django user the token authenticates as.
* `--label LABEL` — required. Free-form identifier shown in the admin and audit log.
* `--expires-at YYYY-MM-DD` — optional ISO date. Default: no expiry.

The plaintext token is printed to **stdout** exactly once. Capture
it then; you cannot retrieve it again. The hashed form is stored in
the DB.

## Listing tokens

```bash
python manage.py mcp_list_tokens
python manage.py mcp_list_tokens --user alice
python manage.py mcp_list_tokens --include-revoked
```

Prints a table of `id`, `label`, `user`, `created_at`, `last_used_at`,
`expires_at`, and `revoked_at`. Useful for audit reviews ("who has
tokens, when did they last use them?").

## Rotating a token

There is no "rotate in place" — Anthropic-style token rotation is
issue-then-revoke:

```bash
# 1. Mint a replacement
python manage.py mcp_issue_token --user alice --label "Claude Desktop (rotated 2026-04-22)"

# 2. Hand the new plaintext to the agent.
# 3. Verify the agent has cut over (last_used_at on the new token starts updating).
# 4. Revoke the old one.
python manage.py mcp_revoke_token --id 17
```

`revoke` sets `revoked_at = now()` and the token immediately stops
authenticating. Auth checks the `revoked_at IS NULL AND (expires_at
IS NULL OR expires_at > now())` predicate on every request.

## Revoking a token

```bash
python manage.py mcp_revoke_token --id 17
python manage.py mcp_revoke_token --user alice --all
```

`--all` revokes every token for the user — appropriate for offboarding
or for a confirmed credential leak.

## Using a token

The token is sent as an HTTP `Authorization: Bearer <token>` header
on every request to the MCP HTTP endpoint:

```bash
curl -X POST https://example.com/mcp/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For stdio transports (Claude Desktop, Cursor) the token is
typically passed via the `WAGTAIL_MCP_SERVER_TOKEN` environment
variable in the client's MCP config. See
[Getting started](../getting-started.md#connecting-an-mcp-client) for
client-specific snippets.

## Bootstrap token (standalone runtime only)

The `wagtail-mcp-serve` standalone runtime mints a single bootstrap
token on first boot and prints it to **stderr** alongside the
auto-created superuser. After that boot, the standalone runtime
behaves identically to the embedded form: issue more tokens with
`mcp_issue_token`, revoke with `mcp_revoke_token`.

The bootstrap is idempotent — once any `UserMcpToken` row exists,
the bootstrap step is a no-op on subsequent boots. Use this if you
want to seed the standalone runtime out-of-band: pre-populate a
token row before the first `wagtail-mcp-serve` invocation and the
bootstrap is skipped.

## Storage format

Tokens are stored as a (token_prefix, hashed_secret) pair:

* `token_prefix` is the first 8 characters of the plaintext, kept in clear so a leaked token can be cross-referenced against an issued row.
* `hashed_secret` is `pbkdf2_sha256` over the rest of the token. Tunable iteration count via `AUTH.TOKEN_HASH_ITERATIONS` (default 480_000 to match Django's password hasher floor).

Auth lookup is `O(1)`: fetch by prefix, then constant-time compare
the hash. There is no "scan all tokens" code path.

## Gotchas

* `last_used_at` is updated on every successful auth — it's a write per request. For very-high-throughput deployments you can disable updates via `AUTH.TRACK_LAST_USED = False` (the column stays, the writes stop).
* Token plaintext is `secrets.token_urlsafe(32)` — 256 bits of entropy. Don't try to make it shorter; the prefix-then-hash storage assumes the plaintext is long enough that the prefix isn't the entire token.
* Per-agent tokens, not per-key. If you spawn three agents with the same Claude Desktop config, all three send the same bearer; they all log as the same `(user, token)` pair in the audit trail. Issue one token per agent identity for clean attribution.
