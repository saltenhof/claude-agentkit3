"""Failure-corpus CLI delegation commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def _setup_failure_corpus_subparsers(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``failure-corpus`` command and its sub-subcommands.

    Called from ``main()`` to wire all six AG3-078 subcommands into the CLI.
    The actual registration is delegated to the thin CLI adapter.

    Args:
        subparsers: The top-level subparsers action from the main parser.
    """
    from agentkit.backend.failure_corpus.cli import register_subparsers as _fc_register

    fc_parser = subparsers.add_parser(
        "failure-corpus",
        help="Failure-corpus commands (FK-41 §41.9, AG3-078)",
    )
    fc_subparsers = fc_parser.add_subparsers(dest="fc_command")
    _fc_register(fc_subparsers)


def _cmd_failure_corpus(args: argparse.Namespace) -> int:
    """Handle ``agentkit failure-corpus`` subcommands (FK-41 §41.9, AG3-078).

    Delegates to the thin CLI adapter in ``agentkit.backend.failure_corpus.cli``.

    Args:
        args: Parsed CLI arguments with ``fc_command`` attribute set by
            the ``failure-corpus`` subparser.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.failure_corpus.cli import dispatch as _fc_dispatch

    return _fc_dispatch(args)


