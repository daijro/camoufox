# 本地 API 管理中心 页面说明

- 会话：# Camoufox 控制台 UI 功能设计
- 页面角色：子页面
- 导出时间：2026/7/29 22:52:59

【页面职责】
本地 API 管理中心是控制台的系统服务管理页面。它主要用于配置和监控运行在本地的 FastAPI 网关服务，该网关接收外部 **Playwright** 自动化框架的调用，实现指纹浏览器实例的调度与控制。

【业务对象】
1. 本地 API 服务：REST/WebSocket 网关进程，包含运行状态、监听 IP、端口、鉴权 Token。
2. 浏览器环境（Profile）：API 操作的虚拟环境实体。
3. 浏览器运行实例（Instance）：被 API 唤醒的 Camoufox 进程，含 PID、Playwright ws_endpoint。
4. 接口调用日志：外部客户端请求流水。

【页面功能说明】
1. 服务运行状态监控：展示本地 API 服务状态与协议版本。
2. 服务网关配置：启停开关、监听地址/端口、API Token 复制/重置。
3. 实时日志流水：最近 100 条 API 请求与系统事件。
4. 开发者集成文档：REST 接口定义、**Python Playwright** 与 Node.js 代码示例。

【重要限制】
- **官方支持 Playwright（Juggler）**，通过 `/start` 返回 `ws_endpoint` 连接。
- **Selenium / CDP 不在 Camoufox 支持范围内**，文档中仅作不支持说明。

【关键用户动作与业务含义】
1. 切换服务启停：控制 FastAPI 网关。
2. 保存并重启服务：应用新端口配置。
3. 复制 Token / 集成代码：供 Playwright 客户端鉴权与连接。

【对后端理解最重要的支撑点】
1. 启动环境接口需返回 Playwright WebSocket 端点。
2. 底层调用 Camoufox Python API 注入指纹并管理进程。
3. `camoufox server` 为独立 WS 服务，REST 网关为控制台新建层。

【页面关系与流程承接】
为外部 Playwright 脚本控制「环境管理」模块中的 Profile 提供网关配置。
