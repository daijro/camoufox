# Camoufox Console API 契约（v0.3）

Base URL：`VITE_API_BASE`（例如 `http://127.0.0.1:50325`）

鉴权：可选 `Authorization: Bearer <CAMOUFOX_API_TOKEN>`（本地 MVP 可不带）

## 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/health` | 健康检查；`realLaunch` 反映 `CAMOUFOX_REAL_LAUNCH` |
| GET | `/api/v1/settings` | 系统设置 |
| GET | `/api/v1/profiles` | 环境列表（`?include_deleted=true`） |
| GET | `/api/v1/profiles/{id}` | 详情 |
| POST | `/api/v1/profiles` | 创建（`templateId` 可选；strategy=template 时必填） |
| PATCH | `/api/v1/profiles/{id}` | 更新 |
| POST | `/api/v1/profiles/{id}/start` | 启动 |
| POST | `/api/v1/profiles/{id}/stop` | 停止 |
| POST | `/api/v1/profiles/{id}/trash` | 软删除 |
| POST | `/api/v1/profiles/{id}/restore` | 恢复 |
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

## 启停语义

| 情况 | 状态码 / 行为 |
|------|----------------|
| 正常启动 | 200，`status=running`，写入 `pid` / 日志 |
| Cookie JSON 非法 | **400**，`status=error` |
| 正在 starting / 已在运行 | **409** Conflict |
| Camoufox 启动失败 | **500**，`status=error` |
| `CAMOUFOX_REAL_LAUNCH=0` | mock：约 0.4s 后假 PID/WS |
| `CAMOUFOX_REAL_LAUNCH=1` | `AsyncNewBrowser(persistent_context=True)` + `user_data_dir` |

### 真实启动映射

- 指纹：`auto` 默认生成；`preset` → `fingerprint_preset=True`；`template` → 优先注入模板 `config_json`，否则 `use_preset` / 按 OS 生成
- 代理 + `alignGeoWithProxy` → Playwright `proxy` + `geoip=True`（探测失败可降级）
- `cookiesJson` → `context.add_cookies(...)`
- `startUrl` → `new_page().goto(...)`（失败不阻断启动）
- `headless` → 传入 launch options

## Profile JSON（camelCase）

见仓库前端 `types/console.ts` 的 `Profile` 字段（含 `templateId`）；后端响应使用相同 camelCase。
