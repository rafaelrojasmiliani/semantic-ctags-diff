# semantic-branch-diff

Ctags-powered **semantic diffs** for code review: symbols added, removed, and
modified — not just changed line numbers. Works with **branches** (merge-request
style), **commits**, or **directory snapshots** (no Git required).

## How it works: ctags line ranges

The semantic diff is **not** an AST diff. It is built on two layers:

1. **Git** reports which files and line numbers changed between two refs.
2. **ctags** reports each symbol’s **start line**, **end line** (when available),
   **kind** (function, class, method, …), and **name/scope**.

Each changed line is mapped to the **innermost enclosing symbol** (a method beats
its class; a class beats its namespace). Symbols are then classified as added,
removed, modified, or file-scope (lines outside any tag range).

This uses a **classic ctags tags file** (`-f tags` + `python-ctags3`). Ctags JSON
output is **not** used or required.

### Example

**Old** header — constructor only:

```cpp
class RobotController {
public:
  RobotController();   // lines 4–4
};
```

**New** header — two methods added:

```cpp
class RobotController {
public:
  RobotController();
  void reset();              // lines 6–6   ← ctags: function, line 6
  void configure(double);    // lines 7–7   ← ctags: function, line 7
};
```

**New** source file:

```cpp
void RobotController::configure(double x) {  // ctags: lines 12–15
  m_gain = x;
}
```

Running a snapshot diff reports **added symbols** by name, not just “lines 6–7
changed”:

```text
Added symbols
=============

Functions:
  + ImFusion::Robotics::RobotController::configure
  + ImFusion::Robotics::RobotController::reset
  + ImFusion::Robotics::RobotController::isReady
```

If you edit line 13 inside `configure()`, Git sees one changed line; ctags knows
that line 13 ∈ `configure` (range 12–15), so the report says **modified function
`configure`**, not merely “line 13 changed”.

Try it:

```bash
semantic-branch-diff \
  --old-dir examples/01_added_methods/old \
  --new-dir examples/01_added_methods/new \
  --format markdown
```

**Limits:** regions ctags cannot tag (some macros, templates, unsupported
extensions) appear as **file-scope** changes or are skipped. Exuberant ctags may
omit `end` lines; the tool estimates function ends from `{`/`}`.

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

## Vim (vim-semantic-ctags-diff plugin)

When used from the Vim plugin, **no pip install of this package** is required.
The plugin runs:

```bash
PYTHONPATH=submodules/semantic-ctags-diff python3 -m semantic_branch_diff.cli ...
```

You still need **PyDriller** and **python-ctags3** importable by that Python.

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
