# 口袋餐谋 / PocketMentor

AI 餐饮专家实时视频连麦原型：用户可以建立门店档案、上传餐饮案例视频，获取案例解构与迁移建议，再通过实时视频连麦补充现场信息。

这是一个可公开阅读的代码快照。仓库不包含 API key、私钥、Cookie、数据库或项目开发配置；示例素材和知识库中的第三方内容仍需遵守其原始授权与使用条款。

## 项目结构

- `4.产品-视频对照诊断MVP/backend/`：FastAPI 后端、视频解析、实时连麦和报告接口。
- `4.产品-视频对照诊断MVP/engine/decision_core/`：决策内核与平台知识库。
- `4.产品-视频对照诊断MVP/integration/`：离线复现与评估工具。
- `web/`：静态前端。
- `docs/product/`：产品与知识库设计文档。

## 本地运行

后端需要 Python 3.12。先复制环境变量模板，再按需填写自己的服务凭据；不要把填写后的文件提交到 Git。

```bash
cd 4.产品-视频对照诊断MVP/backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn yongge_online.main:app --host 127.0.0.1 --port 8010
```

前端可用任意静态服务器启动：

```bash
cd web
python -m http.server 5173 --bind 127.0.0.1
```

运行后端测试：

```bash
cd 4.产品-视频对照诊断MVP/backend
python -m pytest tests --ignore=tests/live
```

## 配置与安全

- 根目录和后端目录的 `.env.example` 只包含变量名和非敏感默认值。
- API 凭据通过环境变量读取，例如 `DEEPSEEK_API_KEY`、`YONGGE_DASHSCOPE_API_KEY` 和 `YONGGE_AMAP_WEB_SERVICE_KEY`。
- 生产环境请使用部署平台的 secret manager；不要提交 `.env`、私钥、Cookie、SQLite 文件、上传文件或运行日志。
- 发现疑似凭据泄露时，请立即撤销并轮换凭据，再清理 Git 历史和相关缓存。详见 [SECURITY.md](SECURITY.md)。

## 许可证与内容授权

本公开快照中的代码、文档、知识库条目和媒体素材可能具有不同的著作权或授权条件。发布或再利用前，请确认所有贡献者同意公开，并分别核实第三方内容的许可证；本仓库不对未明确授权的素材授予额外权利。


