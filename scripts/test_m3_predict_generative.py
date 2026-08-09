"""Tests for the writer arm's span recovery and batching.

These exist because `predict` was changed to sort narratives by length before
batching. That is a pure speed change only if the sorted order is undone before
returning -- and if it is not, every span lands on the wrong narrative and the
scores stay plausible. A silent wrong answer is exactly what this project's
working method is built to prevent, so the ordering is asserted rather than
assumed.

Run: .venv/bin/python scripts/test_m3_predict_generative.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch

from m3_predict_generative import predict, recover, strip_tags

PAD = 0


# --- strip_tags / recover ---------------------------------------------------

def test_strip_tags_returns_clean_text_and_spans():
    clean, spans = strip_tags("I called <PERSON>Jane Roe</PERSON> at <CONTACT>x@y.com</CONTACT>.")
    assert clean == "I called Jane Roe at x@y.com."
    assert (9, 17, "PERSON") in spans
    assert (21, 28, "CONTACT") in spans


def test_strip_tags_ignores_unknown_categories():
    clean, spans = strip_tags("a <NOPE>b</NOPE> c")
    assert clean == "a <NOPE>b</NOPE> c"
    assert spans == []


def test_recover_maps_spans_onto_the_original():
    original = "I called Jane Roe about it."
    tagged = "I called <PERSON>Jane Roe</PERSON> about it."
    spans, drift, ok = recover(original, tagged)
    assert ok and drift == 0
    assert spans == [(9, 17, "PERSON")]
    assert original[9:17] == "Jane Roe"


def test_recover_rejects_output_that_drifted_too_far():
    original = "I called Jane Roe about the late fee on my card."
    tagged = "Something else entirely, unrelated to the complaint at hand."
    spans, drift, ok = recover(original, tagged)
    assert not ok, "drifted output must be rejected"
    assert spans == [], "a rejected output must contribute no spans"


def test_recover_rejects_empty_output():
    spans, drift, ok = recover("some narrative", "   ")
    assert not ok and spans == []


# --- batching / ordering ----------------------------------------------------

class StubTok:
    """Character-level stand-in: token id == ord(char), so decode is exact."""

    pad_token_id = PAD

    def __call__(self, prompts, return_tensors=None, padding=None,
                 padding_side=None, truncation=None, max_length=None,
                 add_special_tokens=True):
        single = isinstance(prompts, str)
        if single:
            prompts = [prompts]
        ids = [[ord(c) for c in p] for p in prompts]
        if return_tensors is None:
            return _Ids(ids[0])
        width = max(len(x) for x in ids)
        # left padding, matching the real call site
        padded = [[PAD] * (width - len(x)) + x for x in ids]
        return _Enc({"input_ids": torch.tensor(padded)})

    def decode(self, ids, skip_special_tokens=True):
        return "".join(chr(int(i)) for i in ids if int(i) != PAD)


class _Ids:
    def __init__(self, ids):
        self.input_ids = ids


class _Enc(dict):
    def to(self, dev):
        return self


class StubModel:
    """Returns, for each prompt, the completion registered for that narrative."""

    def __init__(self, completion_for):
        self.completion_for = completion_for
        self.batch_sizes = []

    def eval(self):
        return self

    def generate(self, input_ids=None, max_new_tokens=None, **kw):
        self.batch_sizes.append(int(input_ids.shape[0]))
        rows, width = [], 0
        tok = StubTok()
        for row in input_ids:
            prompt = tok.decode(row)
            body = prompt.split("PROMPT:")[1].split("\n\nTagged:\n")[0]
            comp = [ord(c) for c in self.completion_for[body]]
            rows.append(comp)
            width = max(width, len(comp))
        out = []
        for row, comp in zip(input_ids, rows):
            out.append(list(int(x) for x in row) + comp + [PAD] * (width - len(comp)))
        return torch.tensor(out)


def test_bucketing_preserves_the_original_order():
    # Deliberately varied lengths so sorting genuinely reorders the batch, and
    # a distinct name per narrative so a mix-up cannot score as correct.
    names = ["Ann Lee", "Bob Rees", "Cal Ford", "Dee Nash", "Eli Park",
             "Fay Sims", "Gil Ross", "Hal Webb"]
    texts, completions = [], {}
    for i, name in enumerate(names):
        filler = "word " * (3 + 11 * ((i * 5) % 7))  # lengths jump around
        body = f"{filler}I spoke to {name} today."
        texts.append(body)
        completions[body] = f"{filler}I spoke to <PERSON>{name}</PERSON> today."

    tok, dev = StubTok(), torch.device("cpu")
    instruction = "PROMPT:"

    model_b = StubModel(completions)
    bucketed, stats_b = predict(texts, model_b, tok, dev, instruction,
                                batch=3, bucket=True)
    model_p = StubModel(completions)
    plain, stats_p = predict(texts, model_p, tok, dev, instruction,
                             batch=3, bucket=False)

    assert bucketed == plain, "bucketing changed the result"
    assert stats_b == stats_p

    # And the spans must actually land on the right name in the right narrative.
    # Comparing against `names[i]` is the point: if bucketing leaked the sorted
    # order, narrative i would carry some other narrative's name and still look
    # like a valid PERSON span.
    for i, (text, spans) in enumerate(zip(texts, bucketed)):
        assert len(spans) == 1, f"expected one span, got {spans}"
        s, e, cat = spans[0]
        assert cat == "PERSON", f"row {i}: category {cat}"
        assert text[s:e] == names[i], (
            f"row {i}: span covers {text[s:e]!r}, expected {names[i]!r}")


def test_bucketing_groups_similar_lengths_together():
    texts, completions = [], {}
    for i in range(9):
        body = ("x " * (1 + 40 * (i % 3))) + f"n{i}"
        texts.append(body)
        completions[body] = body

    tok, dev = StubTok(), torch.device("cpu")
    model = StubModel(completions)
    predict(texts, model, tok, dev, "PROMPT:", batch=3, bucket=True)

    # With three length classes and batch=3, bucketing should make every batch
    # length-homogeneous; the padded width is what generation time scales with.
    assert model.batch_sizes == [3, 3, 3]


def run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
