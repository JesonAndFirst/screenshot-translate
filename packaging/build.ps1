# 打包为可分发版本
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# 产物：
#   release\截屏翻译\ScreenshotTranslate.exe   可直接运行
#   release\截屏翻译-v0.1.0-win64.zip          发给别人的压缩包
#
# 说明：用 onedir（目录版）而不是 onefile（单文件）。
#   1. 启动快：单文件每次都要把 300MB 运行时解压到临时目录，冷启动 5–10 秒；
#   2. 更少误杀：单文件的自解压行为最容易被安全软件拦；
#   3. 便于排查：缺文件时能直接看出来。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYINSTALLER_CONFIG_DIR = Join-Path $root ".pyinstaller"
$name = "ScreenshotTranslate"
$release = Join-Path $root "release"
$appDir = Join-Path $release "截屏翻译"
$zip = Join-Path $release "截屏翻译-v0.1.0-win64.zip"

Write-Host "== 1/5 生成图标 ==" -ForegroundColor Cyan
python packaging\make_icon.py

Write-Host "== 2/5 检查 OCR 模型 ==" -ForegroundColor Cyan
if (-not (Test-Path "models\PP-OCRv6_det_small.onnx")) {
    throw "缺少 OCR 模型，请先把 onnx 模型放到 $root\models"
}

Write-Host "== 3/5 PyInstaller ==" -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name $name `
    --icon packaging\app.ico `
    --version-file packaging\version.txt `
    --add-data "models;models" `
    --collect-data rapidocr `
    --collect-submodules rapidocr `
    --collect-all onnxruntime `
    --exclude-module tkinter `
    --exclude-module matplotlib `
    --exclude-module pytest `
    --distpath "build_out" `
    run.py

if ($LASTEXITCODE -ne 0) { throw "打包失败" }

Write-Host "== 4/5 裁剪冗余文件 ==" -ForegroundColor Cyan
$internal = Join-Path $root "build_out\$name\_internal"
# rapidocr 自带的模型副本（我们用 --add-data models 覆盖，删掉省 30MB）
Remove-Item (Join-Path $internal "rapidocr\models") -Recurse -Force -ErrorAction SilentlyContinue
# 只用于视频捕获，OCR 用不到
Remove-Item (Join-Path $internal "cv2\opencv_videoio_ffmpeg*_64.dll") -Force -ErrorAction SilentlyContinue

Write-Host "== 5/5 组装 release ==" -ForegroundColor Cyan
Remove-Item $appDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $appDir | Out-Null
Copy-Item "build_out\$name\*" $appDir -Recurse -Force
Copy-Item "packaging\使用说明.txt" (Join-Path $appDir "使用说明.txt") -Force

# 先压到临时文件再改名：避免压缩失败时把上一版 zip 弄丢
# 注意扩展名必须是 .zip，Compress-Archive 不认 .tmp
$tmpZip = Join-Path $release "ScreenshotTranslate.partial.zip"
Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $appDir -DestinationPath $tmpZip -CompressionLevel Optimal
Move-Item $tmpZip $zip -Force

$exe = Join-Path $appDir "$name.exe"
$size = [math]::Round((Get-ChildItem $appDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
$zipSize = [math]::Round((Get-Item $zip).Length / 1MB, 1)

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host "目录版: $appDir  ($size MB)"
Write-Host "压缩包: $zip  ($zipSize MB)"
Write-Host ""
Write-Host "自检: & '$exe' --selftest"
Write-Host "     结果写到 %APPDATA%\ScreenshotTranslate\selftest.txt"
