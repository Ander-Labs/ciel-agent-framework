# CI & Release (GitHub Actions)

This document describes the GitHub Actions workflows shipped in
[`.github/workflows/`](https://github.com/ciel-agent-framework/ciel/tree/main/.github/workflows).
The repository is not yet initialized as a git repo locally; commit these files once the
repo is created so CI lights up on the first push.

## Tools

- **[uv](https://docs.astral.sh/uv/)** — fast Python package/workspace manager (installed via
  `astral-sh/setup-uv@v5`, with a cache keyed on `uv.lock`).
- **Python 3.14** — pinned via `uv python install 3.14` (project requires `>=3.14`).

## `ci.yml` — Continuous Integration

**Triggers:** push to `main`, push of any `v*` tag, and pull requests against `main`.

**Matrix:** runs on all three OSes in parallel — `ubuntu-latest`, `windows-latest`,
`macos-latest` (`fail-fast: false` so one OS failing does not cancel the others).

**Steps per job:**

1. `actions/checkout@v4`
2. Install `uv` (with dependency cache).
3. `uv python install 3.14`.
4. `uv sync --extra gateway --extra acp --extra dev` — installs the project plus the gateway,
   ACP and dev (pytest) extras.
5. `uv run pytest -q` — runs the `tests/` suite quietly.

A `concurrency` group keyed on the workflow + ref auto-cancels superseded runs on the same
branch/tag.

## `release.yml` — Build & Publish

**Triggers:** push of any `v*` tag, or manual `workflow_dispatch`.

**Matrix:** same three OSes as CI, building distribution artifacts natively on each.

**Steps per job:**

1. `actions/checkout@v4`
2. Install `uv` + Python 3.14.
3. `uv build` — produces wheels (`dist/*.whl`) and an sdist (`dist/*.tar.gz`) using the
   project's setuptools backend.
4. `actions/upload-artifact@v4` — uploads the build artifacts under the name
   `dist-<os>` (retained 7 days, fails if nothing was produced).

### PyPI publishing (disabled by default)

A `publish` job is included but **commented out** so a tag push never publishes by accident.
To enable it:

1. Add a repository/organization secret named **`CIEL_PYPI_TOKEN`** containing a PyPI API token.
2. Uncomment the `publish` job block (and it already declares `needs: [build]`).

It downloads all per-OS artifacts into a single `dist/` directory and runs `uv publish`,
authenticated via the `UV_PUBLISH_TOKEN` environment variable.

## Local sanity check

Run the same test command the CI uses:

```bash
uv sync --extra gateway --extra acp --extra dev
uv run pytest -q
```

## Validating the YAML locally

Before committing, verify both workflows parse as valid YAML:

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```
