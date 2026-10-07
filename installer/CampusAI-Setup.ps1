param([switch]$Preview, [int]$AutoCloseSeconds = 0, [string]$ScreenshotPath = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object Windows.Forms.Form
$form.Text = '学院 AI Coding · 安装助手'
$form.Size = New-Object Drawing.Size(720, 730)
$form.MinimumSize = $form.Size
$form.MaximumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.BackColor = [Drawing.Color]::FromArgb(246,248,252)
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 9)

$title = New-Object Windows.Forms.Label
$title.Text = '把 AI 编程环境，一次装好。'
$title.Font = New-Object Drawing.Font('Microsoft YaHei UI', 20, [Drawing.FontStyle]::Bold)
$title.Location = New-Object Drawing.Point(32,28)
$title.Size = New-Object Drawing.Size(660,45)
$title.ForeColor = [Drawing.Color]::FromArgb(25,43,73)
$form.Controls.Add($title)
$subtitle = New-Object Windows.Forms.Label
$subtitle.Text = '软件从官方源下载；配置完成后，模型请求直接连接供应商。'
$subtitle.Location = New-Object Drawing.Point(34,83)
$subtitle.Size = New-Object Drawing.Size(630,26)
$subtitle.ForeColor = [Drawing.Color]::FromArgb(113,128,152)
$form.Controls.Add($subtitle)

$chooseClaude = New-Object Windows.Forms.CheckBox
$chooseClaude.Text = 'Claude Code（含 CC Switch）'
$chooseClaude.Location = New-Object Drawing.Point(36,117)
$chooseClaude.Size = New-Object Drawing.Size(274,28)
$chooseClaude.Checked = $true
$form.Controls.Add($chooseClaude)
$chooseHarness = New-Object Windows.Forms.CheckBox
$chooseHarness.Text = 'DeepSeek Harness（本机网页）'
$chooseHarness.Location = New-Object Drawing.Point(330,117)
$chooseHarness.Size = New-Object Drawing.Size(342,28)
$form.Controls.Add($chooseHarness)
try {
    . (Join-Path $PSScriptRoot 'Setup.Core.ps1') -FunctionsOnly
    $selection = Get-CampusSelection $PSScriptRoot
    $chooseClaude.Checked = 'claude-code' -in $selection
    $chooseHarness.Checked = 'deepseek-harness' -in $selection
} catch { $subtitle.Text = '选项读取失败，可重新勾选安装工具。' }

$stepNames = @('系统检查与配置领取','Git','Node.js LTS','Claude Code','DeepSeek Harness','官方模型配置','CC Switch','连接检查')
$stepLabels = @()
for ($index = 0; $index -lt $stepNames.Count; $index++) {
    $label = New-Object Windows.Forms.Label
    $label.Text = ('{0:00}   {1}                                         待开始' -f ($index+1),$stepNames[$index])
    $label.Location = New-Object Drawing.Point(36,(166+$index*38))
    $label.Size = New-Object Drawing.Size(636,34)
    $label.Padding = New-Object Windows.Forms.Padding(12,8,0,0)
    $label.BackColor = [Drawing.Color]::White
    $label.ForeColor = [Drawing.Color]::FromArgb(99,117,143)
    $form.Controls.Add($label)
    $stepLabels += $label
}
$progress = New-Object Windows.Forms.ProgressBar
$progress.Location = New-Object Drawing.Point(36,477)
$progress.Size = New-Object Drawing.Size(636,8)
$progress.Maximum = 8
$form.Controls.Add($progress)
$message = New-Object Windows.Forms.Label
$message.Location = New-Object Drawing.Point(36,497)
$message.Size = New-Object Drawing.Size(636,70)
$message.ForeColor = [Drawing.Color]::FromArgb(91,111,145)
$message.Text = '可同时勾选两种工具。没有配置票据也能先安装软件；已有配置会备份。'
$form.Controls.Add($message)
$start = New-Object Windows.Forms.Button
$start.Location = New-Object Drawing.Point(36,581)
$start.Size = New-Object Drawing.Size(225,44)
$start.Text = '开始安装'
$start.FlatStyle = 'Flat'
$start.FlatAppearance.BorderSize = 0
$start.BackColor = [Drawing.Color]::FromArgb(36,93,224)
$start.ForeColor = [Drawing.Color]::White
$form.Controls.Add($start)
$launch = New-Object Windows.Forms.Button
$launch.Location = New-Object Drawing.Point(276,581)
$launch.Size = New-Object Drawing.Size(240,44)
$launch.Text = '打开 Claude Code'
$launch.FlatStyle = 'Flat'
$launch.Enabled = $false
$form.Controls.Add($launch)
$launch.Add_Click({
    try {
        . (Join-Path $PSScriptRoot 'Setup.Core.ps1') -FunctionsOnly
        Update-CampusPath
        Start-Process -FilePath 'powershell.exe' -WindowStyle Normal -WorkingDirectory ([Environment]::GetFolderPath('MyDocuments')) -ArgumentList @('-NoProfile','-NoExit','-Command','claude') | Out-Null
    } catch { $message.Text = '无法打开 Claude Code，请重新打开终端或下载安装助手后重试。' }
})
$launchHarness = New-Object Windows.Forms.Button
$launchHarness.Location = New-Object Drawing.Point(276,632)
$launchHarness.Size = New-Object Drawing.Size(240,44)
$launchHarness.Text = '打开 DeepSeek Harness'
$launchHarness.FlatStyle = 'Flat'
$launchHarness.Enabled = $false
$form.Controls.Add($launchHarness)
$launchHarness.Add_Click({
    try {
        $taskLauncher = Join-Path (Get-CampusHarnessRoot) 'Launch.ps1'
        if (-not (Test-Path -LiteralPath $taskLauncher)) { throw 'Launcher missing' }
        Start-Process -FilePath 'powershell.exe' -WindowStyle Normal -WorkingDirectory ([Environment]::GetFolderPath('MyDocuments')) -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $taskLauncher + '"')) | Out-Null
    } catch { $message.Text = '无法打开DeepSeek Harness，请通过桌面快捷方式启动，或重新运行安装助手。' }
})
$close = New-Object Windows.Forms.Button
$close.Location = New-Object Drawing.Point(546,581)
$close.Size = New-Object Drawing.Size(126,44)
$close.Text = '关闭'
$close.FlatStyle = 'Flat'
$close.FlatAppearance.BorderColor = [Drawing.Color]::FromArgb(221,228,239)
$form.Controls.Add($close)
$close.Add_Click({$form.Close()})

$script:installJob = $null
$script:terminalState = $false
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 350
$timer.Add_Tick({
    if ($script:installJob) {
        $events = @(Receive-Job -Job $script:installJob -ErrorAction SilentlyContinue)
        foreach ($event in $events) {
            if ($event.Kind -eq 'step') {
                $index = [int]$event.Index
                $stateNames = @{running='进行中';done='完成';warning='待配置/确认';error='未完成';skipped='未选择'}
                $stepLabels[$index].Text = ('{0:00}   {1}                         {2}' -f ($index+1),$stepNames[$index],$stateNames[$event.Status])
                if ($event.Status -eq 'done') { $stepLabels[$index].ForeColor=[Drawing.Color]::FromArgb(36,139,95); $progress.Value=[Math]::Min(8,$index+1) }
                elseif ($event.Status -eq 'error') { $stepLabels[$index].ForeColor=[Drawing.Color]::FromArgb(190,72,72) }
                else { $stepLabels[$index].ForeColor=[Drawing.Color]::FromArgb(36,93,224) }
                $message.Text = $event.Message
            } elseif ($event.Kind -eq 'complete' -or $event.Kind -eq 'failed') {
                $script:terminalState=$true
                $message.Text=$event.Message
                $start.Enabled=$true
                $start.Text=if($event.Kind -eq 'failed'){'重试未完成步骤'}else{'再次检查（需重新领取）'}
                if($event.Kind -eq 'complete'){$progress.Value=8;$launch.Enabled=[bool]$event.Claude;$launchHarness.Enabled=[bool]$event.Harness}
            }
        }
        if ($script:installJob.State -in @('Completed','Failed','Stopped')) {
            if (-not $script:terminalState) { $message.Text='助手未能完成，请重新下载安装包后重试。';$start.Enabled=$true;$start.Text='重试' }
            Remove-Job -Job $script:installJob -Force
            $script:installJob=$null
            $close.Enabled=$true
            $chooseClaude.Enabled=$true;$chooseHarness.Enabled=$true
        }
    }
})
$start.Add_Click({
    if (-not $chooseClaude.Checked -and -not $chooseHarness.Checked) { $message.Text='请至少勾选Claude Code或DeepSeek Harness，也可以同时勾选。';return }
    $chosen = @();if($chooseClaude.Checked){$chosen+='claude-code'};if($chooseHarness.Checked){$chosen+='deepseek-harness'}
    $start.Enabled=$false;$close.Enabled=$false;$script:terminalState=$false;$progress.Value=0
    $chooseClaude.Enabled=$false;$chooseHarness.Enabled=$false;$launch.Enabled=$false;$launchHarness.Enabled=$false
    $message.Text='正在准备安装…'
    $script:installJob=Start-Job -FilePath (Join-Path $PSScriptRoot 'Setup.Core.ps1') -ArgumentList $PSScriptRoot,($chosen -join ',')
})
$form.Add_FormClosing({param($sender,$event)
    if($script:installJob){$event.Cancel=$true;$message.Text='正在安装，请等待当前步骤完成后关闭。'}
})
$form.Add_FormClosed({$timer.Stop();$timer.Dispose()})
if($Preview){$start.Enabled=$false;$message.Text='预览模式：不会安装软件、领取密钥或修改配置。'}
if($Preview -and $ScreenshotPath){
    $captureTimer=New-Object Windows.Forms.Timer;$captureTimer.Interval=700
    $captureTimer.Add_Tick({
        $captureTimer.Stop()
        $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
        $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
        $bitmap.Save($ScreenshotPath,[Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose();$captureTimer.Dispose()
    });$captureTimer.Start()
}
$timer.Start()
if($AutoCloseSeconds -gt 0){
    $autoTimer=New-Object Windows.Forms.Timer;$autoTimer.Interval=$AutoCloseSeconds*1000
    $autoTimer.Add_Tick({$autoTimer.Stop();$form.Close()});$autoTimer.Start()
}
[void]$form.ShowDialog()
$form.Dispose()
