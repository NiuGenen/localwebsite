# 本地文件站（Local File Station）

一个基于 **Nginx + Flask** 的局域网文件共享网站，提供文件浏览与管理、Markdown 阅读、待办事项等功能。

## 功能特性

- **文件浏览**：自定义文件浏览器（替代 Nginx autoindex），解决中文文件名对齐问题，支持完整长文件名显示与响应式布局。
- **文件操作**：多文件上传、新建文件夹、剪切/粘贴移动文件、重命名（文件与文件夹均可）。
- **黑名单目录保护**：`binary-translation` 目录禁止上传、移动、重命名等修改操作（仍可浏览下载）。
- **Markdown 阅读**：文件列表选择 + Markdown 渲染 + 代码高亮，显示完整文件名。
- **待办事项**：服务端持久化（`site/todo.json`），支持添加、行内编辑、删除、优先级（高/中/低，点击循环切换）、按时间/名称/优先级排序、完成沉底置灰。**仅限 localhost 访问**。
- **内容宽度调节**：首页滑条调节内容区宽度（900–1800px），通过 `localStorage` 记住，全站生效。
- **本机访问判定**：首页「待办事项」卡片仅在 localhost 访问时显示。

## 架构

| 组件 | 端口 | 职责 |
|---|---|---|
| Nginx | 8080 | 静态页面、`/files/` autoindex、`/api/` 反向代理到 Flask、todo 页/API 仅限 localhost |
| backend.py（Flask） | 5000 | 提供全部 JSON API（文件浏览、上传、新建、移动、重命名、待办、本机判定） |

## 目录结构

```
.
├── nginx.conf          # Nginx 配置
├── backend.py          # Flask 后端（全部 API）
├── start.sh            # 启动脚本（Flask + Nginx）
├── stop.sh             # 停止脚本
├── venv/               # Python 虚拟环境（Flask）
└── site/
    ├── index.html      # 首页（含内容宽度滑条、待办入口卡片）
    ├── files/
    │   └── index.html  # 文件浏览器（SPA）
    ├── reader.html     # Markdown 阅读器
    ├── todo.html       # 待办事项页面
    ├── info.html       # 关于页
    ├── files/          # 共享文件目录（gitignored）
    ├── js/             # 前端脚本（layout.js、todo.js 等）
    ├── css/style.css   # 全局样式
    └── todo.json       # 待办数据文件（gitignored）
```

## 快速开始

依赖：Nginx、Python3 + venv（Flask）。

```bash
./start.sh     # 启动 Flask 后端 + Nginx
./stop.sh      # 停止服务
```

- 本机访问：<http://localhost:8080>
- 局域网访问：<http://服务器局域网IP:8080>
- **待办事项功能需使用 `http://localhost:8080` 访问**（仅限本机）。

> 注：本项目使用的 Nginx 位于 `/tmp/nginx_install/extracted/usr/sbin/nginx`，若该目录被系统清理，可用 `apt download nginx` 重新解压，或改用系统自带的 Nginx。

## 配置说明

### backend.py

| 配置项 | 说明 |
|---|---|
| `LOCAL_IPS` | 本机判定集合（用于待办访问控制，默认仅回环地址 `127.0.0.1` / `::1`） |
| `BLOCKED_PATHS` | 禁止修改的目录黑名单（相对 `files/`，前缀匹配） |
| `TODO_FILE` | 待办数据文件路径（`site/todo.json`） |
| `PRIORITIES` | 待办优先级白名单（`high` / `medium` / `low`） |

### nginx.conf

- `/todo.html` 与 `/api/todo`：仅允许 `127.0.0.1`、`::1`（其余 `deny all`）
- `/api/`：反向代理到 Flask，`client_max_body_size 100m`（上传大小限制）

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/files?path=` | 列出目录内容（含每项 `blocked` 标志） |
| POST | `/api/upload` | 上传文件（支持多文件） |
| POST | `/api/mkdir` | 新建文件夹（同名拒绝） |
| POST | `/api/move` | 移动文件（剪切/粘贴，仅文件） |
| POST | `/api/rename` | 重命名文件/文件夹 |
| GET | `/api/local` | 本机访问判定 |
| GET / POST | `/api/todo` | 待办列表 / 添加 |
| PUT / DELETE | `/api/todo/<id>` | 更新 / 删除待办 |

## 安全与数据

- **路径穿越防护**：`safe_join_soft` 规范化路径并校验前缀，上传文件名经 `basename` 检查。
- **黑名单保护**：黑名单目录禁止上传、新建、移动、重命名。
- **待办仅本机**：Nginx 层 `allow/deny` + 首页卡片本机判定双重控制。
- **隐藏文件过滤**：点文件（`.` 开头）与 `index.html` 不在文件浏览列表中显示。
- **数据文件**：`site/files/`（共享文件）与 `site/todo.json`（待办数据）均已加入 `.gitignore`，不入库。
