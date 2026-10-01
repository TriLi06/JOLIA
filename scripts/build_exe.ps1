# Baut aus WSL_startup.ps1 die Setup-EXE JOLIA_setup.exe.
param(
    [string]$GitHubRef = ""
)

$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "Windows PowerShell 5.1 oder neuer wird zum Erstellen der EXE benötigt."
}

$sourcePath = Join-Path $PSScriptRoot "WSL_startup.ps1"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outputDirectory = Join-Path $repoRoot "dist"
$outputPath = Join-Path $outputDirectory "JOLIA_setup.exe"
$releaseSourcePath = Join-Path $outputDirectory "WSL_startup.ps1"
$compilerPaths = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

if (-not ($compilerPaths | Where-Object { Test-Path $_ })) {
    throw ".NET Framework C#-Compiler nicht gefunden. Installiere eine Windows-Version mit .NET Framework 4.x Developer Tools."
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if ($GitHubRef) {
    if ($GitHubRef -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or $GitHubRef -match '(^|/)\.\.?(/|$)') {
        throw "Ungültige GitHub-Referenz: $GitHubRef"
    }

    $escapedRef = (($GitHubRef -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join "/"
    $sourceUrl = "https://raw.githubusercontent.com/TriLi06/JOLIA/$escapedRef/scripts/WSL_startup.ps1"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host "Lade WSL_startup.ps1 von GitHub (Ref: $GitHubRef)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $sourceUrl -OutFile $releaseSourcePath -UseBasicParsing
    $sourcePath = $releaseSourcePath
}
elseif (-not (Test-Path $sourcePath)) {
    throw "Startskript nicht gefunden: $sourcePath"
}

$launcherSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Windows.Forms;

internal static class JoliaSetupLauncher
{
    [STAThread]
    private static void Main(string[] args)
    {
        string reference = args.Length == 0 ? "__DEFAULT_GITHUB_REF__" : args[0];
        string scriptPath = Path.Combine(Path.GetTempPath(), "JOLIA-WSL_startup-" + Guid.NewGuid().ToString("N") + ".ps1");
        string bundledScriptPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "WSL_startup.ps1");

        if (String.IsNullOrWhiteSpace(reference))
        {
            if (!File.Exists(bundledScriptPath))
            {
                MessageBox.Show("Die mitgelieferte WSL_startup.ps1 fehlt neben JOLIA_setup.exe.", "JOLIA Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            scriptPath = bundledScriptPath;
        }
        else
        {
            try
            {
                string escapedRef = EscapeReference(reference);
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                string sourceUrl = "https://raw.githubusercontent.com/TriLi06/JOLIA/" + escapedRef + "/scripts/WSL_startup.ps1";
                using (WebClient client = new WebClient())
                {
                    client.DownloadFile(sourceUrl, scriptPath);
                }
            }
            catch (Exception downloadException)
            {
                if (File.Exists(scriptPath))
                {
                    try { File.Delete(scriptPath); } catch { }
                }

                if (!File.Exists(bundledScriptPath))
                {
                    MessageBox.Show("Das Setup-Skript konnte nicht von GitHub geladen werden.\r\n\r\n" + downloadException.Message, "JOLIA Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                scriptPath = bundledScriptPath;
                MessageBox.Show("Das angeforderte Setup-Skript konnte nicht von GitHub geladen werden. Die mitgelieferte Version wird verwendet.\r\n\r\n" + downloadException.Message, "JOLIA Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + scriptPath + "\"",
            WorkingDirectory = Path.GetDirectoryName(scriptPath),
            UseShellExecute = true
        };

        try
        {
            Process.Start(startInfo);
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "JOLIA Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string EscapeReference(string reference)
    {
        if (String.IsNullOrWhiteSpace(reference))
            throw new ArgumentException("GitHub-Referenz darf nicht leer sein.");

        string[] segments = reference.Split('/');
        for (int index = 0; index < segments.Length; index++)
        {
            string segment = segments[index];
            if (segment.Length == 0 || segment == "." || segment == "..")
                throw new ArgumentException("Ungültige GitHub-Referenz.");

            foreach (char character in segment)
            {
                if (!Char.IsLetterOrDigit(character) && character != '.' && character != '_' && character != '-')
                    throw new ArgumentException("Ungültige GitHub-Referenz.");
            }

            segments[index] = Uri.EscapeDataString(segment);
        }

        return String.Join("/", segments);
    }
}
'@
$runtimeGitHubRef = $GitHubRef
$launcherSource = $launcherSource.Replace("__DEFAULT_GITHUB_REF__", $runtimeGitHubRef)

Write-Host "Kompiliere Windows-Launcher mit dem .NET Framework C#-Compiler..." -ForegroundColor Cyan
Remove-Item $outputPath -Force -ErrorAction SilentlyContinue
Add-Type -TypeDefinition $launcherSource -OutputAssembly $outputPath -OutputType WindowsApplication -ReferencedAssemblies "System.Windows.Forms.dll"

if (-not (Test-Path $outputPath)) {
    throw "Der Build wurde beendet, aber die EXE wurde nicht erstellt: $outputPath"
}

if ([IO.Path]::GetFullPath($sourcePath) -ne [IO.Path]::GetFullPath($releaseSourcePath)) {
    Copy-Item -LiteralPath $sourcePath -Destination $releaseSourcePath -Force
}
foreach ($fileName in @("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "LICENSE-OpenCV-4.9.0.txt")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $fileName) -Destination $outputDirectory -Force
}

Write-Host "EXE erstellt: $outputPath" -ForegroundColor Green
Write-Host "Beileger: WSL_startup.ps1, README.md, LICENSE, THIRD_PARTY_NOTICES.md, LICENSE-OpenCV-4.9.0.txt" -ForegroundColor Green