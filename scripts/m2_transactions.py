"""
M2: the synthetic card system — which is the ADVERSARY, not a data generator.

Its only job is to answer one question, later, at M4:

    given this redacted narrative, can I find exactly one customer here?

Everything it contains exists to support that question. Nothing else belongs in
it. The brief is blunt about this and it is worth repeating where the code lives:

    "This is not a data generator. It is the attacker. It should be as small as
     it can be while still supporting that. Building a realistic card platform is
     not the project and every hour spent on it is an hour not spent on the thing
     that matters. Barebones."

So: four tables, no product features, no balances, no payments, no statements, no
authorisation flow, no fraud model. If this file starts growing capabilities,
focus has drifted.

NO REAL DATA, EVER. Every value here is generated from the word lists below and a
fixed seed. There are no real people, cards, or merchants in this project.

WHY THIS RUNS BEFORE THE INJECTOR
---------------------------------
The brief lists the injector first, but the dependency runs the other way. For a
narrative to map to exactly one customer, the personal information injected into
it has to be DRAWN FROM that customer's record — their name, their city, a
merchant they actually shopped at, the exact amount and date of a real
transaction of theirs. Inject invented values and the narrative describes nobody,
and the M4 attack has nothing to find. So the customers exist first.

Writes: data/synthetic/customers.parquet
        data/synthetic/cards.parquet
        data/synthetic/merchants.parquet
        data/synthetic/transactions.parquet
        results/m2_synthetic_summary.txt
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"

SEED = 20260806
N_CUSTOMERS = 10_000
N_MERCHANTS = 400
TXN_PER_CUSTOMER = (12, 60)          # uniform range
WINDOW_START = date(2023, 1, 1)
WINDOW_DAYS = 730                     # two years

# --- word lists ------------------------------------------------------------
# Deliberately ordinary and deliberately synthetic. Combinatorially these give
# far more distinct people than we need, which is the point: name collisions
# should be possible but not the norm, so that a name alone rarely identifies.

FIRST = """James Mary Robert Patricia John Jennifer Michael Linda David Elizabeth William Barbara
Richard Susan Joseph Jessica Thomas Sarah Charles Karen Christopher Nancy Daniel Lisa Matthew Betty
Anthony Margaret Mark Sandra Donald Ashley Steven Kimberly Paul Emily Andrew Donna Joshua Michelle
Kenneth Carol Kevin Amanda Brian Dorothy George Melissa Timothy Deborah Ronald Stephanie Edward Rebecca
Jason Sharon Jeffrey Laura Ryan Cynthia Jacob Kathleen Gary Amy Nicholas Angela Eric Shirley Jonathan
Anna Stephen Brenda Larry Pamela Justin Emma Scott Nicole Brandon Helen Benjamin Samantha Samuel Katherine
Gregory Christine Alexander Debra Patrick Rachel Frank Carolyn Raymond Janet Jack Virginia Dennis Maria
Jerry Heather Tyler Diane Aaron Julie Jose Joyce Adam Victoria Nathan Kelly Henry Christina Douglas Joan
Zachary Evelyn Peter Lauren Kyle Judith Walter Olivia Ethan Frances Jeremy Martha Harold Cheryl Keith Hannah
Christian Jacqueline Roger Ann Noah Gloria Gerald Jean Carl Kathryn Terry Alice Sean Teresa Austin Sara
Arthur Janice Lawrence Doris Jesse Madison Dylan Julia Bryan Grace Joe Judy Jordan Abigail Billy Marie
Bruce Denise Albert Beverly Willie Amber Gabriel Theresa Logan Marilyn Alan Danielle Juan Diana Wayne Brittany
Roy Natalie Ralph Sophia Randy Rose Eugene Isabella Vincent Alexis Russell Kayla Elijah Charlotte Louis Lori""".split()

LAST = """Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez Hernandez Lopez
Gonzalez Wilson Anderson Thomas Taylor Moore Jackson Martin Lee Perez Thompson White Harris Sanchez Clark
Ramirez Lewis Robinson Walker Young Allen King Wright Scott Torres Nguyen Hill Flores Green Adams Nelson
Baker Hall Rivera Campbell Mitchell Carter Roberts Gomez Phillips Evans Turner Diaz Parker Cruz Edwards
Collins Reyes Stewart Morris Morales Murphy Cook Rogers Gutierrez Ortiz Morgan Cooper Peterson Bailey Reed
Kelly Howard Ramos Kim Cox Ward Richardson Watson Brooks Chavez Wood James Bennett Gray Mendoza Ruiz Hughes
Price Alvarez Castillo Sanders Patel Myers Long Ross Foster Jimenez Powell Jenkins Perry Russell Sullivan
Bell Coleman Butler Henderson Barnes Gonzales Fisher Vasquez Simmons Romero Jordan Patterson Alexander
Hamilton Graham Reynolds Griffin Wallace Moreno West Cole Hayes Bryant Herrera Gibson Ellis Tran Medina
Aguilar Stevens Murray Ford Castro Marshall Owens Harrison Fernandez Mcdonald Woods Washington Kennedy
Wells Vargas Henry Chen Freeman Webb Tucker Guzman Burns Crawford Olson Simpson Porter Hunter Gordon Mendez""".split()

CITIES = [
    ("Fremont", "CA", "94536"), ("Springfield", "IL", "62701"), ("Riverside", "CA", "92501"),
    ("Bellevue", "WA", "98004"), ("Arlington", "TX", "76010"), ("Naperville", "IL", "60540"),
    ("Cary", "NC", "27511"), ("Plano", "TX", "75023"), ("Chandler", "AZ", "85224"),
    ("Alexandria", "VA", "22301"), ("Bridgeport", "CT", "06604"), ("Everett", "WA", "98201"),
    ("Lakewood", "CO", "80226"), ("Sandy Springs", "GA", "30328"), ("Waterbury", "CT", "06702"),
    ("Clearwater", "FL", "33755"), ("Rochester", "MN", "55901"), ("Pueblo", "CO", "81003"),
    ("Kenosha", "WI", "53140"), ("Bloomington", "IN", "47401"), ("Duluth", "MN", "55802"),
    ("Redding", "CA", "96001"), ("Bangor", "ME", "04401"), ("Dothan", "AL", "36301"),
    ("Cheyenne", "WY", "82001"), ("Lawrence", "KS", "66044"), ("Bend", "OR", "97701"),
    ("Asheville", "NC", "28801"), ("Missoula", "MT", "59801"), ("Kalamazoo", "MI", "49001"),
]

STREETS = """Main Oak Maple Cedar Elm Washington Lake Hill Park Walnut Spring Ridge Pine Sunset
Highland Willow Church Chestnut River Center Jackson Adams Franklin Lincoln Jefferson Madison""".split()
STREET_TYPE = ["St", "Ave", "Rd", "Dr", "Ln", "Blvd"]

EMPLOYERS = """Riverbend Logistics Coastal Dental Group Hartwell Manufacturing Sunrise Elementary
Pinnacle Roofing Grantham Legal Services Fairview Medical Center Oakridge Transit Authority
Beacon Insurance Brokers Kestrel Software Meridian Grocery Northgate Auto Repair Silverline Staffing
Cloverfield Bakery Ironwood Construction Lakeside Veterinary Clinic Summit Accounting Trellis Marketing""".split("\n")

MERCHANT_STEMS = """Corner Coffee Sunrise Diner Blue Ridge Market Quickstop Fuel Northside Pharmacy
Riverside Grocers Tenth Street Bakery Copper Kettle Cafe Halfmoon Books Garden Center Depot
Family Dental Care Redline Auto Parts Pine Valley Vet Summit Fitness Club Harbor Point Seafood
Willow Dry Cleaners Stone Bridge Hardware Cedar Lane Florist Uptown Barbers Lakeview Pizzeria
Fairground Cinemas Brightway Optical Trailhead Outfitters Meadow Farm Supply Gold Star Laundry
Old Mill Butchers Riverbank Wine Shop Sandpiper Motel Elmwood Pet Supply Crossroads Convenience""".split("\n")

MERCHANT_CATEGORIES = [
    "grocery", "restaurant", "fuel", "pharmacy", "retail", "medical",
    "auto", "fitness", "entertainment", "services",
]

RELATIONSHIPS = ["husband", "wife", "ex-husband", "ex-wife", "son", "daughter",
                 "mother", "father", "brother", "sister"]

HEALTH_PROCEDURES = ["dental implants", "root canal surgery", "LASIK eye surgery",
                     "a hip replacement", "orthodontic treatment", "veterinary surgery for my dog",
                     "physical therapy", "a hearing aid fitting"]

LIFE_EVENTS = ["my divorce", "my husband's passing", "being laid off", "my retirement",
               "my discharge from the Army", "my bankruptcy filing", "my daughter's wedding"]

PROTECTED = ["disabled veteran", "retired teacher on a fixed income", "single mother",
             "78 year old widow", "recent immigrant", "veteran with a service-connected disability"]

BANKS = ["Citibank", "Capital One", "Synchrony Bank", "Barclays", "Discover",
         "Wells Fargo", "US Bank", "Comenity Bank", "TD Bank", "Regions Bank"]


def main() -> int:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    # --- merchants --------------------------------------------------------
    merchants = []
    for i in range(N_MERCHANTS):
        stem = rng.choice(MERCHANT_STEMS)
        city, state, _ = rng.choice(CITIES)
        merchants.append({
            "merchant_id": f"M{i:05d}",
            "merchant_name": stem if rng.random() < 0.6 else f"{stem} #{rng.randint(2, 89)}",
            "category": rng.choice(MERCHANT_CATEGORIES),
            "city": city,
            "state": state,
        })
    mdf = pd.DataFrame(merchants)

    # --- customers --------------------------------------------------------
    customers, cards = [], []
    for i in range(N_CUSTOMERS):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        city, state, zipc = rng.choice(CITIES)
        cid = f"C{i:06d}"
        rel = rng.choice(RELATIONSHIPS)
        customers.append({
            "customer_id": cid,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "street": f"{rng.randint(12, 9899)} {rng.choice(STREETS)} {rng.choice(STREET_TYPE)}",
            "city": city,
            "state": state,
            "zip": zipc,
            "phone": f"({rng.randint(201,989)}) {rng.randint(200,999)}-{rng.randint(1000,9999)}",
            "email": f"{first.lower()}.{last.lower()}{rng.randint(1,99)}@example.com",
            "employer": rng.choice(EMPLOYERS),
            "relationship_type": rel,
            "relative_name": f"{rng.choice(FIRST)} {last if rng.random() < 0.5 else rng.choice(LAST)}",
            "health_procedure": rng.choice(HEALTH_PROCEDURES),
            "life_event": rng.choice(LIFE_EVENTS),
            "protected_attr": rng.choice(PROTECTED),
            "third_party_bank": rng.choice(BANKS),
        })
        n_cards = 1 if rng.random() < 0.82 else 2
        for c in range(n_cards):
            cards.append({
                "card_id": f"{cid}-{c}",
                "customer_id": cid,
                "last4": f"{rng.randint(0, 9999):04d}",
                "opened": (WINDOW_START - timedelta(days=rng.randint(90, 3600))).isoformat(),
            })
    cdf = pd.DataFrame(customers)
    cardsdf = pd.DataFrame(cards)

    # --- transactions -----------------------------------------------------
    # Amounts are the interesting field. An exact amount to the cent carries a
    # lot of entropy, which is precisely the M4 attack surface the CFPB corpus
    # leaves intact in 44.2% of narratives.
    txns = []
    t = 0
    cards_by_cust: dict[str, list[str]] = {}
    for r in cards:
        cards_by_cust.setdefault(r["customer_id"], []).append(r["card_id"])

    for cust in customers:
        cid = cust["customer_id"]
        for _ in range(rng.randint(*TXN_PER_CUSTOMER)):
            m = merchants[rng.randrange(N_MERCHANTS)]
            # log-normal-ish spend, floored and rounded to the cent
            amt = round(min(max(rng.lognormvariate(3.1, 1.0), 1.5), 4800.0), 2)
            d = WINDOW_START + timedelta(days=rng.randrange(WINDOW_DAYS))
            txns.append({
                "txn_id": f"T{t:08d}",
                "card_id": rng.choice(cards_by_cust[cid]),
                "customer_id": cid,
                "merchant_id": m["merchant_id"],
                "merchant_name": m["merchant_name"],
                "merchant_city": m["city"],
                "amount": amt,
                "txn_date": d.isoformat(),
            })
            t += 1
    tdf = pd.DataFrame(txns)

    cdf.to_parquet(OUT / "customers.parquet", index=False)
    cardsdf.to_parquet(OUT / "cards.parquet", index=False)
    mdf.to_parquet(OUT / "merchants.parquet", index=False)
    tdf.to_parquet(OUT / "transactions.parquet", index=False)

    # --- how identifying is each field on its own? ------------------------
    # This is the whole reason the table exists, so it gets measured here rather
    # than assumed at M4. "Unique" = the value occurs for exactly one customer.
    def uniqueness(series: pd.Series, owner: pd.Series) -> tuple[float, float]:
        g = pd.DataFrame({"v": series, "o": owner}).groupby("v")["o"].nunique()
        return 100 * (g == 1).mean(), g.mean()

    checks = [
        ("full_name", *uniqueness(cdf["full_name"], cdf["customer_id"])),
        ("city", *uniqueness(cdf["city"], cdf["customer_id"])),
        ("zip", *uniqueness(cdf["zip"], cdf["customer_id"])),
        ("employer", *uniqueness(cdf["employer"], cdf["customer_id"])),
        ("phone", *uniqueness(cdf["phone"], cdf["customer_id"])),
        ("card last4", *uniqueness(cardsdf["last4"], cardsdf["customer_id"])),
        ("txn amount", *uniqueness(tdf["amount"], tdf["customer_id"])),
        ("txn date", *uniqueness(tdf["txn_date"], tdf["customer_id"])),
        ("merchant name", *uniqueness(tdf["merchant_name"], tdf["customer_id"])),
    ]
    pair = tdf["amount"].astype(str) + "|" + tdf["txn_date"]
    checks.append(("amount + date", *uniqueness(pair, tdf["customer_id"])))
    triple = pair + "|" + tdf["merchant_name"]
    checks.append(("amount + date + merchant", *uniqueness(triple, tdf["customer_id"])))

    L = [
        "M2 — synthetic card system (the adversary's database)",
        "=" * 62,
        "",
        f"seed: {SEED}   |   NO REAL DATA — every value is generated",
        "",
        f"  customers     {len(cdf):>9,}",
        f"  cards         {len(cardsdf):>9,}",
        f"  merchants     {len(mdf):>9,}",
        f"  transactions  {len(tdf):>9,}",
        f"  date window   {WINDOW_START} .. {WINDOW_START + timedelta(days=WINDOW_DAYS-1)}",
        "",
        "-" * 62,
        "HOW IDENTIFYING IS EACH FIELD ON ITS OWN?",
        "",
        "This is measured here rather than assumed at M4. 'unique' is the share",
        "of values held by exactly one customer — a field at 100% identifies",
        "outright, a field near 0% narrows very little.",
        "",
        f"  {'field':<26} {'unique':>8}  {'mean customers/value':>21}",
    ]
    for name, pct, mean in checks:
        L.append(f"  {name:<26} {pct:>7.1f}%  {mean:>21.1f}")
    L += [
        "",
        "The last three rows are the point of the project. A single amount is",
        "already sharply identifying; amount with date is nearly unique. Neither",
        "is personal information under any standard definition, and no PII",
        "detector removes them. That gap is what M4 measures.",
    ]
    out = "\n".join(L)
    (RESULTS / "m2_synthetic_summary.txt").write_text(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
