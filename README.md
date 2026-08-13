# Cat Agent

面向用户的宠物体况咨询 Agent 原型。当前先搭建独立框架：用户通过网页聊天提供宠物数据，系统收集关键信息，初步判断超重/肥胖风险并给出建议。

## 当前能力

- 公开聊天网页: http://localhost:8000
- 流式回复接口: `/api/chat/stream`
- 会话内宠物资料累积
- 本地规则版肥胖风险评估
- 无头像、无气泡聊天 UI，AI 回复支持复制

## 首次本地运行

```powershell
Copy-Item .env.example .env
.\run-local.ps1
```

## Docker 运行

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

## 架构

```text
web/index.html
  -> FastAPI /api/chat/stream
  -> core.assessment.PetProfile
  -> core.assessment.assess_pet()
  -> SSE 流式返回
```

## 后续扩展方向

- 接入 AstrBot 或其他 LLM，让模型负责自然语言追问和结构化抽取。
- 增加猫/犬品种标准体重参考表。
- 增加 BCS 图文引导。
- 增加多宠物档案、历史体重曲线和复诊建议。
- 增加兽医免责声明、危险症状识别和转诊提示。

## 免责声明

本项目只用于健康管理建议和风险提示，不替代兽医诊断。若宠物出现快速消瘦/增重、食欲异常、饮水异常、呕吐腹泻、精神沉郁等情况，应及时就医。
