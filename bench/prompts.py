"""Author: Mike Bell
Last Modified: 2026-09-18
Purpose: The frozen prompt corpus and world state every benchmark arm runs against.

`expected_skills` is the author's label for reading results. It is NOT the
ground truth for an A/B: that is whatever the baseline arm actually loaded on
the same prompt. Prompts with no expected skill exist to measure false
positives, which a pre-selector can produce and the baseline mostly cannot."""

# The scenario every case starts from: the conflict world the demos use.
# Propane empty AND store closed forces a replan; empty pantry forces a budget
# check. Same for every arm, reset before every case.
FROZEN_WORLD = {
    "propane": "empty",
    "hardware_store_open": False,
    "weather_f": 58,
    "pantry_has_veggies": False,
    "budget": 40,
}

# The ladder: skill demand as the independent variable. `tier` is the demand
# DESIGNED into the prompt; the harness records what Dad actually loads, and
# the gap between the two is a finding, not an error. Hosting is the only skill
# in the repo that composes others, so tier 4 is the only real cascade.
LADDER = [
    {"id": "t0-weather", "tier": 0, "prompt": "Morning. What's the weather for my run?",
     "expected_skills": []},
    {"id": "t0-wallet", "tier": 0, "prompt": "How much is in the wallet?",
     "expected_skills": []},
    {"id": "t1-thermo", "tier": 1, "prompt": "Set the thermostat to 74, I'm cold.",
     "expected_skills": ["the-thermostat"]},
    {"id": "t1-faucet", "tier": 1, "prompt": "The kitchen faucet is dripping again. Can you fix it?",
     "expected_skills": ["fixing-things"]},
    {"id": "t2-roadtrip", "tier": 2, "prompt": "Can we afford a road trip to the coast this summer?",
     "expected_skills": ["money-decisions", "road-trips"]},
    {"id": "t2-cold-kids", "tier": 2, "prompt": "It's cold and the kids are bored. Ideas?",
     "expected_skills": ["the-thermostat", "teaching-kids-stuff"]},
    {"id": "t3-cookout", "tier": 3,
     "prompt": "Grilling for the neighbors Saturday, forty bucks to spend, and the lawn's a jungle. What's the order of operations?",
     "expected_skills": ["grilling", "money-decisions", "yard-work"]},
    {"id": "t3-snow-day", "tier": 3,
     "prompt": "Six inches of snow, the kids are fighting over the one sled, and I need to get the driveway clear before work. Go.",
     "expected_skills": ["snow-shoveling", "breaking-up-fights", "saying-no"]},
    {"id": "t4-host", "tier": 4, "prompt": "I'm hosting a cookout Saturday. What do I do?",
     "expected_skills": ["hosting", "money-decisions", "grilling", "yard-work"]},
    {"id": "t4-twelve", "tier": 4, "prompt": "Twelve people Saturday, and I've got forty bucks. Are we set?",
     "expected_skills": ["hosting", "money-decisions", "grilling", "yard-work"]},
]

# Stress block, reported on its own and never folded into the ladder means. No
# realistic single ask needs this many skills; the point is the loop's hard
# ceiling of _MAX_STEPS model calls per turn. A turn that wants seven bodies
# one round trip at a time can run out of calls, which is the exact case a
# pre-selector would relieve, so the ceiling-hit rate is the number to watch.
STRESS = [
    {"id": "s5-heavy-day", "tier": 5, "stress": True,
     "prompt": ("Big Saturday. Hosting the cookout for the neighbors on forty bucks and the lawn's a jungle. "
                "The boys are already fighting over the controller, Maya's in her room crying because she "
                "didn't make the team, and Jake wants to stay out past midnight after. Then I need everyone "
                "in bed at a decent hour. What's the plan, start to finish?"),
     "expected_skills": ["hosting", "money-decisions", "grilling", "yard-work", "breaking-up-fights",
                         "comforting-a-kid", "saying-no", "bedtime"]},
    {"id": "s5-everything", "tier": 5, "stress": True,
     "prompt": "Walk me through everything you know how to handle around here, one by one, and how you'd handle each.",
     "expected_skills": ["answering-big-questions", "bedtime", "breaking-up-fights", "comforting-a-kid",
                         "fixing-things", "grilling", "grocery-runs", "hosting", "money-decisions",
                         "road-trips", "saying-no", "snow-shoveling", "teaching-kids-stuff",
                         "the-thermostat", "yard-work"]},
]

# The wider sweep: one prompt per skill plus composition, ambiguity, and no-skill cases.
CASES = [
    # --- one skill each -------------------------------------------------
    {"id": "grill-01", "prompt": "Can we grill for the cookout this Saturday?",
     "expected_skills": ["grilling"]},
    {"id": "thermo-01", "prompt": "I'm freezing, set the thermostat to 76.",
     "expected_skills": ["the-thermostat"]},
    {"id": "thermo-02", "prompt": "Set the thermostat to 74, I'm cold.",
     "expected_skills": ["the-thermostat"]},
    {"id": "money-01", "prompt": "Can I get the nice grill? It's about $400.",
     "expected_skills": ["money-decisions"]},
    {"id": "yard-01", "prompt": "Lawn's getting long. When should I mow this week?",
     "expected_skills": ["yard-work"]},
    {"id": "grocery-01", "prompt": "We're out of everything. Make me a grocery run plan for tonight.",
     "expected_skills": ["grocery-runs"]},
    {"id": "fix-01", "prompt": "The kitchen faucet is dripping again. Can you fix it?",
     "expected_skills": ["fixing-things"]},
    {"id": "roadtrip-01", "prompt": "Thinking about driving to Austin Saturday morning with the kids. Worth it?",
     "expected_skills": ["road-trips"]},
    {"id": "bedtime-01", "prompt": "The kids won't go to sleep and it's 9:30.",
     "expected_skills": ["bedtime"]},
    {"id": "fight-01", "prompt": "The boys are screaming at each other over the controller again.",
     "expected_skills": ["breaking-up-fights"]},
    {"id": "comfort-01", "prompt": "Maya didn't make the team and she's crying in her room.",
     "expected_skills": ["comforting-a-kid"]},
    {"id": "teach-01", "prompt": "How do I explain fractions to an eight-year-old?",
     "expected_skills": ["teaching-kids-stuff"]},
    {"id": "big-01", "prompt": "Why do people have to die?",
     "expected_skills": ["answering-big-questions"]},
    {"id": "no-01", "prompt": "Everyone else's parents let them stay out till midnight. Can I?",
     "expected_skills": ["saying-no"]},
    {"id": "snow-01", "prompt": "Six inches overnight. What's the plan for the driveway?",
     "expected_skills": ["snow-shoveling"]},
    # --- composition: hosting pulls in three others ------------------------
    {"id": "host-01", "prompt": "I'm hosting a cookout Saturday. What do I do?",
     "expected_skills": ["hosting", "money-decisions", "grilling", "yard-work"]},
    {"id": "host-02", "prompt": "Twelve people Saturday, and I've got forty bucks. Are we set?",
     "expected_skills": ["hosting", "money-decisions", "grilling", "yard-work"]},
    {"id": "host-03", "prompt": "I want to take my family of 4 to Spiderman this Tuesday. Dinner after. I have $100 to spend.",
     "expected_skills": ["money-decisions"]},
    # --- ambiguous: two plausible skills ------------------------------------
    {"id": "amb-01", "prompt": "It's cold and the kids are bored. Ideas?",
     "expected_skills": ["the-thermostat", "teaching-kids-stuff"]},
    {"id": "amb-02", "prompt": "Can we afford a road trip to the coast this summer?",
     "expected_skills": ["money-decisions", "road-trips"]},
    # --- no skill: fact lookups and small talk ------------------------------
    {"id": "none-01", "prompt": "Morning. What's the weather for my run?", "expected_skills": []},
    {"id": "none-02", "prompt": "What's in the pantry right now?", "expected_skills": []},
    {"id": "none-03", "prompt": "Tell me a joke.", "expected_skills": []},
    {"id": "none-04", "prompt": "How much is in the wallet?", "expected_skills": []},
    {"id": "none-05", "prompt": "Is the hardware store open today?", "expected_skills": []},
]
