# 截屏翻译

[![Release](https://img.shields.io/github/v/release/JesonAndFirst/screenshot-translate?label=%E4%B8%8B%E8%BD%BD&color=4c9aff)](https://github.com/JesonAndFirst/screenshot-translate/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/JesonAndFirst/screenshot-translate/total?label=%E4%B8%8B%E8%BD%BD%E9%87%8F)](https://github.com/JesonAndFirst/screenshot-translate/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows)](https://github.com/JesonAndFirst/screenshot-translate)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)

Windows 上按住一个热键 → 框选屏幕区域 → 自动 OCR + LLM 翻译，结果显示在一张悬浮卡片里。

对标 Snipaste 的操作手感：**没有确认步骤**，松开鼠标就开始识别。

> **不想折腾代码？** 到 [Releases](https://github.com/JesonAndFirst/screenshot-translate/releases/latest)
> 下载 `截屏翻译-v0.1.0-win64.zip`，解压双击即可，不需要安装 Python。

## 功能

- 全局热键唤起（默认 `Alt+Q`，可在设置里改）
- 冻结屏幕后框选，支持**多显示器**、**混合 DPI**、负坐标副屏
- 放大镜 + 取色（HEX）+ 物理像素坐标
- 本地 OCR（RapidOCR / onnxruntime，中英混排，完全离线）
- LLM 翻译（任何 OpenAI 兼容接口：DeepSeek / OpenAI / Moonshot / 通义 / vLLM …）
- 结果卡片：缩略图 + 原文 + 译文，可拖动、可复制、可重译
- 托盘常驻、单实例、开机自启、深/浅色主题跟随系统

## 环境

- Windows 10 1903+ / Windows 11
- Python 3.11 – 3.13

## 安装

```powershell
pip install -r requirements.txt
```

首次识别时会自动下载 OCR 模型（约 20MB）到 `%APPDATA%\ScreenshotTranslate\models`，
之后完全离线。

## 配置

启动后右键托盘图标 → **设置…**，填写：

| 项 | 说明 | 示例 |
|---|---|---|
| 截图热键 | 必须带 Ctrl / Alt / Shift | `Alt+Q` |
| API 地址 | OpenAI 兼容的 base url | `https://api.deepseek.com/v1` |
| API Key | 用 Windows DPAPI 加密后落盘 | `sk-…` |
| 模型 | 服务商的模型名 | `deepseek-chat` |
| 翻译为 | 目标语言 | `中文` |

填完可以点「测试连接」验证。配置存在 `%APPDATA%\ScreenshotTranslate\config.json`。

## 使用

```powershell
python run.py          # 带控制台，方便看日志
pythonw run.py         # 后台运行，只有托盘图标
```

1. 按 `Alt+Q`，屏幕定格变暗
2. 拖拽框选要翻译的区域（Esc / 右键取消）
3. 松开鼠标 → 卡片出现，先显示原文，再显示译文
4. `复制译文` / `重译` / `✕`

卡片内按 `Esc` 关闭，`Ctrl+C` 复制译文。

## 项目结构

```
run.py                      入口：先设 DPI 感知，再加载 Qt
app/
  config.py                 配置读写 + DPAPI 加密
  app_controller.py         总装：热键 → 截图 → 选区 → OCR → 翻译 → 卡片
  win32/
    dpi.py                  Per-Monitor V2 DPI 感知
    monitors.py             显示器枚举（物理像素）与 QScreen 绑定
    capture.py              GDI BitBlt 截屏
    winutils.py             光标/置顶/抢焦点/截图排除
    hotkey.py               RegisterHotKey 全局热键
  core/
    geometry.py             物理像素 ↔ Qt 逻辑像素
    grouping.py             OCR 行 → 段落
    pipeline.py             OCR + 翻译流水线（线程池）
  ocr/rapidocr_engine.py    RapidOCR 封装
  mt/llm.py                 OpenAI 兼容翻译客户端
  ui/
    overlay.py              冻结层 + 选区（每屏一个窗口）
    result_card.py          结果卡片
    settings.py             设置对话框
    tray.py                 托盘
    theme.py                主题
```

## 关键实现说明

**多屏与 DPI**：每块显示器一个冻结层窗口，窗口几何用 `SetWindowPos` 按物理像素精确摆放；
鼠标位置一律取 Win32 `GetCursorPos`（物理像素），不经过 Qt 的虚拟桌面逻辑坐标。
这样混合 DPI 下不会出现内容缩放错位或选区偏移。

**OCR 性能**：RapidOCR 默认配置会把宽图放大到 3000+ 像素宽（2.4s）；
改成 `limit_type=max / 1600`、`rec_batch_num=1`、onnxruntime 3 线程后降到 ~0.5s。

**翻译**：整个选区一次请求，提示词要求保留换行、不翻译代码/快捷键/URL，
返回纯译文。已中文则不重复翻译。

**隐私**：只把 OCR 出来的文本发给翻译服务，图片不出本机。

## 打包分发

一条命令出包：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

产物：

| 路径 | 说明 |
|---|---|
| `release\截屏翻译\` | 目录版，双击 `ScreenshotTranslate.exe` 即用 |
| `release\截屏翻译-v0.1.0-win64.zip` | 发给别人的压缩包（约 130 MB） |

朋友拿到 zip 后：**解压 → 双击 exe → 托盘右键“设置”填 API Key**，不需要装 Python。

打包用**目录版**而不是单文件，原因有三：

1. 单文件每次启动都要把约 300 MB 运行时解压到临时目录，冷启动 5–10 秒；
2. 自解压行为最容易被安全软件拦截；
3. 目录版缺文件时能直接看出来，好排查。

打包后可以用内置自检确认产物完整（会截一块屏幕做 OCR）：

```powershell
& '.\release\截屏翻译\ScreenshotTranslate.exe' --selftest
```

结果写到 `%APPDATA%\ScreenshotTranslate\selftest.txt`。

`models\` 目录里需要三个 onnx 模型（det / rec / cls）。源码方式跑过一次之后，
可以从 `%APPDATA%\ScreenshotTranslate\models` 复制过来。

## 已知限制

- 独占全屏游戏、UAC 安全桌面、部分受保护内容抓不到（GDI 的限制）
- 超长译文在卡片里是滚动区，不支持原地覆盖原文
- OCR 在极小字号 / 极低对比度下会漏字，可框大一点

## 排错

| 现象 | 处理 |
|---|---|
| 按热键没反应 | 热键被别的软件占用，设置里换一个 |
| **托盘图标看不到** | Windows 11 默认把新图标收进任务栏的 `^` 折叠区：点 `^` 展开后拖到任务栏，或在「设置 → 个性化 → 任务栏 → 系统托盘图标」里打开。**再双击一次 exe 会直接弹出设置窗口**，不用依赖图标 |
| 提示「没有配置 API Key」 | 托盘 → 设置，填 Key 后点测试连接 |
| 识别不到文字 | 看日志 `%APPDATA%\ScreenshotTranslate\logs\app.log` |
| 首次识别很慢 | 模型首次加载需要 2–3 秒，之后 0.5 秒左右 |
