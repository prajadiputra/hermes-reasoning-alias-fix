"""reasoning-alias-fix — learn "duplicate field `reasoning_content`" rejections.

Why: a relay whose ChatMessage schema treats `reasoning` as an ALIAS of
`reasoning_content` (serde in front of vLLM, behind litellm; also 9Router's
reasoning-content injector) rejects a replayed assistant message that carries
both keys:

    HTTP 400  ... duplicate field `reasoning_content` at line 1 column N

Hermes' own self-healing (`record_reasoning_field_rejection`) never fires for
that wording, because `rejected_reasoning_fields()` gates on
`_UNKNOWN_FIELD_PHRASES` and that list has no "duplicate field" entry. The 400
is classified non-retryable, the fallback model answers instead, and — the
replayed message staying in history — EVERY later turn repeats it.

This plugin wraps `agent.message_sanitization.rejected_reasoning_fields` and
adds exactly that one case: when the body complains about a duplicate
`reasoning_content` AND this request carried both `reasoning_content` and
`reasoning`, report the ALIAS (`reasoning`) as the rejected carrier.
`reasoning_content` — the field that carries the text and that the relay
actually reads — is kept, so the reasoning still replays.

Everything else delegates to the original function unchanged, and any internal
error falls back to the original verdict (fail-safe: never crash the host).

Survives `hermes update`: lives in ~/.hermes/plugins/, which the updater does
not touch (it git-resets only /usr/local/lib/hermes-agent).
"""

import logging

log = logging.getLogger("agent.plugin.reasoning-alias-fix")

_installed = False


def _install() -> bool:
    """Wrap the gate. Returns True when the patch is in place."""
    global _installed
    try:
        from agent import message_sanitization as ms
    except Exception as exc:  # pragma: no cover - import shape changed
        log.warning("reasoning-alias-fix: cannot import agent.message_sanitization (%s)", exc)
        return False

    original = getattr(ms, "rejected_reasoning_fields", None)
    if original is None:
        log.warning("reasoning-alias-fix: rejected_reasoning_fields not found — not patched")
        return False
    if getattr(original, "_hermes_reasoning_alias_fix", False):
        _installed = True
        return True

    rc = getattr(ms, "RC", "reasoning_content")
    r = getattr(ms, "R", "reasoning")
    carriers = tuple(getattr(ms, "REASONING_CARRIERS", (rc, r)))
    named_res = getattr(ms, "_NAMED_FIELD_RES", {})

    def rejected_reasoning_fields(error_body, sent_messages):
        try:
            body = str(error_body or "").lower()
            if "duplicate field" in body and rc in named_res and named_res[rc].search(body):
                sent = {
                    key
                    for msg in (sent_messages if isinstance(sent_messages, list) else ())
                    if isinstance(msg, dict) and msg.get("role") == "assistant"
                    for key in carriers
                    if key in msg
                }
                if rc in sent and r in sent:
                    # Drop only the alias; `reasoning_content` still carries the text.
                    return frozenset({r})
        except Exception as exc:  # pragma: no cover - never break the host
            log.debug("reasoning-alias-fix: falling back to original (%s)", exc)
        return original(error_body, sent_messages)

    rejected_reasoning_fields._hermes_reasoning_alias_fix = True
    ms.rejected_reasoning_fields = rejected_reasoning_fields
    _installed = True
    log.info(
        "reasoning-alias-fix: patched rejected_reasoning_fields "
        "(learns 'duplicate field %s' and drops the '%s' alias)", rc, r,
    )
    return True


def register(ctx=None):
    if _install():
        try:
            ctx.register_command(
                "reasoningaliasfix-status",
                lambda *a, **k: "reasoning-alias-fix: active — 'duplicate field `reasoning_content`' "
                "rejections now drop the `reasoning` alias once and keep `reasoning_content`.",
                "Show reasoning-alias-fix plugin status",
            )
        except Exception:
            pass
