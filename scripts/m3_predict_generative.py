"""
Recover spans from the writer's output, and measure how much it altered the text.

THE PROBLEM THIS SOLVES
-----------------------
An encoder labels tokens, so its spans are exact by construction. The writer
REWRITES the narrative with markup:

    I called <PERSON>Sarah Mendez</PERSON> about the charge.

To score it against the same ground truth, the tags have to be turned back into
character offsets in the ORIGINAL text. That only works if the writer reproduced
everything outside the tags verbatim — and a generative model has no obligation
to. It can fix a typo, drop a clause, or reword a sentence, and nothing stops it.

DRIFT IS REPORTED, NOT REPAIRED
-------------------------------
Decision 006 fixed this in advance: text drift is a FAILURE MODE OF THE
ARCHITECTURE and belongs in the results, not in a repair step. A harness that
quietly patches drift hides the difference it exists to measure — and in a
redaction tool, silently altering the text you hand downstream is a real defect
rather than a cosmetic one.

So this aligns tagged output to the original with difflib, recovers spans where
the alignment holds, and records:

    drift_rate      share of narratives where untagged text was altered
    drift_chars     how much text differs, as a share of the original
    unparseable     share where output was too mangled to align at all

A narrative that cannot be aligned contributes NO predicted spans — it counts as
a miss, which is the honest treatment: a redactor whose output you cannot trust
has not redacted anything.
"""

from __future__ import annotations

import difflib
import re

TAG_RE = re.compile(r"<(/?)([A-Z_]+)>")
CATEGORIES = {
    "PERSON", "ACCOUNT_ID", "GOV_ID", "CONTACT", "CASE_REF", "RELATIONSHIP",
    "LOCATION_FINE", "EMPLOYER", "LIFE_EVENT", "PROTECTED_ATTR", "HEALTH",
    "ORG_THIRD_PARTY", "AMOUNT", "DATE", "MERCHANT", "TEMPORAL",
}


def strip_tags(tagged: str) -> tuple[str, list[tuple[int, int, str]]]:
    """Remove markup, returning clean text and spans in CLEAN-text coordinates."""
    out, spans, stack, pos, last = [], [], [], 0, 0
    for m in TAG_RE.finditer(tagged):
        closing, cat = m.group(1) == "/", m.group(2)
        if cat not in CATEGORIES:
            continue
        literal = tagged[last : m.start()]
        out.append(literal)
        pos += len(literal)
        last = m.end()
        if closing:
            if stack and stack[-1][0] == cat:
                start_cat, start_pos = stack.pop()
                if pos > start_pos:
                    spans.append((start_pos, pos, start_cat))
        else:
            stack.append((cat, pos))
    out.append(tagged[last:])
    return "".join(out), spans


def recover(original: str, tagged: str, drift_tolerance: float = 0.02):
    """
    Map spans from the writer's output back onto the original text.

    Returns (spans, drift_chars, ok). `ok` is False when the output diverged too
    far to trust, in which case NO spans are returned — an untrustworthy
    redaction is scored as having redacted nothing.
    """
    clean, spans = strip_tags(tagged)
    if not clean.strip():
        return [], len(original), False

    sm = difflib.SequenceMatcher(None, clean, original, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched = sum(b.size for b in blocks)
    drift_chars = max(0, len(original) - matched)
    if len(original) and drift_chars / len(original) > drift_tolerance:
        return [], drift_chars, False

    # Map a clean-text offset onto the original using the matching blocks.
    def to_original(i: int) -> int | None:
        for b in blocks:
            if b.a <= i < b.a + b.size:
                return b.b + (i - b.a)
        return None

    out = []
    for s, e, cat in spans:
        os_, oe = to_original(s), to_original(max(s, e - 1))
        if os_ is None or oe is None or oe < os_:
            continue
        out.append((os_, oe + 1, cat))
    return out, drift_chars, True


def predict(texts, model, tok, dev, instruction, max_new_tokens=1400, batch=4,
            bucket=True, progress_every=0):
    """Generate tagged output and recover spans. Also returns drift statistics.

    Batches are formed from narratives of SIMILAR length. `generate` runs a batch
    until every sequence in it has finished, so a 200-token narrative sharing a
    batch with a 1,400-token one pays the long one's cost. On the M3 evaluation
    set the arrival order is effectively random in length, so most batches ran at
    the longest member's cost: measured 11.4 s/narrative, 7.9 hours for 2,492.
    Sorting by length first removes that waste without changing any output.

    Ordering is a correctness concern and not only a speed one -- scoring matches
    spans to texts by index, so the sort is undone before returning. `bucket` is
    left switchable so the two paths can be diffed against each other.
    """
    import torch

    model.eval()
    prompts = [instruction + t + "\n\nTagged:\n" for t in texts]

    order = list(range(len(texts)))
    if bucket:
        lengths = [len(tok(p, add_special_tokens=False).input_ids) for p in prompts]
        order.sort(key=lambda i: lengths[i])

    # Indexed by ORIGINAL position, so the sorted traversal cannot leak into the
    # returned order.
    recovered: list = [None] * len(texts)

    done = 0
    for s in range(0, len(order), batch):
        idx = order[s : s + batch]
        enc = tok([prompts[i] for i in idx], return_tensors="pt", padding=True,
                  padding_side="left", truncation=True, max_length=1024).to(dev)
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=max_new_tokens,
                                 do_sample=False, temperature=None, top_p=None,
                                 pad_token_id=tok.pad_token_id)
        for j, i in enumerate(idx):
            completion = tok.decode(gen[j][enc["input_ids"].shape[1]:],
                                    skip_special_tokens=True)
            recovered[i] = recover(texts[i], completion)
        done += len(idx)
        # A run this long with no output at all is how the previous attempt
        # became impossible to tell apart from a hang.
        if progress_every and (done % progress_every < batch):
            print(f"    writer {done}/{len(texts)}", flush=True)

    preds, drifted, unparseable, drift_total, char_total = [], 0, 0, 0, 0
    for t, (spans, dc, ok) in zip(texts, recovered):
        preds.append(spans)
        char_total += len(t)
        drift_total += dc
        if not ok:
            unparseable += 1
        elif dc > 0:
            drifted += 1
    n = max(len(texts), 1)
    stats = {
        "drift_rate": drifted / n,
        "unparseable_rate": unparseable / n,
        "drift_char_share": drift_total / max(char_total, 1),
    }
    return preds, stats
