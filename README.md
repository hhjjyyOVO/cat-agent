# Cat Agent

面向用户的宠物体况咨询与喂食建议智能体。当前支持两条主线：

- 聊天咨询：根据宠物信息初步判断超重、肥胖或营养风险。
- 拍粮分析：上传宠物粮营养成分参考表，结合宠物数据给出每日喂食建议。

## 当前能力

- 公开聊天网页：`http://localhost:8010`
- 喂食建议接口：`POST /api/ai/feeding`
- 会话内宠物资料累计和新对话重置
- 本地规则版体况咨询：支持猫、狗、年龄、体重、绝育、BCS、活动量和饮食线索
- 拍照识别营养表：在 `data/ai_models.txt` 里配置 `API_BASE_URL` 和 `API_KEY` 后可直接识别图片并提取营养成分
- 图片不清晰时，可直接粘贴 OCR 文本
- 自动换算每日热量与每餐克数，并给出喂食和换粮建议
- 喂食面板默认折叠，点击顶部“喂食”按钮或按 `Ctrl+Alt+F` 打开

## 本地运行

```powershell
Copy-Item .env.example .env
.\run-local.ps1
```

## Docker 运行

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

本机 Docker 默认映射到 `http://localhost:8010`，容器内服务也监听 `8010`。
Compose 默认使用固定镜像标签 `cat-agent:v1.0.1`，不会使用 `latest`。部署到阿里云 ACR 时，可在 `.env` 中将 `IMAGE_REPOSITORY` 改为 `crpi-8mk2whxt6twzwk7w.cn-beijing.personal.cr.aliyuncs.com/hzau-china-purffit-agent/cat-agent`，最终镜像地址为 `crpi-8mk2whxt6twzwk7w.cn-beijing.personal.cr.aliyuncs.com/hzau-china-purffit-agent/cat-agent:v1.0.1`。

## 喂食接口示例

### 表单上传

```powershell
curl -X POST http://localhost:8010/api/ai/feeding `
  -F "session_id=test" `
  -F "pet_text=我家英短，5岁，6.8kg，已绝育，BCS 7/9，平时不太爱动" `
  -F "goal=weight_loss" `
  -F "meals_per_day=2" `
  -F "image=@food-label.jpg"
```

### JSON 调用

```json
{
  "session_id": "test",
  "goal": "maintain",
  "meals_per_day": 2,
  "pet_profile": {
    "species": "cat",
    "breed": "英短",
    "age_months": 60,
    "weight_kg": 6.8,
    "body_condition_score": 7,
    "neutered": true,
    "activity_level": "低"
  },
  "label_text": "代谢能 3600 kcal/kg，粗蛋白 32%，粗脂肪 16%"
}
```

## 环境变量

- `data/ai_models.txt`：容器内独立文本配置，控制 `API_BASE_URL`、`API_KEY`、聊天模型和识图模型。该文件只保存在本机，不提交到 Git。
- `data/ai_models.example.txt`：无密钥配置模板，可复制为 `data/ai_models.txt` 后填写。
- `data/system_prompts.txt`：容器内独立文本配置，分别控制聊天、喂食建议和营养表识图的系统提示词。
- `WEB_PORT`：服务端口，默认 `8010`。
- `HOST_PORT`：Docker 宿主机映射端口，默认 `8010`。
- `AI_MODEL_CONFIG_PATH`：可选，自定义模型配置文本路径。
- `AI_SYSTEM_PROMPTS_PATH`：可选，自定义系统提示词文本路径。
- `API_BASE_URL`：可选，SAE 或系统环境变量中的模型接口地址；会覆盖 `data/ai_models.txt`。
- `API_KEY`：可选，SAE 或系统环境变量中的模型密钥；会覆盖 `data/ai_models.txt`。
- `CHAT_MODEL`：可选，SAE 或系统环境变量中的聊天模型；会覆盖 `data/ai_models.txt`。
- `VISION_MODEL`：可选，SAE 或系统环境变量中的识图模型；会覆盖 `data/ai_models.txt`。

首次配置模型：

```powershell
Copy-Item data/ai_models.example.txt data/ai_models.txt
notepad data/ai_models.txt
```

请勿把真实 API Key 写入 `.env.example`、代码仓库或 Dockerfile。

## 架构

```text
web/index.html
  -> FastAPI /api/chat/stream
  -> FastAPI /api/ai/feeding
  -> core.assessment.PetProfile
  -> core.feeding.FoodLabelFacts
  -> core.feeding.build_feeding_plan()
```

## 说明

本项目只用于健康管理建议和风险提示，不替代兽医诊断。若宠物出现快速消瘦或增重、食欲异常、饮水排尿异常、呕吐腹泻、精神沉郁、呼吸困难、抽搐、便血等情况，应及时就医。
