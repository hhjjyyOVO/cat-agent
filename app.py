"""
Cat Agent - public pet health chat prototype.

This project is intentionally standalone from D:\\project\\agent. It provides a
small FastAPI app, a web chat UI, and a local pet obesity assessment engine that
can later be connected to AstrBot or another LLM runtime.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import uvicorn

from core.assessment import PetProfile, assess_pet

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))
APP_NAME = os.getenv("APP_NAME", "Cat Agent")

app = FastAPI(title=APP_NAME)
SESSIONS: dict[str, PetProfile] = {}


@app.get("/")
async def chat_ui():
    return FileResponse(
        os.path.join(BASE_DIR, "web", "index.html"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME}


@app.post("/api/chat/stream")
async def api_chat_stream(request: Request):
    body = await request.json()
    session_id = str(body.get("session_id", "")).strip() or str(uuid.uuid4())
    message = str(body.get("message", "")).strip()
    if not message:
        return JSONResponse({"error": "请输入消息。"}, status_code=400)

    profile = SESSIONS.setdefault(session_id, PetProfile())
    profile = merge_pet_profile(profile, extract_pet_profile(message))
    SESSIONS[session_id] = profile
    reply = build_reply(message, profile)

    async def stream():
        for chunk in chunk_text(reply):
            payload = {"type": "plain", "data": chunk, "streaming": True}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'complete', 'data': ''}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def extract_pet_profile(message: str) -> PetProfile:
    """Lightweight extraction for the scaffold; replace with LLM extraction later."""
    profile = PetProfile()
    text = message.strip()

    if re.search(r"猫|英短|美短|布偶|暹罗|狸花|缅因|橘猫", text):
        profile.species = "cat"
    elif re.search(r"狗|犬|金毛|泰迪|柯基|拉布拉多|边牧", text):
        profile.species = "dog"

    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|公斤|千克|斤)", text, re.I)
    if weight_match:
        value = float(weight_match.group(1))
        unit = weight_match.group(2).lower()
        profile.weight_kg = round(value / 2, 2) if unit == "斤" else value

    age_match = re.search(r"(\d+(?:\.\d+)?)\s*(岁|个月|月)", text)
    if age_match:
        value = float(age_match.group(1))
        unit = age_match.group(2)
        profile.age_months = int(value * 12) if unit == "岁" else int(value)

    bcs_match = re.search(r"(?:bcs|体况|体态|体况评分)\s*[:：]?\s*(\d)(?:\s*/\s*9)?", text, re.I)
    if bcs_match:
        profile.body_condition_score = int(bcs_match.group(1))

    if re.search(r"绝育|已绝育|去势", text):
        profile.neutered = True
    elif re.search(r"未绝育|没有绝育", text):
        profile.neutered = False

    breed_match = re.search(r"(英短|美短|布偶|暹罗|狸花|缅因|橘猫|金毛|泰迪|柯基|拉布拉多|边牧)", text)
    if breed_match:
        profile.breed = breed_match.group(1)

    return profile


def merge_pet_profile(current: PetProfile, extracted: PetProfile) -> PetProfile:
    merged = PetProfile(**asdict(current))
    for key, value in asdict(extracted).items():
        if value not in (None, "", []):
            setattr(merged, key, value)
    return merged


def build_reply(message: str, profile: PetProfile) -> str:
    missing = profile.missing_fields()
    if missing:
        return (
            "我可以帮你初步判断宠物是否有超重或肥胖风险。\n\n"
            f"我目前已记录：{profile.summary()}\n\n"
            "还需要这些信息：\n"
            + "\n".join(f"- {item}" for item in missing)
            + "\n\n你可以直接一句话告诉我，比如：我家英短，5岁，6.8kg，已绝育，BCS 7/9。"
        )

    result = assess_pet(profile)
    return (
        f"根据你提供的信息，{profile.display_subject()} 的初步判断是：{result.level}。\n\n"
        f"依据：{result.reason}\n\n"
        "建议：\n"
        + "\n".join(f"- {item}" for item in result.suggestions)
        + "\n\n这不是兽医诊断。如果宠物近期体重快速变化、食欲异常、饮水变多或活动明显下降，建议尽快咨询兽医。"
    )


def chunk_text(text: str, size: int = 16):
    for index in range(0, len(text), size):
        yield text[index:index + size]


if __name__ == "__main__":
    print("=" * 50)
    print(f"{APP_NAME} 启动中...")
    print(f"聊天界面: http://localhost:{WEB_PORT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT)
