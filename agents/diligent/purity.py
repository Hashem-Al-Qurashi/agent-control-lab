"""Lint enforcing that the agent entrypoint is safe to run in a pooled process.

One pre-warmed interpreter serves many cases. Anything captured at import time
persists across every case that interpreter handles, so:

  * module-level mutable state leaks results between cases
  * import-time environment reads freeze configuration from whichever case
    happened to be first

Either produces a run that cannot be reproduced, which in a determinism harness
is indistinguishable from a real finding and far more damaging.

A lint rather than a convention, because the failure is silent.
"""

from __future__ import annotations

import ast
import pathlib

MUTABLE_LITERALS = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)
ENV_NAMES = {"environ", "getenv"}


class PurityViolation(Exception):
    """The module would leak state between cases sharing an interpreter."""


def _is_env_read(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in ENV_NAMES:
            return True
        if isinstance(sub, ast.Name) and sub.id in ENV_NAMES:
            return True
    return False


def check_module_purity(path: pathlib.Path | str) -> None:
    path = pathlib.Path(path)
    tree = ast.parse(path.read_text(), filename=str(path))

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue

            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            names = [t.id for t in targets if isinstance(t, ast.Name)]

            if _is_env_read(value):
                raise PurityViolation(
                    f"{path.name}: {names or '<assignment>'} reads os.environ at "
                    "import time; read configuration at call time instead"
                )

            if isinstance(value, MUTABLE_LITERALS):
                raise PurityViolation(
                    f"{path.name}: {names or '<assignment>'} is module-level "
                    "mutable state; it would leak between cases sharing a "
                    "pooled interpreter"
                )

        if isinstance(node, ast.Expr) and _is_env_read(node):
            raise PurityViolation(
                f"{path.name}: reads os.environ at import time"
            )
