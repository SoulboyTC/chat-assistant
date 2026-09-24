# Repeatable validation entrypoint. Offline by default; -Mode Test makes one synthetic cloud request.
param([ValidateSet('SelfTest','Smoke','Test','Stress')][string]$Mode = 'SelfTest')
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'assistant.ps1'
$logDir = Join-Path $PSScriptRoot '验证记录'
if (-not (Test-Path -LiteralPath $logDir)) { [void][IO.Directory]::CreateDirectory($logDir) }
$report = Join-Path $logDir ($Mode.ToLower() + '-results.json')
$preview = Join-Path $PSScriptRoot 'docs\preview.png'
try {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($target,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw (($errors | ForEach-Object { 'line '+$_.Extent.StartLineNumber+': '+$_.Message }) -join '; ') }
    [IO.File]::WriteAllText($report,'{"status":"RUNNING"}',[Text.UTF8Encoding]::new($false))
    $argsMap = @{ReportPath=$report}; $argsMap[$Mode]=$true
    if ($Mode -eq 'Smoke') {
        $docsDir = Split-Path -Parent $preview
        if (-not (Test-Path -LiteralPath $docsDir)) { [void][IO.Directory]::CreateDirectory($docsDir) }
        $argsMap['PreviewPath']=$preview
    }
    & $target @argsMap
    # Stress 模式不写 validator_completed，也不走 PASS 复核：
    # 它靠真实窗口 + 定时器跑，异常收集在报告自身的 errors 里。
    if ($Mode -eq 'Stress') {
        $stressResult = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($report))
        if ($stressResult.status -ne 'PASS') { exit 1 }
        exit 0
    }
    $result = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($report))
    if ($result.status -ne 'PASS') { exit 1 }
    $result | Add-Member -NotePropertyName validator_completed -NotePropertyValue $true -Force
    [IO.File]::WriteAllText($report,($result | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    exit 0
} catch {
    $obj = @{status='FAIL'; error=$_.Exception.Message; at=$_.InvocationInfo.PositionMessage; trace=$_.ScriptStackTrace}
    [IO.File]::WriteAllText($report,($obj | ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
    exit 1
}
