$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$siteBaseUrl = "https://nao-web-lab.github.io/nao-ai-blog"
Set-Location $repoRoot

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git -c "safe.directory=$repoRoot" @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git command failed: git $($Arguments -join ' ')" }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git was not found. Install Git and run this tool again." }
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw "Claude Code CLI was not found. Install/sign in to Claude Code and run this tool again." }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " NAO WEB LAB Auto LP Generator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$url = Read-Host "Affiliate URL"
if ([string]::IsNullOrWhiteSpace($url)) { throw "No URL was entered." }
try {
    $uri = [System.Uri]$url
    if ($uri.Scheme -notin @("http", "https") -or [string]::IsNullOrWhiteSpace($uri.Host)) { throw "Invalid URL." }
} catch { throw "Please enter a valid http or https URL." }

$dirty = Invoke-Git status --porcelain
if ($dirty) {
    Write-Host ""
    Write-Host "The repository has uncommitted changes. Process stopped for safety." -ForegroundColor Yellow
    Write-Host "Please commit or stash the existing changes first."
    exit 1
}

$slugBase = ($uri.Host + $uri.AbsolutePath).ToLower()
$slugBase = $slugBase -replace '^www\.', ''
$slugBase = $slugBase -replace '[^a-z0-9]+', '-'
$slugBase = $slugBase.Trim('-')
if ([string]::IsNullOrWhiteSpace($slugBase)) { $slugBase = "affiliate-lp" }
if ($slugBase.Length -gt 70) { $slugBase = $slugBase.Substring(0, 70).Trim('-') }

$targetDir = Join-Path $repoRoot "lp\auto\$slugBase"
$relativeTarget = "lp/auto/$slugBase"
if (Test-Path -LiteralPath $targetDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $slugBase = "$slugBase-$stamp"
    $targetDir = Join-Path $repoRoot "lp\auto\$slugBase"
    $relativeTarget = "lp/auto/$slugBase"
}
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$publicUrl = "$siteBaseUrl/$relativeTarget/"
$promptFile = Join-Path $repoRoot "tools\auto-lp\prompt.md"
$prompt = Get-Content -Raw -Encoding UTF8 $promptFile
$prompt = $prompt.Replace("{{AFFILIATE_URL}}", $url)
$prompt = $prompt.Replace("{{TARGET_DIR}}", $targetDir)
$prompt = $prompt.Replace("{{RELATIVE_TARGET}}", $relativeTarget)
$prompt = $prompt.Replace("{{PUBLIC_URL}}", $publicUrl)

Write-Host ""
Write-Host "Generating the LP and its local image assets..." -ForegroundColor Green
Write-Host "URL: $url"
Write-Host ""
$prompt | claude -p --permission-mode auto --allowedTools "Read" "Glob" "Grep" "Edit" "Write" "WebFetch" "WebSearch"
if ($LASTEXITCODE -ne 0) { throw "Claude Code failed to generate the LP." }

$requiredFiles = @(
    (Join-Path $targetDir "index.html"),
    (Join-Path $targetDir "style.css"),
    (Join-Path $targetDir "images\hero-visual.svg"),
    (Join-Path $targetDir "images\section-visual.svg"),
    (Join-Path $targetDir "images\og-image.svg")
)
foreach ($file in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required generated file is missing: $file" }
}

Write-Host ""
Write-Host "Running automatic checks..." -ForegroundColor Green
$index = Join-Path $targetDir "index.html"
$html = Get-Content -Raw -Encoding UTF8 $index
$affiliatePattern = [regex]::Escape($url)
$doubleQuote = [char]34
$singleQuote = [char]39
$quoteClass = '[' + $doubleQuote + $singleQuote + ']'
$ctaPattern = '(?is)<a\b[^>]*\bhref\s*=\s*' + $quoteClass + $affiliatePattern + $quoteClass + '[^>]*>'
$ctaMatches = [regex]::Matches($html, $ctaPattern)
if ($ctaMatches.Count -lt 4) { throw "CTA check failed. At least four affiliate CTAs are required; found $($ctaMatches.Count)." }
foreach ($cta in $ctaMatches) {
    $targetPattern = '(?i)\btarget\s*=\s*' + $quoteClass + '_blank' + $quoteClass
    $relPattern = '(?i)\brel\s*=\s*' + $quoteClass + '[^>]*\bnofollow\b[^>]*\bsponsored\b[^>]*' + $quoteClass
    if ($cta.Value -notmatch $targetPattern) { throw "Affiliate CTA target check failed." }
    if ($cta.Value -notmatch $relPattern) { throw "Affiliate CTA rel attribute check failed." }
}
if ($html -notmatch 'PR|広告|アフィリエイト') { throw "PR disclosure check failed." }
if ($html -notmatch '(?is)<title>[^<]+</title>') { throw "SEO title check failed." }
$expectedCanonical = '<link rel="canonical" href="' + $publicUrl + '"'
if ($html -notmatch [regex]::Escape($expectedCanonical)) { throw "Canonical URL check failed." }
if ($html -notmatch 'name="viewport"') { throw "Responsive viewport metadata check failed." }
$expectedOgImage = "$publicUrl/images/og-image.svg"
$expectedOgMeta = 'property="og:image" content="' + $expectedOgImage + '"'
if ($html -notmatch [regex]::Escape($expectedOgMeta)) { throw "OGP image check failed." }
if ($html -notmatch 'name="twitter:card" content="summary_large_image"') { throw "Twitter card check failed." }
$localImagePattern = '(?is)<img\b[^>]*\bsrc\s*=\s*' + $quoteClass + 'images/[^>]*' + $quoteClass + '[^>]*>'
if ([regex]::Matches($html, $localImagePattern).Count -lt 2) { throw "Local image placement check failed. At least two local images are required." }
$remoteImagePattern = '(?i)<(?:img|source)\b[^>]*\bsrc\s*=\s*' + $quoteClass + 'https?://'
if ($html -match $remoteImagePattern) { throw "Remote image check failed. LP images must be local assets." }
foreach ($svg in $requiredFiles | Where-Object { $_ -like '*.svg' }) {
    $svgContent = Get-Content -Raw -Encoding UTF8 $svg
    if ($svgContent -notmatch '(?is)^\s*<svg\b' -or $svgContent -match '(?i)<script\b') { throw "Generated SVG safety check failed: $svg" }
}

$changedFiles = @()
$changedFiles += Invoke-Git diff --name-only
$changedFiles += Invoke-Git ls-files --others --exclude-standard
$changedFiles = $changedFiles | Where-Object { $_ } | Sort-Object -Unique
foreach ($changedFile in $changedFiles) {
    $normalized = $changedFile.Replace('\', '/')
    if (-not $normalized.StartsWith("$relativeTarget/")) { throw "Safety check failed: generation changed a file outside ${relativeTarget}: $changedFile" }
}
if ($changedFiles.Count -eq 0) { throw "No generated files were detected. Publishing was stopped." }

Write-Host "Checks passed." -ForegroundColor Green
Write-Host ""
Write-Host "Publishing to GitHub..." -ForegroundColor Green
Invoke-Git add -- $relativeTarget
Invoke-Git commit -m "Add affiliate LP: $slugBase"
Invoke-Git push origin main

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " PUBLISHED" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "LP URL:"
Write-Host $publicUrl -ForegroundColor Green
Write-Host ""
