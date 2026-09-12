#!/usr/bin/env python3
"""
NAO WEB LAB Auto LP Generator - CI (GitHub Actions) version.

Mirrors tools/auto-lp/generate-and-publish.ps1 but is meant to run
unattended inside a GitHub Actions workflow_dispatch job, triggered
from a phone via the GitHub web UI's Actions tab.

Differences from the PC (PowerShell) version:
- Input is a single-line affiliate URL only (no banner-code paste).
  GitHub's workflow_dispatch form does not reliably support multi-line
  paste, so banner-image LPs are still made from the PC tool.
- Claude Code itself never touches git; this script verifies the
  generated output, then does add/commit/push itself, exactly like
  the PowerShell version.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_BASE_URL = "https://nao-web-lab.github.io/nao-ai-blog"

QUOTE = r'["\']'


class CheckFailed(Exception):
    pass


def fail(message: str) -> "NoReturn":
    raise CheckFailed(message)


def write_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown + "\n")


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        fail(f"Git command failed: git {' '.join(args)}\n{result.stderr}")
    return result.stdout


def compute_slug(uri) -> str:
    base = (uri.netloc + uri.path).lower()
    base = re.sub(r"^www\.", "", base)
    base = re.sub(r"[^a-z0-9]+", "-", base)
    base = base.strip("-")
    if not base:
        base = "affiliate-lp"
    if len(base) > 70:
        base = base[:70].strip("-")
    return base


def main() -> int:
    url = os.environ.get("AFFILIATE_URL", "").strip()
    if not url:
        fail("No URL was entered.")

    uri = urlparse(url)
    if uri.scheme not in ("http", "https") or not uri.netloc:
        fail("Please enter a valid http or https URL.")

    dirty = run_git("status", "--porcelain")
    if dirty.strip():
        fail("The repository has uncommitted changes. Process stopped for safety.")

    slug = compute_slug(uri)
    target_dir = REPO_ROOT / "lp" / "auto" / slug
    relative_target = f"lp/auto/{slug}"
    if target_dir.exists():
        import datetime

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = f"{slug}-{stamp}"
        target_dir = REPO_ROOT / "lp" / "auto" / slug
        relative_target = f"lp/auto/{slug}"
    target_dir.mkdir(parents=True, exist_ok=True)

    public_url = f"{SITE_BASE_URL}/{relative_target}/"
    prompt_file = REPO_ROOT / "tools" / "auto-lp" / "prompt.md"
    prompt = prompt_file.read_text(encoding="utf-8")
    prompt = prompt.replace("{{AFFILIATE_URL}}", url)
    prompt = prompt.replace("{{TARGET_DIR}}", str(target_dir))
    prompt = prompt.replace("{{RELATIVE_TARGET}}", relative_target)
    prompt = prompt.replace("{{PUBLIC_URL}}", public_url)
    prompt = prompt.replace("{{BANNER_IMG_SRC}}", "")
    prompt = prompt.replace("{{BANNER_WIDTH}}", "")
    prompt = prompt.replace("{{BANNER_HEIGHT}}", "")
    prompt = prompt.replace("{{BANNER_ALT}}", "")
    prompt = prompt.replace("{{TRACKING_PIXEL_SRC}}", "")

    print(f"Generating the LP and its local image assets...\nURL: {url}\n")
    result = subprocess.run(
        [
            "claude",
            "-p",
            "--permission-mode",
            "auto",
            "--allowedTools",
            "Read",
            "Glob",
            "Grep",
            "Edit",
            "Write",
            "WebFetch",
            "WebSearch",
        ],
        input=prompt,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        fail("Claude Code failed to generate the LP.")

    required_files = [
        target_dir / "index.html",
        target_dir / "style.css",
        target_dir / "images" / "hero-visual.svg",
        target_dir / "images" / "section-visual.svg",
        target_dir / "images" / "og-image.svg",
    ]
    for f in required_files:
        if not f.is_file():
            fail(f"Required generated file is missing: {f}")

    print("\nRunning automatic checks...")
    index = target_dir / "index.html"
    html = index.read_text(encoding="utf-8")

    cta_re = re.compile(r"(?is)<a\b[^>]*\bhref\s*=\s*" + QUOTE + re.escape(url) + QUOTE + r"[^>]*>")
    ctas = list(cta_re.finditer(html))
    if len(ctas) < 4:
        fail(f"CTA check failed. At least four affiliate CTAs are required; found {len(ctas)}.")
    target_attr_re = re.compile(r"(?i)\btarget\s*=\s*" + QUOTE + "_blank" + QUOTE)
    rel_attr_re = re.compile(r"(?i)\brel\s*=\s*" + QUOTE + r"[^>]*\bnofollow\b[^>]*\bsponsored\b[^>]*" + QUOTE)
    for m in ctas:
        tag = m.group(0)
        if not target_attr_re.search(tag):
            fail("Affiliate CTA target check failed.")
        if not rel_attr_re.search(tag):
            fail("Affiliate CTA rel attribute check failed.")

    if not re.search(r"PR|広告|アフィリエイト", html):
        fail("PR disclosure check failed.")
    if not re.search(r"(?is)<title>[^<]+</title>", html):
        fail("SEO title check failed.")

    expected_canonical = f'<link rel="canonical" href="{public_url}"'
    if expected_canonical not in html:
        fail("Canonical URL check failed.")
    if 'name="viewport"' not in html:
        fail("Responsive viewport metadata check failed.")

    expected_og_image = f"{public_url}images/og-image.svg"
    if 'property="og:image"' not in html or expected_og_image not in html:
        fail("OGP image check failed.")
    if 'name="twitter:card" content="summary_large_image"' not in html:
        fail("Twitter card check failed.")

    local_img_re = re.compile(r"(?is)<img\b[^>]*\bsrc\s*=\s*" + QUOTE + r"images/[^\"']*" + QUOTE + r"[^>]*>")
    if len(local_img_re.findall(html)) < 2:
        fail("Local image placement check failed. At least two local images are required.")

    # No banner input is accepted from the phone flow, so no remote image
    # (other than none) is ever allowed here.
    remote_re = re.compile(r"(?is)<(?:img|source)\b[^>]*\bsrc\s*=\s*" + QUOTE + r"(https?://[^\"']*)" + QUOTE)
    for m in remote_re.finditer(html):
        fail(f"Remote image check failed. Unexpected remote src: {m.group(1)}")

    for svg_path in [f for f in required_files if f.suffix == ".svg"]:
        svg_content = svg_path.read_text(encoding="utf-8")
        if not re.match(r"(?is)^\s*<svg\b", svg_content) or re.search(r"(?i)<script\b", svg_content):
            fail(f"Generated SVG safety check failed: {svg_path}")

    diff_names = run_git("diff", "--name-only").splitlines()
    untracked = run_git("ls-files", "--others", "--exclude-standard").splitlines()
    changed = sorted({f for f in diff_names + untracked if f})
    for changed_file in changed:
        normalized = changed_file.replace("\\", "/")
        if not normalized.startswith(relative_target + "/"):
            fail(f"Safety check failed: generation changed a file outside {relative_target}: {changed_file}")
    if not changed:
        fail("No generated files were detected. Publishing was stopped.")

    print("Checks passed.\n\nPublishing to GitHub...")
    run_git("add", "--", relative_target)
    run_git("commit", "-m", f"Add affiliate LP: {slug} (via GitHub Actions)")
    run_git("push", "origin", "HEAD:main")

    print(f"\nPUBLISHED\nLP URL:\n{public_url}\n")
    write_summary(f"## ✅ 公開しました\n\n**LP URL:** {public_url}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckFailed as e:
        print(f"ERROR: {e}", file=sys.stderr)
        write_summary(f"## ❌ 失敗しました\n\n{e}\n")
        sys.exit(1)
