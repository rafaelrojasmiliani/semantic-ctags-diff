# Example 01 — Added methods (header + new translation unit)

This example shows a typical merge-request change: a class that initially
only declares a constructor gains three new methods in the header and two
out-of-line definitions in a new `.cpp` file.

## Layout

| Path | Role |
|------|------|
| `old/include/robotics/RobotController.h` | Class shell + constructor declaration only |
| `new/include/robotics/RobotController.h` | Same class + **3 new methods** (`reset`, `configure` declarations + inline `isReady`) |
| `new/src/RobotController.cpp` | **New file** with constructor definition + **2 method bodies** (`reset`, `configure`) |

`reset` and `configure` are declaration-only in the header; ctags reports them via
**file-scope line changes** in the header and as **added functions** once defined in
the `.cpp`. Inline `isReady()` appears as an **added symbol** in the header.

## Expected semantic diff

- **`include/robotics/RobotController.h`** — added symbol for inline `isReady()`;
  file-scope lines for `reset` / `configure` declarations.
- **`src/RobotController.cpp`** — added file with symbols for constructor,
  `reset`, and `configure` definitions.

## Run without Git (directory snapshot)

From the repository root:

```bash
semantic-branch-diff \
  --old-dir examples/01_added_methods/old \
  --new-dir examples/01_added_methods/new \
  --format markdown
```

Python API:

```python
from semantic_branch_diff import semantic_diff

result = semantic_diff(
    old_dir="examples/01_added_methods/old",
    new_dir="examples/01_added_methods/new",
    use_pydriller_methods=False,
)
print(result.summary)
```

## Run with Git (single commit, two paths changed)

The helper script builds a temporary repository: one commit with the `old/`
tree, one commit with the `new/` tree (header modified + cpp added).

```bash
./examples/01_added_methods/run_example.sh
```

That runs:

```bash
semantic-branch-diff --repo <tmpdir> --from HEAD~1 --to HEAD --format markdown
```

## File pairing

Each logical file has an **old** and **new** revision:

- Header: `old/include/.../RobotController.h` ↔ `new/include/.../RobotController.h`
- Source: *(missing)* ↔ `new/src/RobotController.cpp` (treated as **add**)

The engine matches paths relative to the snapshot roots, so both trees use the
same directory layout (`include/`, `src/`).
