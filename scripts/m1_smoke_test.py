"""
M1, smoke test: does it even make sense to run a PII detector on scrubbed text?

The plan for M1 is to run Presidio, spaCy and regex against the corpus and score
recall against the XXXX markers. There is a problem with that plan worth checking
before spending hours on a full run.

The published text does not contain personal information. It contains XXXX where
the personal information used to be. So scoring a detector by "did it flag the
marker positions" is asking it to recognise a token that carries no information at
all — the name is gone; only the context around it survives.

If detectors flag markers anyway, they are doing it from context, and the
measurement is meaningful (if unusual). If they flag almost nothing, then the
measurement mostly reports "XXXX does not look like a name", which is true and
useless, and would produce an unfairly weak baseline for Presidio.

This script checks which of those is the case, cheaply, before the full run.

Reads:  data/interim/creditcard_narratives.parquet
Writes: nothing. Prints. This is an exploratory check, not a published number.
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
SEED = 20260806
N = 60

MARKER_SPAN = re.compile(r"(?<![A-Za-z0-9])X{2,}(?:[ \t]+X{2,})*(?![A-Za-z0-9])")


def main() -> int:
    if not IN.exists():
        print(f"missing {IN}", file=sys.stderr)
        return 1

    from presidio_analyzer import AnalyzerEngine

    df = pd.read_parquet(IN, columns=["complaint_id", "narrative"])
    marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
    sample = marked.sample(n=N, random_state=SEED)

    print("loading presidio (spacy en_core_web_lg)...", flush=True)
    analyzer = AnalyzerEngine()

    total_markers = 0
    hit_markers = 0
    entity_types: dict[str, int] = {}

    for text in sample["narrative"]:
        spans = [(m.start(), m.end()) for m in MARKER_SPAN.finditer(text)]
        total_markers += len(spans)

        results = analyzer.analyze(text=text, language="en")
        pred = [(r.start, r.end, r.entity_type) for r in results]

        for s, e in spans:
            # Any overlap counts as a hit for this rough check.
            if any(ps < e and s < pe for ps, pe, _ in pred):
                hit_markers += 1

        for _, _, t in pred:
            entity_types[t] = entity_types.get(t, 0) + 1

    print()
    print(f"narratives sampled:        {N}")
    print(f"marker spans in them:      {total_markers}")
    print(f"markers Presidio flagged:  {hit_markers}  ({100*hit_markers/max(total_markers,1):.1f}%)")
    print()
    print("what Presidio thinks it found (all predictions, whole sample):")
    for t, c in sorted(entity_types.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<24} {c:>6}")
    print()
    print("Reading: a high marker hit-rate means detectors are using context and")
    print("the M1 plan is sound. A low one means we would mostly be measuring")
    print("'XXXX does not look like a name', which understates every baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
