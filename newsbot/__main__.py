"""Entry point: python -m newsbot [--dry-run]"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .pipeline import run_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UWS Instagram news bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="build captions/graphics but do not publish")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = Config.from_env()
    if args.dry_run:
        cfg.dry_run = True

    count = run_once(cfg)
    logging.getLogger(__name__).info("Run complete: %d post(s) produced", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
