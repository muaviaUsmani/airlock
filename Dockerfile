# Airlock runs locally. This image exists so that "clone it and get the numbers"
# works without the reader having to match a Python version on their own machine.
# It is not a deployment target — there is no service here, no port, no entrypoint
# that waits for requests. It runs the pipeline and exits.
#
# The corpus is NOT baked into the image. It is ~8.4GB of public data that the
# CFPB re-publishes nightly, so it lives in a mounted volume and is downloaded on
# first run. See docker-compose.yml.

FROM python:3.12-slim

# unzip for the corpus archive; curl for fetching it. Nothing else is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /airlock

# Dependencies first, so that editing source does not re-install pandas.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY scripts ./scripts
COPY Makefile ./
RUN chmod +x scripts/*.sh

# Default: show what can be run. The real commands come from docker-compose.
CMD ["make", "help"]
