"""Author: Mike Bell
Last Modified: 2026-09-19
Purpose: Selector-facing triggers per skill, and composition derived from the skill bodies.

Two audiences, two texts. The one-line `description` in each skill file is
read by Claude inside a full conversation, so it can carry attitude ("how Dad
defends the thermostat") and shorthand. A classifier reads a typed question
against a bare request, so it needs triggers: what the request is ABOUT, what
counts (`true`), and what does not (`false`). These never touch the files
Claude reads.

Composition is not wording. `composes_from_bodies` reads the "Load `x`" lines
already in the skill bodies, so the dependency graph comes from the one place
it is already written and cannot drift from it."""
from __future__ import annotations

import re

TRIGGERS: dict[str, dict[str, str]] = {
    "answering-big-questions": {
        "about": "a child asking a big or philosophical question, such as about death, why things are, or where things come from",
        "true": "a kid's existential or curiosity question that needs a thoughtful answer",
        "false": "an adult's practical question about money, plans, or the house",
    },
    "bedtime": {
        "about": "getting kids to sleep or handling bedtime",
        "true": "kids not sleeping, bedtime routine, lights out, late at night",
        "false": "adult schedules or the thermostat",
    },
    "breaking-up-fights": {
        "about": "kids fighting, arguing, or screaming at each other",
        "true": "siblings or kids in conflict right now",
        "false": "a kid who is sad or a disagreement with an adult",
    },
    "comforting-a-kid": {
        "about": "a child who is upset, crying, disappointed, or hurt",
        "true": "a kid needing comfort after a loss, rejection, or a bad day",
        "false": "kids fighting each other or a discipline question",
    },
    "fixing-things": {
        "about": "repairing something broken in the house, like a faucet, a door, or an appliance",
        "true": "a leak, a drip, something that broke and needs a repair",
        "false": "cooking, yard work, or a purchase decision",
    },
    "grilling": {
        "about": "cooking on the grill, the menu, or the cook plan for a cookout",
        "true": "grilling, barbecue, cooking outside, the propane or the grill",
        "false": "shopping lists on their own or the lawn",
    },
    "grocery-runs": {
        "about": "going shopping for food or supplies, or being out of something",
        "true": "a store run, provisioning, 'we're out of'",
        "false": "hosting an event where shopping is not mentioned, or a budget question",
    },
    "hosting": {
        "about": "hosting people, having guests over, or planning a cookout, party, or get-together",
        "true": "any event with guests, a cookout, having the neighbors over",
        "false": "a family-only meal or a single chore with no guests",
    },
    "money-decisions": {
        "about": "whether to spend money, a budget, a purchase, or 'can we afford it'",
        "true": "a spending decision, a budget limit, a price, affordability",
        "false": "a child's abstract question about what money is",
    },
    "road-trips": {
        "about": "a drive or trip somewhere with the family, whether planning it, affording it, or surviving it",
        "true": "a trip, a drive, travel to another place, 'are we there yet'",
        "false": "errands around town or a walk",
    },
    "saying-no": {
        "about": "a kid asking permission for something the answer is probably no to",
        "true": "a request to stay out late, buy something, or bend a house rule",
        "false": "a kid who is upset or a purely adult decision",
    },
    "snow-shoveling": {
        "about": "snow on the ground and clearing the driveway or walk",
        "true": "snowfall, shoveling, the driveway in winter",
        "false": "mowing, rain, or summer yard work",
    },
    "teaching-kids-stuff": {
        "about": "explaining or teaching something to a child, or keeping kids occupied with something to learn",
        "true": "how to explain a school topic, a skill, or bored kids who need an activity",
        "false": "comforting a sad kid or breaking up a fight",
    },
    "the-thermostat": {
        "about": "changing the temperature, heat, air conditioning, or the thermostat setting",
        "true": "any ask to set, raise, or lower the thermostat, or being too cold or hot indoors",
        "false": "the weather outside, or a repair",
    },
    "yard-work": {
        "about": "the lawn, the yard, mowing, or outdoor prep for something",
        "true": "mowing, the yard being overgrown, getting the outside ready",
        "false": "snow, cooking, or indoor repairs",
    },
}

_LOAD = re.compile(r"Load `([a-z0-9-]+)`")


def composes_from_bodies(skills) -> dict[str, list[str]]:
    """skill -> skills its body tells Dad to load, in body order."""
    out: dict[str, list[str]] = {}
    for name, sk in skills.items():
        found = [m for m in _LOAD.findall(sk.body) if m in skills and m != name]
        if found:
            out[name] = list(dict.fromkeys(found))
    return out
