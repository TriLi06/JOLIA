$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$scriptPath = Join-Path $PSScriptRoot '../scripts/WSL_startup.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

$localHealthChecks = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Invoke-WebRequest' -and
        $node.Extent.Text -match 'http://(?:localhost|127\.0\.0\.1):\$AppPort/health'
}, $true))
if ($localHealthChecks.Count -ne 3) { throw 'Missing local health checks' }
foreach ($check in $localHealthChecks) {
    if ($check.Extent.Text -match 'http://localhost:') { throw 'Local health check depends on localhost resolution' }
}
Write-Output 'PASS: all Windows local health checks use explicit IPv4'

foreach ($name in @('Set-JoliaEnvVar', 'Set-JoliaDeploymentConfig', 'Register-JoliaAutostart', 'Get-JoliaLanAddresses', 'Test-JoliaOllama')) {
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
    if ($script:wslExitCode -ne 0) { Write-Output 'test: permission denied' }
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
try { Set-JoliaEnvVar -Distro test -AppDir /opt/jolia -Key JOLIA_PORT -Value 8090 } catch {
    $writeFailed = $true
    if ($_.Exception.Message -notlike '*test: permission denied*') { throw 'WSL failure details were lost' }
}
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
function Get-AutostartKeepAlive {
    if ($script:taskExe -notlike '*\WindowsPowerShell\v1.0\powershell.exe' -or
        $script:taskArgs -notlike '*-NoProfile -WindowStyle Hidden -EncodedCommand *') {
        throw 'Autostart launcher is not hidden'
    }
    $launcherEncoded = [regex]::Match($script:taskArgs, '-EncodedCommand ([A-Za-z0-9+/=]+)').Groups[1].Value
    if (-not $launcherEncoded) { throw 'Missing encoded autostart launcher' }
    $launcher = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($launcherEncoded))
    if ($launcher -notmatch 'Start-Process .* -WindowStyle Hidden -Wait -PassThru') {
        throw 'WSL process is not hidden or awaited'
    }
    $keepAliveEncoded = [regex]::Match($launcher, 'echo ([A-Za-z0-9+/=]+) \| base64 -d').Groups[1].Value
    if (-not $keepAliveEncoded) { throw 'Missing encoded keepalive command' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($keepAliveEncoded))
}
Register-JoliaAutostart
$localAutostart = Get-AutostartKeepAlive
if ($localAutostart -notlike 'set -e;*docker compose config --quiet; docker compose up -d app; exec sleep infinity') {
    throw 'Invalid autostart command'
}
if ($script:triggerUser -ne "$env:USERDOMAIN\$env:USERNAME") { throw 'Autostart is not scoped to the WSL owner' }
$StorageMode = 'FritzNas'
$FritzNasUploadMount = '/mnt/fritznas_upload'
$FritzNasBackupMount = '/mnt/fritznas_backup'
Register-JoliaAutostart
$nasAutostart = Get-AutostartKeepAlive
if ($nasAutostart -notlike '*mountpoint -q /mnt/fritznas_upload && mountpoint -q /mnt/fritznas_backup || exit 1*') {
    throw 'NAS autostart does not gate container startup on mounts'
}
Write-Output 'PASS: local/NAS autostart hides WSL and fails before keepalive on startup errors'

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
        $envCommands = @($script:commands | Where-Object { $_ -like 'set -e; set -o pipefail; touch*' } | Select-Object -First 4)
        foreach ($command in $envCommands) {
            $command.Replace('/opt/jolia', "'$linuxDirectory'") | & $bashPath -e
            if ($LASTEXITCODE -ne 0) { throw 'ENV write failed in Bash' }
        }
        $actual = [IO.File]::ReadAllText((Join-Path $tempDirectory '.env'))
        if ($actual -cne ("JOLIA_ENABLE_OCR=false`n" + ($expected -join ''))) { throw 'Malformed ENV was not repaired or override was lost' }
        Write-Output 'PASS: real Bash repairs concatenated ENV while preserving unrelated overrides'
        foreach ($initialContent in @('', "JOLIA_PORT=8080`nJOLIA_PORT=8081`n")) {
            [IO.File]::WriteAllText((Join-Path $tempDirectory '.env'), $initialContent, [Text.UTF8Encoding]::new($false))
            foreach ($command in $envCommands) {
                if ($command.Contains('$?')) { throw 'ENV command depends on shell status expansion across WSL' }
                $command.Replace('/opt/jolia', "'$linuxDirectory'") | & $bashPath -e
                if ($LASTEXITCODE -ne 0) { throw 'Empty or duplicate-key ENV write failed in Bash' }
            }
            $actual = [IO.File]::ReadAllText((Join-Path $tempDirectory '.env'))
            if ($actual -cne ($expected -join '')) { throw 'Empty or duplicate-key ENV was not configured correctly' }
        }
        Write-Output 'PASS: real Bash configures empty ENV and replaces duplicate keys'
    } finally {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
} else {
    Write-Warning 'Git Bash unavailable: real shell regression checks skipped'
}
Write-Output 'PASS: installer PowerShell syntax'

$script:diagnosticWarnings = @()
$script:diagnosticLogs = @()
$script:diagnosticInferenceCalls = 0
$script:missingModel = $false
function Write-Step {}
function Write-Fail {}
function Write-Warn2 { param($message) $script:diagnosticWarnings += $message }
function wsl {
    $global:LASTEXITCODE = 0
    if ($args -contains 'inspect') {
        $containerName = $args[-1]
        $state = if ($containerName -eq 'jolia-ollama-init') {
            @{ Status = 'exited'; Running = $false; ExitCode = 0 }
        } else {
            @{ Status = 'running'; Running = $true; Health = @{ Status = 'healthy' } }
        }
        ConvertTo-Json -InputObject @(@{ State = $state }) -Depth 5 -Compress
    } elseif ($args -contains 'list') {
        'qwen2.5:1.5b id size'
        'qwen2.5:7b id size'
        'qwen2.5vl:3b id size'
        if (-not $script:missingModel) { 'bge-m3:latest id size' }
    } elseif ($args -contains 'logs') {
        $script:diagnosticLogs += $args[-1]
        Write-Error 'pulling model: 100%' -ErrorId NativeCommandError
    } elseif (($args -join "`n") -match 'get_background_ollama_service') {
        $script:diagnosticInferenceCalls++
        'Import-Modell: qwen2.5:7b'
        'Inferenz erfolgreich: OK'
    } else {
        'HTTP 200'
    }
}
Test-JoliaOllama
if ($script:diagnosticWarnings -like "Standardmodell '*' fehlt.*") { throw 'Installed default model tag was reported missing' }
if ($script:diagnosticInferenceCalls -ne 1) { throw 'Configured import-model inference was not tested' }
if (($script:diagnosticLogs -join ',') -ne 'jolia-ollama-init,jolia-ollama,jolia-app') { throw 'stderr prevented remaining container logs' }
if ($ErrorActionPreference -ne 'Stop') { throw 'Diagnostic changed caller error handling' }
$script:missingModel = $true
$script:diagnosticWarnings = @()
Test-JoliaOllama
if (-not ($script:diagnosticWarnings -like "Standardmodell 'bge-m3' fehlt.*")) { throw 'Missing model was not reported' }
if ($script:diagnosticInferenceCalls -ne 2) { throw 'Inference probe did not run when the model list was incomplete' }
Write-Output 'PASS: diagnostics accept latest tags, detect missing models and continue after stderr'