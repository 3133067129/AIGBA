"""LLM 视觉提供方抽象（可插拔：ollama / claude / mock）。

决策层只依赖 VisionProvider 协议。
"""
from __future__ import annotations

import base64
import io

import numpy as np
import requests
from PIL import Image


class VisionError(RuntimeError):
    pass


class VisionProvider:
    """协议：describe(images, prompt) -> str"""

    def describe(self, images: list[np.ndarray], prompt: str) -> str:
        raise NotImplementedError


def _img_to_jpeg_b64(img: np.ndarray, max_side: int = 480) -> str:
    """numpy RGB -> JPEG base64；按最大边长缩放（游戏 240x160 原图即可）。"""
    pil = Image.fromarray(img)
    if max(pil.size) > max_side:
        ratio = max_side / max(pil.size)
        pil = pil.resize((int(pil.width * ratio), int(pil.height * ratio)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


class OllamaVision(VisionProvider):
    def __init__(self, base_url: str, model: str, timeout: int = 120,
                 num_ctx: int = 4096):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx  # 必须显式设置：默认 128k context 在本机加载失败

    def describe(self, images: list[np.ndarray], prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [_img_to_jpeg_b64(img) for img in images],
            }],
            "stream": False,
            "options": {"num_ctx": self.num_ctx},
        }
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload,
                                 timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except requests.RequestException:
            # fallback：GPU 分配失败 → 纯 CPU 重试（2026-08-06：
            # Ollama GPU 后端与驱动不匹配，num_gpu=0 可跑通）
            import time
            time.sleep(3)
            payload["options"]["num_gpu"] = 0
            resp = requests.post(f"{self.base_url}/api/chat", json=payload,
                                 timeout=self.timeout * 2)
            resp.raise_for_status()
            return resp.json()["message"]["content"]


class MockVision(VisionProvider):
    """离线/测试用：返回固定文本。"""

    def __init__(self, text: str = "（mock 场景描述）"):
        self.text = text

    def describe(self, images: list[np.ndarray], prompt: str) -> str:
        return self.text


def make_provider(cfg: dict) -> VisionProvider:
    """从 settings.yaml 的 llm 段构造 provider。"""
    provider = cfg.get("provider", "ollama")
    if provider == "ollama":
        return OllamaVision(
            base_url=cfg.get("base_url", "http://localhost:11434"),
            model=cfg["model"],
            timeout=cfg.get("timeout_sec", 120),
            num_ctx=cfg.get("num_ctx", 4096),
        )
    if provider == "mock":
        return MockVision()
    if provider == "claude":
        from .claude_vision import ClaudeVision  # 延迟导入（升级路径）
        return ClaudeVision(model=cfg["model"], api_key_env=cfg.get("api_key_env"))
    raise ValueError(f"unknown llm provider: {provider}")
