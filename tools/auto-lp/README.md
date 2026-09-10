# NAO WEB LAB Auto LP Generator

1. Copy `auto-lp.bat` and the `tools` folder into the root of `nao-ai-blog`.
2. Double-click `auto-lp.bat`.
3. Paste one affiliate URL.
4. Claude Code researches the offer, creates an original LP with local, original SVG visual assets, runs checks, commits it, and pushes it to GitHub.
5. The GitHub Pages URL is printed at the end.

The repository must be clean before each run. This prevents unrelated local changes from being included in the automated commit.

Do not put API keys, GitHub tokens, or passwords in these files.

## Image handling

Every generated LP includes three self-contained SVG assets: a hero visual, a supporting section visual, and an OGP image. This avoids hotlinking, unlicensed stock images, and any dependence on an image-generation API key. The generator verifies that those assets exist, are locally referenced, and do not contain scripts before publishing.

If a licensed or user-owned photograph is later added, it should be placed inside that LP's `images/` directory and referenced locally. Do not add credentials to this tool to fetch or generate images.
