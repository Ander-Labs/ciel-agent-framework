# CI & Release (GitHub Actions)

[`.github/workflows/`](https://github.com/Ander-Labs/ciel-agent-framework/tree/master/.github/workflows).

The repository is already initialized and pushed; CI runs on every push to `master`
and on `v*` tags.

## Tools

- **[uv](https://docs.astral.sh/uv/)** — fast Python package/workspace manager (installed via
  `astral-sh/setup-uv@v5`, with a cache keyed on `uv.lock`).
- **Python 3.14** — pinned via `uv python install 3.14` (project requires `>=3.11`).

## `ci.yml` — Continuous Integration

**Triggers:** push to `master`, push of any `v*` tag, and pull requests against `master`.

**Matrix:** runs on all three OSes in parallel — `ubuntu-latest`, `windows-latest`,
`macos-latest` (`fail-fast: false` so one OS failing does not cancel the others).

**Steps per job:**

1. `actions/checkout@v4`
2. Install `uv` (with dependency cache).
3. `uv python install 3.14`.
4. `uv sync --all-extras` — installs the project plus every optional extra
   (gateway, acp, observability, messaging, board, security, docs, dev) so the
   full `tests/` suite can be collected.
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

### PyPI publishing (enabled)

A `publish` job is included and **enabled**: on a `v*` tag push it downloads all
per-OS build artifacts into a single `dist/` directory and runs `uv publish`,
authenticated via the `UV_PUBLISH_TOKEN` environment variable (sourced from the
repository secret **`CIEL_PYPI_TOKEN`**).

> Note: the publish step runs on the Linux runner, where `uv publish` with
> `UV_PUBLISH_TOKEN` works directly. (On Windows runners a known quirk corrupts
> the env token via CRLF; the Linux runner avoids it.)

## Local sanity check

Run the same test command the CI uses:

```bash
uv sync --all-extras
uv run pytest -q
```

## Validating the YAML locally

Before committing, verify both workflows parse as valid YAML:

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```
