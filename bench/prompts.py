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
