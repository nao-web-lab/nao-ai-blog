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

$doubleQuote = [char]34
$singleQuote = [char]39
$quoteClass = '[' + $doubleQuote + $singleQuote + ']'
$notQuoteClass = '[^' + $doubleQuote + $singleQuote + ']'

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " NAO WEB LAB Auto LP Generator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$rawInput = Read-Host "Affiliate URL (or paste one ASP banner code block)"
if ([string]::IsNullOrWhiteSpace($rawInput)) { throw "No URL or banner code was entered." }

$bannerImgSrc = ""
$bannerWidth = ""
$bannerHeight = ""
$bannerAlt = ""
$trackingPixelSrc = ""

if ($rawInput -match '(?i)<img') {
    Write-Host ""
    Write-Host "Banner code detected. Parsing the link and image..." -ForegroundColor Green

    $anchorWithImgPattern = '(?is)<a\b[^>]*\bhref\s*=\s*' + $quoteClass + '(' + $notQuoteClass + '+)' + $quoteClass + '[^>]*>(.*?)</a>'
    $anchorMatches = [regex]::Matches($rawInput, $anchorWithImgPattern)
    $chosenHref = $null
    $chosenInner = ""
    foreach ($am in $anchorMatches) {
        if ($am.Groups[2].Value -match '(?i)<img') {
            $chosenHref = $am.Groups[1].Value
            $chosenInner = $am.Groups[2].Value
            break
        }
    }
    if (-not $chosenHref) {
        $firstAnchor = [regex]::Match($rawInput, '(?is)<a\b[^>]*\bhref\s*=\s*' + $quoteClass + '(' + $notQuoteClass + '+)' + $quoteClass)
        if (-not $firstAnchor.Success) { throw "Banner code was detected, but no <a href=...> link was found. Please paste the full banner code, including the <a> link tag." }
        $chosenHref = $firstAnchor.Groups[1].Value
        $chosenInner = ""
    }
    $url = $chosenHref

    $imgTagPattern = '(?is)<img\b[^>]*>'
    $srcPattern = '(?is)\bsrc\s*=\s*' + $quoteClass + '(' + $notQuoteClass + '+)' + $quoteClass
    $widthPattern = '(?i)\bwidth\s*=\s*' + $quoteClass + '?(\d+)' + $quoteClass + '?'
    $heightPattern = '(?i)\bheight\s*=\s*' + $quoteClass + '?(\d+)' + $quoteClass + '?'
    $altPattern = '(?is)\balt\s*=\s*' + $quoteClass + '(' + $notQuoteClass + '*)' + $quoteClass

    $bannerTagMatch = [regex]::Matches($chosenInner, $imgTagPattern) | Select-Object -First 1
    if ($bannerTagMatch) {
        $tagText = $bannerTagMatch.Value
        $srcMatch = [regex]::Match($tagText, $srcPattern)
        if ($srcMatch.Success) {
            $bannerImgSrc = $srcMatch.Groups[1].Value
            $widthMatch = [regex]::Match($tagText, $widthPattern)
            $heightMatch = [regex]::Match($tagText, $heightPattern)
            $altMatch = [regex]::Match($tagText, $altPattern)
            if ($widthMatch.Success) { $bannerWidth = $widthMatch.Groups[1].Value }
            if ($heightMatch.Success) { $bannerHeight = $heightMatch.Groups[1].Value }
            if ($altMatch.Success) { $bannerAlt = $altMatch.Groups[1].Value }
        }
    }

    $allImgTags = [regex]::Matches($rawInput, $imgTagPattern)
    foreach ($tag in $allImgTags) {
        $tagText = $tag.Value
        $widthMatch = [regex]::Match($tagText, $widthPattern)
        $heightMatch = [regex]::Match($tagText, $heightPattern)
        $isPixel = $widthMatch.Success -and $heightMatch.Success -and $widthMatch.Groups[1].Value -eq "1" -and $heightMatch.Groups[1].Value -eq "1"
        if ($isPixel) {
            $srcMatch = [regex]::Match($tagText, $srcPattern)
            if ($srcMatch.Success) { $trackingPixelSrc = $srcMatch.Groups[1].Value }
            break
        }
    }

    if ($bannerImgSrc) {
        Write-Host "Banner image: $bannerImgSrc ($bannerWidth x $bannerHeight)"
    } else {
        Write-Host "No banner image found in the pasted code (text-only link?). Continuing with SVG illustrations only."
    }
    if ($trackingPixelSrc) { Write-Host "Tracking pixel: $trackingPixelSrc" }
} else {
    $url = $rawInput.Trim()
}

try {
    $uri = [System.Uri]$url
    if ($uri.Scheme -notin @("http", "https") -or [string]::IsNullOrWhiteSpace($uri.Host)) { throw "Invalid URL." }
} catch { throw "Please enter a valid http or https URL (or a banner code containing one)." }

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
$prompt = $prompt.Replace("{{BANNER_IMG_SRC}}", $bannerImgSrc)
$prompt = $prompt.Replace("{{BANNER_WIDTH}}", $bannerWidth)
$prompt = $prompt.Replace("{{BANNER_HEIGHT}}", $bannerHeight)
$prompt = $prompt.Replace("{{BANNER_ALT}}", $bannerAlt)
$prompt = $prompt.Replace("{{TRACKING_PIXEL_SRC}}", $trackingPixelSrc)

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
$expectedOgImage = "${publicUrl}images/og-image.svg"
$expectedOgMeta = 'property="og:image" content="' + $expectedOgImage + '"'
if ($html -notmatch 'property="og:image"' -or $html -notmatch [regex]::Escape($expectedOgImage)) { throw "OGP image check failed." }
if ($html -notmatch 'name="twitter:card" content="summary_large_image"') { throw "Twitter card check failed." }
$localImagePattern = '(?is)<img\b[^>]*\bsrc\s*=\s*' + $quoteClass + 'images/[^>]*' + $quoteClass + '[^>]*>'
if ([regex]::Matches($html, $localImagePattern).Count -lt 2) { throw "Local image placement check failed. At least two local images are required." }

$allowedRemoteSrcs = @()
if ($bannerImgSrc) { $allowedRemoteSrcs += $bannerImgSrc }
if ($trackingPixelSrc) { $allowedRemoteSrcs += $trackingPixelSrc }
$remoteSrcPattern = '(?is)<(?:img|source)\b[^>]*\bsrc\s*=\s*' + $quoteClass + '(https?://' + $notQuoteClass + '*)' + $quoteClass
$remoteMatches = [regex]::Matches($html, $remoteSrcPattern)
foreach ($rm in $remoteMatches) {
    $foundSrc = $rm.Groups[1].Value
    if ($allowedRemoteSrcs -notcontains $foundSrc) {
        throw "Remote image check failed. LP images must be local assets or the exact supplied banner/tracking image. Unexpected remote src: $foundSrc"
    }
}
if ($bannerImgSrc -and $html -notmatch [regex]::Escape($bannerImgSrc)) { throw "Banner image check failed. The supplied banner image was not found in the generated page." }
if ($trackingPixelSrc -and $html -notmatch [regex]::Escape($trackingPixelSrc)) { throw "Tracking pixel check failed. The supplied tracking pixel was not found in the generated page." }

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
