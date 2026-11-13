"""CLI do uploadu przez UI Studio — wygodne do wpięcia z n8n (SSH Execute Command).

Przykład:
    python examples/upload_example.py \
        --file /mnt/AMPStorage/apps/clippyme/output/<job>/clip_1.mp4 \
        --title "GTA VI scene is insane #shorts" \
        --desc "Clipped with ClippyMe\n#shorts" \
        --tags "gta6,shorts" --privacy public --headed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from youtube_browser_upload import setup_logging, upload_to_youtube


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload wideo na YouTube przez Studio (Playwright)")
    parser.add_argument("--file", required=True, help="ścieżka do pliku wideo")
    parser.add_argument("--title", required=True)
    parser.add_argument("--desc", default="", help="opis (\\n = nowa linia)")
    parser.add_argument("--tags", default="", help="tagi rozdzielone przecinkami")
    parser.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    parser.add_argument("--thumb", default=None, help="opcjonalna miniatura (jpg/png)")
    parser.add_argument("--headed", action="store_true", help="widoczne okno (debug / re-login)")
    parser.add_argument(
        "--profile",
        default="/mnt/AMPStorage/apps/yt-upload-profile",
        help="katalog trwałego profilu sesji",
    )
    parser.add_argument(
        "--publish-timeout-min", type=int, default=45,
        help="maks. oczekiwanie na upload+processing (min)",
    )
    args = parser.parse_args()

    setup_logging()
    result = upload_to_youtube(
        video_path=args.file,
        title=args.title,
        description=args.desc.replace("\\n", "\n"),
        tags=args.tags,
        privacy=args.privacy,
        thumbnail_path=args.thumb,
        headless=not args.headed,
        profile_dir=args.profile,
        publish_timeout_ms=args.publish_timeout_min * 60_000,
    )
    # JSON na stdout → parsowalny przez n8n (logi lecą na stderr, nie brudzą)
    print(json.dumps({
        "video_id": result.video_id,
        "url": result.url,
        "title": result.title,
        "privacy": result.privacy,
        "video_path": result.video_path,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
