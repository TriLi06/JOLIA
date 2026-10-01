[CmdletBinding()]
param(
    [string[]]$Image = @(),
    [string]$WslDistro = "jolia-wsl"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outputDirectory = Join-Path $repoRoot "dist\sbom"
$syftImage = "anchore/syft:v1.52.0"

function ConvertTo-BashQuotedString ([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Ein erforderlicher WSL-/Bash-Pfad oder Wert ist leer."
    }
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Invoke-WslDockerCommand ([string]$Command) {
    $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Command))
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & wsl.exe -d $WslDistro -u root -- bash -lc "printf '%s' '$encodedCommand' | base64 -d | bash" 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        throw "WSL-Docker-Befehl fehlgeschlagen (Exitcode $exitCode)."
    }
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "wsl.exe wurde nicht gefunden."
}

$distroList = ((& wsl.exe -l -q) -join "`n") -replace "`0", ""
if ($LASTEXITCODE -ne 0 -or $distroList -notmatch "(?m)^\s*$([regex]::Escape($WslDistro))\s*$") {
    throw "WSL-Distribution '$WslDistro' wurde nicht gefunden. Installiere JOLIA zuerst ueber scripts/WSL_startup.ps1."
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$wslRepoInput = $repoRoot -replace '\\', '/'
$wslOutputInput = $outputDirectory -replace '\\', '/'
$wslRepoRoot = (& wsl.exe -d $WslDistro -u root -- wslpath -a $wslRepoInput).Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslRepoRoot) {
    throw "Der Repository-Pfad ist aus der WSL-Distribution nicht erreichbar."
}
$wslOutputDirectory = (& wsl.exe -d $WslDistro -u root -- wslpath -a $wslOutputInput).Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslOutputDirectory) {
    throw "Der SBOM-Ausgabeordner ist aus der WSL-Distribution nicht erreichbar."
}

$commit = (& git -C $repoRoot rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) { $commit = "unversioned" }
$dirty = & git -C $repoRoot status --porcelain
if ($dirty) { $commit = "$commit-dirty" }

$quotedRepo = ConvertTo-BashQuotedString $wslRepoRoot
$quotedOutput = ConvertTo-BashQuotedString $wslOutputDirectory
$quotedSyftImage = ConvertTo-BashQuotedString $syftImage
$sourceFileName = "jolia-source-$commit.cdx.json"
$sourceCommand = @(
    "docker run --rm",
    "-v /var/run/docker.sock:/var/run/docker.sock",
    "-v ${quotedRepo}:/src:ro",
    "-v ${quotedOutput}:/out",
    $quotedSyftImage,
    "scan dir:/src --base-path /src",
    "--exclude '**/.git/**' --exclude '**/dist/**' --exclude '**/.venv/**'",
    "--exclude '**/node_modules/**' --exclude '**/__pycache__/**' --exclude '**/jolia/**'",
    "--source-name 'JOLIA source' --source-version '$commit'",
    "-o 'cyclonedx-json=/out/$sourceFileName'"
) -join " "

Write-Host "Erzeuge Quell-SBOM mit $syftImage ..." -ForegroundColor Cyan
Invoke-WslDockerCommand $sourceCommand
Write-Host "SBOM erstellt: $(Join-Path $outputDirectory $sourceFileName)" -ForegroundColor Green

foreach ($imageName in $Image) {
    if ($imageName -notmatch '^[A-Za-z0-9][A-Za-z0-9._/:@-]*$') {
        throw "Ungueltiger Docker-Image-Name: $imageName"
    }
    $safeName = $imageName -replace '[^A-Za-z0-9._-]', '_'
    $imageFileName = "image-$safeName-$commit.cdx.json"
    $quotedImageName = ConvertTo-BashQuotedString "docker:$imageName"
    $imageCommand = @(
        "docker run --rm",
        "-v /var/run/docker.sock:/var/run/docker.sock",
        "-v ${quotedOutput}:/out",
        $quotedSyftImage,
        "scan $quotedImageName --source-name '$imageName' --source-version '$commit'",
        "-o 'cyclonedx-json=/out/$imageFileName'"
    ) -join " "
    Write-Host "Erzeuge Image-SBOM fuer $imageName ..." -ForegroundColor Cyan
    Invoke-WslDockerCommand $imageCommand
    Write-Host "SBOM erstellt: $(Join-Path $outputDirectory $imageFileName)" -ForegroundColor Green
}
