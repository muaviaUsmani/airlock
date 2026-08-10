# What this project taught us

Airlock was built as a learning exercise, not a product. This page is the part
that transfers to the next project.

Everything here was found by attacking our own results. Almost none of it was
found by something breaking.

---

## The short version

**1. We nearly published a wrong headline, and it looked completely convincing.**
We trained three models of different sizes and gave them all the same amount of
training time. The big ones finished learning early and kept going, which made
them worse. We read that as "small models are better at this job." When we gave
each model a fair place to stop, the answer flipped. The finding was about our
setup, not about the models.

**2. Almost every mistake we made produced a believable number, not an error.**
Nothing crashed. Nothing printed a warning. Bad results looked exactly like good
results. That is the whole reason we kept re-checking things that seemed fine.

**3. Three separate times, we marked a model wrong for an answer it could not
possibly have given.** Once the answer key was blank and we scored the blank as
a wrong answer. Once we offered a list of possible answers that left out most of
the correct ones. Each time it looked like the model was bad, when really the
test was broken.

**4. When we measured how slow our "expensive" approach was, most of the
slowness turned out to be our own careless code.** We were about to report it as
a fact about the technique. After tidying the code it got nine times faster,
then almost three times faster again. The original number said more about us
than about the method.

**5. The notes we wrote for our own future reference contained things that were
not true.** Three specific claims in our handover document did not survive being
checked — including one that sent us to rewrite a document that was already
finished. We had been treating them as facts because we wrote them ourselves.

**6. Some of the questions we used to measure "is this still useful?" were
questions nobody could answer.** One asked what a company did about a complaint
— but the answer gets recorded after the complaint is written, so it was never
in the text to begin with.

**7. Moving files off the rented computer cost more than the experiments did.**
Two bugs in our own copying code meant we paid to send the same data
repeatedly — about 17 gigabytes of transfer to store 8.

**8. Some questions cannot be answered with the effort available, and noticing
that is itself the answer.** The difference we were chasing between models was
smaller than the random variation between runs. Measuring it properly would have
taken about forty hours of rented computer time. The honest conclusion is "these
are equally good, and one is cheaper," not a ranking.

**9. The cheap checks were worth more than the expensive experiments.** Testing
whether our own measurement was broken usually took minutes and repeatedly
changed what we believed. The long training runs mostly confirmed things.

**10. The very first line of our own README quoted a size no file ever had.** It
described the model as 372MB. That number was half of another model's size — a
"this is what it would be if we converted it" figure, printed once, then quoted
as though it were the thing itself. Nobody converted anything. The real number is
291MB.

**11. We built a safety net and then walked around it.** We wrote a check that
backed up the published numbers before running a test that would overwrite them,
and it worked exactly as designed — twice. Then we ran the underlying command
directly instead of through it, and quietly replaced a published table with
test output. Version control caught it, not the safety net.

**12. Writing down a plan is not the same as scheduling it.** The single most
expensive mistake in this project was a step that was described in three
separate messages and never actually written into the script that was supposed
to run it.

---

## The longer version

### 1. Same recipe, three model sizes — and the recipe decided the winner

We compared three sizes of the same model family: 70 million, 184 million and
434 million parameters. All three got an identical training recipe: the same
learning rate, the same three passes over the data, and no rule for stopping
early. We saved whatever the third pass produced.

That is where the problem is. A bigger model learns the training material
faster. By the second pass the largest model had essentially memorised it, and
we made it keep going. The smallest model was still genuinely learning when we
stopped it. So each model was measured at a different stage of its own learning,
and the bigger the model, the further past its best point we had pushed it.

Trained for one pass instead of three — changing nothing else — the ranking
reversed. The largest model went from worst to best; the smallest got slightly
worse, because it was the only one that actually wanted the extra training.

The same cause showed up from another direction. Because the number of passes
was fixed, giving the models *more* data meant more repetition, so the two
larger models actually got worse as we gave them more training material, while
the smallest kept improving. That also killed the competing theory that the big
models had simply been given too little data to work with — too little data
predicts the opposite of what we saw.

**The transferable point:** comparing models of different sizes is only a
comparison if each size is allowed its own stopping point. A shared schedule
quietly turns a question about model size into a question about the schedule,
and the result still looks clean and publishable.

Recorded in [decision 017](../DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md).

### 2. What we would do instead, and what it would cost

To answer the size question properly:

1. **Split the data three ways, not two.** Keep a slice for choosing settings
   and a separate slice, untouched until the very end, for the final number.
   Today every number is chosen and reported on the same data.
2. **Choose the stopping point on the slice that resembles the real task.**
   Stopping based on how well a model fits the training material would reward
   exactly the memorisation that hurt us.
3. **Check progress after every pass and keep the best version.** This costs
   seconds. It was missing because nobody wrote it, not because it was expensive.
4. **Tune the learning rate separately for each size.** Ours was a fixed value
   buried in the code — not even adjustable from the command line, so it was
   never varied.
5. **Only then run each model three times with different random starts** and
   report the average and the spread.

Estimated cost: five to six hours of rented GPU, about $1.10.

**But there is a catch worth more than the experiment.** The run-to-run
variation we already measured is larger than the difference we would be trying
to detect. Distinguishing a one-point difference against that much noise would
need roughly thirty repeats per model — about forty hours of rented time for the
largest one alone, and that is to resolve a difference small enough that nobody
would make a decision on it.

So the defensible conclusion is not a ranking. It is: **after fair tuning the
three sizes are indistinguishable on accuracy, and they differ enormously on
cost** — the smallest is three times cheaper and three times faster per
complaint. That difference is far larger than the noise, and it is the one that
would actually change what someone builds.

Knowing which question your measurements can settle is part of the method.

### 3. Three broken answer keys, all of which looked like model failures

**Blank answers scored as wrong.** Eight percent of the source records have no
value in one of the fields we used as an answer key. Converting a blank to text
produced the literal word "nan", which became the correct answer for those rows
— something no reader could ever produce. Worse, that same "nan" was added to
the list of choices offered, so it sat there as a decoy on every single
question. Fixed: rows without an answer are now left out of that question's
score rather than counted as failures.

**A multiple-choice list that excluded most of the right answers.** For another
question we offered twelve options, selected by taking the first twelve
alphabetically from a list of twenty-seven. Only a third of the correct answers
were among them. The two most common correct answers were missing because they
happened to start with the wrong letters. That capped the achievable score at
about a third before the reader saw any text. Now fixed: every label that
appears is offered, and the code checks that a correct answer is always
available rather than assuming it.

**A question whose answer was never in the text.** We asked whether the company
gave the customer money back. That outcome is recorded after the complaint is
filed, so a complaint written beforehand cannot contain it. The reader correctly
answered "I don't know" and we scored that as failure.

All three produced low scores that looked like genuine findings about redaction
damage.

**The transferable point:** before believing a low score, check that a perfect
answer was available. We now publish, next to each question, the score you would
get by ignoring the text entirely — which immediately reveals that two of our
three questions carry almost no information.

Recorded in [decision 014](../DECISIONS/014-m5-answer-key-and-baselines.md).

### 4. We measured our own sloppiness and nearly called it a property of the method

One approach in this project rewrites the whole complaint with the private
details marked, rather than just pointing at them. It looked hopelessly slow:
about seven hundred times slower than the alternative.

Then we looked at why. Work was being processed in arbitrary order, and because
items are handled in groups that finish together, every short complaint waited
for the longest one in its group. Sorting by length first — which changes no
output whatsoever — made it nine times faster. Adjusting how many were handled
at once made it nearly three times faster again.

We had been about to publish the original figure as a fact about the technique.
Our own handover notes had already flagged the identical mistake on the training
side and we still made it on the measurement side.

There is a second layer. Most of the remaining cost comes from asking the model
to rewrite the entire document just to mark a few words. Asking it to only point
at the words instead would cut the work by roughly another factor of thirteen —
and would also eliminate the approach's biggest quality problem, because a model
that never rewrites the text cannot corrupt it. But that is a different method,
not a faster version of the same one, so it is written up as a proposal rather
than folded in.

Recorded in [decision 016](../DECISIONS/016-span-emitting-writer-proposed.md).

### 5. Our own handover notes were not reliable

Three claims in the document written specifically to bring the next person up to
speed did not survive checking. One said a particular measurement had scored
zero; the committed evidence showed it was the highest-scoring of its group. The
second said a piece of code was covered by tests; there were no tests for it
anywhere in the project. The third listed a document as an unwritten stub when it
was already two hundred lines long — we only noticed because we opened it to
write it.

Neither was dishonest. Both were written from memory at the end of a long
session, which is exactly when handover notes get written.

Our README had the same problem in a louder form: it described a directory of
per-milestone specifications and plans, said where to find them, and explained
what was in each one. That directory does not exist and never did. A reader
would have gone looking for it.

**The transferable point:** a handover document, and a README, are the things a
later reader trusts without re-deriving — which makes an unchecked claim in one
unusually expensive. Describing work that was never done is the same failure as
publishing a number that was never measured; it just does not look like one.

### 6. The plumbing cost more than the science

Getting eight gigabytes of trained models off a rented machine took most of a
day and cost more than every experiment combined.

The rented machine's upload speed was roughly two percent of what was
advertised, and it varied by a factor of a hundred through the day. Our first
tool gave up on any file over a few hundred megabytes. The replacement had two
bugs of its own: one where transfers were killed just before finishing and
restarted from scratch, and one where stopping the tool left orphaned copies
running that duplicated each other's work. Together those meant we paid to send
about seventeen gigabytes in order to store eight.

The fix that mattered was not speed but ordering: finishing nearly-complete
files first, so that if we had to stop early we would have whole usable models
rather than fragments of all of them.

**The transferable point:** for anything rented and metered, work out the exit
path before you start, and make the transfer resumable at a small granularity.
Also, measure the connection rather than trusting the advertised figure.

Recorded in [decision 013](../DECISIONS/013-where-trained-weights-live.md).

### 7. The one artefact that could not be rebuilt

Every trained model in this project can be rebuilt from a script for about a
dollar. The source data cannot. It is downloaded from a public address that
always serves the current version, with no way to ask for the version we used.
If that file changes, none of our numbers can be reproduced, and nothing would
announce that.

It is now archived with a fingerprint so a future reader can prove they have the
same version. That should have happened on day one, and it very nearly did not
happen at all — we only noticed while tidying up.

**The transferable point:** identify which of your inputs is the one that cannot
be regenerated, and treat it differently from everything else.

### 8. A hypothetical number one edit away from a real one

The README's opening sentence described "a 372MB model". No such file has ever
existed. 372 is exactly half of 743.8, the size of a *different* model, and it
came from a line in an old report that read "an fp16 export would be ~372 MB" —
a statement about a conversion nobody performed. Somewhere between that report
and the README it lost the conditional and became the headline.

It also named the wrong model: by then a 291MB model had replaced the one that
figure referred to.

**The transferable point:** keep hypothetical numbers visibly hypothetical, and
keep them away from real ones. Ours sat on the same line as a measurement,
formatted the same way, and it took an audit to notice the difference.

### 9. A guard you can bypass is a guard you will bypass

Several of our scripts write their results unconditionally. Running one at a
small sample size to check it still worked would therefore overwrite a published
table with a test result that looked exactly like a real one — same file, same
format, plausible numbers.

So we wrote a wrapper that copies the results aside, runs the chain, and restores
them afterwards — on success, on failure, and on interrupt. It worked: we killed
it twice mid-run and the published numbers came back byte-identical both times.

Then we ran the underlying script directly, because we only wanted one quick
check, and overwrote a published table without noticing. The numbers sat wrong
for about an hour. What caught it was not the wrapper but **version control** —
the file showed as modified, and the committed version still had the real
numbers.

**The transferable point:** if the unsafe path is still the shortest one, the
safe path is decoration. Either the scripts should refuse to overwrite published
output without being told to, or the results should be treated as build artifacts
that never sit in the same place as the committed ones. And keep the generated
numbers in version control regardless — it was the only thing that actually
worked.

### 10. A plan described is not a plan scheduled

The single most expensive error in the project was not technical. A necessary
step was described as "step one" in three separate messages and was never
actually added to the script meant to perform it. The machine sat running,
billing by the hour, waiting to do something nobody had told it to do.

Checking the script rather than the intention would have caught it in seconds.

---

## What we would tell someone starting a similar project

- Budget real time for checking your own measurements. On this project the cheap
  self-checks changed our conclusions repeatedly; the expensive experiments
  mostly confirmed what we already suspected.
- Before believing any comparison, ask what else differs between the things
  being compared. Here it was the training schedule, and it decided the result.
- Before believing any low score, verify a perfect score was achievable.
- Publish the score you would get by not trying. If your method cannot beat it,
  that is the finding.
- Write down what your measurements *cannot* settle. It is more useful than
  pretending they settled it.
