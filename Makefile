# Airlock. Every number in the README comes from `make repro`.
#
# Milestones run in order and each one refuses to start until the previous one
# has written its numbers down. That ordering is the project's working method,
# not a build-system detail — see .specify/memory/constitution.md, principle II.

PY := .venv/bin/python
RESULTS := results

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@echo "Airlock — local PII redaction gate"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "First time:  ./scripts/bootstrap.sh"

.PHONY: setup
setup:  ## Build the venv and install dependencies (no data)
	./scripts/bootstrap.sh --skip-data

.PHONY: data
data:  ## Download and unpack the CFPB corpus (~1.3GB down, ~8.4GB on disk)
	./scripts/bootstrap.sh

# --- Milestones -------------------------------------------------------------

.PHONY: m0
m0: $(RESULTS)/m0_product_counts.csv $(RESULTS)/m0_extract_summary.txt $(RESULTS)/m0_marker_stats.txt  ## M0: characterise the corpus

$(RESULTS)/m0_product_counts.csv:
	$(PY) scripts/m0_scan_products.py

$(RESULTS)/m0_extract_summary.txt: $(RESULTS)/m0_product_counts.csv
	$(PY) scripts/m0_extract.py

$(RESULTS)/m0_marker_stats.txt: $(RESULTS)/m0_extract_summary.txt
	$(PY) scripts/m0_marker_stats.py

.PHONY: m1
m1: $(RESULTS)/m1_baselines.txt  ## M1: what Presidio, spaCy and regex already achieve

$(RESULTS)/m1_baselines.txt: $(RESULTS)/m0_marker_stats.txt
	$(PY) scripts/m1_baselines.py

.PHONY: m2
m2: $(RESULTS)/m2_injection_summary.txt  ## M2: injection harness and the adversary's database

$(RESULTS)/m2_category_distribution.txt: $(RESULTS)/m0_marker_stats.txt
	$(PY) scripts/m2_category_distribution.py

$(RESULTS)/m2_synthetic_summary.txt:
	$(PY) scripts/m2_transactions.py

# The injector depends on the customers existing first: injected values are drawn
# FROM a customer's record, or the narrative describes nobody and M4 has nothing
# to find.
$(RESULTS)/m2_injection_summary.txt: $(RESULTS)/m2_category_distribution.txt $(RESULTS)/m2_synthetic_summary.txt
	$(PY) scripts/m2_inject.py

# --- weights ----------------------------------------------------------------
# Decision 011 commits repro to NOT retraining: "a repro that silently requires
# a rented A100 is not a repro". The published arms are fetched instead, from a
# public bucket, anonymously. Retraining them is still possible and still
# reproducible (fixed seeds) — see `make train` — it just is not required.

MICRO := models/encoder-micro-s20260806/model.safetensors

.PHONY: weights
weights: $(MICRO)  ## Fetch the published trained arms (7.3 GiB, no AWS account needed)

$(MICRO):
	./scripts/fetch_weights.sh models

.PHONY: train
train:  ## Retrain every arm from scratch instead of fetching (needs CUDA, ~1.5h)
	./scripts/train_all_seeds.sh

.PHONY: m3
m3: $(RESULTS)/m3_arms.txt  ## M3: compare every method on real prose

# The four-arm comparison is the published one. `m3_evaluate.py` produced the
# older single-model m3_comparison.txt and no longer backs any README number.
# Baselines are deliberately left ON: with --no-baselines their per-category
# column used to render as "0.0%", which reads as measured-and-failed.
$(RESULTS)/m3_arms.txt: $(RESULTS)/m2_injection_summary.txt $(MICRO)
	$(PY) scripts/m3_compare_arms.py --arms micro,base2,large

.PHONY: m4
m4: $(RESULTS)/m4_attack.txt  ## M4: the attack — the headline

$(RESULTS)/m4_attack.txt: $(RESULTS)/m3_arms.txt
	$(PY) scripts/m4_attack.py --set natural_v2

.PHONY: m5
m5: $(RESULTS)/m5_utility.txt  ## M5: does the redacted text still answer questions?

# The only part of the project that needs a credential, read from the
# environment (constitution principle VI). Costs roughly $2 of Haiku calls.
$(RESULTS)/m5_utility.txt: $(RESULTS)/m4_attack.txt
	@test -n "$$ANTHROPIC_API_KEY" || { \
		echo "ANTHROPIC_API_KEY is not set — see .secrets/README.md."; \
		echo "M5 is the one milestone that needs a key; everything else runs without one."; \
		exit 1; }
	$(PY) scripts/m5_utility.py --n 250 --methods raw,presidio,airlock,spacy

.PHONY: m6
m6: $(RESULTS)/m6_dbsize.txt $(RESULTS)/m6_overfit_gap.txt $(RESULTS)/m2_uniqueness_curve.txt  ## M6: ablations that need no GPU

$(RESULTS)/m6_dbsize.txt: $(RESULTS)/m4_attack.txt
	$(PY) scripts/m6_ablate_dbsize.py

$(RESULTS)/m6_overfit_gap.txt: $(RESULTS)/m3_arms.txt
	$(PY) scripts/m6_overfit_gap.py --n 4000 --arms micro,base2,large

# Cheap (~45s) and it answers the objection the headline attracts most: that
# 99.7% uniqueness was measured against one small database. Generates each
# population in a temp dir, so data/synthetic/ is never touched.
$(RESULTS)/m2_uniqueness_curve.txt: $(RESULTS)/m2_synthetic_summary.txt
	$(PY) scripts/m2_uniqueness_curve.py

.PHONY: repro
repro: repro-banner m0 m1 m2 m3 m4 m5 m6  ## Regenerate every number in the README from scratch
	@echo
	@echo "Regenerated: m0 m1 m2 m3 m4 m5 m6"
	@echo
	@echo "NOT regenerated here, and each says so where it is published:"
	@echo "  writer arm accuracy + cost       — needs CUDA; run 'make gpu-arms'"
	@echo "  m6 data-scaling / epoch ablation — needs CUDA; trains 9 arms (~50 min)"

# Stating the cost before spending it, rather than after — the same rule the
# constitution applies to GPU spend (principle I.3).
#
# The seven-hour figure is an ESTIMATE, not a measurement: micro was timed on an
# M1 at ~72 ms/narrative and the other two arms were scaled from their GPU ratio.
# It is here to set expectations, and it is not published as a result anywhere.
.PHONY: repro-banner
repro-banner:
	@echo "make repro regenerates every published number. On an M1 that is about"
	@echo "SEVEN HOURS, most of it m6_overfit_gap (4 sets x 9 arms, ~5.7h alone)."
	@echo "M5 also spends roughly \$$2 of Anthropic API credit."
	@echo
	@echo "To check the wiring instead, without the wait:  make repro-smoke"
	@echo

# Same chain, same scripts, tiny samples. Proves every milestone still runs and
# still hands the next one what it expects. The scripts write to results/
# unconditionally, so it backs that directory up and restores it afterwards —
# otherwise a smoke run would silently replace published numbers with
# small-sample ones that look identical.
.PHONY: repro-smoke
repro-smoke:  ## Run the whole chain at small n to prove the wiring (~3 min)
	./scripts/repro_smoke.sh

# --- targets that require a GPU ----------------------------------------------
# Kept out of `repro` deliberately. The writer generates ~365 tokens per
# narrative; on an M1 that is hours, so a repro that included it would not
# finish on the hardware this project claims to run on.

.PHONY: gpu-arms
gpu-arms: $(RESULTS)/m3_writer_cost.txt $(RESULTS)/m6_data_scaling.txt $(RESULTS)/m6_epoch_ablation.txt  ## Everything needing CUDA

$(RESULTS)/m3_writer_cost.txt:
	$(PY) scripts/m3_writer_cost.py --n 300

$(RESULTS)/m6_data_scaling.txt:
	./scripts/m6_data_scaling.sh && $(PY) scripts/m6_data_scaling.py

$(RESULTS)/m6_epoch_ablation.txt:
	./scripts/m6_epoch_ablation.sh && $(PY) scripts/m6_epoch_ablation.py

.PHONY: prune
prune:  ## Delete build artifacts that are regenerable — weights, archives, caches
	@echo "Removing the downloaded archive (the extracted CSV is what gets read;"
	@echo "bootstrap.sh re-downloads it if ever needed)..."
	rm -f data/raw/*.zip
	@echo "Removing superseded model weights. Every arm is rebuildable from its"
	@echo "recipe — see docs/04a-base-encoder.md — and make repro regenerates the"
	@echo "training data before training anything, so weights are never an input."
	rm -rf models/airlock-encoder models/airlock-encoder-ep1
	@echo
	@echo "NOT removed, because published numbers currently cite them:"
	@echo "  models/encoder-*-s*   run 'make prune-superseded' once newer arms replace them"
	@du -sh models data/raw 2>/dev/null || true

.PHONY: prune-superseded
prune-superseded:  ## Also delete arm weights whose numbers have been superseded
	@echo "Removing the authored/ and hard/ arms. The four-arm comparison"
	@echo "(micro, base2, large, writer) replaced them and no published number"
	@echo "cites them any more. They are rebuildable from scripts/train_all_seeds.sh,"
	@echo "and the surviving arms are re-fetchable with 'make weights'."
	rm -rf models/encoder-authored-s* models/encoder-hard-s*
	rm -rf models/airlock-encoder models/airlock-encoder-ep1
	@du -sh models 2>/dev/null || true

.PHONY: clean
clean:  ## Remove generated results (keeps the downloaded corpus)
	rm -rf $(RESULTS)/*.csv $(RESULTS)/*.txt data/interim/*

.PHONY: clean-all
clean-all: clean  ## Also remove the downloaded corpus
	rm -rf data/raw/*
