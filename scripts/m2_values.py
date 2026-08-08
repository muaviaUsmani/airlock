"""
M2: the values injected, diversified and split so they cannot be memorised.

TWO PROBLEMS THIS FIXES (decision 010)
--------------------------------------
1. POOLS TOO SMALL. ORG_THIRD_PARTY drew from ten bank names, PROTECTED_ATTR
   from six phrases, HEALTH from eight. A model can memorise ten strings and look
   like it understands a category. Pools are expanded by roughly an order of
   magnitude.

2. NO TRAIN/EVAL SEPARATION. Every value the model saw in training could appear
   in evaluation. So value memorisation was invisible — the same blind spot the
   template split was meant to close, one level down.

   Pools are now split disjointly: a model that memorised training values scores
   zero on held-out ones, which turns a hidden failure into a measured number.

A THIRD PROBLEM, CAUGHT LATE AND WORTH RECORDING
------------------------------------------------
The old ten-bank pool collided with the company the complaint was filed against
in 47.4% of narratives. DEFINITIONS.md is explicit that the complained-about
company is NOT personal information — it is a structured field of the record.
Injecting "Citibank" as third-party PII into a complaint filed against Citibank
teaches precisely the rule DEFINITIONS.md forbids.

The entity-site miner already guards the SITE. It could not guard the VALUE,
because the value is chosen later. So `pick_bank()` takes the narrative's company
and excludes anything matching it.
"""

from __future__ import annotations

import re

TRAIN_FRACTION = 0.7

BANKS = """Citibank|Capital One|Synchrony Bank|Barclays|Discover|Wells Fargo|US Bank|Comenity Bank
TD Bank|Regions Bank|Fifth Third Bank|KeyBank|Huntington National Bank|M&T Bank|Citizens Bank
Ally Bank|Navy Federal Credit Union|PenFed Credit Union|First Premier Bank|Credit One Bank
Merrick Bank|Continental Finance|Total Visa|Avant|Upgrade|LendingClub|Prosper|SoFi|Marcus
Truist|BMO Harris|PNC|Santander|Union Bank|Zions Bank|Frost Bank|BBVA|Valley National Bank
Webster Bank|People's United|Eastern Bank|Rockland Trust|Berkshire Bank|Cathay Bank
East West Bank|Hancock Whitney|Trustmark|Renasant Bank|South State Bank|Pinnacle Bank
Arvest Bank|Commerce Bank|UMB Bank|Great Western Bank|Glacier Bank|Washington Federal
Banner Bank|Columbia Bank|Umpqua Bank|Heritage Bank""".replace("\n", "|").split("|")

PROTECTED = """disabled veteran|retired teacher on a fixed income|single mother
78 year old widow|recent immigrant|veteran with a service-connected disability
legally blind customer|wheelchair user|senior citizen on social security
cancer survivor|deaf customer|person with severe anxiety|recovering addict
first generation immigrant|non-native English speaker|full time carer for my mother
disabled army veteran|widower living alone|retired nurse on disability
person with a learning disability|survivor of domestic abuse|homeless veteran
diabetic on a fixed income|single father of three""".replace("\n", "|").split("|")

HEALTH = """dental implants|root canal surgery|LASIK eye surgery|a hip replacement
orthodontic treatment|veterinary surgery for my dog|physical therapy|a hearing aid fitting
chemotherapy sessions|an emergency appendectomy|fertility treatment|knee reconstruction
cataract surgery|a spinal injection|dermatology treatment|my son's braces
gallbladder removal|cardiac stent placement|a sleep apnea machine|prosthetic fitting
addiction rehabilitation|counselling sessions|a wheelchair ramp|hormone therapy
oral surgery|shoulder surgery|a diabetes monitor|allergy immunotherapy""".replace("\n", "|").split("|")

LIFE_EVENTS = """my divorce|my husband's passing|being laid off|my retirement
my discharge from the Army|my bankruptcy filing|my daughter's wedding|my wife's stroke
losing my job of twenty years|my mother moving into care|the birth of my twins
my separation|my house fire|the flood that destroyed our home|my son's deployment
my cancer diagnosis|a workplace injury|my father's funeral|my eviction
returning from deployment|my heart attack|my business closing|my green card approval
the death of my brother""".replace("\n", "|").split("|")

EMPLOYERS = """Riverbend Logistics|Coastal Dental Group|Hartwell Manufacturing|Sunrise Elementary
Pinnacle Roofing|Grantham Legal Services|Fairview Medical Center|Oakridge Transit Authority
Beacon Insurance Brokers|Kestrel Software|Meridian Grocery|Northgate Auto Repair
Silverline Staffing|Cloverfield Bakery|Ironwood Construction|Lakeside Veterinary Clinic
Summit Accounting|Trellis Marketing|Alder Creek Schools|Bramble Hill Farms|Copperfield Hotels
Dunmore Textiles|Elmridge Engineering|Foxglove Catering|Granite Peak Mining|Harborview Shipping
Inglewood Printing|Juniper Health Systems|Kingsley Motors|Larkspur Landscaping|Maplewood Dairy
Northbrook Security|Oakhaven Care Homes|Pemberton Plastics|Quarry Lane Cement|Redstone Utilities
Sablewood Furniture|Thornfield Aviation|Underhill Brewing|Vantage Point Media|Westmoor Recycling
Yarrow Valley Wines|Ashford Tooling|Blackwater Fisheries|Cedarholm Windows|Drayton Freight
Everly Home Care|Fernbank Nurseries|Glenmoor Bakery|Havenwood Joinery""".replace("\n", "|").split("|")


def _norm_company(name: str) -> str:
    n = re.sub(r"[^a-z ]", " ", str(name).lower())
    n = re.sub(r"\b(inc|llc|na|n a|corp|corporation|company|co|holdings?|group|bank|usa|us)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def split_pool(pool: list[str], train: bool) -> list[str]:
    """
    Disjoint train/eval halves of a value pool.

    Deterministic by position rather than shuffled, so the split is stable across
    runs without carrying a seed around, and obvious to inspect.
    """
    cut = int(len(pool) * TRAIN_FRACTION)
    return pool[:cut] if train else pool[cut:]


def pick_bank(rng, company: str | None, train: bool) -> str:
    """
    A third-party bank that is NOT the company the complaint was filed against.

    Without this the injector labels the complained-about company as third-party
    personal information, which DEFINITIONS.md explicitly excludes. The old
    ten-name pool collided on 47.4% of narratives.
    """
    pool = split_pool(BANKS, train)
    if company:
        cn = _norm_company(company)
        if cn:
            safe = [b for b in pool
                    if (bn := _norm_company(b)) and bn not in cn and cn not in bn]
            if safe:
                pool = safe
    return rng.choice(pool)


POOLS = {
    "bank": BANKS, "protected": PROTECTED, "health": HEALTH,
    "life_event": LIFE_EVENTS, "employer": EMPLOYERS,
}
