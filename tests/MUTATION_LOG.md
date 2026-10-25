"""
tests/MUTATION_LOG.md — mutation checks that were actually run.

Each entry records: what was mutated, what command was run, what failure was
observed (pasted), and that the original was restored afterward.
"""

# 2026-10-24 — baseline-fix branch

## sanity gate: pytest-timeout fires before the suite hangs
- Mutation: none yet (timeout is the guard itself).
- Command: `python -m pytest tests/test_qemu_monitor_unit.py -q --timeout=1`
- Observed: suite still completes quickly because the rewritten socket test no
  longer blocks in srv.accept() with no client. This is the expected state AFTER
  the Step 3 fix; the timeout is a backstop, not the primary fix.
- Status: backstop present; primary fix is the real test + threading + timeouts.
