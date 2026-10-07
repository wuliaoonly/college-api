param([Parameter(Mandatory=$true)][string]$PackageRoot)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. (Join-Path $PackageRoot 'Setup.Core.ps1') -FunctionsOnly
$config = Get-CampusConfiguration $PackageRoot
if($config.direct_connect -ne $true -or $config.env.ANTHROPIC_BASE_URL -ne 'https://api.deepseek.com/anthropic'){throw 'Unexpected direct-connect configuration'}
if((Test-CampusCredential $config) -ne 'valid'){throw 'Official credential could not be verified'}
Set-CampusClaudeConfig (Join-Path $PackageRoot 'isolated-config\settings.json') $config.env
$cached = Get-CampusConfiguration $PackageRoot
if($cached.env.ANTHROPIC_AUTH_TOKEN -ne $config.env.ANTHROPIC_AUTH_TOKEN){throw 'DPAPI retry configuration changed'}
$ticket=Get-Content -LiteralPath (Join-Path $PackageRoot 'ticket.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$rejected=$false
try {
    $null=Invoke-RestMethod -Uri $ticket.endpoint -Method Post -ContentType 'application/json' -Body (@{ticket=$ticket.ticket}|ConvertTo-Json) -TimeoutSec 20
} catch {
    if($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 410){$rejected=$true}
}
if(-not $rejected){throw 'A consumed ticket was not rejected'}
Write-Output 'PASS: trusted HTTPS exchange, official authentication, isolated config, DPAPI retry and single-use ticket.'
