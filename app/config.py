"""配置读写 + API Key 的 DPAPI 加密存储。"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import shutil
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "ScreenshotTranslate"


def _writable(path: Path) -> bool:
    """真的试着写一个文件——只看 ACL 不够，某些受限令牌下 os.access 会说谎。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_probe_{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _pick_home() -> Path:
    """决定配置/日志/模型放哪。

    顺序：环境变量 → %APPDATA% → exe 同级的 data\\ → %LOCALAPPDATA%。
    之所以要挑：某些受限环境（远程桌面、加固系统、虚拟化沙箱）里，
    进程对 %APPDATA% 没有写权限，硬写会导致保存失败、设置无法持久化。
    """
    env = os.environ.get("SCREENSHOT_TRANSLATE_HOME")
    if env:
        return Path(env)

    roaming = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    candidates = [roaming]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "data")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / APP_NAME)

    for candidate in candidates:
        if _writable(candidate):
            return candidate
    return roaming


APP_DIR = _pick_home()
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"

_save_warned = False


def _migrate_legacy_config() -> None:
    """回退到别的目录时，把 %APPDATA% 里已有的配置搬过来（DPAPI 密文同用户可解）。"""
    try:
        legacy = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "config.json"
        if CONFIG_PATH == legacy or CONFIG_PATH.exists() or not legacy.exists():
            return
        shutil.copy2(legacy, CONFIG_PATH)
    except Exception:
        pass


_migrate_legacy_config()


def resource_dir() -> Path:
    """打包后指向 PyInstaller 解包目录，源码运行时指向项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def dpapi_protect(text: str) -> str:
    if not text:
        return ""
    try:
        data_in = _blob(text.encode("utf-8"))
        data_out = DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(data_in), "ScreenshotTranslate", None, None, None, 0,
            ctypes.byref(data_out),
        )
        if not ok:
            return ""
        try:
            return "dpapi:" + base64.b64encode(_blob_bytes(data_out)).decode("ascii")
        finally:
            kernel32.LocalFree(data_out.pbData)
    except Exception:
        return ""


def dpapi_unprotect(token: str) -> str:
    if not token:
        return ""
    if not token.startswith("dpapi:"):
        return token  # 兼容手动填写的明文
    try:
        raw = base64.b64decode(token[6:])
        data_in = _blob(raw)
        data_out = DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
        )
        if not ok:
            return ""
        try:
            return _blob_bytes(data_out).decode("utf-8", "replace")
        finally:
            kernel32.LocalFree(data_out.pbData)
    except Exception:
        return ""


@dataclass
class Config:
    # 热键
    hotkey: str = "Alt+Q"

    # 翻译（OpenAI 兼容接口）
    api_base: str = "https://api.deepseek.com/v1"
    api_key: str = ""          # 内存中为明文，落盘时加密
    model: str = "deepseek-chat"
    target_lang: str = "中文"
    source_lang: str = "auto"
    temperature: float = 0.2
    timeout: int = 60

    # OCR
    ocr_engine: str = "rapidocr"
    ocr_upscale_retry: bool = True

    # 界面
    theme: str = "auto"        # auto | dark | light
    card_width: int = 440
    autostart: bool = False
    tray_hint_shown: bool = False

    # 其它
    copy_on_finish: bool = False

    _path: Path = field(default=CONFIG_PATH, repr=False, compare=False)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        p = Path(path) if path else CONFIG_PATH
        cfg = cls(_path=p)
        if not p.exists():
            return cfg
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cfg

        key_token = raw.pop("api_key", "")
        for k, v in raw.items():
            if hasattr(cfg, k) and not k.startswith("_"):
                try:
                    setattr(cfg, k, v)
                except Exception:
                    pass
        cfg.api_key = dpapi_unprotect(key_token)
        cfg._path = p
        return cfg

    def save(self) -> bool:
        """原子写配置。

        注意：这里**不能**用 tempfile.mkstemp —— 目标目录不可写时，
        它在 Windows 上会因 PermissionError 而重试到 TMP_MAX（21 亿次），
        表现为主线程死循环、CPU 跑满、界面完全无响应。
        """
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(self)
            data.pop("_path", None)
            key = self.api_key
            data["api_key"] = dpapi_protect(key) if key else ""
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self._path)
            return True
        except Exception as exc:
            global _save_warned
            if not _save_warned:
                _save_warned = True
                logging.getLogger(__name__).warning(
                    "配置保存失败（后续不再提示）：%s", exc
                )
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    def endpoint(self) -> str:
        base = (self.api_base or "").strip().rstrip("/")
        if not base:
            raise ValueError("未配置 API 地址")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1") or base.endswith("/v1beta"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"
