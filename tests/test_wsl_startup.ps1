$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$scriptPath = Join-Path $PSScriptRoot '../scripts/WSL_startup.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

foreach ($name in @('Set-JoliaEnvVar', 'Set-JoliaDeploymentConfig', 'Register-JoliaAutostart', 'Get-JoliaLanAddresses')) {
    $definition = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if (-not $definition) { throw "Missing function: $name" }
    Invoke-Expression $definition.Extent.Text
}

$DistroName = 'test'
$AppDirLinux = '/opt/jolia'
$ArchiveLinux = '/data/archive'
$AppPort = 8090
$JoliaInboxLinux = '/mnt/c/JOLIA Data/inbox'
$JoliaBackupLinux = '/mnt/c/JOLIA Data/backup'
$TaskName = 'test'
$StorageMode = 'Local'
$script:commands = @()
$script:wslExitCode = 0
function wsl {
    $script:commands += [string]$args[-1]
    $global:LASTEXITCODE = $script:wslExitCode
}

Set-JoliaDeploymentConfig -Distro test
$entries = @($script:commands | ForEach-Object {
    $match = [regex]::Match($_, 'echo ([A-Za-z0-9+/=]+) \| base64 -d')
    if ($match.Success) {
        [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($match.Groups[1].Value))
    }
})
$expected = @("JOLIA_PORT=8090`n", "JOLIA_INBOX=$JoliaInboxLinux`n", "JOLIA_ARCHIVE=$ArchiveLinux`n", "JOLIA_BACKUP=$JoliaBackupLinux`n")
if ($entries.Count -ne $expected.Count) { throw 'Incomplete deployment configuration' }
for ($index = 0; $index -lt $expected.Count; $index++) {
    if ($entries[$index] -cne $expected[$index]) { throw "Invalid ENV entry: $index" }
}
Write-Output 'PASS: deployment writes four LF-terminated ENV entries'

$script:wslExitCode = 1
$writeFailed = $false
try { Set-JoliaEnvVar -Distro test -AppDir /opt/jolia -Key JOLIA_PORT -Value 8090 } catch { $writeFailed = $true }
if (-not $writeFailed) { throw 'WSL write failure was ignored' }
$script:wslExitCode = 0
Write-Output 'PASS: WSL write failure aborts configuration'

function New-ScheduledTaskAction { param($Execute, $Argument) $script:taskExe = $Execute; $script:taskArgs = $Argument }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User) $script:triggerUser = $User }
function New-ScheduledTaskPrincipal { param($UserId, $RunLevel) }
function New-ScheduledTaskSettingsSet { param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, $ExecutionTimeLimit) }
function Stop-ScheduledTask {}
function Unregister-ScheduledTask {}
function Register-ScheduledTask {}
function Start-ScheduledTask {}
function Write-Ok {}
Register-JoliaAutostart
$encoded = [regex]::Match($script:taskArgs, 'echo ([A-Za-z0-9+/=]+) \| base64 -d').Groups[1].Value
$localAutostart = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
if ($script:taskExe -notlike '*\wsl.exe' -or $localAutostart -notlike 'set -e;*docker compose config --quiet; docker compose up -d app; exec sleep infinity') {
    throw 'Unsafe autostart command'
}
if ($script:triggerUser -ne "$env:USERDOMAIN\$env:USERNAME") { throw 'Autostart is not scoped to the WSL owner' }
$StorageMode = 'FritzNas'
$FritzNasUploadMount = '/mnt/fritznas_upload'
$FritzNasBackupMount = '/mnt/fritznas_backup'
Register-JoliaAutostart
$encoded = [regex]::Match($script:taskArgs, 'echo ([A-Za-z0-9+/=]+) \| base64 -d').Groups[1].Value
$nasAutostart = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
if ($nasAutostart -notlike '*mountpoint -q /mnt/fritznas_upload && mountpoint -q /mnt/fritznas_backup || exit 1*') {
    throw 'NAS autostart does not gate container startup on mounts'
}
Write-Output 'PASS: local/NAS autostart uses direct WSL invocation and fails before keepalive on startup errors'

function Get-NetIPConfiguration {
    foreach ($adapter in @(
        @('192.168.178.20', $true, 'Up', 'gateway'),
        @('172.17.0.1', $false, 'Up', 'gateway'),
        @('10.0.0.5', $true, 'Down', 'gateway'),
        @('169.254.1.2', $true, 'Up', 'gateway'),
        @('192.168.1.2', $true, 'Up', $null)
    )) {
        [pscustomobject]@{
            IPv4DefaultGateway = $adapter[3]
            NetAdapter = [pscustomobject]@{ HardwareInterface = $adapter[1]; Status = $adapter[2] }
            IPv4Address = [pscustomobject]@{ IPAddress = $adapter[0] }
        }
    }
}
$addresses = @(Get-JoliaLanAddresses)
if ($addresses.Count -ne 1 -or $addresses[0] -ne '192.168.178.20') { throw 'Incorrect LAN address selection' }
Write-Output 'PASS: LAN addresses exclude virtual, disconnected and link-local adapters'

$bashPath = Join-Path $env:ProgramFiles 'Git/bin/bash.exe'
if (Test-Path $bashPath) {
    foreach ($command in @($localAutostart, $nasAutostart)) {
        $command | & $bashPath -n
        if ($LASTEXITCODE -ne 0) { throw 'Invalid autostart Bash syntax' }
    }
    $tempDirectory = Join-Path ([IO.Path]::GetTempPath()) ('jolia-env-test-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $tempDirectory
    try {
        $linuxDirectory = $tempDirectory.Replace('\', '/')
        $seed = "JOLIA_PORT=8090JOLIA_INBOX=/brokenJOLIA_ARCHIVE=/brokenJOLIA_BACKUP=/broken`nJOLIA_ENABLE_OCR=false`n"
        [IO.File]::WriteAllText((Join-Path $tempDirectory '.env'), $seed, [Text.UTF8Encoding]::new($false))
        foreach ($command in ($script:commands | Where-Object { $_ -like 'set -e; touch*' } | Select-Object -First 4)) {
            $command.Replace('/opt/jolia', "'$linuxDirectory'") | & $bashPath -e
            if ($LASTEXITCODE -ne 0) { throw 'ENV write failed in Bash' }
        }
        $actual = [IO.File]::ReadAllText((Join-Path $tempDirectory '.env'))
        if ($actual -cne ("JOLIA_ENABLE_OCR=false`n" + ($expected -join ''))) { throw 'Malformed ENV was not repaired or override was lost' }
        Write-Output 'PASS: real Bash repairs concatenated ENV while preserving unrelated overrides'
    } finally {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
} else {
    Write-Warning 'Git Bash unavailable: real shell regression checks skipped'
}
Write-Output 'PASS: installer PowerShell syntax'