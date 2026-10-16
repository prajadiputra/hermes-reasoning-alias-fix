#!/usr/bin/env python3
"""Selftest for reasoning-alias-fix.

Run with the Hermes venv python (stdlib only, no framework):

    /usr/local/lib/hermes-agent/venv/bin/python selftest.py      # exit 0 = pass

It exercises the patch against the REAL installed module, so it proves the
plugin still fixes the behaviour even after a `hermes update` resets the tree —
the install must be UNPATCHED for the run to be meaningful (asserted below).
"""

import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("reasoning_alias_fix", HERE / "__init__.py")
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

FAILURES = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f" {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


sys.path.insert(0, "/usr/local/lib/hermes-agent")
from agent import message_sanitization as ms  # noqa: E402

if getattr(ms.rejected_reasoning_fields, "_hermes_reasoning_alias_fix", False):
    print("  FAIL the install tree is ALREADY patched — revert it before running this selftest,")
    print("       otherwise the run proves nothing about the plugin.")
    sys.exit(1)

check("install returns True", plugin._install() is True)
check("wrapper is marked", getattr(ms.rejected_reasoning_fields, "_hermes_reasoning_alias_fix", False))
check("re-install is a no-op", plugin._install() is True)

SENT_BOTH = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "yo", "reasoning": "r1", "reasoning_content": "r2",
     "reasoning_details": [{"type": "reasoning.text", "text": "r3"}]},
]
SENT_ALIAS_ONLY = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "yo", "reasoning": "r1"},
]
SENT_RC_ONLY = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "yo", "reasoning_content": "r2"},
]
DUP = json.dumps({"error": {"message": "Failed to deserialize the JSON body into the target type: "
    "duplicate field `reasoning_content` at line 1 column 230262 (request id: x)",
    "code": "invalid_request"}})

check("duplicate + both keys -> drop ONLY the alias",
      set(ms.rejected_reasoning_fields(DUP, SENT_BOTH)) == {"reasoning"})
check("rejection repeats: still the alias, never all carriers",
      set(ms.rejected_reasoning_fields(DUP, SENT_BOTH)) == {"reasoning"})
check("alias sent alone -> original verdict (nothing to drop)",
      set(ms.rejected_reasoning_fields(DUP, SENT_ALIAS_ONLY)) == set())
check("reasoning_content alone -> original verdict (kept)",
      set(ms.rejected_reasoning_fields(DUP, SENT_RC_ONLY)) == set())
check("duplicate field about another key -> not attributed",
      set(ms.rejected_reasoning_fields(json.dumps({"error": {"message": "duplicate field `temperature`"}}),
                                       SENT_BOTH)) == set())
check("unrelated error -> not attributed",
      set(ms.rejected_reasoning_fields(json.dumps({"error": {"message": "rate limit exceeded"}}),
                                       SENT_BOTH)) == set())
check("unknown-field path keeps the widening behaviour (no regression)",
      set(ms.rejected_reasoning_fields(json.dumps({"error": {"message": "unknown field `reasoning_content`"}}),
                                       SENT_BOTH)) == set(ms.REASONING_CARRIERS))

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
    sys.exit(1)
print("all checks passed")
