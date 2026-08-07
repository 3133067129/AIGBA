"""Ollama 视觉模型中文读图评测工具。

用法: python tools/ocr_test.py [image_path]
- 不传图片路径时，自动生成一张模拟绿宝石界面的中文文字图（simhei 字体）
- 输出模型的识别文本，人工对比准确率
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from PIL import Image, ImageDraw, ImageFont

CONFIG_PATH = ROOT / "config" / "settings.yaml"

FONT_CANDIDATES = [
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]


def make_test_image(size=(240, 160)) -> Image.Image:
    """生成模拟游戏对话/菜单界面的文字图。"""
    img = Image.new("RGB", size, (248, 248, 200))  # 游戏对话框米黄色底
    draw = ImageDraw.Draw(img)
    font = None
    for f in FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(f, 14)
            break
        except OSError:
            continue
    if font is None:
        raise RuntimeError("no CJK font found")

    lines = [
        "皮卡丘，使用十万伏特！",
        "效果绝佳！",
        "对面的拉达倒下了。",
        "获得 120 经验值！",
        "是否使用精灵球？ 是/否",
    ]
    y = 8
    for line in lines:
        draw.text((8, y), line, font=font, fill=(8, 8, 8))
        y += 24
    return img


def query_ollama(img: Image.Image, base_url: str, model: str, prompt: str,
                 num_ctx: int = 4096) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    resp = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [b64],
            }],
            "stream": False,
            "options": {"num_ctx": num_ctx},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def main() -> None:
    import yaml
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    llm = cfg["llm"]

    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    img = Image.open(img_path) if img_path else make_test_image()

    shot_dir = ROOT / "data" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    if img_path is None:
        img.save(shot_dir / "ocr_test_zh.png")

    prompt = ("请识别这张图片里的全部文字，逐行列出，不要解释。"
              "这是宝可梦绿宝石游戏的中文界面截图。")
    text = query_ollama(img, llm["base_url"], llm["model"], prompt)
    print("=== 模型识别结果 ===")
    print(text)
    print("=== 期望文本 ===")
    if img_path is None:
        for line in ["皮卡丘，使用十万伏特！", "效果绝佳！", "对面的拉达倒下了。",
                     "获得 120 经验值！", "是否使用精灵球？ 是/否"]:
            print(" ", line)


if __name__ == "__main__":
    main()
