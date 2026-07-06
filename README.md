# semantic-branch-diff

Semantic branch diffs for C++ repositories using Universal Ctags and PyDriller.

## Install

```bash
pip install -e ".[dev]"
```

## CLI

```bash
semantic-branch-diff --repo . --base main --head HEAD --format markdown
```

## Python API

```python
from semantic_branch_diff import semantic_diff

result = semantic_diff(repo="/path/to/repo", base="main", head="HEAD")
print(result.to_dict())
```
