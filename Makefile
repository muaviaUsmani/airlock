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

.PHONY: repro
repro: m0 m1  ## Regenerate every number in the README from scratch
	@echo
	@echo "Milestones beyond M1 are not built yet."

.PHONY: clean
clean:  ## Remove generated results (keeps the downloaded corpus)
	rm -rf $(RESULTS)/*.csv $(RESULTS)/*.txt data/interim/*

.PHONY: clean-all
clean-all: clean  ## Also remove the downloaded corpus
	rm -rf data/raw/*
