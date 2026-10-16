# reasoning-alias-fix

A Hermes user plugin. Fixes **HTTP 400 `duplicate field \`reasoning_content\``** on every
replayed turn, for any upstream whose schema treats `reasoning` as an **alias** of
`reasoning_content`.

Survives `hermes update` — it lives in `~/.hermes/plugins/`, which the updater never touches.

## The symptom it fixes

Multi-turn conversations against such an upstream fail on **every** turn that has assistant
history, and a fallback model silently answers instead of your configured model:

```
HTTP 400  Failed to deserialize the JSON body into the target type:
          duplicate field `reasoning_content` at line 1 column 845083
Streaming failed before delivery: Error code: 400 ...
API call failed (attempt 1/3, not retryable) error_type=BadRequestError
Fallback activated: <your model> -> <fallback model>
```

Reproduction matrix (same model/key, one-shot calls) — the endpoint is the oracle:

| assistant message carries | result |
|---|---|
| `reasoning_content` only | 200 |
| `reasoning` only | 200 |
| **`reasoning_content` + `reasoning`** | **400 `duplicate field reasoning_content`** |

## How it works

Hermes already replays prior reasoning and already has a self-healing path
(`agent.message_sanitization.record_reasoning_field_rejection`) that learns which reasoning
carrier a route rejects and retries once without it. That learner gates on
`_UNKNOWN_FIELD_PHRASES` — a list of "unknown field"-style wordings. A serde `duplicate field`
complaint matches none of them, so **nothing is ever learned and the same 400 recurs forever**.

This plugin wraps `rejected_reasoning_fields()` and adds exactly that one case: when the body
complains about a duplicate `reasoning_content` **and** this request carried both
`reasoning_content` and `reasoning`, it reports the **alias** (`reasoning`) as the rejected
carrier. `reasoning_content` — the field that carries the text and that the relay actually
reads — is kept, so reasoning still replays on the retry.

Every other input delegates to the original function. Any internal error falls back to the
original verdict (fail-safe: it can never crash the host process).

## Install

```bash
git clone https://github.com/<owner>/hermes-reasoning-alias-fix.git
cp -r hermes-reasoning-alias-fix ~/.hermes/plugins/reasoning-alias-fix
hermes plugins doctor reasoning-alias-fix     # expect: registration passed
hermes plugins enable reasoning-alias-fix
```

Then restart the process that serves the patched route — **enabling does not patch an
already-running process**, and the gateway and the dashboard are different processes:

```bash
systemctl --user restart hermes-gateway        # and/or hermes-dashboard, whichever serves your route
```

A new session also picks it up (`hermes plugins enable` reports "takes effect on next session").

## Verify

1. **Registration** — `hermes plugins doctor reasoning-alias-fix` → `registration passed`.
2. **Live process** — the register-time log line:
   ```bash
   grep 'reasoning-alias-fix' ~/.hermes/logs/agent.log | tail -1
   # INFO agent.plugin.reasoning-alias-fix: patched rejected_reasoning_fields ...
   ```
3. **Selftest** (stdlib, no framework) — run it with the Hermes venv python:
   ```bash
   /usr/local/lib/hermes-agent/venv/bin/python ~/.hermes/plugins/reasoning-alias-fix/selftest.py
   ```
   The install tree must be **unpatched** for the run to be meaningful; the selftest asserts that
   and exits non-zero otherwise.
4. **End-to-end** — the next multi-turn conversation against the aliasing upstream completes on
   your configured model instead of falling back.

## Compatibility / fails-safe

- Wraps one module-global symbol, `agent.message_sanitization.rejected_reasoning_fields`, which is
  called from inside that same module — so one patch covers every route and caller.
- If the symbol is missing or moved by a future Hermes release, the plugin logs a warning and
  **does not patch** — the host keeps working, the bug simply returns.
- Needs no dependencies (stdlib only), so a post-update venv sync cannot break it.

### Recovery after an update

If the plugin ever stops loading, the updater's eviction path **disables** (never deletes) it:

```bash
hermes plugins enable reasoning-alias-fix
```

## Security notes

- Widens nothing but one error-classification condition. No authentication, authorization, or
  redaction logic is touched.
- The only input it inspects is the upstream **error body** plus the assistant messages already
  being sent. It never reads, writes, or logs message content, credentials, or tokens.

## What this does NOT change

- It does not disable reasoning replay in general.
- It does not touch the `reasoning_content` carrier on must-echo routes (DeepSeek-style), where
  omitting it is itself an HTTP 400.
- It does not fix a route that sends **only** `reasoning_content` and is told `duplicate field
  reasoning_content` — there is no carrier left to drop. That case is upstream's to fix.
- It is a client-side workaround. The durable fixes are upstream: `NousResearch/hermes-agent#136487`
  (this same change) and `decolua/9router#4881` (the injector that mints the duplicate).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `doctor` passes, 400 continues | serving process not restarted | restart the unit that serves your route |
| No log line at all | plugin disabled by an update | `hermes plugins enable reasoning-alias-fix` |
| Log line present, 400 continues | the route sent `reasoning_content` only | upstream issue — see "What this does NOT change" |
| Plugin vanished from `plugins list` | wrong `HERMES_HOME` / plugin dir name mismatch | dir name must equal the plugin `name` |

## License

MIT — see `LICENSE`.
