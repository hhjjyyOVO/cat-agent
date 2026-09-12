"""
Cat Agent - public pet body-condition consultation assistant.

The app is intentionally lightweight: FastAPI serves a chat UI, keeps an
in-memory profile per session, extracts basic pet facts with local rules, and
returns structured consultation guidance through SSE. It can later be wired to
AstrBot or another LLM runtime without changing the public web API.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
import uvicorn

from core.assessment import PetProfile, assess_pet
from core.consultation import generate_feeding_advice, generate_llm_reply
from core.feeding import (
    analyze_food_label,
    build_feeding_plan,
    parse_pet_profile_payload,
    plan_to_dict,
)
from core.model_config import ensure_model_config_file, load_model_config

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_PORT = int(os.getenv("WEB_PORT", "8010"))
APP_NAME = os.getenv("APP_NAME", "Cat Agent")
MODEL_CONFIG_PATH = os.getenv("AI_MODEL_CONFIG_PATH", os.path.join(BASE_DIR, "data", "ai_models.txt"))

ensure_model_config_file(MODEL_CONFIG_PATH)

app = FastAPI(title=APP_NAME)
SESSIONS: dict[str, PetProfile] = {}
CHAT_HISTORY: dict[str, list[dict[str, str]]] = {}

CAT_BREEDS = (
    "英短|英国短毛猫|美短|美国短毛猫|布偶|暹罗|狸花|缅因|橘猫|加菲|波斯|无毛猫|德文|金吉拉"
)
DOG_BREEDS = (
    "金毛|金毛寻回犬|泰迪|贵宾|柯基|拉布拉多|边牧|边境牧羊犬|柴犬|比熊|博美|哈士奇|萨摩耶|法斗|法国斗牛犬|雪纳瑞"
)


@app.get("/")
async def chat_ui():
    return FileResponse(
        os.path.join(BASE_DIR, "web", "index.html"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    model_config = load_model_config(MODEL_CONFIG_PATH)
    return {
        "status": "ok",
        "app": APP_NAME,
        "sessions": len(SESSIONS),
        "chat_ai_ready": bool(model_config.get("api_key", "").strip()),
        "feeding_ai_ready": bool(model_config.get("api_key", "").strip()),
        "api_base_url": model_config.get("api_base_url", ""),
        "chat_model": model_config.get("chat_model", "gpt-4o-mini"),
        "vision_model": model_config.get("vision_model", "gpt-4o-mini"),
        "model_config_path": MODEL_CONFIG_PATH,
    }


@app.post("/api/session/reset")
async def reset_session(request: Request):
    body = await request.json()
    session_id = str(body.get("session_id", "")).strip()
    if session_id:
        SESSIONS.pop(session_id, None)
        CHAT_HISTORY.pop(session_id, None)
    return {"ok": True}


@app.post("/api/ai/feeding")
async def api_ai_feeding(request: Request):
    payload = await parse_feeding_request(request)
    session_id = payload["session_id"] or str(uuid.uuid4())
    profile = SESSIONS.setdefault(session_id, PetProfile())
    profile = merge_pet_profile(profile, parse_pet_profile_payload(payload["pet_profile"]))
    profile = merge_pet_profile(profile, extract_pet_profile(payload["pet_text"]))
    SESSIONS[session_id] = profile

    label = analyze_food_label(
        image_bytes=payload["image_bytes"],
        image_name=payload["image_name"],
        supplement_text=payload["label_text"],
    )
    goal = payload["goal"]
    meals_per_day = payload["meals_per_day"]
    plan = build_feeding_plan(profile, label, goal=goal, meals_per_day=meals_per_day)
    response = plan_to_dict(profile, label, plan)
    llm_reply = None
    try:
        llm_reply = generate_feeding_advice(profile, label, plan, model_path=MODEL_CONFIG_PATH)
    except Exception as exc:
        print(f"Feeding LLM reply failed, falling back to deterministic advice: {exc}")
    response.update(
        {
            "status": "ok",
            "session_id": session_id,
            "goal": plan.goal,
            "feeding_ai_ready": bool(load_model_config(MODEL_CONFIG_PATH).get("api_key", "").strip()),
            "missing_profile_fields": profile.missing_fields(),
        }
    )
    if llm_reply:
        response["llm_reply"] = llm_reply
        response["reply_text"] = llm_reply
        response["llm_used"] = True
    else:
        response["llm_used"] = False
    return JSONResponse(response)


@app.get("/api/ai/feeding")
async def api_ai_feeding_page():
    return RedirectResponse(url="/", status_code=302)


@app.get("/api/chat/stream")
async def api_chat_stream_page():
    return RedirectResponse(url="/", status_code=302)


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
    reply = build_chat_reply(session_id, message, profile)

    async def stream():
        for chunk in chunk_text(reply):
            payload = {"type": "plain", "data": chunk, "streaming": True}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'complete', 'data': reply}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def build_chat_reply(session_id: str, message: str, profile: PetProfile) -> str:
    if is_emergency_message(message):
        reply = build_emergency_reply(profile)
        append_chat_history(session_id, message, reply)
        return reply

    reply = None
    try:
        reply = generate_llm_reply(
            message=message,
            profile=profile,
            history=CHAT_HISTORY.get(session_id, []),
            model_path=MODEL_CONFIG_PATH,
        )
    except Exception as exc:
        print(f"LLM reply failed, falling back to rule-based reply: {exc}")

    if not reply:
        reply = build_reply(message, profile)

    append_chat_history(session_id, message, reply)
    return reply


def append_chat_history(session_id: str, user_message: str, assistant_reply: str) -> None:
    history = CHAT_HISTORY.setdefault(session_id, [])
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
    if len(history) > 8:
        CHAT_HISTORY[session_id] = history[-8:]


def extract_pet_profile(message: str) -> PetProfile:
    """Rule-based extraction for a public prototype."""
    profile = PetProfile()
    text = normalize_text(message)

    if re.search(rf"猫|喵|{CAT_BREEDS}", text):
        profile.species = "cat"
    elif re.search(rf"狗|犬|汪|{DOG_BREEDS}", text):
        profile.species = "dog"

    breed_match = re.search(rf"({CAT_BREEDS}|{DOG_BREEDS})", text)
    if breed_match:
        profile.breed = breed_match.group(1)
        if re.search(rf"{CAT_BREEDS}", profile.breed):
            profile.species = "cat"
        if re.search(rf"{DOG_BREEDS}", profile.breed):
            profile.species = "dog"

    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|公斤|千克|斤|g|克)", text, re.I)
    if weight_match:
        value = float(weight_match.group(1))
        unit = weight_match.group(2).lower()
        if unit == "斤":
            value = value / 2
        elif unit in ("g", "克"):
            value = value / 1000
        profile.weight_kg = round(value, 2)

    age_match = re.search(r"(\d+(?:\.\d+)?)\s*(岁|周岁|个月|月)", text)
    if age_match:
        value = float(age_match.group(1))
        unit = age_match.group(2)
        profile.age_months = int(value * 12) if unit in ("岁", "周岁") else int(value)

    bcs_match = re.search(r"(?:bcs|体况|体态|体况评分)\s*[:：]?\s*(\d)(?:\s*/\s*9)?", text, re.I)
    if bcs_match:
        profile.body_condition_score = int(bcs_match.group(1))
    else:
        profile.body_condition_score = infer_bcs_from_description(text)

    if re.search(r"已绝育|绝育了|做过绝育|去势|已去势|噶了", text):
        profile.neutered = True
    elif re.search(r"未绝育|没有绝育|没绝育|没做绝育|未去势", text):
        profile.neutered = False

    if re.search(r"不爱动|不太爱动|不怎么动|很少动|懒|趴着|活动少|运动少", text):
        profile.activity_level = "低"
    elif re.search(r"正常活动|一般活动|活动一般", text):
        profile.activity_level = "中"
    elif re.search(r"很活跃|活动多|运动多|爱跑|精力旺盛", text):
        profile.activity_level = "高"

    diet_note = extract_diet_note(text)
    if diet_note:
        profile.diet_note = diet_note

    profile.symptoms = extract_symptoms(text)
    return profile


def normalize_text(text: str) -> str:
    return text.strip().replace("ＫＧ", "kg").replace("㎏", "kg")


def infer_bcs_from_description(text: str) -> int | None:
    high_tokens = ("摸不到肋骨", "肋骨摸不到", "没有腰线", "看不到腰", "肚子下垂", "肚腩", "圆滚滚", "很胖")
    mild_high_tokens = ("肋骨不好摸", "腰线不明显", "有点胖", "偏胖", "肉多")
    ideal_tokens = ("能摸到肋骨", "腰线明显", "体型正常", "不胖不瘦")
    low_tokens = ("肋骨很明显", "太瘦", "偏瘦", "骨头突出")
    if any(token in text for token in high_tokens):
        return 8
    if any(token in text for token in mild_high_tokens):
        return 6
    if any(token in text for token in ideal_tokens):
        return 5
    if any(token in text for token in low_tokens):
        return 3
    return None


def extract_diet_note(text: str) -> str:
    match = re.search(r"((?:每天|一天|每日).{0,40}(?:吃|主粮|猫粮|狗粮|罐头|零食).{0,40})", text)
    return match.group(1).strip("，。；; ") if match else ""


def extract_symptoms(text: str) -> list[str]:
    symptoms = []
    tokens = ("不吃", "食欲下降", "呕吐", "腹泻", "便血", "精神差", "嗜睡", "喝水多", "尿多", "呼吸", "疼痛")
    for token in tokens:
        if token in text:
            symptoms.append(token)
    return symptoms


def merge_pet_profile(current: PetProfile, extracted: PetProfile) -> PetProfile:
    merged = PetProfile(**asdict(current))
    for key, value in asdict(extracted).items():
        if value not in (None, "", []):
            if key == "symptoms":
                merged.symptoms = list(dict.fromkeys([*merged.symptoms, *value]))
            else:
                setattr(merged, key, value)
    return merged


def build_reply(message: str, profile: PetProfile) -> str:
    if is_emergency_message(message):
        return build_emergency_reply(profile)

    missing = profile.missing_fields()
    if missing:
        return (
            "我可以先帮你做宠物体况和肥胖风险的初步咨询。\n\n"
            f"我目前已记录：{profile.summary()}\n\n"
            "还需要补充：\n"
            + "\n".join(f"- {item}" for item in missing)
            + "\n\n你可以直接一句话发来，例如：我家英短，5岁，6.8kg，已绝育，BCS 7/9，平时不太爱动。"
        )

    result = assess_pet(profile)
    sections = [
        f"初步判断：{profile.display_subject()} {result.level}。",
        f"依据：{result.reason}。",
    ]

    if result.red_flags:
        sections.append(
            "需要优先留意的情况：\n"
            + "\n".join(f"- {item}" for item in result.red_flags)
            + "\n如果这些情况正在发生，建议尽快联系兽医，而不是先自行减重。"
        )

    sections.append("建议：\n" + "\n".join(f"- {item}" for item in result.suggestions))

    if result.next_questions:
        sections.append("为了把建议做得更贴近它，我还想确认：\n" + "\n".join(f"- {item}" for item in result.next_questions))

    sections.append("说明：这不是兽医诊断；如果近期体重快速变化、食欲异常、饮水排尿异常、呕吐腹泻或精神明显下降，请及时就医。")
    return "\n\n".join(sections)


def is_emergency_message(message: str) -> bool:
    text = normalize_text(message)
    return bool(re.search(r"急|马上|救命|不吃|反复呕吐|便血|呼吸困难|抽搐|站不起来|昏迷", text))


def build_emergency_reply(profile: PetProfile) -> str:
    subject = profile.display_subject()
    return (
        f"如果{subject}现在有呼吸困难、抽搐、昏迷、站不起来、持续呕吐、便血，或超过 24 小时明显不吃，请优先联系附近动物医院或急诊。\n\n"
        "在就医前可以先做三件事：\n"
        "- 保持安静和保暖，不要强行喂食或灌水。\n"
        "- 记录症状开始时间、呕吐/腹泻次数、最近吃过什么、是否误食异物或药物。\n"
        "- 带上疫苗、驱虫、既往病史和正在吃的药物信息。\n\n"
        "等紧急风险排除后，我再帮你整理体况、饮食和体重管理方案。"
    )


def chunk_text(text: str, size: int = 18):
    for index in range(0, len(text), size):
        yield text[index:index + size]


async def parse_feeding_request(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        image_file = form.get("image")
        image_bytes = await image_file.read() if hasattr(image_file, "read") else None
        image_name = getattr(image_file, "filename", "") if hasattr(image_file, "filename") else ""
        pet_profile = _parse_jsonish(form.get("pet_profile"))
        return {
            "session_id": str(form.get("session_id", "")).strip(),
            "pet_profile": pet_profile if isinstance(pet_profile, dict) else {},
            "pet_text": str(form.get("pet_text", "")).strip(),
            "label_text": str(form.get("label_text", "")).strip(),
            "goal": str(form.get("goal", "")).strip(),
            "meals_per_day": _coerce_int(form.get("meals_per_day"), default=2),
            "image_bytes": image_bytes,
            "image_name": image_name,
        }

    body = await request.json()
    image_bytes = None
    image_name = str(body.get("image_name", "")).strip()
    image_base64 = str(body.get("image_base64", "")).strip()
    if image_base64:
        image_bytes = _decode_image_base64(image_base64)
    pet_profile = body.get("pet_profile", {})
    if isinstance(pet_profile, str):
        pet_profile = _parse_jsonish(pet_profile)
    if not isinstance(pet_profile, dict):
        pet_profile = {}
    return {
        "session_id": str(body.get("session_id", "")).strip(),
        "pet_profile": pet_profile,
        "pet_text": str(body.get("pet_text", "")).strip(),
        "label_text": str(body.get("label_text", "")).strip(),
        "goal": str(body.get("goal", "")).strip(),
        "meals_per_day": _coerce_int(body.get("meals_per_day"), default=2),
        "image_bytes": image_bytes,
        "image_name": image_name,
    }


def _parse_jsonish(value):
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decode_image_base64(value: str) -> bytes | None:
    try:
        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        import base64

        return base64.b64decode(value, validate=True)
    except Exception:
        return None


def _coerce_int(value, default: int = 2) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


if __name__ == "__main__":
    print("=" * 50)
    print(f"{APP_NAME} 启动中...")
    print(f"聊天界面: http://localhost:{WEB_PORT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT)
