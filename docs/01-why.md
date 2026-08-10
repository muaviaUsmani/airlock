# Why this project exists

**Status: written at M0, revised as later milestones changed what the argument
could claim.**

---

## The situation

A bank has hundreds of thousands of written customer complaints. It wants a
frontier model to read them — to find the pattern nobody spotted, the product
that generates disproportionate anger, the branch with a problem.

It cannot send them. The text is full of personal information, and personal
information is not allowed to leave the company's control.

So something has to strip that information out first. And that something has to
run **inside the company's own trust boundary**, because of a constraint that
sounds circular until you sit with it:

> *If you could send the text out to be checked, you would not have needed to
> check it.*

A redaction service you call over the internet has already received the
unredacted text. The problem it was hired to solve happened before it answered.

## What "inside the boundary" means, and what it does not

It means infrastructure the company controls: its own VPC, its own cloud
account, under its own contracts. It does **not** mean a physical building, and
it does not mean a laptop
([decision 012](../DECISIONS/012-the-premise-is-a-trust-boundary-not-a-laptop.md)).

Airlock is measured on an M1 MacBook because a floor is useful to know and it
makes a good demonstration, not because a laptop is what protects the data. The
committed latency table in `results/m3_arms.txt` was produced on a rented GPU and
now says so in its own heading; running `make m3` on a laptop replaces it with
real M1 figures. No M1 number is quoted here until that run is committed —
principle III does not make exceptions for numbers we happen to have seen.

Training runs on a rented GPU
([decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md)), which does
not weaken the argument: the training data is public CFPB text with synthetic
personal information we generated ourselves, so nothing confidential goes
anywhere. Only the *deployed* model has to stay inside.

## The part that is actually interesting

Redaction is not the interesting part. Presidio exists, spaCy exists, regexes
exist, and a fine-tuned encoder is a well-understood object.

The interesting part is **measurement**. Anyone can claim they removed the
personal information. The question nobody answers is whether it worked — and
"worked" cannot mean "we removed the names", because:

- **Names are not what identifies people.** M2 found that in a synthetic
  transaction database, an exact date identifies nobody (479 customers share
  one) and a merchant identifies nobody (1,329 do). Put an amount, a date and a
  merchant together and you reach **99.7% uniqueness**. None of those three is
  personal information. No PII detector removes any of them.
- **Human redactors already miss this.** The CFPB's own trained redactors, working
  to a published standard, leave an intact dollar amount in **44.2%** of
  narratives. An exact transaction amount is one of the strongest join keys
  there is.

So Airlock builds a synthetic transaction database and then **attacks its own
output** — takes the redacted text and tries to find the one customer it belongs
to. That attack is the headline, and re-identification rate is the metric, not
span-level F1.

## Why the metric had to be a trade, not a rate

A re-identification rate on its own rewards destruction. Blank every narrative
and nothing leaks — spaCy effectively does this, scoring 0.0% re-identification
by removing five times more text than it should.

So the result is always two numbers: how much leaked, and how much of the text's
usefulness survived ([M5](06-utility.md)). A redactor is only good if it moves
down the first without moving far down the second.

## Why the corpus is real complaints and not synthetic text

No synthetic corpus reproduces how somebody writes when they are angry at their
bank at 1am. The CFPB database is real text written by real people about real
money problems, it is public, and it is already scrubbed to a published standard.

That last property is what makes it usable *and* what makes it awkward: the
personal information has already been replaced by `XXXX` markers, so the text
cannot be used to train a detector directly — a model fitted to it learns
`XXXX → redact` and is worthless on text where no such token exists. Working
around that shaped most of the project's method, and is written up in
[the data](02-data.md) and [the model](04-model.md).

## What this project is honest about

It is a learning exercise, not a product. The narrowness is the argument, not a
limitation to apologise for — see [what this is not](08-limitations.md).

And several of its early conclusions were wrong in ways that looked right. The
most important: a headline that a small model beat a large one by 5 F1 turned
out to be a fact about our own training schedule, not about model size
([decision 017](../DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md)).
Those are collected, in plain language, in [what this taught us](09-lessons.md),
and that page is arguably the real output of the work.

---

Next: [the corpus, and what is wrong with it](02-data.md).
