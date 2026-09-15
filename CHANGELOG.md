# Changelog

This starts now, at 1.2.0, not at the beginning. Everything before this line
shipped without the version number moving; see `docs/HANDOFF.md` for that
history. From here, bump `pyproject.toml` and `dadloop/__init__.py` together,
in the same change that earns the bump, not after.

## 1.2.0 (2026-09-13)

Two people, one Dad, plus the visibility to trust what it's doing.

- **Multi-user collaboration.** `dadloop --serve` / `dadloop --join --as
  <name>`; the first plain `dadloop` on a machine opens the house, later ones
  join it. One journal, one writer, turns serialized.
- **Mid-turn fact injection.** A second person can hand Dad something while a
  turn is still running (`AgentLoop.inject_fact`), and it changes his answer
  before he gives it, not after.
- **Derived duplicate-ask handling.** Every shared turn carries a session
  record built from the journal (`stages.session_ledger`), so catching a
  repeated ask doesn't depend on the model recalling a transcript.
- **Household Ledger, all six categories.** Mom's Console read four memory
  categories before; now all six, with `usage` and `outcomes` (harness
  telemetry) translated into plain sentences, and a raw toggle for the record
  exactly as written to disk.
- **Fixes:** clarifying replies (questions with no tool call) were silently
  dropped by the TUI since the day `clarify` was added, now rendered; a
  failing model call no longer kills the house silently; Windows port binding
  hardened; the Household Ledger's tab row now wraps instead of clipping
  categories off-screen at narrow widths, and stopped assuming Google Fonts
  is reachable from every network this runs on.
