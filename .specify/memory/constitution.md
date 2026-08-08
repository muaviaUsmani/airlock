# Airlock Constitution

Airlock is a local PII redaction gate for consumer complaint text. It exists to answer one
question honestly: **after we redact a complaint, can the customer still be identified?**

These principles are derived from the project brief dated 2026-08-06. They are not style
preferences. They are the conditions under which the results of this project are allowed to be
believed. Where a principle says NON-NEGOTIABLE, no plan, task, or implementation may override
it — the correct response to a conflict is to stop and surface it, not to route around it.

## Core Principles

### I. Forks Are Surfaced, Never Silently Resolved (NON-NEGOTIABLE)

The project brief names three open decisions: model architecture, the definition of
"re-identified", and how the adversary matches. These are not to be decided by the implementing
agent.

When a decision point arrives that is genuinely open — that is, where two defensible choices
would produce different headline numbers — work stops and the decision is put to the human,
with the evidence gathered so far attached. This applies to forks not on the brief's list too:
an unlisted fork is surfaced, not picked.

A silently resolved fork invalidates the result that depends on it. This is the specific failure
mode the whole working method exists to prevent.

**Standing instruction from the human, given 2026-08-06 and applying to all forks unless
overridden for a specific one:**

> *Build every branch. Publish the comparison. Do not pick one and discard the rest.*

The reasoning behind it is that this portfolio is analytical in intent — the deliverable is the
comparison itself, not a single tuned artifact. A fork resolved by choosing one branch throws
away exactly the evidence a reader needs to judge whether the choice was right.

This changes what "surface the fork" means in practice, and does not remove the obligation:

1. **Forks are still surfaced**, because the human still decides scope, cost, and which branch
   supplies the headline. A fork resolved by this rule is still written up in `DECISIONS/`.
2. **Surface anything the rule cannot absorb.** Where branches are not comparable on any common
   axis, or where building all of them is disproportionate to what the comparison would show,
   that is itself a fork and it stops the work.
3. **State the cost before spending it.** Where building every branch is materially expensive —
   training two models rather than one — the estimate is put to the human before the work
   starts, not reported afterwards.
4. **Where branches form a parameterised family rather than a menu, publish the curve.** Two
   points chosen from a continuum are a weaker answer than the continuum.
5. **Pre-register how any tunable parameter is selected**, before the comparison runs. A
   comparison whose parameters are chosen after seeing the results is not a comparison.

### II. Measure Before Building (NON-NEGOTIABLE)

Baselines are published before the thing that beats them is built. The corpus is characterised
before the labels derived from it are trusted. The injection distribution is derived from the
real corpus, never invented.

No milestone begins until the previous milestone's done-when condition is met and its numbers
are committed. "Numbers are committed" means written to a file in the repository, not stated in
conversation.

### III. Every Published Number Is Reproducible (NON-NEGOTIABLE)

Every number appearing in any document in this repository is produced by a committed script with
a fixed seed. If a number cannot be regenerated from a clean checkout, it does not get published
— it gets deleted.

`make repro` regenerates every number in the README from scratch. A number that `make repro`
does not touch is a number that does not belong in the README.

### IV. Negative Results Are The Product

If the model loses to Presidio, if the attack fails to re-identify anyone, if the CFPB oracle is
too noisy to use — that is a finding, and it goes in the README in plain language, not in a
footnote and not in a directory nobody opens.

The brief includes a stop condition at M0 and permits the entire project to conclude as a
negative result. Reporting a clean negative result is a successful outcome. Manufacturing a
positive one is the only actual failure.

Structured PII (card numbers, SSNs) stays in the evaluation even though Presidio wins that row.
Publishing the row we lose is the point.

### V. Complexity Only Where It Earns Its Place

Complexity is permitted in exactly four places: the model, the injection harness, the adversary,
and the evaluation.

Everything else — data loading, the synthetic transaction system, any command-line interface —
stays as simple as it can be while working. The transaction system in particular is a linkage
adversary, not a data generator: if it starts growing features that do not serve the question
"can I find exactly one matching customer?", that is a signal that focus has drifted, and the
features come back out.

Nothing is built for reuse speculatively. Later projects in this portfolio may lift pieces of
this one; that is their problem, not this project's. Extract when a second caller actually
exists.

### VI. No Secrets, No Real Personal Data (NON-NEGOTIABLE)

No API keys, credentials, tokens, or real personal data enter this repository at any point,
including test fixtures and commit history.

Every part of this project runs with no keys at all, with exactly one exception: M5 calls a
frontier model, and reads its key from the environment. Synthetic customers, cards, and
transactions are generated from a fixed seed and are fake in their entirety.

The CFPB corpus is downloaded, never committed. It is already public and already scrubbed, and
it still does not go in the repository.

### VII. Written For A Reader Who Remembers Nothing

Documentation is written as the work happens, not assembled at the end.

Every module carries a header comment saying what it is for in plain language. Every milestone
gets a document. Every term is defined where it first appears. High-level document first, links
down into detail — including for the person who wrote it, who will not remember either.

## Scope Boundaries

Airlock is **not**: a general-purpose PII detector, a compliance tool, a replacement for
Presidio, a product, or a benchmark of frontier models.

The narrowness is the argument, not a limitation to apologise for. No document in this
repository may suggest that Airlock satisfies any regulation.

No deployment. No hosting, no service, no Docker orchestration beyond what `make repro` needs.
The code is the artifact.

**Inference** runs on an M1 MacBook with 16GB of memory and no GPU. A design whose *inference*
needs more than that is out of scope regardless of its merits, because the deployment premise is
a bank running the model on its own hardware.

**Training** may run on rented GPU, per [decision 011](../../DECISIONS/011-training-moves-to-rented-gpu.md).
The premise is that the *data* cannot leave the building, which constrains inference; the
training data here is public CFPB text with synthetic personal information we generated
ourselves, so there is nothing confidential in it. Inference latency and memory are still
measured on the M1, because that is the claim being made.

## Decided, And Not To Be Revisited

These were settled in the brief. Re-opening one requires a written amendment, not an
implementation choice:

- The CFPB Consumer Complaint Database is the corpus.
- The `XXXX` markers are the recall oracle; injection is the precision oracle.
- The transaction system is a linkage adversary and stays minimal.
- Re-identification rate is the headline metric, not span-level F1.
- Inference runs locally on the M1, no GPU. **Amended 2026-08-08** — training may use rented
  GPU; see [decision 011](../../DECISIONS/011-training-moves-to-rented-gpu.md). The original
  wording, "everything runs locally on the M1", was revisited deliberately by the human.
- Structured PII stays in the evaluation even though Presidio wins that row.

## Development Workflow

Work proceeds through the milestones M0–M6 defined in the brief, in order. Each milestone is
a Spec Kit feature: specified, planned, tasked, then implemented.

`DEFINITIONS.md` is written at M0 and locked before any measurement begins. After M1 starts it
does not change without a dated written reason recorded in `DECISIONS/`.

Each resolved fork produces one file in `DECISIONS/`, containing the options considered, the
choice, the reasoning, and the date. A decision without its reasoning attached is not recorded.

Python dependencies live in a virtual environment at `.venv/`. The repository never assumes a
globally installed package.

## Governance

This constitution supersedes other practices in this repository. Where a plan or task conflicts
with it, the constitution wins and the plan is corrected.

Amendments are dated, recorded in `DECISIONS/`, and carry the reasoning that motivated them.
Principles marked NON-NEGOTIABLE may be amended only by the human, never by an implementing
agent noticing that the principle is inconvenient.

**Version**: 1.0.0 | **Ratified**: 2026-08-06 | **Last Amended**: 2026-08-06
