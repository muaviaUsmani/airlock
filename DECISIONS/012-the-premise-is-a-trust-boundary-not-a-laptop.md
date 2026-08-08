# 012 — The premise is a trust boundary, not a laptop

**Date:** 2026-08-08
**Status:** Decided by the human. Reframes the brief's opening argument.
**Blocks:** nothing. Reopens [decision 009](009-dropping-the-generative-branch.md).

---

## What I had wrong

The brief opens with:

> *"...the text contains personal information that is not allowed to leave the building. So
> something has to strip the personal information out first — and that something must run
> locally, on the bank's own hardware, because if you could send the text out to be checked, you
> wouldn't have needed to check it."*

I treated "leave the building" literally, and let it carry weight it cannot bear. Every time the
hardware question came up I reasoned as though a laptop were protecting the data.

**It never was.** The human's correction, and it is obviously right once stated:

> *A company using a private model wants to refine or distil before passing data to a frontier
> model. Practically, most companies run on AWS or Azure. "Run locally" is a leftover from not
> wanting to rent infra.*

## The premise, stated correctly

The constraint is a **trust boundary**, not a physical location.

The complaint text may move freely inside infrastructure the company controls — its own VPC, its
own cloud account, under its own contracts. What it may not do is reach a **third-party model
API** that sits outside that boundary.

The brief's actual argument survives this intact, and it is the good part:

> *if you could send the text out to be checked, you wouldn't have needed to check it*

That is a statement about **where the redactor runs relative to the boundary**, and it is still
true. The redactor must sit inside. It says nothing about whether "inside" is a MacBook or an
EC2 instance with an A100 in the company's own account.

## What was actually doing the work

| constraint | what it really protects | still binding? |
|---|---|---|
| redactor runs inside the trust boundary | **the privacy argument** | **yes — this is the thesis** |
| redactor runs on an M1 laptop, no GPU | project cost, and portfolio accessibility | no — a preference, not a premise |

[Decision 011](011-training-moves-to-rented-gpu.md) already split training from inference and got
the training half right. It got the *reason* half wrong: it justified keeping inference on the
laptop as "the claim being made", when the claim that matters is the boundary, not the hardware.

## What changes

1. **Inference may run on a GPU inside the company's own infrastructure.** This is not a
   weakening of the privacy argument. It was never the privacy argument.
2. **The model-size ceiling relaxes.** "372MB" stops being load-bearing. A larger encoder is
   now a legitimate arm to test rather than something that "breaks the thesis" — which is how I
   wrongly described DeBERTa-large.
3. **A laptop-sized model becomes a *demonstration* claim, not the thesis.** "A 70MB version
   runs on a laptop" is a good line and an honest one, sitting beside a deployment story rather
   than standing in for it.
4. **Latency on the M1 is still measured and still published**, because a reader wants to know
   the floor — but it is no longer the constraint that decides what may be built.

## The consequence that matters most

**[Decision 009](009-dropping-the-generative-branch.md) is reopened.**

That decision dropped the generative branch on one disqualifying number: 4–5 seconds per
narrative at inference on the M1, which meant weeks of wall-clock for a bank's complaint volume.
Its own closing paragraph anticipated exactly this:

> *"If the premise ever changes to allow a GPU at inference time, that decision should be
> reopened, and this paragraph is the note to whoever does it."*

The premise has changed. On a cloud GPU that 4–5 seconds becomes roughly 50–100ms, and the
argument that killed the branch evaporates. What remains of decision 009 is the *second* reason —
too many confounds for the value — and that was always the weaker half.

Under the standing "build every branch" rule, and at a cost measured in cents, the generative arm
is back on the table. It is not resumed silently: it goes back to the human as a scope question,
with the note that its blocking objection no longer holds.

## What does not change

**No measurement is invalidated.** Every number in this repository was produced by a committed
script against fixed data, and none of them depended on this framing. What changes is the
*argument around* the numbers and the *scope* of what is worth building next.

`README.md`, `docs/01-why.md`, `docs/08-limitations.md` and the constitution carry the corrected
premise. The old framing is not quietly deleted — this file records that it was wrong and why,
because "the redactor must run on a laptop" is a mistake a reader could easily make on their own.
