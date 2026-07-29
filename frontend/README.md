# Camoufox 控制台（前端）

React + TypeScript + Vite 控制台，对齐 `原型/`。

- **无 `VITE_API_BASE`**：Zustand 内存 mock（纯 UI）
- **有 `VITE_API_BASE`**：启动时 hydrate，CRUD / 启停走 [`backend/`](../backend/) Local API

## 快速开始

```bash
cd frontend
npm install
npm run dev
```

http://localhost:10020 → `/profiles`

```bash
npm run build
```

## 双端联调

```bash
# 终端 1 — 后端
scripts\dev-backend.bat
# 或: cd backend && uvicorn app.main:app --host 127.0.0.1 --port 50325

# 终端 2 — 前端
cd frontend
echo VITE_API_BASE=http://127.0.0.1:50325> .env
npm run dev
```

真实窗口启停：后端设置 `CAMOUFOX_REAL_LAUNCH=1`（见 [backend/README.md](../backend/README.md)）。

## 手测清单（API 模式）

1. 打开控制台，顶栏显示「API 模式」，无红色 hydrate 错误横幅
2. **新建环境** → 仅保存 → 回到列表可见
3. **刷新页面** → 新建环境仍在（SQLite 持久化）
4. 点击 **启动** → 状态经 starting → running（mock 或真实窗口）
5. **实例监控** 可见该实例；等待约 8s 或点「立即刷新」仍同步
6. **停止** → idle；真实模式下窗口关闭
7. 详情 → 扔进回收站 → `/profiles/trash` 可恢复；彻底删除后磁盘无 Profile 目录
8. 代理页 → 检测 → 有出口 IP 或 fail；批量粘贴导入；删被引用代理应提示 409
9. **指纹策略** → 新建自定义 → 采样固化 → 新建环境选该模板 → 启动成功且无「preset 代替」日志
10. **浏览器版本** → 刷新已安装；对本机已安装版本「设为 Active」（无假安装按钮）

## 路由

| 路径 | 页面 |
|------|------|
| `/profiles` | 环境管理 |
| `/profiles/new` | 新建向导 |
| `/profiles/:id` | 详情 |
| `/profiles/import` `/groups` `/trash` | 导入 / 分组标签 / 回收站 |
| `/proxies` `/fingerprints` `/runtime` | 代理 / 指纹 / 监控 |
| `/browser` `/api` `/settings` | 版本 / Local API / 设置 |
| `/addons` `/tasks` | Phase 2 占位 |

契约：[docs/api-contract.md](../docs/api-contract.md)
