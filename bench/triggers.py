"""Author: Mike Bell
Last Modified: 2026-09-19
Purpose: Selector-facing triggers per skill, and composition derived from the skill bodies.

Two audiences, two texts. The one-line `description` in each skill file is
read by Claude inside a full conversation, so it can carry attitude ("how Dad
defends the thermostat") and shorthand. A classifier reads a typed question
against a bare request, so it needs triggers: what the request is ABOUT, what
counts (`true`), and what does not (`false`). These never touch the files
Claude reads.

Negatives are phrased as the ABSENCE of the trigger ("no child is asking
permission"), never as a competing topic ("a kid who is upset"): on a request
that mentions several things at once, a competing-topic negative suppresses a
true positive. Measured: saying-no fell from 0.59 to 0.05 on the heavy-day
prompt with the competing-topic wording, and recovered with this one.

Composition is not wording. `composes_from_bodies` reads the "Load `x`" lines
already in the skill bodies, so the dependency graph comes from the one place
it is already written and cannot drift from it."""
from __future__ import annotations

import re

TRIGGERS: dict[str, dict[str, str]] = {
    "answering-big-questions": {
        "about": "a child asking a big or philosophical question, such as about death, why things are, or where things come from",
        "true": "a kid's existential or curiosity question that needs a thoughtful answer",
        "false": "no child is asking a why or what-is question",
    },
    "bedtime": {
        "about": "getting kids to sleep or handling bedtime",
        "true": "kids not sleeping, bedtime routine, lights out, late at night",
        "false": "nothing about sleep or getting kids to bed is mentioned",
    },
    "breaking-up-fights": {
        "about": "kids fighting, arguing, or screaming at each other",
        "true": "siblings or kids in conflict right now",
        "false": "no kids are fighting or arguing with each other",
    },
    "comforting-a-kid": {
        "about": "a child who is upset, crying, disappointed, or hurt",
        "true": "a kid needing comfort after a loss, rejection, or a bad day",
        "false": "no child is upset, sad, or hurt",
    },
    "fixing-things": {
        "about": "repairing something broken in the house, like a faucet, a door, or an appliance",
        "true": "a leak, a drip, something that broke and needs a repair",
        "false": "nothing is broken or in need of repair",
    },
    "grilling": {
        "about": "cooking on the grill, the menu, or the cook plan for a cookout",
        "true": "grilling, barbecue, cooking outside, the propane or the grill",
        "false": "no cooking on the grill or cookout food is involved",
    },
    "grocery-runs": {
        "about": "going shopping for food or supplies, or being out of something",
        "true": "a store run, provisioning, 'we're out of'",
        "false": "no shopping trip or running out of something is mentioned",
    },
    "hosting": {
        "about": "hosting people, having guests over, or planning a cookout, party, or get-together",
        "true": "any event with guests, a cookout, having the neighbors over",
        "false": "no guests or event are involved",
    },
    "money-decisions": {
        "about": "whether to spend money, a budget, a purchase, or 'can we afford it'",
        "true": "a spending decision, a budget limit, a price, affordability",
        "false": "no spending decision is being made; merely checking a balance or amount does not count",
    },
    "road-trips": {
        "about": "a drive or trip somewhere with the family, whether planning it, affording it, or surviving it",
        "true": "a trip, a drive, travel to another place, 'are we there yet'",
        "false": "no trip or drive to another place is mentioned",
    },
    "saying-no": {
        "about": "a kid asking permission for something the answer is probably no to",
        "true": "a request to stay out late, buy something, or bend a house rule",
        "false": "no child is asking permission for anything",
    },
    "snow-shoveling": {
        "about": "snow on the ground and clearing the driveway or walk",
        "true": "snowfall, shoveling, the driveway in winter",
        "false": "no snow is mentioned",
    },
    "teaching-kids-stuff": {
        "about": "explaining or teaching something to a child, or keeping kids occupied with something to learn",
        "true": "how to explain a school topic, a skill, or bored kids who need an activity",
        "false": "nothing needs explaining to a child and no child needs an activity",
    },
    "the-thermostat": {
        "about": "changing the temperature, heat, air conditioning, or the thermostat setting",
        "true": "any ask to set, raise, or lower the thermostat, or being too cold or hot indoors",
        "false": "no indoor temperature or thermostat change is asked for",
    },
    "yard-work": {
        "about": "the lawn, the yard, mowing, or outdoor prep for something",
        "true": "mowing, the yard being overgrown, getting the outside ready",
        "false": "the lawn or yard is not mentioned and no outdoor prep is needed",
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
