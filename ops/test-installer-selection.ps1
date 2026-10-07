$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$core = Join-Path $workspace 'installer\Setup.Core.ps1'
. $core -FunctionsOnly
$root = Join-Path $workspace ('artifacts\selection-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $root 'ticket.json'),'{}')
$action = [scriptblock]::Create(([IO.File]::ReadAllText($core) -split '\$currentStep = 0',2)[1].Insert(0,'$currentStep = 0'))

# Check serialization into a clean background PowerShell process without installing software.
foreach($choice in @('claude-code','deepseek-harness','claude-code,deepseek-harness')) {
    $job=Start-Job -ScriptBlock {
        param($corePath,$package,$selected)
        . $corePath -PackageRoot $package -Clients $selected -FunctionsOnly
        [pscustomobject]@{Package=$PackageRoot;Selected=$Clients}
    } -ArgumentList $core,$root,$choice
    Wait-Job $job -Timeout 15 | Out-Null
    if($job.State -ne 'Completed'){throw 'Background job did not finish'}
    $result=Receive-Job $job -ErrorAction Stop
    Remove-Job $job
    if($result.Package -ne $root -or $result.Selected -ne $choice){throw 'Background client selection was not retained'}
}

# Run the real orchestration with isolated software/configuration boundaries.
function Install-CampusPackage([string]$Id) { throw 'Unexpected package installation' }
function Find-CampusCCSwitch { return 'fixture-cc-switch.exe' }
function Install-CampusHarness([string]$Root) { $script:calls += 'harness-install'; return 'fixture-entry.js' }
function Set-CampusHarnessConfig([string]$Root,[string]$Entry,[hashtable]$Config) { if($Config){$script:calls+='harness-config'} }
function Set-CampusHarnessLauncher { }
function Set-CampusClaudeConfig { $script:calls += 'claude-config' }
function Start-Process { $script:calls += 'cc-open' }
function Get-CampusConfiguration { if($script:ticketFails){throw 'Expired fixture ticket'}; return @{env=@{ANTHROPIC_BASE_URL='https://api.deepseek.com/anthropic';ANTHROPIC_AUTH_TOKEN='fixture-only'};models_url='https://api.deepseek.com/models';harness=@{supported=$true}} }
function Test-CampusCredential { return 'valid' }
function git { $global:LASTEXITCODE=0;return 'git fixture' }
function node { $global:LASTEXITCODE=0;return 'v24.14.0' }
function claude { $script:calls += 'claude-check';$global:LASTEXITCODE=0;return 'claude fixture' }
function Get-Command { param([string]$Name) return [pscustomobject]@{Source='fixture.exe'} }

foreach($ticketFailure in @($false,$true)) {
    foreach($choice in @('claude-code','deepseek-harness','claude-code,deepseek-harness')) {
        $script:calls = @();$script:ticketFails=$ticketFailure
        $PackageRoot = $root;$Clients=$choice
        $events = @(. $action)
        $complete = @($events | Where-Object Kind -eq 'complete')
        if($complete.Count -ne 1){throw ('Installer did not complete: '+$choice+' '+(($events|Where-Object Kind -eq 'failed').Message))}
        if($complete[0].Claude -ne ($choice.Contains('claude-code')) -or $complete[0].Harness -ne ($choice.Contains('deepseek-harness'))){throw 'Launch options incorrect'}
        if(-not $choice.Contains('claude-code') -and @($script:calls|Where-Object{$_ -in @('claude-check','claude-config','cc-open')}).Count){throw 'Unselected Claude environment touched'}
        if(-not $choice.Contains('deepseek-harness') -and @($script:calls|Where-Object{$_ -in @('harness-install','harness-config')}).Count){throw 'Unselected Harness environment touched'}
        if($ticketFailure -and @($script:calls|Where-Object{$_ -like '*-config'}).Count){throw 'Expired ticket wrote model configuration'}
        if($complete[0].Configured -eq $ticketFailure){throw 'Configuration completion was misreported'}
    }
}

Write-Output 'PASS: all three tool choices, unselected environment preservation, expired-ticket software installation, and real background-job option binding.'
