"""
Generates a synthetic, realistic-looking batch of leads for testing the
agent pipeline, since real Honda lead data/access is not yet available.

Deliberately includes messy/ambiguous/spammy cases, not just clean "great
lead" examples -- otherwise the agent's branching logic never gets tested.
Swap this out once real (anonymized) lead patterns are confirmed with Honda.
"""
import random

NAMES = ["Ahmed Raza", "Sara Khan", "Bilal Hussain", "Ayesha Malik", "Usman Tariq",
         "Fatima Noor", "Hamza Sheikh", "Zainab Iqbal", "Omar Farooq", "Mahnoor Aslam",
         "Ali Hassan", "Sana Javed", "Talha Aziz", "Rida Saeed", "Danish Iqbal"]

VEHICLES = ["Honda Civic RS", "Honda City Aspire", "Honda BR-V", "Honda Civic", "City",
            "BRV", None, "some Honda car"]

SOURCES = ["Facebook Ads", "Website Form", "Walk-in"]

TIMELINES = ["this month", "this week", "just browsing", "not sure yet", "asap",
             "next year maybe", "no rush", None]

MESSAGES_GOOD = [
    "Interested in a test drive this week, please share price and installment plan.",
    "Want to book a test drive for the Civic RS, available this weekend?",
    "Please share finance options, planning to buy this month.",
    "Is the City Aspire available for viewing? Want to visit the showroom.",
]
MESSAGES_VAGUE = [
    "just checking prices for now",
    "maybe interested later this year",
    "how much for a Honda",
]
MESSAGES_SPAM = [
    "Click here for free money www.totally-legit-offer.com guaranteed cash!!!",
    "Visit http://cheap-cars-deal.biz for guaranteed discount",
]


def generate_leads(n: int = 40, seed: int = 42):
    random.seed(seed)
    leads = []
    for i in range(1, n + 1):
        roll = random.random()
        name = random.choice(NAMES)
        source = random.choice(SOURCES)
        vehicle = random.choice(VEHICLES)
        timeline = random.choice(TIMELINES)

        if roll < 0.08:  # spam
            leads.append({
                "id": i, "name": name, "contact": "N/A", "source": source,
                "vehicle_interest": vehicle, "budget_hint": None, "timeline": timeline,
                "message": random.choice(MESSAGES_SPAM),
            })
        elif roll < 0.20:  # incomplete
            leads.append({
                "id": i, "name": name, "contact": random.choice(["", "03xx-xxxxxxx"]),
                "source": source, "vehicle_interest": None, "budget_hint": None,
                "timeline": None, "message": None,
            })
        elif roll < 0.45:  # vague / cold
            leads.append({
                "id": i, "name": name, "contact": f"03{random.randint(10,49)}-{random.randint(1000000,9999999)}",
                "source": source, "vehicle_interest": vehicle,
                "budget_hint": random.choice([None, "not decided yet"]),
                "timeline": random.choice(["just browsing", "not sure yet", "no rush"]),
                "message": random.choice(MESSAGES_VAGUE),
            })
        else:  # good / hot-ish
            leads.append({
                "id": i, "name": name, "contact": f"03{random.randint(10,49)}-{random.randint(1000000,9999999)}",
                "source": source, "vehicle_interest": random.choice(VEHICLES[:5]),
                "budget_hint": f"around {random.randint(35,65)}00,000",
                "timeline": random.choice(["this week", "this month", "asap"]),
                "message": random.choice(MESSAGES_GOOD),
            })
    return leads


# A tiny synthetic "past leads with outcomes" set, used only by the
# lookup_similar_leads tool for borderline-score cases.
PAST_LEADS_WITH_OUTCOMES = [
    {"vehicle_interest": "Honda Civic RS", "outcome_score": 78},
    {"vehicle_interest": "Honda City Aspire", "outcome_score": 55},
    {"vehicle_interest": "Honda BR-V", "outcome_score": 40},
    {"vehicle_interest": "City", "outcome_score": 60},
    {"vehicle_interest": "Civic", "outcome_score": 70},
]
