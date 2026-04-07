"""Shared yt-dlp helpers for detecting JS runtimes and building commands."""

import shutil


def get_js_runtime_args() -> list[str]:
    """Detect available JS runtimes and return yt-dlp args to use them.

    yt-dlp requires a JS runtime for YouTube. It defaults to deno only,
    but node.js and bun also work. This checks what's installed and
    returns the appropriate --js-runtimes flag.
    """
    runtimes = []
    for name in ("deno", "node", "bun"):
        if shutil.which(name):
            runtimes.append(name)

    if runtimes:
        return ["--js-runtimes", ",".join(runtimes)]
    return []
