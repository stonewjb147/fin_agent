FROM python:3.10-slim

# tzdata would otherwise open an interactive prompt during build.
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# tzdata + certificates are the only system packages the batch job needs;
# all Python dependencies ship as manylinux wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the package and metadata first so dependency installation is cached
# independently of scripts/tests.
COPY pyproject.toml ./
COPY deploy/constraints.txt ./deploy/constraints.txt
COPY finagent ./finagent

# Editable install is deliberate: finagent.config derives PROJECT_ROOT from
# __file__, so `pip install .` would point configs/ at site-packages instead
# of /app and universe.yaml would not be found.
RUN pip install --upgrade pip \
    && pip install -c deploy/constraints.txt -e .

COPY configs ./configs
COPY scripts ./scripts
COPY tests ./tests
COPY evals ./evals
COPY README.md Makefile ./

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "finagent.cli", "--help"]
