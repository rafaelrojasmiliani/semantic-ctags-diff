# Workflow reference — semantic-branch-diff

## `ci.yml`

| Field | Value |
|-------|-------|
| **Goal** | Ensure `semantic_branch_diff` unit tests pass before merge |
| **Methodology** | Single job, three stages (`S01`–`S03`), no API keys, `contents: read` |
| **Used by** | This repo’s Actions tab; duplicated as S03 inside the Vim plugin parent CI |

### Steps

| Step | Name | What it does |
|------|------|--------------|
| **S01** | Checkout repository | Full tree at the triggering commit |
| **S02** | Install system packages | `git` for `test_diff_engine` temp repos; `universal-ctags` for `test_ctags_parsing` / examples |
| **S03** | Python unit tests | Python 3.12, `pip install -e ./ctags3-improved` then `-e ".[dev]"`, `pytest -v` |

### Test modules exercised

| Module | Covers |
|--------|--------|
| `ctags3-improved/tests/` | `index_source` / normalize / type tree |
| `test_diff_engine.py` | `semantic_diff` with real mini Git repos |
| `test_examples.py` | Bundled `examples/01_added_methods` snapshot |
| `test_navigation.py` | Flog limit strings / symbol-at helpers |
| `test_report_filtering.py` | Reportable / anonymous filters |

### Failure triage

- **ctags not found** — S02 `universal-ctags` package missing or not on `PATH` as `ctags`.
- **git errors in diff_engine** — git not installed or sandbox permissions (should not happen on `ubuntu-latest`).
- **Import errors** — run `pip install -e ".[dev]"` locally to reproduce.
