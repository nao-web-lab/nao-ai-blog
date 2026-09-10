$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\")).Path
Set-Location $repoRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " NAO WEB LAB Auto LP Generator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$url = Read-Host "Affiliate URL"
if ([string]::IsNullOrWhiteSpace($url)) {
    throw "No URL was entered."
}

try {
    $uri = [System.Uri]$url
    if ($uri.Scheme -notin @("http","https") -or [string]::IsNullOrWhiteSpace($uri.Host)) {
        throw "Invalid URL."
    }
} catch {
    throw "Please enter a valid http or https URL."
}

$dirty = git status --porcelain
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
if ($slugBase.Length -gt 70) { $slugBase = $slugBase.Substring(0,70).Trim('-') }

$targetDir = Join-Path $repoRoot "lp\auto\$slugBase"
$relativeTarget = "lp/auto/$slugBase"

if (Test-Path $targetDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $slugBase = "$slugBase-$stamp"
    $targetDir = Join-Path $repoRoot "lp\auto\$slugBase"
    $relativeTarget = "lp/auto/$slugBase"
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$promptFile = Join-Path $repoRoot "tools\auto-lp\prompt.md"
$prompt = Get-Content -Raw -Encoding UTF8 $promptFile
$prompt = $prompt.Replace("{{AFFILIATE_URL}}", $url)
$prompt = $prompt.Replace("{{TARGET_DIR}}", $targetDir)
$prompt = $prompt.Replace("{{RELATIVE_TARGET}}", $relativeTarget)

Write-Host ""
Write-Host "Generating the LP..." -ForegroundColor Green
Write-Host "URL: $url"
Write-Host ""

$prompt | claude -p --permission-mode auto --allowedTools "Read" "Glob" "Grep" "Edit" "Write" "WebFetch" "WebSearch"

if ($LASTEXITCODE -ne 0) {
    throw "Claude Code failed to generate the LP."
}

$index = Join-Path $targetDir "index.html"
if (-not (Test-Path $index)) {
    throw "index.html was not generated. Publishing was stopped."
}

Write-Host ""
Write-Host "Running automatic checks..." -ForegroundColor Green

$html = Get-Content -Raw -Encoding UTF8 $index
if ($html -notmatch 'rel="[^"]*(nofollow|sponsored)') {
    throw "Affiliate link rel attribute check failed."
}
if ($html -notmatch 'PR|広告|アフィリエイト') {
    throw "PR disclosure check failed."
}
if ($html -notmatch '<title>') {
    throw "SEO title check failed."
}
if ($html -notmatch 'canonical') {
    throw "Canonical URL check failed."
}

Write-Host "Checks passed." -ForegroundColor Green
Write-Host ""
Write-Host "Publishing to GitHub..." -ForegroundColor Green

git add -- $relativeTarget
if ($LASTEXITCODE -ne 0) { throw "git add failed." }

git commit -m "Add affiliate LP: $slugBase"
if ($LASTEXITCODE -ne 0) { throw "git commit failed." }

git push origin main
if ($LASTEXITCODE -ne 0) { throw "git push failed." }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " PUBLISHED" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "LP URL:"
Write-Host "https://nao-web-lab.github.io/nao-ai-blog/$relativeTarget/" -ForegroundColor Green
Write-Host ""
