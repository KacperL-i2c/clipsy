"""Pierwsze logowanie — otwiera widoczne okno Chromium i czeka na login+2FA.

Profil sesji zapisuje się na dysku; kolejne uploady mogą być headless.
Na homelabie: odpal przy pulpicie GNOME albo przez `xvfb-run -a` (zob. README).

Użycie:
    python examples/first_login.py [--profile /ścieżka/do/profilu]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Umożliwia odpalenie examples/ bez instalacji pakietu
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from youtube_browser_upload import login_interactive, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Pierwsze logowanie do YouTube (profil sesji)")
    parser.add_argument(
        "--profile",
        default="/mnt/AMPStorage/apps/yt-upload-profile",
        help="katalog trwałego profilu (default: AMPStorage — przeżywa restarty)",
    )
    parser.add_argument("--wait-minutes", type=int, default=15)
    args = parser.parse_args()

    setup_logging()
    ok = login_interactive(args.profile, wait_minutes=args.wait_minutes)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
