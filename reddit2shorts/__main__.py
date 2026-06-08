"""
Entry point for running reddit2shorts as a module.

Usage:
    python -m reddit2shorts reddit --num-videos 1
    python -m reddit2shorts knights --num-videos 1
    python -m reddit2shorts darkmotiv --num-videos 1
"""

from reddit2shorts.cli import cli

if __name__ == "__main__":
    cli()
