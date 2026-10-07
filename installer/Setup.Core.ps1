# Requires Windows PowerShell 5.1. Functions are reusable by configuration tests.
param([string]$PackageRoot = $PSScriptRoot, [string]$Clients = 'claude-code', [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'

function Send-Step([int]$Index, [string]$Status, [string]$Message) {
    [pscustomobject]@{ Kind = 'step'; Index = $Index; Status = $Status; Message = $Message }
}

function ConvertTo-CampusMap($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [string] -or $Value -is [ValueType]) { return $Value }
    if ($Value -is [System.Collections.IDictionary]) {
        $map = @{}; foreach ($key in $Value.Keys) { $map[$key] = ConvertTo-CampusMap $Value[$key] }; return $map
    }
    if ($Value -is [pscustomobject]) {
        $map = @{}; foreach ($property in $Value.PSObject.Properties) { $map[$property.Name] = ConvertTo-CampusMap $property.Value }; return $map
    }
    if ($Value -is [array]) { return ,@($Value | ForEach-Object { ConvertTo-CampusMap $_ }) }
    return $Value
}

function Protect-CampusFile([string]$Path) {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $sections = [Security.AccessControl.AccessControlSections]::Access
    if ($PSVersionTable.PSEdition -eq 'Core') {
        $acl = [IO.FileSystemAclExtensions]::GetAccessControl((Get-Item -LiteralPath $Path), $sections)
    } else { $acl = [IO.File]::GetAccessControl($Path, $sections) }
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in $acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])) { $acl.RemoveAccessRuleSpecific($rule) }
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')))
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule('SYSTEM', 'FullControl', 'Allow')))
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [IO.FileSystemAclExtensions]::SetAccessControl((Get-Item -LiteralPath $Path), $acl)
    } else { [IO.File]::SetAccessControl($Path, $acl) }
}

function Set-CampusClaudeConfig([string]$SettingsPath, [hashtable]$ManagedEnv) {
    $folder = Split-Path -Parent $SettingsPath
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $settings = @{}
    if (Test-Path -LiteralPath $SettingsPath) {
        try { $settings = ConvertTo-CampusMap (Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json) }
        catch { throw '已有Claude配置不是有效JSON，已停止写入，请先修复配置。' }
        if ($settings -isnot [hashtable]) { throw '已有Claude配置格式不正确，未覆盖原文件。' }
    }
    if (-not $settings.ContainsKey('env')) { $settings['env'] = @{} }
    if ($settings['env'] -isnot [hashtable]) { throw '已有env配置格式不正确，未覆盖原文件。' }
    # ANTHROPIC_API_KEY overrides token auth in some client versions; remove conflicting legacy auth.
    $settings['env'].Remove('ANTHROPIC_API_KEY')
    foreach ($name in $ManagedEnv.Keys) { $settings['env'][$name] = $ManagedEnv[$name] }
    $temporary = $SettingsPath + '.campus-' + [guid]::NewGuid().ToString('N')
    $backup = $SettingsPath + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)
    try {
        [IO.File]::WriteAllText($temporary, ($settings | ConvertTo-Json -Depth 64), (New-Object Text.UTF8Encoding($false)))
        Protect-CampusFile $temporary
        if (Test-Path -LiteralPath $SettingsPath) {
            [IO.File]::Replace($temporary, $SettingsPath, $backup)
            Protect-CampusFile $backup
        } else { [IO.File]::Move($temporary, $SettingsPath) }
        Protect-CampusFile $SettingsPath
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Update-CampusPath {
    $paths = @($env:PATH, [Environment]::GetEnvironmentVariable('Path','Machine'), [Environment]::GetEnvironmentVariable('Path','User'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'), (Join-Path $env:USERPROFILE '.local\bin'),
        (Join-Path $env:APPDATA 'npm'), (Join-Path $env:ProgramFiles 'Git\cmd'), (Join-Path $env:ProgramFiles 'nodejs'))
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $unique = New-Object 'System.Collections.Generic.List[string]'
    foreach ($part in (($paths -join ';') -split ';')) {
        $part = $part.Trim()
        if ($part -and $seen.Add($part)) { $unique.Add($part) }
    }
    $env:PATH = $unique -join ';'
}

function Install-CampusPackage([string]$Id) {
    $winget = (Get-Command winget.exe -ErrorAction Stop).Source
    $process = Start-Process -FilePath $winget -ArgumentList @('install','--id',$Id,'--exact','--source','winget',
        '--accept-package-agreements','--accept-source-agreements','--silent','--disable-interactivity') -WindowStyle Hidden -Wait -PassThru
    # Already installed is acceptable only if caller's post-check confirms capability.
    Update-CampusPath
    return $process.ExitCode
}

function Find-CampusCCSwitch {
    $command = Get-Command 'cc-switch.exe' -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'CC Switch\cc-switch.exe'), (Join-Path $env:ProgramFiles 'CC-Switch\cc-switch.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\CC Switch\cc-switch.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\CC-Switch\cc-switch.exe'),
        (Join-Path $env:LOCALAPPDATA 'CC-Switch\cc-switch.exe'))
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    foreach ($registry in @('Registry::HKEY_CURRENT_USER\Software\Classes\ccswitch\shell\open\command',
            'Registry::HKEY_CLASSES_ROOT\ccswitch\shell\open\command')) {
        if (Test-Path $registry) {
            $value = (Get-Item -LiteralPath $registry).GetValue('')
            if ($value -match '^"([^"]+)"' -and (Test-Path -LiteralPath $Matches[1])) { return $Matches[1] }
        }
    }
    return $null
}

function Get-CampusConfiguration([string]$Root) {
    Add-Type -AssemblyName System.Security
    $cachePath = Join-Path $Root 'setup-cache.bin'
    if (Test-Path -LiteralPath $cachePath) {
        try {
            $plain = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($cachePath), $null,
                [Security.Cryptography.DataProtectionScope]::CurrentUser)
            return ConvertTo-CampusMap ([Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json)
        } catch { throw '无法读取本机配置缓存，请重新下载安装包。' }
    }
    $ticketPath = Join-Path $Root 'ticket.json'
    if (-not (Test-Path -LiteralPath $ticketPath)) { throw '没有找到ticket.json，请完整解压或重新下载安装包。' }
    $ticket = Get-Content -LiteralPath $ticketPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $uri = [uri]$ticket.endpoint
    if ($uri.Scheme -ne 'https' -and $uri.Host -notin @('localhost','127.0.0.1','::1')) { throw '配置领取必须使用HTTPS，请联系管理员。' }
    try {
        $result = Invoke-RestMethod -Uri $uri.AbsoluteUri -Method Post -ContentType 'application/json' -Body (@{ticket=$ticket.ticket}|ConvertTo-Json) -TimeoutSec 30
    } catch {
        throw '配置领取失败：票据可能已过期、被使用或账户已暂停。请重新登录网站下载；网络异常也请重试。'
    }
    $plain = [Text.Encoding]::UTF8.GetBytes(($result | ConvertTo-Json -Depth 32))
    $encrypted = [Security.Cryptography.ProtectedData]::Protect($plain, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    [IO.File]::WriteAllBytes($cachePath, $encrypted)
    Protect-CampusFile $cachePath
    return ConvertTo-CampusMap $result
}

function Test-CampusCredential([hashtable]$Config) {
    try {
        $result = Invoke-WebRequest -Uri $Config.models_url -Headers @{Authorization=('Bearer ' + $Config.env.ANTHROPIC_AUTH_TOKEN)} -TimeoutSec 20 -UseBasicParsing
        if ($result.StatusCode -eq 200) { return 'valid' }
        return 'uncertain'
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { return 'invalid' }
        return 'uncertain'
    }
}

function Get-CampusSelection([string]$Root) {
    $path = Join-Path $Root 'selection.json'
    if (-not (Test-Path -LiteralPath $path)) { return ,@('claude-code') }
    try { $selection = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw '安装选项文件损坏，请重新下载安装包。' }
    $items = @($selection.clients)
    if (-not $items.Count -or $items.Count -gt 2 -or @($items | Select-Object -Unique).Count -ne $items.Count) { throw '请至少选择一个安装工具。' }
    foreach ($item in $items) { if ($item -notin @('claude-code','deepseek-harness')) { throw '安装工具选项不受支持。' } }
    return ,$items
}

function Get-CampusHarnessRoot { return (Join-Path $env:LOCALAPPDATA 'CampusAI\Harness') }

function Install-CampusHarness([string]$Root = (Get-CampusHarnessRoot)) {
    $runtime = Join-Path $Root 'runtime-0.2.0-rc.2'
    $entry = Join-Path $runtime 'node_modules\@deepseek-ai\dsh\lib\bin.js'
    $metadata = Join-Path $runtime 'node_modules\@deepseek-ai\dsh\package.json'
    $installed = $false
    if (Test-Path -LiteralPath $metadata) {
        try { $installed = (Get-Content -LiteralPath $metadata -Raw | ConvertFrom-Json).version -eq '0.2.0-rc.2' } catch { }
    }
    if (-not $installed -or -not (Test-Path -LiteralPath $entry)) {
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        $npmCli = Join-Path (Split-Path -Parent $npm) 'node_modules\npm\bin\npm-cli.js'
        if (-not (Test-Path -LiteralPath $npmCli)) { throw '未找到Node.js自带npm，请修复Node.js LTS后重试。' }
        $node = (Get-Command node.exe -ErrorAction Stop).Source
        $stdout = Join-Path $Root 'npm-install.log'; $stderr = Join-Path $Root 'npm-install-error.log'
        $arguments = @(('"' + $npmCli + '"'),'install','--prefix',('"' + $runtime + '"'),
            '--cache',('"' + (Join-Path $Root 'npm-cache') + '"'),'--registry','https://registry.npmjs.org',
            '--no-fund','--no-audit','--fetch-timeout','30000','--fetch-retries','1','@deepseek-ai/dsh@0.2.0-rc.2')
        $process = Start-Process -FilePath $node -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if ($process.ExitCode -ne 0) { throw 'DeepSeek Harness安装失败，请检查能否访问官方npm源、磁盘空间和Node.js版本，然后重试。' }
    }
    if (-not (Test-Path -LiteralPath $entry)) { throw 'DeepSeek Harness安装文件不完整，请重试。' }
    $null = & node.exe $entry --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'DeepSeek Harness无法运行，请修复Node.js后重试。' }
    return $entry
}

function Set-CampusHarnessConfig([string]$Root, [string]$Entry, [hashtable]$Config) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $path = Join-Path $Root 'launch.json'
    $settings = @{entry=$Entry;home=(Join-Path $Root 'home');node=(Get-Command node.exe -ErrorAction Stop).Source}
    if ($Config) {
        if (-not $Config.harness.supported) { throw '此供应商尚未验证Harness配置，已保留软件安装，请联系管理员。' }
        Add-Type -AssemblyName System.Security
        $encrypted = [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($Config.harness.api_key), $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $settings['credential'] = [Convert]::ToBase64String($encrypted)
        $settings['base_url'] = $Config.harness.base_url
        $settings['model'] = $Config.harness.model
    } elseif (Test-Path -LiteralPath $path) {
        # A software-only reinstall must retain the existing managed credential.
        try {
            $existing = ConvertTo-CampusMap (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
            foreach ($name in @('credential','base_url','model')) { if ($existing.ContainsKey($name)) { $settings[$name] = $existing[$name] } }
        } catch { throw '已有Harness启动配置损坏，未覆盖原文件，请检查后重试。' }
    }
    if (Test-Path -LiteralPath $path) {
        $backup = $path + '.backup-' + [guid]::NewGuid().ToString('N')
    }
    $temporary = $path + '.new-' + [guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText($temporary, ($settings | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
    Protect-CampusFile $temporary
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary,$path,$backup); Protect-CampusFile $backup } else { [IO.File]::Move($temporary,$path) }
    Protect-CampusFile $path
}

function Set-CampusHarnessLauncher([string]$Root, [string]$SourceRoot) {
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'Harness.Launch.ps1') -Destination (Join-Path $Root 'Launch.ps1') -Force
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '学院 DeepSeek Harness.lnk'))
    $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'Launch.ps1') + '"'
    $link.WorkingDirectory = [Environment]::GetFolderPath('MyDocuments')
    $link.Description = '打开本机 DeepSeek Harness 网页界面'
    $link.Save()
}

if ($FunctionsOnly) { return }
$currentStep = 0
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $chosen = @($Clients -split ',')
    if (-not $chosen.Count -or @($chosen | Where-Object { $_ -notin @('claude-code','deepseek-harness') }).Count) { throw '请至少勾选一个受支持的工具。' }
    $installClaude = 'claude-code' -in $chosen; $installHarness = 'deepseek-harness' -in $chosen
    Send-Step 0 'running' '检查系统与安装选项…'
    if (-not [Environment]::Is64BitOperatingSystem) { throw '首版支持64位Windows 10/11。' }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw '没有WinGet，请在Microsoft Store安装“应用安装程序”后重试。' }
    $config = $null; $configurationMessage = '当前安装包不含领取票据，将先安装软件；分配Key后重新下载完成配置。'
    if ((Test-Path -LiteralPath (Join-Path $PackageRoot 'ticket.json')) -or (Test-Path -LiteralPath (Join-Path $PackageRoot 'setup-cache.bin'))) {
        try {
            $config = Get-CampusConfiguration $PackageRoot
            if (([uri]$config.env.ANTHROPIC_BASE_URL).Scheme -ne 'https' -or ([uri]$config.models_url).Scheme -ne 'https') { throw '供应商配置必须使用HTTPS。' }
            $configurationMessage = '专属配置已安全领取。'
        } catch {
            $config = $null
            $configurationMessage = '配置暂未领取（票据可能过期或网络异常），仍可安装软件；请重新下载完成配置。'
        }
    }
    $ccExisted = $installClaude -and [bool](Find-CampusCCSwitch)
    Send-Step 0 'done' ('系统检查通过。' + $configurationMessage)

    $currentStep = 1; Send-Step 1 'running' '安装或复用Git…'
    Update-CampusPath
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { $null = Install-CampusPackage 'Git.Git' }
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git安装未完成，请检查权限和官方安装源后重试。' }
    $null = & git --version
    if ($LASTEXITCODE -ne 0) { throw 'Git无法运行，请修复已有安装。' }
    Send-Step 1 'done' 'Git已就绪。'

    $currentStep = 2; Send-Step 2 'running' '安装或复用Node.js LTS…'
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $supportedNode = $false
    if ($node) { $version = & node --version; if ($version -match '^v(\d+)\.(\d+)') { $supportedNode = [int]$Matches[1] -gt 22 -or ([int]$Matches[1] -eq 22 -and [int]$Matches[2] -ge 12) } }
    if (-not $supportedNode) { $null = Install-CampusPackage 'OpenJS.NodeJS.LTS' }
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) { throw 'Node.js安装未完成，请检查官方源后重试。' }
    $version = & node --version
    if ($version -notmatch '^v(\d+)\.(\d+)' -or [int]$Matches[1] -lt 22 -or ([int]$Matches[1] -eq 22 -and [int]$Matches[2] -lt 12)) { throw '需要Node.js 22.12或以上，请升级已有Node.js后重试。' }
    Send-Step 2 'done' 'Node.js已就绪。'

    $currentStep = 3
    if ($installClaude) {
    Send-Step 3 'running' '安装或复用Claude Code…'
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { $null = Install-CampusPackage 'Anthropic.ClaudeCode' }
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw 'Claude Code安装未完成，请检查官方源后重试。' }
    $null = & claude --version
    if ($LASTEXITCODE -ne 0) { throw 'Claude Code无法运行，请修复已有安装。' }
    Send-Step 3 'done' 'Claude Code已就绪。'
    } else { Send-Step 3 'skipped' '未勾选Claude Code，保留已有软件和配置。' }

    $currentStep = 4; $harnessRoot = Get-CampusHarnessRoot
    if ($installHarness) {
        Send-Step 4 'running' '从DeepSeek官方npm包安装Harness，请等待下载完成…'
        $harnessEntry = Install-CampusHarness $harnessRoot
        Set-CampusHarnessConfig $harnessRoot $harnessEntry $null
        Set-CampusHarnessLauncher $harnessRoot $PackageRoot
        Send-Step 4 'done' 'DeepSeek Harness已就绪，桌面快捷方式已创建。'
    } else { Send-Step 4 'skipped' '未勾选DeepSeek Harness，保留已有环境。' }

    $currentStep = 5; $probe = 'not_configured'; $configured = $false
    if ($config) {
    Send-Step 5 'running' '验证官方鉴权并保存所选工具的直连配置…'
    $probe = Test-CampusCredential $config
    if ($probe -eq 'invalid') {
        Send-Step 5 'warning' '官方Key不可鉴权，未修改客户端配置；请联系管理员替换后重新下载。'
    } else {
    if ($installClaude) {
    $claudeDirectory = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
    $settingsPath = Join-Path $claudeDirectory 'settings.json'
    Set-CampusClaudeConfig $settingsPath $config.env
    }
    if ($installHarness) { Set-CampusHarnessConfig $harnessRoot $harnessEntry $config }
    $configured = $true
    Send-Step 5 'done' '所选工具的官方直连配置已保存，原配置已备份。'
    }
    } else { Send-Step 5 'warning' $configurationMessage }

    $currentStep = 6
    if ($installClaude) {
    Send-Step 6 'running' '安装或复用CC Switch…'
    $cc = Find-CampusCCSwitch
    if (-not $cc) { $null = Install-CampusPackage 'farion1231.CC-Switch'; $cc = Find-CampusCCSwitch }
    if (-not $cc) { throw 'CC Switch安装未完成，请检查官方源后重试。' }
    if ($configured) {
    if (-not $ccExisted) {
        Start-Process -FilePath $cc -WindowStyle Normal | Out-Null
        Send-Step 6 'done' 'CC Switch已打开；首次启动会导入已有Claude配置。'
    } else {
        $encodedConfig = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((@{env=$config.env}|ConvertTo-Json -Depth 32 -Compress)))
        $fields = @{resource='provider';app='claude';name='学院 DeepSeek';endpoint=$config.env.ANTHROPIC_BASE_URL;
            apiKey=$config.env.ANTHROPIC_AUTH_TOKEN;model=$config.env.ANTHROPIC_MODEL;
            haikuModel=$config.env.ANTHROPIC_DEFAULT_HAIKU_MODEL;sonnetModel=$config.env.ANTHROPIC_DEFAULT_SONNET_MODEL;
            opusModel=$config.env.ANTHROPIC_DEFAULT_OPUS_MODEL;configFormat='json';config=$encodedConfig}
        $query = ($fields.GetEnumerator() | ForEach-Object { [uri]::EscapeDataString($_.Key) + '=' + [uri]::EscapeDataString([string]$_.Value) }) -join '&'
        $localImport = 'ccswitch://v1/import?' + $query
        try { Start-Process -FilePath $localImport | Out-Null } catch { throw '无法打开CC Switch导入窗口。Claude Code已配置；请修复CC Switch协议关联后重试。' }
        Send-Step 6 'done' '请在CC Switch窗口确认导入，原有供应商会保留。'
    }
    } else { Send-Step 6 'done' 'CC Switch已就绪，未导入缺失或无效的模型配置。' }
    } else { Send-Step 6 'skipped' '仅选择Harness，无需CC Switch。' }

    $currentStep = 7
    if ($configured -and $probe -eq 'valid') { Send-Step 7 'done' '官方鉴权成功，模型流量直接连接DeepSeek；检查未发起收费推理。' }
    elseif ($configured) { Send-Step 7 'warning' '软件和配置已完成，官方连接暂无法确认，请检查网络。' }
    else { Send-Step 7 'warning' '软件安装完成，模型配置尚未完成；分配有效Key后重新下载即可继续。' }
    $cache = Join-Path $PackageRoot 'setup-cache.bin'
    if (Test-Path -LiteralPath $cache) { Remove-Item -LiteralPath $cache -Force }
    $completion = if ($configured) { '安装与配置完成，点击对应按钮即可打开所选工具。' } else { '软件安装完成；当前未完成模型配置，请在分配有效Key后重新下载安装助手。' }
    [pscustomobject]@{Kind='complete';Message=$completion;Verified=($configured -and $probe -eq 'valid');Claude=$installClaude;Harness=$installHarness;Configured=$configured}
} catch {
    # All credential-bearing network/launch errors are converted to safe messages above.
    $safeMessage = [string]$_.Exception.Message
    if ($safeMessage -match 'sk-[A-Za-z0-9_-]{10,}|Bearer |ccswitch://') { $safeMessage = '当前步骤未完成，请重新下载或联系管理员；详细凭据不会显示。' }
    Send-Step $currentStep 'error' $safeMessage
    [pscustomobject]@{Kind='failed';Message=$safeMessage}
}
