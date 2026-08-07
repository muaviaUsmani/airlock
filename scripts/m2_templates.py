"""
Carrier sentence templates for the injector, split into disjoint train/eval sets.

WHY THIS FILE EXISTS SEPARATELY
-------------------------------
The injector splices generated personal information into clean narratives inside
carrier sentences. If the model is trained and evaluated on the SAME carrier
phrasings, it can score well by memorising the phrasing rather than by learning
what personal information looks like — the same degenerate shortcut as
"XXXX -> redact", one level up, and just as worthless on real text.

So every category has six templates. The first four are TRAIN, the last two are
EVAL, and the two sets never mix. A model that memorised phrasing collapses on
the held-out templates, and the size of that collapse is a published number
rather than an assumption. See DECISIONS/006-model-architecture.md.

FORMAT
------
A template is a plain sentence with the injected value marked [[field]]. Anything
outside the brackets is carrier text and is never labelled. A template may carry
more than one field.

Fields resolve against one synthetic customer and one of their real transactions,
so that every narrative genuinely describes exactly one customer — which is what
makes the M4 attack possible at all.
"""

from __future__ import annotations

TRAIN_PER_CATEGORY = 4  # first N templates train, remainder eval

TEMPLATES: dict[str, list[str]] = {
    # --- Tier 1: direct identifiers ---------------------------------------
    "PERSON": [
        "I spoke with a representative named [[person_first]] who promised to call back.",
        "My name is [[person_full]] and I have banked with them for years.",
        "The supervisor, [[person_full]], refused to escalate the matter.",
        "A woman called [[person_first]] took my details and then hung up.",
        "The letter was signed by [[person_full]] in the disputes department.",
        "I asked for [[person_first]] again but was told no such person worked there.",
    ],
    "ACCOUNT_ID": [
        "The card ending in [[last4]] is the one that was charged.",
        "My account number [[account_num]] has been active since 2019.",
        "They closed the account ending [[last4]] without any warning.",
        "Every letter references account [[account_num]] which is not even mine.",
        "The statement lists card [[last4]] as the source of the payment.",
        "I gave them my account number, [[account_num]], three separate times.",
    ],
    "GOV_ID": [
        "They asked me to confirm my social security number [[ssn]] over the phone.",
        "The application had my SSN listed as [[ssn]] which is incorrect.",
        "I was told to fax a copy of my ID along with [[ssn]] to verify.",
        "My social, [[ssn]], appears on a document I never signed.",
        "They already had [[ssn]] on file and still asked me to resend it.",
        "The dispute form required [[ssn]] before it would submit.",
    ],
    "CONTACT": [
        "They can reach me at [[phone]] during business hours.",
        "I sent the documents from [[email]] and never got a reply.",
        "My mailing address is [[address]] and nothing has ever arrived.",
        "I have called from [[phone]] more times than I can count.",
        "Correspondence should go to [[address]] rather than the old one.",
        "Please contact me at [[email]] because the phone line disconnects.",
    ],
    "CASE_REF": [
        "I was given case number [[case_ref]] and told to wait.",
        "The reference for this complaint is [[case_ref]].",
        "They opened dispute [[case_ref]] and then closed it without telling me.",
        "Nobody could find case [[case_ref]] when I called back.",
        "My claim number is [[case_ref]] if that helps locate the file.",
        "The confirmation they emailed says ticket [[case_ref]] was resolved.",
    ],
    # --- Tier 2: contextual identifiers -----------------------------------
    "RELATIONSHIP": [
        "My [[relationship]] opened this account without telling me.",
        "I had to ask my [[relationship]] to help me read the statement.",
        "The charges were made by my [[relationship]] while we were separated.",
        "My [[relationship]] is the only other person with access to the card.",
        "I am still paying for something my [[relationship]] signed up for.",
        "They kept discussing my balance with my [[relationship]] instead of me.",
    ],
    "LOCATION_FINE": [
        "I went into the [[city]] branch to sort it out in person.",
        "The nearest office is in [[city_state]] and it was closed.",
        "Staff at the [[city]] location told me they could not help.",
        "I drove to [[city_state]] twice and got nowhere both times.",
        "The branch on the north side of [[city]] would not take my paperwork.",
        "They told me to visit their [[city]] office, which no longer exists.",
    ],
    "EMPLOYER": [
        "I have worked at [[employer]] for eleven years and my pay is direct deposited.",
        "My employer, [[employer]], had to write a letter confirming my income.",
        "Since being let go from [[employer]] I have had no steady income.",
        "They called [[employer]] to verify my job without my permission.",
        "The income they listed came from my time at [[employer]].",
        "I took the card out while I was still employed by [[employer]].",
    ],
    "LIFE_EVENT": [
        "This started right after [[life_event]] and I could not keep up.",
        "Following [[life_event]] my finances have never recovered.",
        "I explained that [[life_event]] was the reason for the missed payment.",
        "They showed no understanding about [[life_event]] at all.",
        "Everything went wrong in the months around [[life_event]].",
        "I asked for a hardship plan because of [[life_event]] and was refused.",
    ],
    "PROTECTED_ATTR": [
        "I am a [[protected]] and I felt they took advantage of that.",
        "As a [[protected]], I rely on this account for everything.",
        "They treated me differently once they knew I was a [[protected]].",
        "Being a [[protected]] should not mean worse terms than anyone else.",
        "I told them I am a [[protected]] and the tone of the call changed.",
        "The agent made a remark about me being a [[protected]].",
    ],
    "HEALTH": [
        "The account was opened to pay for [[health]] which I could not afford outright.",
        "I financed [[health]] through this card on the clinic's advice.",
        "The balance is entirely from [[health]] two years ago.",
        "They promised interest-free terms for [[health]] and then charged me.",
        "I am still repaying [[health]] that did not even work.",
        "The card was only ever used for [[health]] and nothing else.",
    ],
    "ORG_THIRD_PARTY": [
        "I also contacted [[bank]] to see if they could help.",
        "The debt was sold to [[bank]] without any notice to me.",
        "[[bank]] told me the account had already been closed.",
        "I filed the same complaint with [[bank]] and got a faster answer.",
        "My other card is with [[bank]] and they handled it properly.",
        "They advised me to take it up with [[bank]] instead.",
    ],
    # --- Tier 3: quasi-identifiers ----------------------------------------
    "AMOUNT": [
        "There is a charge of [[amount]] that I never authorised.",
        "They took [[amount]] out without any notice.",
        "The disputed transaction is for [[amount]] exactly.",
        "I was refunded everything except [[amount]] which they kept.",
        "A payment of [[amount]] was applied to the wrong account.",
        "The statement shows [[amount]] that nobody can explain.",
    ],
    "DATE": [
        "This happened on [[date]] and I reported it the same week.",
        "The charge posted on [[date]] according to their own records.",
        "I called them on [[date]] and was left on hold for an hour.",
        "Nothing has moved since [[date]] despite repeated promises.",
        "The account was closed on [[date]] without my agreement.",
        "My payment cleared on [[date]] and was still marked late.",
    ],
    "MERCHANT": [
        "The charge shows as [[merchant]] which I do not recognise.",
        "I have never shopped at [[merchant]] in my life.",
        "They insisted the transaction at [[merchant]] was mine.",
        "The receipt from [[merchant]] proves I was not there.",
        "A second charge from [[merchant]] appeared the following week.",
        "I asked them to contact [[merchant]] directly and they refused.",
    ],
    "TEMPORAL": [
        "It was a [[weekday]] and I called at [[time]].",
        "I always pay on a [[weekday]] so the late fee makes no sense.",
        "The call was placed on [[weekday]] at [[time]] exactly.",
        "They told me to try again on [[weekday]] morning.",
        "I waited until [[time]] on [[weekday]] and nobody answered.",
        "The branch closed early that [[weekday]], around [[time]].",
    ],
}


def split() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (train_templates, eval_templates). Disjoint, by construction."""
    train = {c: t[:TRAIN_PER_CATEGORY] for c, t in TEMPLATES.items()}
    evl = {c: t[TRAIN_PER_CATEGORY:] for c, t in TEMPLATES.items()}
    for c in TEMPLATES:
        assert not (set(train[c]) & set(evl[c])), f"template leak in {c}"
        assert evl[c], f"no held-out templates for {c}"
    return train, evl


CATEGORIES = list(TEMPLATES)
