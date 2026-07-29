# Camoufox Console API 契约（v0.2）

Base URL：`VITE_API_BASE`（例如 `http://127.0.0.1:50325`）

鉴权：可选 `Authorization: Bearer <CAMOUFOX_API_TOKEN>`（本地 MVP 可不带）

## 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/health` | 健康检查；`realLaunch` 反映 `CAMOUFOX_REAL_LAUNCH` |
| GET | `/api/v1/settings` | 系统设置 |
| GET | `/api/v1/profiles` | 环境列表（`?include_deleted=true`） |
| GET | `/api/v1/profiles/{id}` | 详情 |
| POST | `/api/v1/profiles` | 创建 |
| PATCH | `/api/v1/profiles/{id}` | 更新 |
| POST | `/api/v1/profiles/{id}/start` | 启动 |
| POST | `/api/v1/profiles/{id}/stop` | 停止 |
| POST | `/api/v1/profiles/{id}/trash` | 软删除 |
| POST | `/api/v1/profiles/{id}/restore` | 恢复 |
| DELETE | `/api/v1/profiles/{id}` | 彻底删除 |
| GET | `/api/v1/runtime` | 运行中实例 |
| GET/POST | `/api/v1/proxies` | 代理列表 / 新建 |
| POST | `/api/v1/proxies/{id}/check` | 经代理探测公网出口 IP |
| DELETE | `/api/v1/proxies/{id}` | 删除代理 |
| GET/POST | `/api/v1/groups` | 分组 |
| PATCH | `/api/v1/groups/{id}` | 重命名 |
| DELETE | `/api/v1/groups/{id}` | 删除（环境归未分类） |
| GET/POST | `/api/v1/tags` | 标签 |
| DELETE | `/api/v1/tags/{id}` | 删除标签 |
| GET | `/api/v1/browser/versions` | 全局版本列表 |

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

- 指纹：`auto` 默认生成；`preset` / `template` → `fingerprint_preset=True`（template 暂用 preset 并写日志）
- 代理 + `alignGeoWithProxy` → Playwright `proxy` + `geoip=True`
- `cookiesJson` → `context.add_cookies(...)`
- `startUrl` → `new_page().goto(...)`（失败不阻断启动）
- `headless` → 传入 launch options

## Profile JSON（camelCase）

见仓库前端 `types/console.ts` 的 `Profile` 字段；后端响应使用相同 camelCase。
