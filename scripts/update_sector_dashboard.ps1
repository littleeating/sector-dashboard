$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Script = Join-Path $Root "sector_dashboard.py"
$KlineScript = Join-Path $Root "fetch_kline_snapshots.py"
$OutputDir = Join-Path $Root "output\sector_dashboard"
$Output = Join-Path $OutputDir "index.html"
$KlineDir = Join-Path $OutputDir "data\kline"

Set-Location $Root

function Write-Step {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Ensure-PythonDependencies {
    $check = @"
import importlib.util
import sys
missing = [name for name in ("akshare", "requests", "pandas") if importlib.util.find_spec(name) is None]
if missing:
    print(",".join(missing))
    sys.exit(1)
"@
    & $Python -c $check
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Installing missing Python dependencies."
        & $Python -m pip install --disable-pip-version-check akshare requests pandas openpyxl lxml html5lib
    }
}

function Assert-DashboardOutput {
    if (-not (Test-Path -LiteralPath $Output)) {
        throw "Dashboard HTML was not generated: $Output"
    }
    if (-not (Test-Path -LiteralPath $KlineDir)) {
        throw "K-line directory was not generated: $KlineDir"
    }
    $validator = @"
import json
import pathlib
import re
import sys

html_path = pathlib.Path(r"$Output")
kline_dir = pathlib.Path(r"$KlineDir")
html = html_path.read_text(encoding="utf-8")
codes = sorted(set(re.findall(r'data-stock-code="([0-9]{6})"', html)))
missing_files = []
missing_change = []
for code in codes:
    path = kline_dir / f"{code}.json"
    if not path.exists():
        missing_files.append(code)
        continue
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    change_count = sum(1 for row in rows if row.get("change_pct") is not None)
    if len(rows) > 1 and change_count < len(rows) - 1:
        missing_change.append(f"{code}:{change_count}/{len(rows)}")
if "metric('涨跌幅', percentText(selected.changePct), changeTone(selected.changePct))" not in html:
    raise SystemExit("K-line daily close change metric is missing from index.html")
if missing_files or missing_change:
    raise SystemExit(json.dumps({
        "missing_files": missing_files[:10],
        "missing_change": missing_change[:10],
    }, ensure_ascii=False))
print(json.dumps({
    "targets": len(codes),
    "missing_files": 0,
    "missing_change": 0,
}, ensure_ascii=False))
"@
    & $Python -c $validator
    if ($LASTEXITCODE -ne 0) {
        throw "Dashboard validation failed."
    }
}

function Commit-And-Push-Master {
    $date = Get-Date -Format "yyyy-MM-dd"
    git add -- output/sector_dashboard/index.html output/sector_dashboard/data/kline
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Step "No dashboard changes to commit on master."
        return
    }
    git commit -m "Daily sector dashboard update $date"
    git push origin master
}

function Deploy-GitHubPages {
    $deployMessage = "Deploy daily sector dashboard update $(Get-Date -Format 'yyyy-MM-dd')"
    git fetch origin gh-pages
    $tempIndex = Join-Path $env:TEMP ("sector-dashboard-ghpages-" + [guid]::NewGuid().ToString("N") + ".index")
    $oldIndex = $env:GIT_INDEX_FILE
    try {
        $env:GIT_INDEX_FILE = $tempIndex
        git read-tree --empty
        $indexSha = (git hash-object -w "output/sector_dashboard/index.html").Trim()
        git update-index --add --cacheinfo 100644,$indexSha,index.html
        $tmpNojekyll = New-TemporaryFile
        Set-Content -LiteralPath $tmpNojekyll -Value "" -NoNewline
        $nojekyllSha = (git hash-object -w $tmpNojekyll).Trim()
        git update-index --add --cacheinfo 100644,$nojekyllSha,.nojekyll
        Remove-Item -LiteralPath $tmpNojekyll -Force
        Get-ChildItem "output/sector_dashboard/data/kline/*.json" | ForEach-Object {
            $sha = (git hash-object -w $_.FullName).Trim()
            $repoPath = "data/kline/" + $_.Name
            git update-index --add --cacheinfo 100644,$sha,$repoPath
        }
        $tree = (git write-tree).Trim()
        $parent = (git rev-parse origin/gh-pages).Trim()
        $currentTree = (git rev-parse "$parent^{tree}").Trim()
        if ($tree -eq $currentTree) {
            Write-Step "No GitHub Pages changes to deploy."
            return
        }
        $commit = (git commit-tree $tree -p $parent -m $deployMessage).Trim()
        git update-ref refs/heads/gh-pages $commit
    } finally {
        $env:GIT_INDEX_FILE = $oldIndex
        if (Test-Path -LiteralPath $tempIndex) {
            Remove-Item -LiteralPath $tempIndex -Force
        }
    }
    git push origin gh-pages
}

Write-Step "Starting sector dashboard update."
Ensure-PythonDependencies
& $Python $Script --output $Output --max-workers 1 --min-delay 1.2 --max-delay 2.5
& $Python $KlineScript --cache-only --request-budget 0 --output-dir $OutputDir --html $Output
Assert-DashboardOutput
Commit-And-Push-Master
Deploy-GitHubPages
Write-Step "Sector dashboard update complete."
