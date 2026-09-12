from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import asdict, dataclass, field

from core.assessment import PetProfile
from core.model_config import get_api_base_url, get_api_key, get_vision_model
from core.prompt_config import get_system_prompt

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at runtime
    OpenAI = None


@dataclass
class FoodLabelFacts:
    product_name: str = ""
    brand: str = ""
    raw_text: str = ""
    source: str = "manual"
    confidence: float | None = None
    energy_kcal_per_kg: float | None = None
    energy_kcal_per_100g: float | None = None
    protein_pct: float | None = None
    fat_pct: float | None = None
    fiber_pct: float | None = None
    ash_pct: float | None = None
    moisture_pct: float | None = None
    calcium_pct: float | None = None
    phosphorus_pct: float | None = None
    sodium_pct: float | None = None
    ingredients: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.brand or self.product_name:
            parts.append("".join(x for x in [self.brand, self.product_name] if x))
        if self.energy_kcal_per_kg is not None:
            parts.append(f"{self.energy_kcal_per_kg:g} kcal/kg")
        elif self.energy_kcal_per_100g is not None:
            parts.append(f"{self.energy_kcal_per_100g:g} kcal/100g")
        if self.protein_pct is not None:
            parts.append(f"粗蛋白 {self.protein_pct:g}%")
        if self.fat_pct is not None:
            parts.append(f"粗脂肪 {self.fat_pct:g}%")
        if self.moisture_pct is not None:
            parts.append(f"水分 {self.moisture_pct:g}%")
        return "；".join(parts) if parts else "未识别到可用的营养信息"


@dataclass
class FeedingPlan:
    goal: str
    meals_per_day: int
    rer_kcal: float | None
    der_kcal: float | None
    life_stage_factor: float | None
    life_stage: str
    target_weight_kg: float | None
    daily_kcal_low: float | None
    daily_kcal_high: float | None
    daily_grams_low: float | None
    daily_grams_high: float | None
    per_meal_grams_low: float | None
    per_meal_grams_high: float | None
    title: str
    summary: str
    bullets: list[str]
    cautions: list[str]
    missing: list[str]


GOAL_ALIASES = {
    "maintain": "maintain",
    "维持": "maintain",
    "维持体重": "maintain",
    "减重": "weight_loss",
    "减脂": "weight_loss",
    "weight_loss": "weight_loss",
    "增重": "gain",
    "恢复": "gain",
    "gain": "gain",
    "幼宠": "growth",
    "成长": "growth",
    "growth": "growth",
}


def parse_pet_profile_payload(payload) -> PetProfile:
    if not isinstance(payload, dict):
        return PetProfile()
    profile = PetProfile()
    if payload.get("species") in ("cat", "dog"):
        profile.species = payload["species"]
    if isinstance(payload.get("breed"), str):
        profile.breed = payload["breed"].strip()
    if payload.get("age_months") is not None:
        profile.age_months = _coerce_int(payload.get("age_months"))
    if payload.get("weight_kg") is not None:
        profile.weight_kg = _coerce_float(payload.get("weight_kg"))
    if payload.get("body_condition_score") is not None:
        profile.body_condition_score = _coerce_int(payload.get("body_condition_score"))
    if payload.get("neutered") is not None:
        profile.neutered = _coerce_bool(payload.get("neutered"))
    if isinstance(payload.get("activity_level"), str):
        profile.activity_level = payload["activity_level"].strip()
    if isinstance(payload.get("diet_note"), str):
        profile.diet_note = payload["diet_note"].strip()
    if isinstance(payload.get("symptoms"), list):
        profile.symptoms = [str(item).strip() for item in payload["symptoms"] if str(item).strip()]
    return profile


def parse_goal(goal: str, profile: PetProfile) -> str:
    normalized = GOAL_ALIASES.get(str(goal).strip(), "")
    if normalized:
        return normalized
    if profile.age_months is not None and profile.age_months < 12:
        return "growth"
    if profile.body_condition_score is not None and profile.body_condition_score >= 7:
        return "weight_loss"
    return "maintain"


def analyze_food_label(
    image_bytes: bytes | None = None,
    image_name: str = "",
    supplement_text: str = "",
) -> FoodLabelFacts:
    raw_text = supplement_text.strip()
    source = "manual"
    if image_bytes and get_api_key().strip() and OpenAI is not None:
        ai_result = _extract_with_openai(image_bytes, image_name, supplement_text)
        if _label_has_data(ai_result):
            return ai_result
        if not raw_text:
            raw_text = ai_result.notes[0] if ai_result.notes else ""
        source = ai_result.source
    facts = parse_food_label_text(raw_text, source=source)
    if not raw_text and image_bytes:
        facts.notes.append("图片已上传，但当前未配置可用的视觉识别后端；请补充 OCR 文本或配置 OpenAI_API_KEY。")
    return facts


def parse_food_label_text(text: str, source: str = "manual") -> FoodLabelFacts:
    normalized = normalize_label_text(text)
    facts = FoodLabelFacts(raw_text=text.strip(), source=source)
    if not normalized:
        return facts

    facts.product_name = _extract_product_name(normalized)
    facts.brand = _extract_brand(normalized)
    facts.energy_kcal_per_kg, facts.energy_kcal_per_100g = _extract_energy(normalized)
    facts.protein_pct = _extract_pct(normalized, ("粗蛋白", "粗蛋白质", "蛋白质"))
    facts.fat_pct = _extract_pct(normalized, ("粗脂肪", "脂肪"))
    facts.fiber_pct = _extract_pct(normalized, ("粗纤维", "纤维"))
    facts.ash_pct = _extract_pct(normalized, ("粗灰分", "灰分"))
    facts.moisture_pct = _extract_pct(normalized, ("水分",))
    facts.calcium_pct = _extract_pct(normalized, ("钙",))
    facts.phosphorus_pct = _extract_pct(normalized, ("磷",))
    facts.sodium_pct = _extract_pct(normalized, ("钠",))
    facts.ingredients = _extract_ingredients(normalized)
    facts.notes = _extract_notes(normalized)
    return facts


def build_feeding_plan(
    profile: PetProfile,
    label: FoodLabelFacts,
    goal: str = "maintain",
    meals_per_day: int = 2,
) -> FeedingPlan:
    meals_per_day = max(1, min(int(meals_per_day or 2), 6))
    normalized_goal = parse_goal(goal, profile)
    missing = []
    if profile.weight_kg is None:
        missing.append("宠物体重")
    if profile.species not in ("cat", "dog"):
        missing.append("宠物种类")

    target_weight = _estimate_target_weight(profile, normalized_goal)
    rer_kcal, der_kcal, life_stage_factor, life_stage = _estimate_energy(profile, normalized_goal, target_weight)
    daily_kcal = der_kcal
    daily_kcal_low = round(daily_kcal * 0.9, 0) if daily_kcal is not None else None
    daily_kcal_high = round(daily_kcal * 1.1, 0) if daily_kcal is not None else None

    kcal_per_gram = _kcal_per_gram(label)
    daily_grams_low = daily_grams_high = per_meal_low = per_meal_high = None
    if daily_kcal_low is not None and daily_kcal_high is not None and kcal_per_gram:
        daily_grams_low = round(daily_kcal_low / kcal_per_gram, 1)
        daily_grams_high = round(daily_kcal_high / kcal_per_gram, 1)
        per_meal_low = round(daily_grams_low / meals_per_day, 1)
        per_meal_high = round(daily_grams_high / meals_per_day, 1)

    title = _goal_title(normalized_goal)
    summary = _build_summary(profile, label, normalized_goal, target_weight, daily_kcal_low, daily_kcal_high, daily_grams_low, daily_grams_high, meals_per_day)
    bullets = _build_bullets(profile, label, normalized_goal, meals_per_day, daily_grams_low, daily_grams_high)
    cautions = _build_cautions(profile, label, normalized_goal)

    if label.energy_kcal_per_kg is None and label.energy_kcal_per_100g is None:
        missing.append("营养表中的代谢能/能量值")

    return FeedingPlan(
        goal=normalized_goal,
        meals_per_day=meals_per_day,
        rer_kcal=round(rer_kcal, 0) if rer_kcal is not None else None,
        der_kcal=round(der_kcal, 0) if der_kcal is not None else None,
        life_stage_factor=life_stage_factor,
        life_stage=life_stage,
        target_weight_kg=target_weight,
        daily_kcal_low=daily_kcal_low,
        daily_kcal_high=daily_kcal_high,
        daily_grams_low=daily_grams_low,
        daily_grams_high=daily_grams_high,
        per_meal_grams_low=per_meal_low,
        per_meal_grams_high=per_meal_high,
        title=title,
        summary=summary,
        bullets=bullets,
        cautions=cautions,
        missing=missing,
    )


def format_feeding_reply(profile: PetProfile, label: FoodLabelFacts, plan: FeedingPlan) -> str:
    lines = [f"{plan.title}"]
    lines.append(f"宠物信息：{profile.summary()}")
    lines.append(f"营养表识别：{label.summary()}")
    if plan.target_weight_kg is not None:
        lines.append(f"建议参考体重：{plan.target_weight_kg:g}kg")
    if plan.rer_kcal is not None:
        lines.append(f"静息能量需求 RER：{plan.rer_kcal:g} kcal/天")
    if plan.der_kcal is not None:
        factor_text = f"（系数 {plan.life_stage_factor:g}）" if plan.life_stage_factor is not None else ""
        stage_text = f"；阶段：{plan.life_stage}" if plan.life_stage else ""
        lines.append(f"每日能量需求 DER：{plan.der_kcal:g} kcal/天 {factor_text}{stage_text}".rstrip())
    if plan.daily_kcal_low is not None and plan.daily_kcal_high is not None:
        lines.append(f"每日热量：{plan.daily_kcal_low:g}-{plan.daily_kcal_high:g} kcal")
    if plan.daily_grams_low is not None and plan.daily_grams_high is not None:
        lines.append(
            f"按当前这款粮换算：{plan.daily_grams_low:g}-{plan.daily_grams_high:g}g/天，"
            f"分 {plan.meals_per_day} 餐时约 {plan.per_meal_grams_low:g}-{plan.per_meal_grams_high:g}g/餐。"
        )
    else:
        lines.append("这张图里没有识别到明确的代谢能，暂时只能给出热量目标，无法精确换算成克数。")
    if plan.missing:
        lines.append("还缺少这些信息：")
        lines.extend(f"- {item}" for item in plan.missing)
    if plan.bullets:
        lines.append("执行建议：")
        lines.extend(f"- {item}" for item in plan.bullets)
    if plan.cautions:
        lines.append("注意：")
        lines.extend(f"- {item}" for item in plan.cautions)
    return "\n".join(lines)


def plan_to_dict(profile: PetProfile, label: FoodLabelFacts, plan: FeedingPlan) -> dict:
    return {
        "profile": asdict(profile),
        "label": asdict(label),
        "plan": asdict(plan),
        "reply_text": format_feeding_reply(profile, label, plan),
    }


def normalize_label_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("　", " ").replace("㎏", "kg").replace("ＫＧ", "kg")
    normalized = normalized.replace("千卡/公斤", "kcal/kg").replace("千卡/100克", "kcal/100g")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized.strip()


def _extract_with_openai(image_bytes: bytes, image_name: str, supplement_text: str) -> FoodLabelFacts:
    api_key = get_api_key()
    if not api_key or OpenAI is None:
        return FoodLabelFacts(raw_text=supplement_text.strip(), source="openai-unavailable")

    model = get_vision_model()
    mime_type = mimetypes.guess_type(image_name or "")[0] or "image/jpeg"
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    client_kwargs = {"api_key": api_key}
    api_base_url = get_api_base_url()
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    client = OpenAI(**client_kwargs)
    prompt = get_system_prompt("vision")
    if supplement_text.strip():
        prompt += f"用户补充文字：{supplement_text.strip()}"

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", "") or ""
        data = _parse_json_object(text)
        if not data:
            return FoodLabelFacts(raw_text=text.strip(), source=f"openai:{model}", notes=["图片识别结果无法解析为 JSON。"])
        return _food_label_from_dict(data, source=f"openai:{model}")
    except Exception as exc:  # pragma: no cover - network/model failures are runtime only
        return FoodLabelFacts(
            raw_text=supplement_text.strip(),
            source=f"openai:{model}:error",
            notes=[f"OpenAI 图片识别失败：{exc}"],
        )


def _food_label_from_dict(data: dict, source: str) -> FoodLabelFacts:
    facts = FoodLabelFacts(source=source)
    facts.product_name = str(data.get("product_name", "") or "").strip()
    facts.brand = str(data.get("brand", "") or "").strip()
    facts.raw_text = str(data.get("raw_text", "") or "").strip()
    facts.confidence = _coerce_float(data.get("confidence"))
    facts.energy_kcal_per_kg = _coerce_float(data.get("energy_kcal_per_kg"))
    facts.energy_kcal_per_100g = _coerce_float(data.get("energy_kcal_per_100g"))
    facts.protein_pct = _coerce_float(data.get("protein_pct"))
    facts.fat_pct = _coerce_float(data.get("fat_pct"))
    facts.fiber_pct = _coerce_float(data.get("fiber_pct"))
    facts.ash_pct = _coerce_float(data.get("ash_pct"))
    facts.moisture_pct = _coerce_float(data.get("moisture_pct"))
    facts.calcium_pct = _coerce_float(data.get("calcium_pct"))
    facts.phosphorus_pct = _coerce_float(data.get("phosphorus_pct"))
    facts.sodium_pct = _coerce_float(data.get("sodium_pct"))
    facts.ingredients = [str(item).strip() for item in data.get("ingredients", []) if str(item).strip()] if isinstance(data.get("ingredients"), list) else []
    facts.notes = [str(item).strip() for item in data.get("notes", []) if str(item).strip()] if isinstance(data.get("notes"), list) else []
    return facts


def _label_has_data(facts: FoodLabelFacts) -> bool:
    return any(
        [
            facts.product_name,
            facts.brand,
            facts.raw_text,
            facts.energy_kcal_per_kg is not None,
            facts.energy_kcal_per_100g is not None,
            facts.protein_pct is not None,
            facts.fat_pct is not None,
            facts.fiber_pct is not None,
            facts.ash_pct is not None,
            facts.moisture_pct is not None,
            facts.calcium_pct is not None,
            facts.phosphorus_pct is not None,
            facts.sodium_pct is not None,
            facts.ingredients,
            facts.notes,
        ]
    )


def _parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_product_name(text: str) -> str:
    patterns = [
        r"(?:品名|产品名称|名称)[:：]\s*([^\n；;]{2,40})",
        r"(?:适用对象|系列)[:：]\s*([^\n；;]{2,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if re.search(r"(?:kcal|粗蛋白|粗脂肪|粗纤维|粗灰分|水分|钙|磷|钠|代谢能|%|保证成分|原料|配料|成分|配方)", candidate, re.I):
            continue
        return candidate[:40]
    return ""


def _extract_brand(text: str) -> str:
    match = re.search(r"(?:品牌|厂商|生产商)[:：]\s*([^\n；;]{2,30})", text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_energy(text: str) -> tuple[float | None, float | None]:
    compact = text.replace(" ", "")
    patterns = [
        r"(?:代谢能|能量|ME)[:：]?(?:约)?(\d+(?:\.\d+)?)kcal/kg",
        r"(?:代谢能|能量|ME)[:：]?(?:约)?(\d+(?:\.\d+)?)千卡/?公斤",
        r"(?:代谢能|能量|ME)[:：]?(?:约)?(\d+(?:\.\d+)?)kcal/100g",
        r"(?:代谢能|能量|ME)[:：]?(?:约)?(\d+(?:\.\d+)?)千卡/?100g",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.I)
        if not match:
            continue
        value = _coerce_float(match.group(1))
        if value is None:
            continue
        if "100g" in pattern or "100g" in match.group(0):
            return None, value
        if "千卡/?100g" in pattern or "100g" in pattern:
            return None, value
        return value, round(value / 10.0, 2) if "kg" in pattern.lower() or "公斤" in pattern else None
    # Support standalone "3600 kcal/kg" lines.
    match = re.search(r"(\d+(?:\.\d+)?)\s*kcal/kg", compact, re.I)
    if match:
        value = _coerce_float(match.group(1))
        return value, round(value / 10.0, 2) if value is not None else (None, None)
    match = re.search(r"(\d+(?:\.\d+)?)\s*kcal/100g", compact, re.I)
    if match:
        value = _coerce_float(match.group(1))
        return None, value
    return None, None


def _extract_pct(text: str, keys: tuple[str, ...]) -> float | None:
    compact = text.replace(" ", "")
    for key in keys:
        match = re.search(rf"{re.escape(key)}[:：]?(?:约)?(\d+(?:\.\d+)?)\s*%?", compact)
        if match:
            return _coerce_float(match.group(1))
    return None


def _extract_ingredients(text: str) -> list[str]:
    markers = ("原料", "配料", "成分", "配方")
    for marker in markers:
        match = re.search(rf"{marker}[:：]?\s*([^\n]+)", text)
        if match:
            raw = match.group(1)
            raw = re.split(r"(?:保证成分|营养成分|分析保证值|粗蛋白|粗脂肪|粗纤维|水分)", raw)[0]
            parts = re.split(r"[、,，;；/]", raw)
            cleaned = [part.strip() for part in parts if part.strip()]
            if cleaned:
                return cleaned[:8]
    return []


def _extract_notes(text: str) -> list[str]:
    notes = []
    if "适口性" in text:
        notes.append("图中包含适口性描述")
    if "幼猫" in text or "幼犬" in text:
        notes.append("这款粮看起来可能有成长阶段定位")
    if "成猫" in text or "成犬" in text:
        notes.append("这款粮看起来可能是成年宠物配方")
    return notes


def _build_summary(
    profile: PetProfile,
    label: FoodLabelFacts,
    goal: str,
    target_weight: float | None,
    daily_kcal_low: float | None,
    daily_kcal_high: float | None,
    daily_grams_low: float | None,
    daily_grams_high: float | None,
    meals_per_day: int,
) -> str:
    parts = []
    parts.append(f"当前目标：{_goal_title(goal)}")
    if target_weight is not None:
        parts.append(f"参考体重 {target_weight:g}kg")
    if daily_kcal_low is not None and daily_kcal_high is not None:
        parts.append(f"每日 {daily_kcal_low:g}-{daily_kcal_high:g} kcal")
    if daily_grams_low is not None and daily_grams_high is not None:
        parts.append(f"对应 {daily_grams_low:g}-{daily_grams_high:g}g/天")
        parts.append(f"分 {meals_per_day} 餐后约 {round(daily_grams_low / meals_per_day, 1):g}-{round(daily_grams_high / meals_per_day, 1):g}g/餐")
    if label.energy_kcal_per_kg is not None or label.energy_kcal_per_100g is not None:
        parts.append("已识别到代谢能，可换算克数")
    else:
        parts.append("未识别到代谢能，只能先给热量目标")
    if profile.body_condition_score is not None and profile.body_condition_score >= 7:
        parts.append("当前更适合先控量，不建议猛减")
    return "；".join(parts)


def _build_bullets(
    profile: PetProfile,
    label: FoodLabelFacts,
    goal: str,
    meals_per_day: int,
    daily_grams_low: float | None,
    daily_grams_high: float | None,
) -> list[str]:
    bullets = [
        "每天固定时间喂，先按同一把秤连续记录 1-2 周。",
        "零食和罐头也要算进总热量，不要只盯主粮。",
        "换粮时用 5-7 天渐进过渡，观察粪便、食欲和呕吐情况。",
    ]
    if daily_grams_low is not None and daily_grams_high is not None:
        bullets.insert(0, f"当前这款粮可先从 {daily_grams_low:g}-{daily_grams_high:g}g/天 起步，分 {meals_per_day} 餐。")
    if goal == "weight_loss":
        bullets.append("减重期建议每 1-2 周复称一次，若体重不降可小幅下调 5-10%。")
    elif goal == "growth":
        bullets.append("幼宠成长更看重稳定供能，别为了控肥把量压得太低。")
    if profile.neutered:
        bullets.append("绝育宠物更容易热量过剩，零食最好也纳入上限。")
    return bullets


def _build_cautions(profile: PetProfile, label: FoodLabelFacts, goal: str) -> list[str]:
    cautions = []
    if profile.weight_kg is None:
        cautions.append("缺少体重，热量目标只能先做粗略估计。")
    if profile.body_condition_score is None:
        cautions.append("缺少 BCS，建议尽快补充体况评分。")
    if label.energy_kcal_per_kg is None and label.energy_kcal_per_100g is None:
        cautions.append("缺少代谢能，建议重新拍清楚能量值或补充 OCR 文本。")
    if any(symptom in ("不吃", "呕吐", "腹泻", "精神差") for symptom in profile.symptoms):
        cautions.append("如果它最近有不吃、呕吐、腹泻或精神差，先排查疾病再谈控量。")
    if goal == "weight_loss" and profile.species == "cat":
        cautions.append("猫减重不要太快，避免脂肪肝风险。")
    return cautions


def _goal_title(goal: str) -> str:
    return {
        "maintain": "维持体重",
        "weight_loss": "减重/控肥",
        "gain": "增重/恢复",
        "growth": "幼宠成长",
    }.get(goal, "维持体重")


def _kcal_per_gram(label: FoodLabelFacts) -> float | None:
    if label.energy_kcal_per_100g is not None:
        return label.energy_kcal_per_100g / 100.0
    if label.energy_kcal_per_kg is not None:
        return label.energy_kcal_per_kg / 1000.0
    return None


def _estimate_target_weight(profile: PetProfile, goal: str) -> float | None:
    if profile.weight_kg is None:
        return None
    if goal == "weight_loss":
        if profile.body_condition_score is not None and profile.body_condition_score >= 8:
            return round(profile.weight_kg * 0.8, 2)
        if profile.body_condition_score == 7:
            return round(profile.weight_kg * 0.9, 2)
        return round(profile.weight_kg * 0.95, 2)
    if goal == "gain":
        return round(profile.weight_kg * 1.1, 2)
    return round(profile.weight_kg, 2)


def _estimate_daily_kcal(profile: PetProfile, goal: str, target_weight: float | None) -> float | None:
    _, der, _, _ = _estimate_energy(profile, goal, target_weight)
    return round(der, 0) if der is not None else None


def _estimate_energy(profile: PetProfile, goal: str, target_weight: float | None) -> tuple[float | None, float | None, float | None, str]:
    base_weight = target_weight or profile.weight_kg
    if base_weight is None:
        return None, None, None, ""
    rer = 70 * (base_weight ** 0.75)
    factor = _maintenance_factor(profile, goal)
    return rer, rer * factor, factor, _life_stage_name(profile, goal)


def _maintenance_factor(profile: PetProfile, goal: str) -> float:
    if goal == "growth":
        return 2.4 if profile.species == "cat" else 3.0
    if goal == "gain":
        return 1.4 if profile.species == "cat" else 1.8
    if goal == "weight_loss":
        base = 0.8 if profile.species == "cat" else 1.0
    else:
        base = 1.2 if profile.species == "cat" else 1.5
    if profile.neutered:
        base -= 0.05 if profile.species == "cat" else 0.1
    if profile.activity_level == "低":
        base -= 0.1
    elif profile.activity_level == "高":
        base += 0.1
    return max(base, 0.6)


def _life_stage_name(profile: PetProfile, goal: str) -> str:
    if goal == "weight_loss":
        return "减重"
    if goal == "growth":
        return "幼宠成长"
    if profile.neutered:
        return "成年已绝育"
    return "成年未绝育"


def _coerce_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _coerce_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _coerce_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "是", "已绝育", "绝育"):
        return True
    if text in ("0", "false", "no", "off", "否", "未绝育", "没有"):
        return False
    return None
