$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'installer\Setup.Core.ps1') -FunctionsOnly
$testRoot = Join-Path $workspace ('artifacts\installer-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
$settingsPath = Join-Path $testRoot 'settings.json'
[IO.File]::WriteAllText($settingsPath, '{"permissions":{"allow":["Read"]},"env":{"KEEP_ME":"yes","ANTHROPIC_API_KEY":"old"}}')
$managed = @{ANTHROPIC_BASE_URL='https://api.deepseek.com/anthropic';ANTHROPIC_AUTH_TOKEN='fixture-key-only';ANTHROPIC_MODEL='deepseek-flash[1m]'}
Set-CampusClaudeConfig $settingsPath $managed
$result = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if($result.env.KEEP_ME -ne 'yes' -or $result.permissions.allow[0] -ne 'Read'){throw 'Existing settings were lost'}
if($result.env.ANTHROPIC_AUTH_TOKEN -ne 'fixture-key-only'){throw 'Managed settings missing'}
if($result.env.PSObject.Properties.Name -contains 'ANTHROPIC_API_KEY'){throw 'Conflicting auth was retained'}
Set-CampusClaudeConfig $settingsPath $managed
if(@(Get-ChildItem -LiteralPath $testRoot -Filter 'settings.json.backup-*').Count -ne 2){throw 'Backup missing on repeat'}
[IO.File]::WriteAllText($settingsPath,'{broken')
$rejected=$false
try{Set-CampusClaudeConfig $settingsPath $managed}catch{$rejected=$true}
if(-not $rejected -or [IO.File]::ReadAllText($settingsPath) -ne '{broken'){throw 'Invalid configuration overwritten'}
$harnessRoot = Join-Path $testRoot 'harness'
$fixtureConfig = @{harness=@{supported=$true;api_key='fixture-harness-key-only';base_url='https://api.deepseek.com/anthropic';model='deepseek-flash'}}
Set-CampusHarnessConfig $harnessRoot 'fixture-entry.js' $fixtureConfig
$launchPath = Join-Path $harnessRoot 'launch.json'
$launchSettings = Get-Content -LiteralPath $launchPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([IO.File]::ReadAllText($launchPath).Contains('fixture-harness-key-only')) { throw 'Harness credential was stored in plaintext' }
Add-Type -AssemblyName System.Security
$decoded = [Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($launchSettings.credential),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
if ([Text.Encoding]::UTF8.GetString($decoded) -ne 'fixture-harness-key-only') { throw 'Harness credential cannot be recovered by current user' }
Set-CampusHarnessConfig $harnessRoot 'updated-entry.js' $null
$retained = Get-Content -LiteralPath $launchPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($retained.credential -ne $launchSettings.credential -or $retained.entry -ne 'updated-entry.js') { throw 'Software reinstall lost credential or runtime update' }
[IO.File]::WriteAllText((Join-Path $testRoot 'selection.json'),'{"clients":["deepseek-harness","claude-code"]}')
$selection = Get-CampusSelection $testRoot
if ($selection.Count -ne 2 -or $selection[0] -ne 'deepseek-harness') { throw 'Multiple installer choices not retained' }
foreach($file in @('Setup.Core.ps1','CampusAI-Setup.ps1','Harness.Launch.ps1')){
    $parseErrors=$null;$tokens=$null
    [Management.Automation.Language.Parser]::ParseInput([IO.File]::ReadAllText((Join-Path $workspace "installer\$file")),[ref]$tokens,[ref]$parseErrors)|Out-Null
    if($parseErrors.Count){throw "Installer parser failed for $file"}
}
Write-Output 'PASS: configuration preservation, backups, client choices, Harness DPAPI credentials, repeat software installation, and PowerShell syntax.'
