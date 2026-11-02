<#
.SYNOPSIS
  本机模拟 RTMP：MediaMTX 收流 + ffmpeg 循环推现有大疆成片。
.DESCRIPTION
  协议模拟，不是播放器演示。默认推 20 秒后停，JPEG 会进 Job 队列。
.EXAMPLE
  .\scripts\simulate_rtmp.ps1
  .\scripts\simulate_rtmp.ps1 -Duration 60
#>
param(
    [double]$Duration = 20,
    [string]$Video = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Root "src"
$argsList = @("-m", "uva", "ingest-rtmp", "--duration", "$Duration")
if ($Video) { $argsList += @("--video", $Video) }
& $VenvPython @argsList
