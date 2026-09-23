# Repeatable validation entrypoint. Offline by default; -Mode Test makes one synthetic cloud request.
param([ValidateSet('SelfTest','Smoke','Test')][string]$Mode = 'SelfTest')
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'assistant.ps1'
$report = Join-Path $PSScriptRoot ($Mode.ToLower() + '-results.json')
$preview = Join-Path $PSScriptRoot 'assistant-preview.png'
try {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($target,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw (($errors | ForEach-Object { 'line '+$_.Extent.StartLineNumber+': '+$_.Message }) -join '; ') }
    [IO.File]::WriteAllText($report,'{"status":"RUNNING"}',[Text.UTF8Encoding]::new($false))
    $argsMap = @{ReportPath=$report}; $argsMap[$Mode]=$true
    if ($Mode -eq 'Smoke') { $argsMap['PreviewPath']=$preview }
    & $target @argsMap
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
