# NAO WEB LAB Auto LP Generator

1. Copy `auto-lp.bat` and the `tools` folder into the root of `nao-ai-blog`.
2. Double-click `auto-lp.bat`.
3. Paste one affiliate URL.
4. Claude Code researches the offer, creates an original LP, runs basic checks, commits it, and pushes it to GitHub.
5. The GitHub Pages URL is printed at the end.

The repository must be clean before each run. This prevents unrelated local changes from being included in the automated commit.

Do not put API keys, GitHub tokens, or passwords in these files.
