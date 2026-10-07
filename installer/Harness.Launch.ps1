# The launcher contains no API key. Its credential is DPAPI protected for the current user.
param([string]$Root = $PSScriptRoot, [switch]$NoOpen, [ValidateRange(1,65535)][int]$Port = 3080)
$ErrorActionPreference = 'Stop'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $settings = Get-Content -LiteralPath (Join-Path $Root 'launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $settings.entry) -or -not (Test-Path -LiteralPath $settings.node)) { throw 'Installation incomplete' }
    $env:DSH_HOME = $settings.home
    $env:DSH_TELEMETRY_MODE = 'DISABLED'
    $options = @('web')
    New-Item -ItemType Directory -Path $settings.home -Force | Out-Null
    if ($settings.credential) {
        Add-Type -AssemblyName System.Security
        $plain = [Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($settings.credential), $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $env:DEEPSEEK_API_KEY = [Text.Encoding]::UTF8.GetString($plain)
        $overlay = @(
            @{id='llm-deepseek';config=@{apiKeyEnv='DEEPSEEK_API_KEY';baseURL=$settings.base_url}},
            @{id='agent-default-model';config=@{provider='deepseek-official';model=$settings.model}}
        )
        $patch = Join-Path $Root 'campus.patch.json'
        [IO.File]::WriteAllText($patch, (ConvertTo-Json -InputObject $overlay -Depth 10), (New-Object Text.UTF8Encoding($false)))
        $options += @('--patch',$patch)
    } else {
        # Without a platform Key, the official local Models settings can still be used.
        Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    }
    $options += @('--host','127.0.0.1','--port',[string]$Port)
    if ($NoOpen) { $options += '--no-open' }
    & $settings.node $settings.entry @options
    if ($LASTEXITCODE -ne 0) { throw 'Harness launch failed' }
} catch {
    if ($NoOpen) { Write-Error 'DeepSeek Harness未能启动，请检查安装、Node.js版本或端口占用。' -ErrorAction Continue; exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show('DeepSeek Harness未能启动。请检查官方npm安装是否完整、Node.js版本和端口3080是否被占用，然后重新运行安装助手。配置中的密钥不会显示。','学院 AI Coding')
} finally {
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
}
