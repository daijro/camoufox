# Camoufox 控制台 UI 功能设计

> 本文档描述基于 Camoufox 的指纹浏览器控制台（对标 AdsPower 类产品）的 UI 模块划分与各模块界面功能清单。
>
> **版本：** v0.2  
> **最后更新：** 2026-07-29  
> **状态：** 设计草案（已与 `原型/` 对齐）

---

## 1. 背景与约束

### 1.1 项目定位

Camoufox 控制台是一套本地/局域网部署的指纹浏览器管理界面，用于管理独立浏览器环境（Profile）、代理、指纹配置，并提供 Local API 供 Playwright 等框架调用。

### 1.2 与 AdsPower 的根本差异

| 维度 | AdsPower | Camoufox |
|------|----------|----------|
| 浏览器内核 | Chromium | Firefox |
| 扩展生态 | Chrome Web Store (.crx/.zip) | Firefox Add-ons (.xpi) |
| 自动化协议 | CDP + 自研 Local API | Playwright (Juggler) |
| Profile 存储 | 自研 Profile 目录 | Playwright `persistent_context` + `user_data_dir` |
| 指纹注入 | 应用层 | C++ 层（`CAMOU_CONFIG` / `camoucfg.jvv`） |
| 指纹来源 | 用户手填 UA/Canvas 等 | **默认 BrowserForge 自动生成**（`generate_fingerprint()`） |
| 内核版本 | 可 per-Profile | **全局 Active**（`multiversion.set_active()`） |

### 1.3 现有可复用能力

| 模块 | 位置 | 说明 |
|------|------|------|
| 版本管理 GUI | `pythonlib/camoufox/gui/` | PySide6 + QML，管理浏览器版本、Channel、GeoIP |
| Python API | `pythonlib/camoufox/` | 指纹生成、代理、插件、启动参数 |
| Playwright Server | `camoufox server` | WebSocket 端点，非 REST API |
| 指纹配置 schema | `settings/camoucfg.jvv` | UA、Canvas、WebGL、WebRTC、字体等 |
| 插件管理 | `pythonlib/camoufox/addons.py` | Firefox `.xpi` 与本地解压目录 |

### 1.4 推荐技术栈

```
前端：React + TypeScript + Vite + shadcn/ui + TanStack Table
后端：Python FastAPI（编排层，需新建）
数据库：SQLite（单机）/ PostgreSQL（团队版）
实时：WebSocket（实例状态推送）
桌面壳：Tauri 2（推荐）或 Electron
任务调度：APScheduler / Celery + Redis（Phase 2）
```

### 1.5 优先级图例

| 标记 | 含义 |
|------|------|
| **MVP** | 第一版必做 |
| **Phase 2** | 第二版 |
| **Future** | 远期规划 |

---

## 2. 总体信息架构

### 2.1 模块总览

```
控制台壳层（M0）
├── M1  环境管理      ← 核心业务
├── M6  实例监控      ← 核心业务
├── M2  代理中心
├── M3  指纹策略
├── M4  插件中心      ← Phase 2
├── M5  任务中心      ← Phase 2
├── M7  浏览器版本    ← 复用现有 GUI 能力
├── M8  本地 API
├── M9  系统设置
└── M10 团队与权限    ← Future
```

### 2.2 侧边导航

| 序号 | 模块 | 图标语义 | 优先级 |
|------|------|----------|--------|
| M1 | 环境管理 | 文件夹/用户 | MVP |
| M6 | 实例监控 | 显示器 | MVP |
| M2 | 代理中心 | 地球/链路 | MVP |
| M3 | 指纹策略 | 指纹 | MVP |
| M4 | 插件中心 | 拼图 | Phase 2 |
| M5 | 任务中心 | 机器人 | Phase 2 |
| M7 | 浏览器版本 | 下载 | MVP |
| M8 | 本地 API | 接口 | MVP |
| M9 | 系统设置 | 齿轮 | MVP |

### 2.3 页面路由

| 路径 | 页面 |
|------|------|
| `/` | 重定向到 `/profiles` |
| `/profiles` | M1 环境列表 |
| `/profiles/new` | M1 新建环境 |
| `/profiles/import` | M1 批量导入 |
| `/profiles/:id` | M1 环境详情 |
| `/profiles/groups` | M1 分组管理 |
| `/profiles/trash` | M1 回收站 |
| `/runtime` | M6 实例监控 |
| `/proxies` | M2 代理列表 |
| `/proxies/check` | M2 检测面板（亦可为抽屉） |
| `/fingerprints` | M3 策略模板列表 |
| `/fingerprints/:id/edit` | M3 策略编辑器（高级） |
| `/addons` | M4 插件中心 |
| `/tasks` | M5 任务列表 |
| `/tasks/new` | M5 创建任务 |
| `/tasks/:id/logs` | M5 执行记录 |
| `/browser` | M7 浏览器版本 |
| `/api` | M8 API 管理 + 文档 |
| `/settings` | M9 系统设置 |
| `/settings/team` | M10 团队（Future） |

---

## 3. M0 控制台壳层（全局框架）

所有模块共用的外壳，不单独算业务模块，但决定第一屏体验。

| 区域 | 功能 | 优先级 | 说明 |
|------|------|--------|------|
| 顶栏 | 全局搜索 | MVP | 按环境名、标签、代理 IP、备注搜索 |
| 顶栏 | 运行状态摘要 | MVP | 如「运行中 3 / 总计 128」 |
| 顶栏 | 快捷启动 | MVP | 最近使用的 3 个环境一键打开 |
| 顶栏 | 通知中心 | Phase 2 | 代理失效、任务失败、版本更新提醒 |
| 侧边栏 | 模块导航 | MVP | 可折叠，记住上次位置 |
| 底栏/托盘 | 最小化到托盘 | MVP | 关闭窗口不杀浏览器进程 |
| 全局 | 空状态引导 | MVP | 首次使用：安装浏览器 → 建代理 → 建环境 |
| 全局 | 快捷键 | Phase 2 | `Ctrl+N` 新建环境、`Ctrl+K` 搜索 |

---

## 4. M1 环境管理（Profile Management）

**核心模块。** 产品用语建议使用「环境」而非「账号」，避免与登录凭据混淆。

底层实现：`Camoufox(persistent_context=True, user_data_dir=...)` + 独立 Profile 目录 + 元数据存 SQLite。

### 4.1 环境列表页（主页面）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 表格列：序号 | MVP | |
| 表格列：环境名称 | MVP | 可内联编辑 |
| 表格列：平台/用途 | MVP | 自定义文本，如 Facebook、Amazon |
| 表格列：绑定代理 | MVP | 显示 IP 或代理别名，悬停看详情 |
| 表格列：指纹摘要 | MVP | 格式：`{OS} · FF {version} · {resolution}` |
| 表格列：运行状态 | MVP | 未启动 / 运行中 / 异常 |
| 表格列：最后启动时间 | MVP | |
| 表格列：标签 | MVP | 多标签 Chip 展示 |
| 表格列：所属分组 | MVP | |
| 行操作：启动 | MVP | 单实例启动 |
| 行操作：停止 | MVP | |
| 行操作：编辑 | MVP | 跳转详情 |
| 行操作：复制环境 | Phase 2 | 复制指纹+配置，新 Profile 目录 |
| 行操作：删除 | MVP | 进回收站 |
| 行操作：更多 | Phase 2 | 导出配置、打开 Profile 目录 |
| 批量操作：批量启动 | Phase 2 | 需限制并发数 |
| 批量操作：批量停止 | MVP | |
| 批量操作：批量删除 | MVP | |
| 批量操作：批量改分组/标签 | Phase 2 | |
| 批量操作：批量绑定代理 | Phase 2 | |
| 筛选：按分组 | MVP | 左侧树或下拉 |
| 筛选：按标签 | MVP | |
| 筛选：按运行状态 | MVP | |
| 筛选：按平台 | MVP | |
| 筛选：按代理状态 | Phase 2 | 正常/失效/未绑定 |
| 排序 | MVP | 名称、创建时间、最后启动 |
| 分页 / 虚拟滚动 | MVP | 上百环境时需要 |
| 视图切换 | Phase 2 | 表格 / 卡片 |

### 4.2 新建环境（单条）

**布局建议：** 分步向导（4 步）或左侧 Tab 单页表单。

| 步骤/Tab | 字段与功能 | 优先级 |
|----------|------------|--------|
| 基础信息 | 环境名称（必填） | MVP |
| 基础信息 | 平台/用途（选填） | MVP |
| 基础信息 | 备注 | MVP |
| 基础信息 | 分组选择 / 新建分组 | MVP |
| 基础信息 | 标签（多选） | MVP |
| 代理 | 不绑定 / 从代理库选择 | MVP |
| 代理 | 新建代理并绑定 | MVP |
| 代理 | 启动时检测代理连通性 | Phase 2 |
| 指纹 | 策略：自动随机 / 真实预设 / 已保存模板 | MVP |
| 指纹 | 操作系统（Win/Mac/Linux） | MVP |
| 指纹 | ☑ 启动时根据代理自动对齐 Geo/WebRTC | MVP |
| 指纹 | 高级参数（分辨率、WebRTC） | Phase 2 → 折叠，跳转 M3 |
| 凭据与 Cookie | 账号/密码（加密存 DB，不写入浏览器） | Phase 2 |
| 凭据与 Cookie | Cookie JSON 导入 | MVP |
| 凭据与 Cookie | 启动 URL（可选） | MVP |
| 插件 | 继承全局插件 | Phase 2 |
| 插件 | 本环境额外插件 | Phase 2 |
| 预览 | 指纹摘要卡片 | MVP |
| 预览 | 代理 Geo 预览（国家/时区） | MVP |
| 操作 | 保存并启动 | MVP |
| 操作 | 仅保存 | MVP |

### 4.3 批量导入

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 下载 CSV/Excel 模板 | MVP | 列：名称、平台、代理、Cookie、标签、备注 |
| 上传文件解析 | MVP | |
| 导入预览表 | MVP | 标红错误行 |
| 字段映射 | Phase 2 | 自定义列映射 |
| 代理自动匹配 | Phase 2 | 按 IP:端口匹配代理库 |
| 指纹策略 | MVP | 全部随机 / 全部用某模板 |
| 导入进度条 | MVP | |
| 导入结果报告 | MVP | 成功 N、失败 N、失败原因 |

### 4.4 环境详情页

| Tab | 功能 | 优先级 |
|-----|------|--------|
| 概览 | 基本信息、运行状态、快捷启停 | MVP |
| 概览 | Profile 目录路径、磁盘占用 | MVP |
| 指纹 | 只读展示当前指纹 JSON 摘要 | MVP |
| 指纹 | 「编辑指纹」跳转 M3 | Phase 2 |
| 代理 | 当前绑定代理、连通性、一键重测 | MVP |
| 代理 | 更换代理 | MVP |
| Cookie | 查看/导入/导出 Cookie | MVP |
| 插件 | 本环境已装插件列表 | Phase 2 |
| 启动配置 | 无头/有头、启动 URL、窗口大小 | MVP |
| 日志 | 该环境最近启动/停止记录 | Phase 2 |
| 危险操作 | 重置 Profile（清 Cookie 保留指纹） | Phase 2 |
| 危险操作 | 删除进回收站 | MVP |

### 4.5 分组管理

| 功能 | 优先级 |
|------|--------|
| 分组树（支持一级或两级） | MVP |
| 新建/重命名/删除分组 | MVP |
| 拖拽环境到分组 | Phase 2 |
| 分组统计（环境数量） | MVP |

### 4.6 标签管理

| 功能 | 优先级 |
|------|--------|
| 标签列表 + 使用计数 | MVP |
| 新建/删除标签 | MVP |
| 标签颜色 | Phase 2 |

### 4.7 回收站

| 功能 | 优先级 |
|------|--------|
| 已删除环境列表 | MVP |
| 恢复 | MVP |
| 彻底删除（删 Profile 目录） | MVP |
| 自动清理（30 天） | Phase 2 |
| 批量恢复/清空 | Phase 2 |

---

## 5. M2 代理中心（Proxy Management）

底层复用：`camoufox.ip.Proxy`、`public_ip()`、GeoIP 自动推导。

### 5.1 代理列表页

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 列：别名 | MVP | |
| 列：协议 | MVP | HTTP / HTTPS / SOCKS5 |
| 列：地址 | MVP | host:port |
| 列：认证 | MVP | 有/无（密码脱敏） |
| 列：出口 IP | MVP | 检测后填充 |
| 列：国家/地区 | MVP | GeoIP |
| 列：延迟 | MVP | ms |
| 列：状态 | MVP | 未检测 / 正常 / 失效 |
| 列：关联环境数 | MVP | |
| 列：备注 | MVP | |
| 新建代理 | MVP | 表单 |
| 编辑 / 删除 | MVP | 删除前检查是否被引用 |
| 批量导入（文本/CSV） | MVP | `ip:port:user:pass` 格式 |
| 批量检测 | MVP | |
| 批量删除失效代理 | Phase 2 | |
| 筛选：按状态/国家/协议 | MVP | |
| 分配给环境 | Phase 2 | 从代理页反向绑定 |

### 5.2 代理检测面板

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 单条检测 | MVP | 调 `public_ip` + GeoIP |
| 显示：出口 IP、国家、时区、延迟 | MVP | |
| 显示：是否与预期 IP 一致 | Phase 2 | |
| WebRTC 泄露检测链接 | Phase 2 | 打开 Camoufox 测站 |
| 检测历史 | Phase 2 | 最近一次结果时间 |

### 5.3 代理商对接（可选）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 代理商配置（API Key） | Future | Bright Data、922 等 |
| 从代理商拉取 IP 列表 | Future | |
| 自动轮换策略 | Future | |

---

## 6. M3 指纹策略模板（Fingerprint Strategy）

Camoufox **默认在每次 launch 时自动生成指纹**（BrowserForge），用户无需手填 UA。本模块供管理默认策略与高级固定模板。

### 6.0 Camoufox 默认行为（必读）

| 行为 | 后端实现 |
|------|----------|
| 未指定 fingerprint 时 | `generate_fingerprint()` 自动生成 |
| canvas/audio seed | 默认每次 launch 随机（`utils.py`） |
| 使用真实预设 | `fingerprint_preset=True` |
| 固定模板 | 持久化 camoucfg JSON，launch 时原样注入 |
| Geo 对齐 | `geoip=True` 跟随代理 IP |

### 6.1 模板列表

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 系统预设：BrowserForge 自动随机 | MVP | 默认，不可删除 |
| 系统预设：真实设备预设采样 | MVP | |
| 用户自定义模板 | MVP | 固定 seed / 高级参数 |
| 设为默认模板 | MVP | 新建环境默认策略 |
| 新建 / 复制 / 删除 | MVP | 系统预设仅查看/复制 |

### 6.2 策略编辑器（高级）

**布局：** 左侧分类 + 中间表单 + 右侧 JSON 预览（camoucfg）。

| 分类 | 可配置项 | 优先级 | 说明 |
|------|----------|--------|------|
| 基础 | 操作系统（Win/Mac/Linux） | MVP | UA **自动生成**，只读展示 |
| 屏幕 | 分辨率、DPR | Phase 2 | |
| 地理 | 时区/语言跟随代理 | MVP | toggle |
| WebRTC | 跟随代理 IP / 禁用 | MVP | 无「透传」选项 |
| Seed | 每次随机 / 固定存模板 | Phase 2 | 非 Seed Ratio 滑块 |
| 字体 | 随机 OS 子集 / 完整 / 自定义 | Phase 2 | |
| 高级 | 原始 JSON 编辑 | Phase 2 | |

| 编辑器功能 | 优先级 |
|------------|--------|
| 「随机生成」按钮 | MVP |
| 「从真实预设采样」 | MVP |
| 与代理 Geo 一键对齐 | MVP |
| 预览：在检测页打开测试 | Phase 2 |

### 6.3 全局指纹策略

| 功能 | 优先级 |
|------|--------|
| 新环境默认：自动随机 / 指定模板 | MVP |
| WebRTC 自动跟随代理 IP | MVP |
| GeoIP 自动推导时区语言 | MVP |
| 禁止重复指纹警告 | Phase 2 |

---

## 7. M4 插件中心（Firefox Add-ons）

> **重要：** Camoufox 基于 Firefox，仅支持 Firefox 插件（`.xpi`），不支持 Chrome 扩展（`.crx` / Chrome Web Store）。

底层复用：`pythonlib/camoufox/addons.py`。

### 7.1 插件库

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 已安装插件列表 | Phase 2 | 名称、版本、路径 |
| 从本地目录导入（含 manifest.json） | Phase 2 | |
| 从 URL 下载 .xpi | Phase 2 | |
| 内置推荐：uBlock Origin 等 | Phase 2 | |
| 删除插件 | Phase 2 | |

### 7.2 全局插件策略

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 全局启用插件列表 | Phase 2 | 新环境自动安装 |
| 按环境覆盖 | Future | |
| 启动时检测插件完整性 | Future | |

### 7.3 明确不做的功能

| 功能 | 原因 |
|------|------|
| Chrome 商店链接导入 | Firefox 不支持 |
| .crx 上传 | 不支持 |

---

## 8. M5 任务中心（Automation）

MVP 阶段做「脚本任务」，不做可视化拖拽 RPA，不做窗口同步器。

### 8.1 任务列表

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 任务名称、类型、状态 | Phase 2 | |
| 关联环境（单个/多个） | Phase 2 | |
| 上次执行 / 下次执行时间 | Phase 2 | |
| 启用 / 禁用 | Phase 2 | |
| 手动立即执行 | Phase 2 | |
| 查看执行日志 | Phase 2 | |

### 8.2 创建任务

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 任务类型：Playwright Python 脚本 | Phase 2 | |
| 选择目标环境 | Phase 2 | |
| 脚本编辑器（Monaco） | Phase 2 | |
| 参数注入（环境变量/JSON） | Phase 2 | |
| 定时：一次 / Cron / 间隔 | Phase 2 | |
| 失败重试次数 | Phase 2 | |
| 并发限制 | Phase 2 | |

### 8.3 执行记录

| 功能 | 优先级 |
|------|--------|
| 执行历史列表 | Phase 2 |
| 日志流（stdout/stderr） | Phase 2 |
| 截图附件（可选） | Future |

### 8.4 明确不做（首期）

| 功能 | 替代方案 |
|------|----------|
| 可视化拖拽 RPA | 脚本 + 模板 |
| 窗口同步器（多窗鼠标键盘实时同步） | 批量脚本并行执行 |

---

## 9. M6 实例监控（Runtime Monitor）

环境列表只显示状态摘要，本模块管理当前正在运行的浏览器实例。

### 9.1 运行中实例面板

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 实例卡片/表格 | MVP | PID、环境名、启动时间 |
| 当前 URL（如能获取） | Phase 2 | Playwright 连接时 |
| 绑定代理、指纹 OS | MVP | |
| 无头/有头标识 | MVP | |
| 一键停止 | MVP | |
| 一键聚焦窗口 | Phase 2 | 有头模式 |
| 打开 DevTools / Playwright Inspector | Phase 2 | |
| 资源占用（CPU/内存） | Phase 2 | |

### 9.2 批量控制

| 功能 | 优先级 |
|------|--------|
| 全部停止 | MVP |
| 并发上限设置 | Phase 2 |
| 启动队列（排队等待） | Phase 2 |

### 9.3 实时事件流

| 功能 | 优先级 |
|------|--------|
| WebSocket 推送实例启停 | MVP |
| 代理失效告警 | Phase 2 |
| 浏览器崩溃自动标记 | Phase 2 |

---

## 10. M7 浏览器版本（Browser Versions）

**Camoufox 版本为全局配置**，通过 `multiversion.py` 管理 Active build，**不存在 per-Profile 内核**。建议复用/嵌入现有 `camoufox gui` 能力。

### 10.1 版本管理页

| 功能 | 优先级 | 现有支持 |
|------|--------|----------|
| 已安装 build 列表 | MVP | ✅ `camoufox gui` |
| 安装 / 卸载 build | MVP | ✅ |
| 设为 Active（全局运行版本） | MVP | ✅ `set_active()` |
| Follow Channel / Pin 版本 | MVP | ✅ |
| 同步远程版本列表 | MVP | ✅ |
| 下载进度 | MVP | ✅ |
| GeoIP 从远程源同步 | MVP | ✅ 非上传 .mmdb |
| 安装路径、磁盘占用 | MVP | ✅ |

### 10.2 集成方式

| 方案 | 说明 |
|------|------|
| A. Web UI 调 API，后端转调 camoufox CLI/Python API | 统一体验，**推荐** |
| B. 保留独立 `camoufox gui` 窗口，设置里提供「打开版本管理器」 | 开发量最小 |

---

## 11. M8 本地 API（Local API）

对标 AdsPower Local API，协议按 **Playwright** 生态设计。**Selenium / CDP 不在支持范围内。**

### 11.1 API 管理页

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 服务启停开关 | MVP | |
| 监听地址 / 端口配置 | MVP | 默认 `127.0.0.1:50325` |
| API Key / Token | MVP | 本地鉴权 |
| 连接状态指示 | MVP | |
| 请求日志（最近 N 条） | Phase 2 | |

### 11.2 API 端点（建议）

| 端点 | 方法 | 优先级 | 说明 |
|------|------|--------|------|
| `/api/v1/profiles` | GET/POST | MVP | 环境列表 / 创建 |
| `/api/v1/profiles/{id}` | GET/PATCH/DELETE | MVP | 环境详情 / 更新 / 删除 |
| `/api/v1/profiles/{id}/start` | POST | MVP | 启动环境 |
| `/api/v1/profiles/{id}/stop` | POST | MVP | 停止环境 |
| `/api/v1/profiles/{id}/status` | GET | MVP | 运行状态 |
| `/api/v1/browser/active` | GET | MVP | 所有运行中实例 |
| `/api/v1/proxies` | CRUD | Phase 2 | 代理管理 |
| WebSocket 端点 | — | MVP | 实例状态推送 |
| Playwright 连接说明 | — | MVP | 文档内嵌 |

### 11.3 API 文档页（内嵌）

| 功能 | 优先级 |
|------|--------|
| 端点列表与参数说明 | MVP |
| 代码示例（Python Playwright / Node） | MVP |
| 说明：不支持 Selenium | MVP |
| Swagger / Redoc 内嵌 | Phase 2 |
| 「测试启动环境」按钮 | Phase 2 |

---

## 12. M9 系统设置（Settings）

### 12.1 常规

| 功能 | 优先级 |
|------|--------|
| 语言（中/英） | Phase 2 |
| 主题（亮/暗） | MVP |
| 开机自启 | Phase 2 |
| 关闭主窗口行为（托盘/退出） | MVP |
| 默认启动模式（有头/无头） | MVP |

### 12.2 存储与路径

| 功能 | 优先级 |
|------|--------|
| Profile 根目录 | MVP |
| 数据目录占用统计 | Phase 2 |
| 一键打开数据目录 | MVP |
| 缓存清理 | Phase 2 |

### 12.3 安全

| 功能 | 优先级 |
|------|--------|
| 本地主密码（加密代理密码/Cookie） | Phase 2 |
| 导出数据加密 | Future |
| 操作日志保留天数 | Phase 2 |

---

## 13. M10 团队与权限（Future）

若后续做团队版，建议独立模块，不与 M9 混在一起。Camoufox 仓库当前无用户系统，需完全自建。

### 13.1 成员管理

| 功能 | 优先级 |
|------|--------|
| 邀请子账号 | Future |
| 禁用/删除成员 | Future |

### 13.2 RBAC 权限

| 功能 | 优先级 |
|------|--------|
| 角色：管理员 / 操作员 / 只读 | Future |
| 细粒度：能否启动环境 | Future |
| 细粒度：能否查看/导出代理密码 | Future |
| 细粒度：能否查看/导出 Cookie | Future |
| 细粒度：能否删除环境 | Future |

### 13.3 审计日志

| 功能 | 优先级 |
|------|--------|
| 操作记录：启停环境 | Future |
| 操作记录：修改指纹/代理 | Future |
| 操作记录：导入/导出数据 | Future |
| 按成员/时间筛选 | Future |

---

## 14. 能力矩阵总览

| 模块 | 前端难度 | 后端难度 | Camoufox 依赖 | MVP 优先级 |
|------|----------|----------|---------------|------------|
| M1 环境管理 | 中 | 中 | 高 | ★★★★★ |
| M2 代理中心 | 低 | 低 | 低 | ★★★★★ |
| M3 指纹策略 | 中 | 中 | 高 | ★★★★ |
| M6 实例监控 | 中 | 中 | 高 | ★★★★★ |
| M8 本地 API | 低 | 中 | 高 | ★★★★ |
| M7 浏览器版本 | 低 | 低 | 高（已有 GUI） | ★★★★ |
| M9 系统设置 | 低 | 低 | 低 | ★★★ |
| M4 插件中心 | 低 | 中 | 中（Firefox only） | ★★★ |
| M5 任务中心 | 中 | 中 | 高 | ★★ |
| M10 团队权限 | 中 | 高 | 无 | ★ |

---

## 15. MVP 最小界面集合

第一版建议只做以下 **8 个页面**：

1. **环境列表**（含启停、筛选、标签）
2. **新建环境向导**
3. **批量导入**
4. **环境详情**（概览 + 代理 + Cookie）
5. **代理列表**（含批量导入与检测）
6. **指纹策略模板列表 + 策略编辑器（高级参数默认折叠）**
7. **实例监控**
8. **设置 + API 管理 + 浏览器版本**

其余模块（插件中心、任务中心、回收站高级功能、团队版）放 Phase 2。

---

## 16. 与 AdsPower 功能对照

| AdsPower 模块 | 本方案对应 | 差异说明 |
|---------------|------------|----------|
| 环境管理 | M1 | 基本一致 |
| 代理管理 | M2 | 基本一致；代理商 API 对接为 Future |
| 插件中心 | M4 | **仅 Firefox 插件** |
| RPA + 同步器 | M5 | **仅脚本任务，无窗口同步器** |
| 团队权限 | M10 | 后期独立模块 |
| Local API | M8 | 需新建 REST 层，底层 Playwright |
| 指纹设置 | M3 | **默认自动生成**；UI 以策略选择为主，高级模板可选 |

---

## 17. 分期路线图

### Phase 1 — 可用控制台（4–6 周）

- 技术栈：React + FastAPI + SQLite + Tauri 桌面壳
- 模块：M1、M2、M3（简易）、M6、M7、M8、M9
- Local API 基础端点

### Phase 2 — 运维增强（2–4 周）

- M1 回收站高级、批量操作、复制环境
- M4 插件中心
- M5 脚本任务 + 定时调度
- M2 代理高级检测

### Phase 3 — 团队版（按需）

- M10 多用户、RBAC、审计日志
- PostgreSQL 多租户

### 明确不做（或远期）

- 窗口同步器（操作系统级输入镜像）
- 可视化拖拽 RPA 设计器
- Chrome 扩展支持

---

## 18. 待决事项

以下问题影响具体交互与架构，需在开发前确认：

1. **部署形态：** 纯本机 Tauri 客户端，还是浏览器访问 `localhost`？
2. **M7 集成方式：** Web UI 统一体验（方案 A）还是保留独立 `camoufox gui` 窗口（方案 B）？
3. **MVP 是否接受降级：** 不做同步器、不做可视化 RPA、插件仅 Firefox？
4. **单机 vs 团队：** 第一版是否只做单用户本地版？

---

## 附录 A：数据模型（草案）

```
Profile（环境）
├── id, name, platform, remark
├── group_id, tags[]
├── proxy_id (nullable)
├── fingerprint_template_id (nullable)
├── fingerprint_strategy: auto_random | preset | fixed
├── user_data_dir (path)
├── cookies (encrypted blob, optional)
├── launch_url, headless
├── status: idle | running | error
├── deleted_at (nullable, 回收站)
└── created_at, updated_at, last_started_at

Proxy（代理）
├── id, alias, protocol, host, port
├── username, password (encrypted)
├── exit_ip, country, timezone, latency_ms
├── status: unknown | ok | failed
└── remark, created_at

FingerprintTemplate（指纹策略模板）
├── id, name, description
├── strategy: auto_random | preset | fixed
├── is_system, is_default
├── os (optional)
├── geoip_follow (bool)
├── webrtc_mode: follow_proxy | disabled
├── seed_mode: random_per_launch | fixed
├── config (JSON, 对应 camoucfg；fixed 时持久化 seed)
└── created_at

BrowserInstance（运行实例，内存/Redis）
├── profile_id, pid
├── started_at, headless
├── playwright_ws_endpoint (optional)
└── status

Group / Tag — 标准 CRUD
```

## 附录 B：相关代码路径

| 能力 | 路径 |
|------|------|
| 启动 API | `pythonlib/camoufox/sync_api.py`, `async_api.py` |
| 启动参数 | `pythonlib/camoufox/utils.py` → `launch_options()` |
| 指纹生成 | `pythonlib/camoufox/fingerprints.py` |
| 代理检测 | `pythonlib/camoufox/ip.py` |
| 插件 | `pythonlib/camoufox/addons.py` |
| 现有 GUI | `pythonlib/camoufox/gui/` |
| 指纹 schema | `settings/camoucfg.jvv` |
| Playwright Server | `pythonlib/camoufox/server.py` |
| 多实例示例 | `local_open_multiple.py` |

## 附录 C：原型对齐变更摘要（v0.2）

与 `原型/` HTML 同步的关键修正：

| 项 | 改前 | 改后 |
|----|------|------|
| 指纹主流程 | 手填 UA/内核/硬件并发 | 三策略：自动随机 / 预设采样 / 已保存模板 |
| 指纹摘要列 | Chrome / Safari 标签 | `{OS} · FF {ver} · {分辨率}` |
| 内核管理 | per-Profile「缺失内核」 | 全局 Active（M7 / 系统设置） |
| 代理协议 | 含 SSH | 仅 HTTP / HTTPS / SOCKS5 |
| WebRTC | 含「真实透传」 | 跟随代理 / 禁用 |
| Seed | Seed Ratio 滑块 | 每次随机 / 固定存模板 |
| Local API | Playwright + Selenium | 仅 Playwright；注明不支持 Selenium |
| GeoIP | 上传 .mmdb | 从远程源同步 |
| 版本号示例 | Firefox 115 / 120 | Camoufox 152.0.4-beta.28 |

原型文件目录：`原型/02`–`原型/12`（HTML + 说明.md）。
