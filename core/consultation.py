from __future__ import annotations

from dataclasses import asdict
import json
from typing import Iterable

from core.assessment import PetProfile
from core.feeding import FoodLabelFacts, FeedingPlan
from core.model_config import get_api_base_url, get_api_key, get_chat_model
from core.prompt_config import get_system_prompt

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional runtime dependency
    OpenAI = None


MAX_HISTORY_MESSAGES = 8


def generate_llm_reply(
    message: str,
    profile: PetProfile,
    history: list[dict[str, str]] | None = None,
    model_path: str | None = None,
) -> str | None:
    api_key = get_api_key(model_path)
    if not api_key or OpenAI is None:
        return None

    model = get_chat_model(model_path)
    client_kwargs: dict[str, str] = {"api_key": api_key}
    api_base_url = get_api_base_url(model_path)
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    client = OpenAI(**client_kwargs)

    messages = [{"role": "system", "content": build_system_prompt(profile)}]
    messages.extend(normalize_history(history or [])[-MAX_HISTORY_MESSAGES:])
    messages.append(
        {
            "role": "user",
            "content": build_user_prompt(message, profile),
        }
    )

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
    )
    reply = _extract_reply_text(response)
    return reply.strip() if reply else None


def generate_feeding_advice(
    profile: PetProfile,
    label: FoodLabelFacts,
    plan: FeedingPlan,
    model_path: str | None = None,
) -> str | None:
    api_key = get_api_key(model_path)
    if not api_key or OpenAI is None:
        return None

    model = get_chat_model(model_path)
    client_kwargs: dict[str, str] = {"api_key": api_key}
    api_base_url = get_api_base_url(model_path)
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    client = OpenAI(**client_kwargs)

    messages = [
        {
            "role": "system",
            "content": get_system_prompt("feeding"),
        },
        {
            "role": "user",
            "content": build_feeding_prompt(profile, label, plan),
        },
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.35,
    )
    reply = _extract_reply_text(response)
    return reply.strip() if reply else None


def build_system_prompt(profile: PetProfile) -> str:
    missing = profile.missing_fields()
    profile_summary = profile.summary()
    subject = profile.display_subject()
    base_prompt = get_system_prompt("chat")
    context = (
        f"当前咨询对象：{subject}。"
        f"已知资料：{profile_summary}。"
        f"仍缺信息：{'; '.join(missing) if missing else '无'}。"
    )
    return f"{base_prompt}\n{context}".strip() if base_prompt else context


def build_user_prompt(message: str, profile: PetProfile) -> str:
    payload = {
        "pet_profile": asdict(profile),
        "pet_summary": profile.summary(),
        "latest_user_message": message,
    }
    return (
        "请基于下面的宠物信息和最新用户消息回复。"
        "如果用户明显在问喂食量、体况、减重或营养问题，请直接给建议。"
        "如果缺少关键数据，请先提问。"
        "如果出现呕吐、腹泻、便血、呼吸困难、抽搐、明显不吃等危险情况，请先建议尽快就医。\n\n"
        f"{payload}"
    )


def normalize_history(history: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _extract_reply_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if not message:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    text = part.get("text") or part.get("content") or ""
                    if text:
                        parts.append(str(text))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def build_feeding_prompt(profile: PetProfile, label: FoodLabelFacts, plan: FeedingPlan) -> str:
    payload = {
        "pet_profile": asdict(profile),
        "label": asdict(label),
        "plan": asdict(plan),
        "task": "基于这些数据生成喂食建议，优先解释 RER 和 DER，再给出每日和每餐喂食量。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
