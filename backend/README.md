# Camoufox 控制台后端（Local API）

FastAPI + SQLite 编排层，供 `frontend/` 通过 `VITE_API_BASE` 对接。

## 启动

```bash
# 推荐：仓库脚本
scripts\dev-backend.bat          # Windows
bash scripts/dev-backend.sh      # macOS/Linux

# 或手动
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 50325
```

健康检查：http://127.0.0.1:50325/api/v1/health

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CAMOUFOX_CONSOLE_DATA` | `backend/data` | SQLite 与数据目录 |
| `CAMOUFOX_PROFILE_ROOT` | `data/profiles` | Profile `user_data_dir` |
| `CAMOUFOX_API_TOKEN` | `cf_dev_token_mock_8f3a` | Bearer Token（可选校验） |
| `CAMOUFOX_REAL_LAUNCH` | `0` | `1` 时用 Camoufox/Playwright 真实启停 |
| `CAMOUFOX_VERSION` | `152.0.4-beta.28` | 全局 Active 版本展示 |

## 真实启停（Windows 示例）

```bat
cd backend
set CAMOUFOX_REAL_LAUNCH=1
uvicorn app.main:app --host 127.0.0.1 --port 50325
```

需已安装 `camoufox` + `playwright`，且本机有可用 Camoufox 二进制。启动逻辑见 `app/launch.py`（Cookie / startUrl / 指纹策略 / 代理 geoip）。

真机一键脚本：`scripts\dev-backend-real.bat`（设置 `CAMOUFOX_REAL_LAUNCH=1` + `PYTHONPATH=pythonlib`）。

未开启时，`POST .../start` 走 mock 状态机。

## MVP 手测（指纹 / 版本 / 导入）

1. `GET /api/v1/fingerprint-templates` 应有 `tpl_auto` / `tpl_preset`
2. 新建自定义模板 → `POST .../sample` → `hasConfig=true` → 建环境 `fingerprintStrategy=template` + `templateId` → 启动日志**不应**再出现「暂以 preset 代替」
3. `GET /api/v1/browser/versions` 反映 `multiversion.list_installed`；`POST /api/v1/browser/active`
4. `POST /api/v1/proxies/import`；删除仍被引用的代理应 **409**
5. `DELETE /api/v1/profiles/{id}` 后 Profile 目录不存在

## 前端对接

```bash
# frontend/.env
VITE_API_BASE=http://127.0.0.1:50325
```

契约：[`docs/api-contract.md`](../docs/api-contract.md)
