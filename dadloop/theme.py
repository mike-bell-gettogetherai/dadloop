"""Author: Swami Chandrasekaran
Last Modified: 2026-09-04
Purpose: Textual UI colour themes for the TUI — three of them, chosen by the clock.

The dadloop design system — "a calmer, long-horizon work surface."

Colour here carries meaning, so it is defined once, in this file, rather than
guessed at each call site. The rule: a reader should be able to tell *what kind
of thing* they are looking at from its colour alone, before reading a word.

Every palette carries the same roles, so the rest of the TUI never changes:

    dad      Dad, and the single accent. His voice, the active plan step, the
             prompt caret, the one number that matters (spend). Used sparingly —
             if everything is the accent, nothing is.
    done     things that went right: a completed step, an enabled tool, budget
             headroom. Calm, not a neon "success" toast.
    skill / hold  two related jobs — skills being assembled off the shelf, AND
             Mom holding an action for review. Both are "pay attention, but
             nothing broke." A governance hold is authority pausing the loop,
             not an error; this colour says wait, red would lie.
    problem  genuine trouble: a veto, a tool that needs review, a real problem
             the world reports back. The only place red belongs.
    paper..faint  a five-stop neutral ramp (bright -> dim) that does all the
             structural work: headings, body, labels, chrome, hairlines.

The distinction that matters most is hold vs problem. Mom pausing the loop to
ask is the system *working*. A vetoed spend or an empty propane tank is
something *refusing to proceed*. Different events, different colours.

Three palettes, one house
-------------------------
Dad's constitution grounds him in the real date and time — "tonight" and
"this weekend" resolve against a real clock. The TUI now dresses for that same
clock, because a work surface you open at 6am and at 11pm should not feel like
the same room with the lights left on:

    sunrise     05:00–10:59   The kitchen at first light. Cream paper, coffee
                              ink, a marmalade accent. The only light theme.
    workshop    11:00–17:59   The garage bench at dusk. Warm near-black, one
                              coral lamp over a cold bench. The original.
    porchlight  18:00–04:59   Everyone's asleep but Dad. Midnight indigo, a
                              moth-yellow porch light for the accent, moonlit
                              greys. The quietest of the three.

Set DADLOOP_THEME=sunrise|workshop|porchlight to pin one (tests and screenshots
do). Otherwise the hour decides, once, at startup — the palette does not shift
under you mid-session.
"""

from __future__ import annotations

import os
import time

from textual.theme import Theme

# --- the three palettes ------------------------------------------------------
# Same keys in every dict. Nothing outside this file references a hex value.

_WORKSHOP = dict(
    name="workshop", dark=True,
    dad="#d97757", dad_dim="#a85c44", done="#8ba86a", skill="#c9a24c",
    hold="#c9a24c", problem="#c96f5a",
    paper="#e9e3d6", paper_2="#c9c1b3", mute="#9a9184", mute_2="#6b6459",
    faint="#4f4941",
    ink="#100e0a", ink_bar="#161310", panel="#1b1915", panel_2="#201d18",
    panel_3="#211d18", hair="#34302a", hair_2="#2e2a24", row="#232019",
    hold_bg="#2a2114",
)

_SUNRISE = dict(
    name="sunrise", dark=False,
    dad="#c4521f", dad_dim="#9a4119", done="#5e7d3c", skill="#b07d1f",
    hold="#b07d1f", problem="#b23a2b",
    paper="#1f1a14", paper_2="#3a3229", mute="#6b6157", mute_2="#948a7d",
    faint="#bdb3a5",
    ink="#efe6d7", ink_bar="#e6dccb", panel="#f7f0e4", panel_2="#fbf6ee",
    panel_3="#f3ebdd", hair="#d9cdb9", hair_2="#e5dbcb", row="#f1e9db",
    hold_bg="#f4e8cc",
)

_PORCHLIGHT = dict(
    name="porchlight", dark=True,
    dad="#e6c15a", dad_dim="#a88a3c", done="#7fa07a", skill="#c99a4a",
    hold="#c99a4a", problem="#d06f5f",
    paper="#e4e6ee", paper_2="#b9bdcc", mute="#8a90a3", mute_2="#5e6478",
    faint="#414659",
    ink="#0a0d17", ink_bar="#0e1220", panel="#121729", panel_2="#171d32",
    panel_3="#151a2e", hair="#272e48", hair_2="#222840", row="#1a2036",
    hold_bg="#2a2416",
)

_PALETTES = {p["name"]: p for p in (_WORKSHOP, _SUNRISE, _PORCHLIGHT)}


def _pick_palette() -> dict:
    """Pin by env var if set, otherwise let the hour decide."""
    forced = os.environ.get("DADLOOP_THEME", "").strip().lower()
    if forced in _PALETTES:
        return _PALETTES[forced]
    hour = time.localtime().tm_hour
    if 5 <= hour < 11:
        return _SUNRISE
    if 11 <= hour < 18:
        return _WORKSHOP
    return _PORCHLIGHT


_P = _pick_palette()
ACTIVE_PALETTE = _P["name"]

# A greeting the title bar can use, so the theme change reads as intentional
# rather than as a config accident.
GREETING = {
    "sunrise": "morning. coffee's on.",
    "workshop": "afternoon. bench is clear.",
    "porchlight": "late. porch light's on.",
}[ACTIVE_PALETTE]


DADLOOP_THEME = Theme(
    name="dadloop",
    dark=_P["dark"],
    # Textual's slots, mapped to our semantics.
    primary=_P["dad"],
    secondary=_P["skill"],
    accent=_P["dad"],
    warning=_P["hold"],
    error=_P["problem"],
    success=_P["done"],
    foreground=_P["paper"],
    background=_P["ink"],
    surface=_P["panel"],
    panel=_P["panel_2"],
    # Component tokens. Widgets reference these names, never the hex above, so a
    # palette change stays a one-file edit — and now, a one-clock edit.
    variables={
        "dad": _P["dad"], "dad-dim": _P["dad_dim"], "done": _P["done"],
        "skill": _P["skill"], "hold": _P["hold"], "problem": _P["problem"],
        "paper": _P["paper"], "ink-text": _P["paper_2"], "muted": _P["mute"],
        "muted-2": _P["mute_2"], "faint": _P["faint"],
        "shell": _P["panel"], "rail": _P["panel_2"], "bar": _P["panel_3"],
        "bar-low": _P["ink_bar"], "hair": _P["hair"], "hair-2": _P["hair_2"],
        "row-alt": _P["row"], "hold-bg": _P["hold_bg"],
        "footer-key-foreground": _P["dad"],
        "footer-description-foreground": _P["mute_2"],
        "block-cursor-background": _P["dad"],
        "block-cursor-foreground": _P["ink"],
        "input-selection-background": f"{_P['dad']} 35%",
        "scrollbar": _P["hair"],
        "scrollbar-hover": _P["mute_2"],
        "scrollbar-active": _P["dad"],
    },
)


# --- version-proof token substitution ---------------------------------------
# Textual only began resolving a Theme's custom `variables` inside App.CSS in
# recent versions. On older ones every $dad / $rail / $shell is an undefined
# variable and the app dies at stylesheet-parse time. Rather than depend on that
# behaviour, we substitute the tokens into the CSS ourselves before Textual ever
# sees it — which works on every version, including the ones that would have
# resolved them anyway.
TOKENS: dict[str, str] = {
    "dad": _P["dad"], "dad-dim": _P["dad_dim"], "done": _P["done"],
    "skill": _P["skill"], "hold": _P["hold"], "problem": _P["problem"],
    "paper": _P["paper"], "ink-text": _P["paper_2"], "muted": _P["mute"],
    "muted-2": _P["mute_2"], "faint": _P["faint"],
    "shell": _P["panel"], "rail": _P["panel_2"], "bar": _P["panel_3"],
    "bar-low": _P["ink_bar"], "hair": _P["hair"], "hair-2": _P["hair_2"],
    "row-alt": _P["row"], "hold-bg": _P["hold_bg"], "ink": _P["ink"],
}


def paint(css: str) -> str:
    """Replace every $token in a stylesheet with its hex value.

    Longest names first, so $hair-2 is not clobbered by $hair, and $dad-dim not
    by $dad. Textual's own variables ($background, $surface, $primary…) are left
    alone — they are not in TOKENS, so they pass straight through to Textual,
    which resolves them from the active theme as usual.
    """
    for name in sorted(TOKENS, key=len, reverse=True):
        css = css.replace(f"${name}", TOKENS[name])
    return css


def markup(text: str) -> str:
    """Same substitution for Rich console markup like [$dad]…[/].

    Content markup is resolved by Rich at render time, not by the CSS parser, and
    Rich has no notion of Textual theme variables at all — so these need the same
    treatment as the stylesheet.
    """
    for name in sorted(TOKENS, key=len, reverse=True):
        text = text.replace(f"[${name}]", f"[{TOKENS[name]}]")
        text = text.replace(f"[on ${name}", f"[on {TOKENS[name]}")
        text = text.replace(f"${name}", TOKENS[name])
    return text
