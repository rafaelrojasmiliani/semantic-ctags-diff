# GitHub Actions — semantic-branch-diff

Continuous integration for the **Python** library
[`semantic-ctags-diff`](https://github.com/rafaelrojasmiliani/semantic-ctags-diff).

## Inventory

| File | Goal | Methodology | Where used |
|------|------|-------------|------------|
| [`workflows/ci.yml`](workflows/ci.yml) | Guard semantic diff correctness on every change | `ubuntu-latest`: checkout → `git` + `ctags` → editable install → `pytest -v` | **push** / **pull_request** to `main`; badge in [`README.md`](../README.md) |
| [`workflows/README.md`](workflows/README.md) | Maintainer reference for `ci.yml` steps | Maps `S01`–`S03` to commands and test modules | Editing CI or debugging Actions logs |

## Consumed by the Vim plugin

The Vim plugin repo
[`ctags-difftastic-semantic-diff-vim`](https://github.com/rafaelrojasmiliani/ctags-difftastic-semantic-diff-vim)
vendors this project as `submodules/semantic-ctags-diff` and re-runs the same
`pytest` suite in its own CI **plus** Vim headless self-checks. Fixing a failing
test here should be done in this repository first, then the submodule pointer in
the parent repo is updated.

## Badge

Root README shows:

```markdown
[![CI](https://github.com/rafaelrojasmiliani/semantic-ctags-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelrojasmiliani/semantic-ctags-diff/actions/workflows/ci.yml)
```
