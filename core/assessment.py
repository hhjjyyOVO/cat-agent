from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PetProfile:
    species: str = ""
    breed: str = ""
    age_months: int | None = None
    weight_kg: float | None = None
    body_condition_score: int | None = None
    neutered: bool | None = None

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.species:
            missing.append("宠物种类（猫/狗，当前框架优先支持猫）")
        if not self.age_months:
            missing.append("年龄")
        if not self.weight_kg:
            missing.append("当前体重")
        if self.body_condition_score is None:
            missing.append("体况评分 BCS（1-9分；不知道也可以描述腰线、肋骨是否容易摸到）")
        if self.neutered is None:
            missing.append("是否绝育")
        return missing

    def summary(self) -> str:
        parts = []
        if self.species:
            parts.append("猫" if self.species == "cat" else self.species)
        if self.breed:
            parts.append(self.breed)
        if self.age_months:
            if self.age_months >= 12:
                years = self.age_months / 12
                parts.append(f"{years:g}岁")
            else:
                parts.append(f"{self.age_months}个月")
        if self.weight_kg:
            parts.append(f"{self.weight_kg:g}kg")
        if self.body_condition_score is not None:
            parts.append(f"BCS {self.body_condition_score}/9")
        if self.neutered is not None:
            parts.append("已绝育" if self.neutered else "未绝育")
        return "、".join(parts) if parts else "还没有足够信息"

    def display_subject(self) -> str:
        if self.breed:
            return f"这只{self.breed}"
        if self.species == "cat":
            return "这只猫"
        if self.species == "dog":
            return "这只狗"
        return "这只宠物"


@dataclass
class AssessmentResult:
    level: str
    reason: str
    suggestions: list[str]


def assess_pet(profile: PetProfile) -> AssessmentResult:
    score = 0
    reasons = []

    if profile.body_condition_score is not None:
        if profile.body_condition_score >= 8:
            score += 3
            reasons.append(f"BCS {profile.body_condition_score}/9 通常提示肥胖风险较高")
        elif profile.body_condition_score == 7:
            score += 2
            reasons.append("BCS 7/9 通常提示已有超重倾向")
        elif profile.body_condition_score == 6:
            score += 1
            reasons.append("BCS 6/9 通常提示轻度超重")
        elif 4 <= profile.body_condition_score <= 5:
            reasons.append("BCS 4-5/9 通常接近理想体况")
        else:
            reasons.append("BCS 偏低，肥胖风险不高，但需关注营养状态")

    if profile.weight_kg and profile.species == "cat":
        if profile.weight_kg >= 7:
            score += 2
            reasons.append("体重已达到多数家猫需要重点关注的区间")
        elif profile.weight_kg >= 5.5:
            score += 1
            reasons.append("体重处于不少家猫的偏高区间，需结合体型和 BCS 判断")

    if profile.neutered:
        score += 1
        reasons.append("绝育后基础能量需求可能下降，体重更容易上升")

    if score >= 4:
        level = "肥胖风险较高"
    elif score >= 2:
        level = "可能超重"
    else:
        level = "暂未显示明显肥胖风险"

    suggestions = build_suggestions(profile, score)
    return AssessmentResult(level=level, reason="；".join(reasons), suggestions=suggestions)


def build_suggestions(profile: PetProfile, score: int) -> list[str]:
    suggestions = [
        "连续2-4周记录体重、每日喂食量和零食量，先确认趋势。",
        "用厨房秤称量主粮，不要只按“几把”估算。",
        "每天安排2-3次短时间互动活动，例如逗猫棒、追逐玩具或食物益智玩具。",
    ]
    if score >= 2:
        suggestions.insert(1, "在兽医确认健康状态后，再考虑逐步减少每日热量，避免突然断食。")
    if profile.neutered:
        suggestions.append("绝育宠物可和兽医讨论是否需要调整为绝育后体重管理配方。")
    suggestions.append("每周体重下降不宜过快，猫尤其要避免快速减重。")
    return suggestions
