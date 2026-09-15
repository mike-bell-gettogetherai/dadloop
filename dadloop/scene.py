"""Author: Swami Chandrasekaran
Last Modified: 2026-09-04
Purpose: The house, drawn in the terminal's own materials, for the launch page and the rail.

Two views of one house, built from block and box-drawing characters and coloured
with the same semantic tokens as everything else in the TUI:

    launch_scene()   The landing page centrepiece. A whole house under a sky that
                     matches the time-of-day palette theme.py chose — sun low and
                     warm at sunrise, high at midday, a moon and stars at night
                     with every window lit. Smoke off the chimney in the evening.
                     It is decoration, but decoration that tells the truth: the
                     scene agrees with the clock.

    mini_house()     The rail's live floor plan. Eight rooms as a two-by-four
                     grid of markers, keyed to the same tool-to-room mapping the
                     web console uses, so the two surfaces agree on where Dad is.
                     A room lights as its tool runs, turns red when the tool
                     reports a problem, gold when Mom holds the call, and Dad's
                     marker sits beside whichever room he is working in. This is
                     the "you can see the whole thing happen" thesis inside the
                     terminal itself.

Everything here is pure: state in, markup out. No widgets, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .theme import ACTIVE_PALETTE

# ---------------------------------------------------------------- rooms
# Mirrors console/static/console.js ROOM_OF / SKILL_ROOM. Keep them in step.
ROOM_OF_TOOL = {
    "check_grill": "grill", "check_pantry": "pantry", "check_weather": "porch",
    "check_wallet": "study", "find_tool": "garage", "check_hardware_store": "drive",
    "web_search": "drive", "set_thermostat": "hall",
}
ROOM_OF_SKILL = {
    "yard-work": "lawn", "the-thermostat": "hall", "grilling": "grill",
    "hosting": "pantry", "money-decisions": "study", "grocery-runs": "drive",
    "fixing-things": "garage",
}
ROOM_ORDER = ("grill", "pantry", "porch", "lawn", "study", "garage", "drive", "hall")
ROOM_LABEL = {"grill": "grill", "pantry": "pantry", "porch": "porch", "lawn": "lawn",
              "study": "study", "garage": "garage", "drive": "drive", "hall": "hall"}
SENDS_DAD_OUT = {"check_hardware_store"}


@dataclass
class HouseState:
    """What the rail needs to draw the house: per-room state and where Dad is.

    Values in `rooms` are None (idle), 'lit', 'trouble' or 'governed'. Reset at
    the start of every turn; the house is a picture of THIS turn's work.
    """
    rooms: dict = field(default_factory=dict)
    dad_room: str = "hall"
    dad_out: bool = False

    def reset(self) -> None:
        self.rooms.clear()
        self.dad_room = "hall"
        self.dad_out = False

    def on_tool_call(self, name: str, args: dict | None) -> None:
        room = ROOM_OF_TOOL.get(name)
        if name == "load_skill":
            room = ROOM_OF_SKILL.get((args or {}).get("name", ""), None)
        if room:
            self.dad_room = room
            self.dad_out = False
        if name in SENDS_DAD_OUT:
            self.dad_out = True

    def on_tool_result(self, name: str, out, problem: bool, args: dict | None = None) -> None:
        room = ROOM_OF_TOOL.get(name)
        if name == "load_skill":
            room = ROOM_OF_SKILL.get((args or {}).get("name", ""), None)
        if room:
            # a governed room stays governed; a result never downgrades a hold
            if self.rooms.get(room) != "governed":
                self.rooms[room] = "trouble" if problem else "lit"
            self.dad_room = room
        if name in SENDS_DAD_OUT:
            self.dad_out = False

    def on_governed(self, name: str) -> None:
        room = ROOM_OF_TOOL.get(name)
        if room:
            self.rooms[room] = "governed"
            self.dad_room = room


def mini_house(state: HouseState) -> str:
    """The rail's floor plan: two rows of four rooms, coloured by state.

        HOUSE  dad · drive
        ▪ grill     ▪ pantry
        ▪ porch     ▪ lawn
        ▪ study     ▪ garage
        ◍ drive     ▪ hall

    Idle rooms are faint; the marker takes the room's state colour, and Dad's
    own marker (◍, coral) replaces the marker of the room he is in. When he is
    out at the store the drive shows him leaving instead.
    """
    colour = {None: "$faint", "lit": "$skill", "trouble": "$problem", "governed": "$hold"}
    cells = []
    for room in ROOM_ORDER:
        st = state.rooms.get(room)
        here = (state.dad_room == room) and not state.dad_out
        if room == "drive" and state.dad_out:
            mark = "[$dad]→[/]"                  # leaving
        elif here:
            mark = "[$dad]◍[/]"
        else:
            mark = f"[{colour[st]}]▪[/]"
        label_c = "$ink-text" if (st or here) else "$muted-2"
        cells.append(f"{mark} [{label_c}]{ROOM_LABEL[room]:<7}[/]")
    # The rail is about 36 columns wide: two rooms per row fit, four wrap.
    rows = ["   ".join(cells[i:i + 2]) for i in range(0, len(cells), 2)]
    where = ("[$muted-2]out at the store[/]" if state.dad_out
             else f"[$muted-2]dad · {ROOM_LABEL[state.dad_room]}[/]")
    return f"[$muted]HOUSE[/]  {where}\n" + "\n".join(rows) + "\n\n"


# --------------------------------------------------------------- launch scene
def launch_scene() -> str:
    """The landing-page house, under the sky the clock chose.

    Built as plain rows first so the geometry can be checked by eye, then
    coloured by row and by character class. Widths are equal by construction.
    """
    pal = ACTIVE_PALETTE
    night = pal == "porchlight"
    morning = pal == "sunrise"

    # Windows: lit at night, warm at sunrise, dark glass by day.
    win = "▓▓" if night else ("░░" if morning else "  ")
    winc = "$skill" if night else ("$hold" if morning else "$faint")

    # Sky row: where the sun or moon hangs, and stars only at night.
    if night:
        sky1 = "      ·      ✦          ·        ☾        ✦     ·   "
        sky2 = "  ✦        ·      ·           ·       ✦          · "
    elif morning:
        sky1 = "   ☀                                               "
        sky2 = "                                                   "
    else:
        sky1 = "                                          ☀        "
        sky2 = "                                                   "
    smoke = "                 ∿  ∿                              " if not morning else " " * 51
    W = 58

    rows_plain = [
        sky1,
        sky2,
        smoke,
        "                ▄██▄                               ",
        "         ▄▄▄▄▄▄▄████▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄                ",
        "      ▄▄█████████████████████████████▄▄       ▲    ",
        "     ███████████████████████████████████     ▲▲▲   ",
        "      █ ┌──┐ ┌──┐ dadloop  ┌──┐ ┌──┐ █     ▲▲▲▲▲  ",
        f"      █ │{win}│ │{win}│          │{win}│ │{win}│ █       ║║    ",
        "      █ └──┘ └──┘ ┌────┐   └──┘ └──┘ █       ║║      ▄▄▄▄▄    ",
        "      █           │ ●  │            █           ▄█████████▄ ",
        "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔●▔▔▔▔▔▔●▔▔▔",
    ]
    # normalise width defensively (the f-string rows can drift by a char)
    rows_plain = [r.ljust(W)[:W] for r in rows_plain]

    def colour_row(i: int, row: str) -> str:
        out = []
        for ch in row:
            if ch in "☀":            tok = "$skill"
            elif ch in "☾":          tok = "$paper"
            elif ch in "✦":          tok = "$muted"
            elif ch in "·":          tok = "$faint"
            elif ch in "∿":          tok = "$faint"
            elif ch in "▲":          tok = "$done"
            elif ch in "║":          tok = "$muted-2"
            elif ch in "▔":          tok = "$done"
            elif ch in "●":          tok = "$ink-text"
            elif ch in "▓░":         tok = winc
            elif ch in "┌┐└┘│─":     tok = "$muted-2"
            elif ch in "█▄" and 3 <= i <= 6:   tok = "$dad"       # roof + chimney
            elif ch in "█▄" and i >= 7 and i <= 10: tok = "$muted" # walls, car
            elif ch.isalpha():       tok = "$paper"
            else:                    tok = None
            # merge runs of one colour into one span: fewer tags, and a word
            # like the nameplate stays a word instead of seven kerned letters
            if out and out[-1][0] == tok:
                out[-1] = (tok, out[-1][1] + ch)
            else:
                out.append((tok, ch))
        return "".join(f"[{t}]{txt}[/]" if t else txt for t, txt in out)

    # the car body on rows 9–10 is the last 9 columns; recolour those to ink-text
    coloured = []
    for i, row in enumerate(rows_plain):
        if i in (9, 10):
            head, tail = row[:46], row[46:]
            coloured.append(colour_row(i, head) + "".join(
                f"[$ink-text]{c}[/]" if c in "█▄" else c for c in tail))
        else:
            coloured.append(colour_row(i, row))
    return "\n".join(coloured)
