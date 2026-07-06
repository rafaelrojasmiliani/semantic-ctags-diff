#!/usr/bin/env bash
# Build a two-commit Git repo from old/ and new/ snapshots, then run semantic-diff.
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$EXAMPLE_DIR/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$WORK" init -q
git -C "$WORK" config user.email "example@semantic-diff.local"
git -C "$WORK" config user.name "Example User"

# Commit 1: old snapshot (header only).
mkdir -p "$WORK/include/robotics"
cp "$EXAMPLE_DIR/old/include/robotics/RobotController.h" "$WORK/include/robotics/"
git -C "$WORK" add -A
git -C "$WORK" commit -q -m "Initial RobotController shell"

# Commit 2: new snapshot (extended header + new cpp).
cp "$EXAMPLE_DIR/new/include/robotics/RobotController.h" "$WORK/include/robotics/"
mkdir -p "$WORK/src"
cp "$EXAMPLE_DIR/new/src/RobotController.cpp" "$WORK/src/"
git -C "$WORK" add -A
git -C "$WORK" commit -q -m "Add reset/configure API and RobotController.cpp"

echo "=== Directory snapshot mode (no Git) ==="
semantic-branch-diff \
  --old-dir "$EXAMPLE_DIR/old" \
  --new-dir "$EXAMPLE_DIR/new" \
  --no-pydriller-methods \
  --format markdown

echo ""
echo "=== Git commit mode (HEAD~1..HEAD) ==="
semantic-branch-diff \
  --repo "$WORK" \
  --from HEAD~1 \
  --to HEAD \
  --no-pydriller-methods \
  --format markdown
