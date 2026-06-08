"""Command-line interface for reddit2shorts.

This module provides the CLI for running the Reddit2Shorts workflow.
All commands are automatically generated from OrchestratorRegistry via CLICommandFactory.
"""

import click

from reddit2shorts.cli_factory import CLICommandFactory


@click.group()
def cli():
    """Reddit2Shorts - Automated video creation from Reddit stories and images."""
    pass


# ============================================================================
# AUTOMATIC COMMAND REGISTRATION
# ============================================================================
# All commands are automatically generated from OrchestratorRegistry
# No need to manually create @cli.command() functions!
#
# This replaces ~600 lines of duplicated code with automatic generation.
# ============================================================================

CLICommandFactory.register_all_commands(cli)


def main():
    """Main entry point"""
    cli()


if __name__ == '__main__':
    main()
