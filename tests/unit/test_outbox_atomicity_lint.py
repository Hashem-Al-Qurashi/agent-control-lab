"""The outbox's atomicity is a STRUCTURAL property, so it is checked structurally.

A behavioural test cannot catch this. Moving publish() outside the effect's
transaction still passes every functional test, because in the happy path both
commits succeed and the row counts match. It only diverges when something fails
between the two commits -- and at that point the event is already lost.

Verified: that exact mutation passed all 9 outbox tests before this lint existed.

So the check is lexical and structural: publish() must be called with the same
cursor that performed the INSERT, inside the same `with connect()` block, before
that block's commit. Same reasoning as agents/diligent/purity.py -- when the
failure is silent, a lint beats a convention.
"""

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TARGETS = [
    ("apps/billing/main.py", "create_refund"),
    ("apps/ledger/main.py", "create_credit"),
]


def _function(path, name):
    tree = ast.parse((REPO / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def _with_block_containing(func, call_name):
    """The `with` statement whose body contains a call to call_name."""
    for node in ast.walk(func):
        if isinstance(node, ast.With):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == call_name
                ):
                    return node
    return None


@pytest.mark.parametrize("path,func_name", TARGETS)
def test_publish_shares_the_effects_transaction(path, func_name):
    func = _function(path, func_name)

    with_block = _with_block_containing(func, "publish")
    assert with_block is not None, f"{path}:{func_name} does not call publish()"

    # The same with-block must open the connection that performs the write.
    opens_connection = any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "connect"
        for item in with_block.items
    )
    assert opens_connection, (
        f"{path}:{func_name} calls publish() outside the `with connect()` block "
        "that performs the write. The event could then commit without the effect, "
        "making propagation lag a harness bug rather than a real property."
    )


@pytest.mark.parametrize("path,func_name", TARGETS)
def test_publish_receives_the_same_cursor(path, func_name):
    func = _function(path, func_name)
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "publish"
        ):
            assert node.args, "publish() called without a cursor"
            first = node.args[0]
            assert isinstance(first, ast.Name) and first.id == "cur", (
                f"{path}:{func_name} passes {ast.dump(first)} to publish() "
                "instead of the cursor `cur` used for the INSERT. A different "
                "cursor means a different transaction."
            )
            return
    raise AssertionError(f"{path}:{func_name} never calls publish()")


@pytest.mark.parametrize("path,func_name", TARGETS)
def test_publish_precedes_the_commit(path, func_name):
    func = _function(path, func_name)
    publish_line = next(
        n.lineno for n in ast.walk(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "publish"
    )
    commit_lines = [
        n.lineno for n in ast.walk(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "commit"
    ]
    assert commit_lines, "no commit found"
    assert publish_line < min(commit_lines), (
        f"{path}:{func_name} publishes after committing. The effect would be "
        "durable while the event was not."
    )
