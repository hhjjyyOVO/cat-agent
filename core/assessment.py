from __future__ import annotations

from dataclasses import dataclass, field


SPECIES_LABELS = {
    "cat": "猫",
    "dog": "狗",
}


@dataclass
class PetProfile:
    species: str = ""
    breed: str = ""
    age_months: int | None = None
    weight_kg: float | None = None
    body_condition_score: int | None = None
    neutered: bool | None = None
    activity_level: str = ""
    diet_note: str = ""
    symptoms: list[str] = field(default_factory=list)

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.species:
            missing.append("宠物种类：猫或狗")
        if self.age_months is None:
            missing.append("年龄：例如 3岁、8个月")
        if self.weight_kg is None:
            missing.append("当前体重：例如 5.6kg、12斤")
        if self.body_condition_score is None:
            missing.append("体况 BCS：1-9 分；不知道也可以描述肋骨、腰线、肚腩")
        if self.neutered is None:
            missing.append("是否绝育")
        return missing

    def summary(self) -> str:
        parts = []
        if self.species:
            parts.append(SPECIES_LABELS.get(self.species, self.species))
        if self.breed:
            parts.append(self.breed)
        if self.age_months is not None:
            if self.age_months >= 12:
                years = self.age_months / 12
                parts.append(f"{years:g}岁")
            else:
                parts.append(f"{self.age_months}个月")
        if self.weight_kg is not None:
            parts.append(f"{self.weight_kg:g}kg")
        if self.body_condition_score is not None:
            parts.append(f"BCS {self.body_condition_score}/9")
        if self.neutered is not None:
            parts.append("已绝育" if self.neutered else "未绝育")
        if self.activity_level:
            parts.append(f"活动量{self.activity_level}")
        return "，".join(parts) if parts else "还没有足够信息"

    def display_subject(self) -> str:
        if self.breed:
            return f"这只{self.breed}"
        if self.species:
            return f"这只{SPECIES_LABELS.get(self.species, '宠物')}"
        return "这只宠物"


@dataclass
class AssessmentResult:
    level: str
    reason: str
    suggestions: list[str]
    red_flags: list[str]
    next_questions: list[str]


def assess_pet(profile: PetProfile) -> AssessmentResult:
    score = 0
    reasons = []

    if profile.body_condition_score is not None:
        bcs = profile.body_condition_score
        if bcs >= 8:
            score += 4
            reasons.append(f"BCS {bcs}/9 通常提示肥胖风险较高")
        elif bcs == 7:
            score += 3
            reasons.append("BCS 7/9 通常提示已经超重")
        elif bcs == 6:
            score += 1
            reasons.append("BCS 6/9 通常提示轻度超重")
        elif 4 <= bcs <= 5:
            reasons.append("BCS 4-5/9 通常接近理想体况")
        else:
            reasons.append("BCS 偏低，当前重点不是减重，而是确认营养和健康状态")

    if profile.weight_kg is not None:
        score += _weight_risk_score(profile)
        weight_reason = _weight_reason(profile)
        if weight_reason:
            reasons.append(weight_reason)

    if profile.neutered:
        score += 1
        reasons.append("绝育后基础能量需求可能下降，体重更容易上升")

    if profile.activity_level == "低":
        score += 1
        reasons.append("日常活动量偏低，会增加热量盈余的可能")

    if score >= 5:
        level = "肥胖风险较高"
    elif score >= 2:
        level = "可能超重"
    else:
        level = "暂未显示明显肥胖风险"

    if profile.body_condition_score is not None and profile.body_condition_score <= 3:
        level = "可能偏瘦或营养风险"

    red_flags = detect_red_flags(profile.symptoms)
    suggestions = build_suggestions(profile, score)
    next_questions = build_next_questions(profile)
    return AssessmentResult(
        level=level,
        reason="；".join(reasons) or "目前信息较少，只能做保守判断",
        suggestions=suggestions,
        red_flags=red_flags,
        next_questions=next_questions,
    )


def _weight_risk_score(profile: PetProfile) -> int:
    if profile.species == "cat":
        if profile.weight_kg >= 7:
            return 2
        if profile.weight_kg >= 5.5:
            return 1
    if profile.species == "dog":
        # Dog body size differs greatly by breed; weight alone is a weak signal.
        if profile.weight_kg >= 35 and not profile.breed:
            return 1
    return 0


def _weight_reason(profile: PetProfile) -> str:
    if profile.species == "cat":
        if profile.weight_kg >= 7:
            return "体重已达到多数家猫需要重点关注的区间"
        if profile.weight_kg >= 5.5:
            return "体重处于不少家猫的偏高区间，需要结合体型和 BCS 判断"
    if profile.species == "dog" and not profile.breed:
        return "狗的标准体重受品种和体型影响很大，单看体重只能作为弱参考"
    return ""


def detect_red_flags(symptoms: list[str]) -> list[str]:
    red_flags = []
    mapping = {
        "不吃": "超过 24 小时明显不吃或食欲骤降",
        "呕吐": "反复呕吐",
        "腹泻": "持续腹泻或便血",
        "精神差": "精神沉郁、虚弱或不愿活动",
        "喝水多": "饮水量明显增加",
        "尿多": "排尿明显增加",
        "呼吸": "呼吸急促或费力",
        "疼痛": "明显疼痛、哀叫或抗拒触碰",
    }
    for token, text in mapping.items():
        if any(token in symptom for symptom in symptoms):
            red_flags.append(text)
    return list(dict.fromkeys(red_flags))


def build_suggestions(profile: PetProfile, score: int) -> list[str]:
    suggestions = [
        "连续 2-4 周记录体重、每日主粮量、零食量和运动量，先确认趋势。",
        "用厨房秤称量主粮，不要只按“几把”或“半碗”估算。",
        "每天安排 2-3 次短时间互动活动，比如逗猫棒、追逐玩具、嗅闻游戏或食物益智玩具。",
    ]
    if score >= 2:
        suggestions.insert(1, "在兽医确认健康状态后，再考虑逐步减少每日热量，避免突然断食。")
    if profile.species == "cat":
        suggestions.append("猫减重不宜过快，通常需要循序渐进，避免脂肪肝风险。")
    if profile.neutered:
        suggestions.append("可以和兽医讨论是否需要调整为绝育后体重管理配方。")
    if profile.body_condition_score is not None and profile.body_condition_score <= 3:
        suggestions = [
            "不要以减重为目标，先记录食欲、精神、排便和体重变化。",
            "如果近期消瘦、食欲下降或精神变差，建议尽快就医排查。",
            "在兽医确认健康前，不建议自行大幅调整饮食。",
        ]
    return suggestions


def build_next_questions(profile: PetProfile) -> list[str]:
    questions = []
    if not profile.diet_note:
        questions.append("它每天大概吃多少主粮、罐头和零食？")
    if not profile.activity_level:
        questions.append("平时活动量偏低、一般，还是比较高？")
    if profile.species == "dog" and not profile.breed:
        questions.append("狗狗的品种或大概体型是小型、中型还是大型？")
    return questions[:2]
