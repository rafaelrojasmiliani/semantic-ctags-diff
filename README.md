# semantic-branch-diff

Ctags-powered **semantic diffs** for code review: symbols added, removed, and
modified — not just changed line numbers. Works with **branches** (merge-request
style), **commits**, or **directory snapshots** (no Git required).

## Install

```bash
pip install -e ".[dev]"
```

Requires [Universal Ctags](https://github.com/universal-ctags/ctags) (or
Exuberant Ctags with reduced C++ metadata).

## Comparison modes

### Merge request / branch (default)

Compares `merge-base(base, head)..head` — same as a typical PR:

```bash
semantic-branch-diff --repo . --base main --head feature --format markdown
```

### Commit to commit

```bash
semantic-branch-diff --repo . --from abc1234 --to def5678 --format markdown
```

### Directory snapshots (no Git)

Compare `old/` and `new/` folder trees — ideal for examples and local experiments:

```bash
semantic-branch-diff \
  --old-dir examples/01_added_methods/old \
  --new-dir examples/01_added_methods/new \
  --format markdown
```

## Python API

```python
from semantic_branch_diff import semantic_diff

# Branch / MR
result = semantic_diff(repo="/path/to/repo", base="main", head="HEAD")

# Commits
result = semantic_diff(repo="/path/to/repo", from_ref="HEAD~1", to_ref="HEAD")

# Directory snapshots
result = semantic_diff(
    old_dir="examples/01_added_methods/old",
    new_dir="examples/01_added_methods/new",
)
print(result.to_dict())
```

## Examples

| Example | Description |
|---------|-------------|
| [01_added_methods](examples/01_added_methods/) | Class with constructor only → header gains **3 methods**, new `.cpp` with **2 bodies** |

### Example 01 — Added methods

**Old** (`examples/01_added_methods/old/`):

- `include/robotics/RobotController.h` — class + constructor declaration only

**New** (`examples/01_added_methods/new/`):

- `include/robotics/RobotController.h` — adds `reset()`, `configure(double)`, inline `isReady()`
- `src/RobotController.cpp` — **new file** with constructor + `reset` / `configure` definitions

Run the snapshot diff:

```bash
semantic-branch-diff \
  --old-dir examples/01_added_methods/old \
  --new-dir examples/01_added_methods/new \
  --no-pydriller-methods \
  --format markdown
```

Or build a two-commit Git repo and diff `HEAD~1..HEAD`:

```bash
./examples/01_added_methods/run_example.sh
```

See [examples/01_added_methods/README.md](examples/01_added_methods/README.md) for
expected output and file layout.

## Vim

```vim
:read !semantic-branch-diff --repo . --base main --head HEAD --format markdown
```

Debug logs go to **stderr**; stdout is only the report.

### Symbol at cursor (Flog integration)

Resolve the enclosing ctags symbol at a line — used by vim-semantic-ctags-diff
`:Flogsplit*` commands. Uses **classic ctags tags output**, not ctags JSON:

```bash
semantic-branch-diff --symbol-at --file src/foo.cpp --line 42 --kind function
```

JSON includes `flog_limit` (`start,end:path`), `label`, and `symbol`.

Branch-diff JSON also includes a top-level `navigation` list (modified symbols
with `flog_limit`) for `:SemanticCtagsDiffFlogSymbol`.

### Python navigation API

```python
from semantic_branch_diff.navigation import (
    collect_navigation_choices,
    flog_line_limit,
    symbol_at_source,
)

limit = flog_line_limit("src/foo.cpp", 10, 50)  # "10,50:src/foo.cpp"
```

Ctags requirements: [Universal Ctags](https://github.com/universal-ctags/ctags)
or Exuberant Ctags. **JSON output format is not used or required.**
