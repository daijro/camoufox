# Camoufox Console API 契约（v0.5）

Base URL：`VITE_API_BASE`（例如 `http://127.0.0.1:50325`）

鉴权：可选 `Authorization: Bearer <CAMOUFOX_API_TOKEN>`（本地 MVP 可不带）

## 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/health` | 健康检查；`realLaunch` 反映 `CAMOUFOX_REAL_LAUNCH` |
| GET | `/api/v1/settings` | 系统设置 |
| GET | `/api/v1/profiles` | 环境列表（`?include_deleted=true`） |
| GET | `/api/v1/profiles/{id}` | 详情（含 `hasFingerprintConfig` / `restoreSession`） |
| POST | `/api/v1/profiles` | 创建（`restoreSession` 默认 true） |
| PATCH | `/api/v1/profiles/{id}` | 更新（可改 `restoreSession`） |
| POST | `/api/v1/profiles/{id}/start` | 启动；首次锁定指纹；条件注入 Cookie；加载 Console Home |
| POST | `/api/v1/profiles/{id}/stop` | 停止 |
| POST | `/api/v1/profiles/{id}/resample-fingerprint` | 重新采样并锁定指纹（须先停止；**409** if running） |
| POST | `/api/v1/profiles/{id}/trash` | 软删除 |
| POST | `/api/v1/profiles/{id}/restore` | 从回收站恢复 |
| DELETE | `/api/v1/profiles/{id}` | 彻底删除（含 `rmtree` Profile 目录） |
| GET | `/api/v1/runtime` | 运行中实例 |
| GET/POST | `/api/v1/proxies` | 代理列表 / 新建 |
| POST | `/api/v1/proxies/import` | 批量文本导入 |
| POST | `/api/v1/proxies/{id}/check` | 经代理探测公网出口 IP |
| DELETE | `/api/v1/proxies/{id}` | 删除；仍被环境引用时 **409** |
| GET/POST | `/api/v1/groups` | 分组 |
| PATCH | `/api/v1/groups/{id}` | 重命名 |
| DELETE | `/api/v1/groups/{id}` | 删除（环境归未分类） |
| GET/POST | `/api/v1/tags` | 标签 |
| DELETE | `/api/v1/tags/{id}` | 删除标签 |
| GET | `/api/v1/fingerprint-templates` | 指纹模板列表 |
| POST | `/api/v1/fingerprint-templates` | 新建自定义模板 |
| PATCH | `/api/v1/fingerprint-templates/{id}` | 更新 |
| POST | `/api/v1/fingerprint-templates/{id}/sample` | 采样固化 `config_json` |
| POST | `/api/v1/fingerprint-templates/{id}/default` | 设为全局默认 |
| POST | `/api/v1/fingerprint-templates/{id}/copy` | 复制为 custom |
| DELETE | `/api/v1/fingerprint-templates/{id}` | 仅 custom；被引用 **409** |
| GET | `/api/v1/browser/versions` | 本机已安装 + Active + 远程目录 |
| POST | `/api/v1/browser/active` | `{ "version": "..." }` 设 Active |
| POST | `/api/v1/browser/refresh` | 重扫已安装列表 |
| GET | `/api/v1/platform-presets` | 预置平台 URL 列表 |
| GET/POST | `/api/v1/profiles/{id}/platform-accounts` | 平台账号列表 / 新建 |
| PATCH | `/api/v1/profiles/{id}/platform-accounts/{aid}` | 更新 |
| POST | `/api/v1/profiles/{id}/platform-accounts/{aid}/activate` | 设为当前服务 |
| DELETE | `/api/v1/profiles/{id}/platform-accounts/{aid}` | 删除 |
| GET | `/api/v1/home/{id}?token=` | Console Home 聚合数据 |

## 环境身份持久化

| 能力 | 行为 |
|------|------|
| 指纹锁定 | `fingerprint_config_json`；首次启动采样写入；之后只注入锁定 config |
| 重新采样 | `POST .../resample-fingerprint` 覆盖锁定配置 |
| 会话恢复 | `restoreSession`（默认 true）→ prefs `browser.startup.page=3` 等；写入 profile `user.js` |
| Cookie | 仅当 `cookies.sqlite` 不存在或过小才 `add_cookies(cookiesJson)` |
| Console Home | 临时扩展；**不**每次强制新开首页（避免抢走恢复的标签）；新标签 / 工具栏仍可打开 |

### 真实启动映射

- 指纹：锁定 config 优先；否则按 strategy 生成并回写 DB
- 代理 + `alignGeoWithProxy` → `proxy` + `geoip`（可降级）
- Cookie：条件注入（见上）
- `startUrl`：仅在 `restoreSession=false` 且无强制首页时 `goto`
- `headless` → launch options

### 平台账号 / Gemini

- 凭据加密；Gemini 可「打开并自动登录」（尽力填表）

## Profile JSON（camelCase）

见 `types/console.ts`：`hasFingerprintConfig`、`restoreSession`、`fingerprintConfigJson`（有锁时可能返回）等。
