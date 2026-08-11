# 本地文件站（Local File Station）

一个基于 **Nginx + Flask** 的局域网文件共享网站，提供文件浏览与管理、Markdown 阅读、自定义阅读页面、待办事项等功能。

## 功能特性

- **文件浏览**：自定义文件浏览器（替代 Nginx autoindex），解决中文文件名对齐问题，支持完整长文件名显示与响应式布局。
- **文件操作**：多文件上传、新建文件夹、剪切/粘贴移动文件、重命名（文件与文件夹均可）。
- **文件阅读入口**：`md` 文件在文件浏览中带有「阅读」按钮，点击可直接在站内 Markdown 阅读页打开。
- **黑名单目录保护**：`binary-translation` 目录禁止上传、移动、重命名等修改操作（仍可浏览下载）。
- **Markdown 阅读**：文件列表选择 + Markdown 渲染 + 代码高亮，显示完整文件名；支持**图片渲染**与**相对链接**（图片/链接按当前文档所在目录解析，`[链接](其他.md)` 可在阅读器内直接跳转）。
- **自定义页面**：创建独立的 Markdown 阅读页（标题 + markdown 简介 + 文档清单），组织若干相关文档集中阅读。
  - 每个页面内置**文件浏览器**：上传文档（`.md`）/图片（png/jpg/jpeg/gif/webp/bmp）、新建文件夹、删除、子目录导航。
  - markdown 中可引用同目录图片（`![](pic.png)`）与相对链接（含 `../` 退级）。
  - 页面可**贴到首页**形成导航卡片（仅本机可操作，卡片对所有访客可见）。
  - **创建 / 编辑 / 上传 / 删除 / 贴首页** 均**仅限本机**；查看对所有局域网用户开放。
- **待办事项**：服务端持久化（`site/todo.json`），支持添加、行内编辑、删除、优先级（高/中/低，点击循环切换）、**进行中标记**（未完成项点击「进行中」切换，进行中事项排在最前，蓝色高亮）、按时间/名称/优先级排序、完成沉底置灰。**仅限 localhost 访问**。
- **内容宽度调节**：首页滑条调节内容区宽度（900–1800px），通过 `localStorage` 记住，全站生效。
- **本机访问判定**：首页「待办事项」「自定义页面」的管理入口仅在 localhost 访问时显示。

## 架构

| 组件 | 端口 | 职责 |
|---|---|---|
| Nginx | 8080 | 静态页面、`/files/` autoindex、`/api/` 反向代理到 Flask、todo 页/API 仅限 localhost |
| backend.py（Flask） | 5000 | 提供全部 JSON API（文件浏览、上传、新建、移动、重命名、自定义页面、待办、本机判定） |

## 目录结构

```
.
├── nginx.conf          # Nginx 配置
├── backend.py          # Flask 后端（全部 API）
├── start.sh            # 启动脚本（Flask + Nginx）
├── stop.sh             # 停止脚本
├── venv/               # Python 虚拟环境（Flask）
└── site/
    ├── index.html      # 首页（内容宽度滑条、待办/自定义页面入口、贴首页卡片）
    ├── files/
    │   └── index.html  # 文件浏览器（SPA，含 md 阅读入口）
    ├── reader.html     # Markdown 阅读器（支持图片与相对链接）
    ├── pages.html      # 自定义页面列表（创建、贴首页）
    ├── custom.html     # 自定义页面查看（页面文件浏览器 + 阅读）
    ├── todo.html       # 待办事项页面
    ├── info.html       # 关于页
    ├── files/          # 共享文件目录（gitignored）
    ├── custom/         # 自定义页面文件目录（gitignored）
    ├── custom_pages.json  # 自定义页面元数据（gitignored）
    ├── js/             # 前端脚本（layout.js、todo.js、pages.js、custom.js、pinned.js 等）
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
- **待办事项与自定义页面的创建/管理需使用 `http://localhost:8080` 访问**（仅限本机）。
- 自定义页面/待办查看对所有局域网用户开放。

> 注：本项目使用的 Nginx 位于 `~/nginx_install/usr/sbin/nginx`（由 `apt download nginx nginx-common nginx-core` 下载后用 `dpkg-deb -x` 解压到 home）。

## 配置说明

### backend.py

| 配置项 | 说明 |
|---|---|
| `LOCAL_IPS` | 本机判定集合（待办与自定义页面管理访问控制，默认仅回环地址 `127.0.0.1` / `::1`） |
| `BLOCKED_PATHS` | 禁止修改的目录黑名单（相对 `files/`，前缀匹配） |
| `TODO_FILE` | 待办数据文件路径（`site/todo.json`） |
| `PRIORITIES` | 待办优先级白名单（`high` / `medium` / `low`） |
| `CUSTOM_PAGES_FILE` | 自定义页面元数据文件（`site/custom_pages.json`） |
| `CUSTOM_DIR` | 自定义页面文件根目录（`site/custom/`） |
| `DOC_EXTS` / `IMAGE_EXTS` | 自定义页面上传允许的文档（`.md`）与图片扩展名（png/jpg/jpeg/gif/webp/bmp，不含 svg） |

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
| GET / POST | `/api/pages` | 自定义页面列表 / 创建（写操作仅本机） |
| PUT / DELETE | `/api/pages/<id>` | 修改标题/简介/pinned / 删除页面（仅本机） |
| GET | `/api/pages/<id>/tree?path=` | 列出页面目录子路径（开放） |
| POST | `/api/pages/<id>/upload` | 上传文档/图片到页面目录（仅本机） |
| POST | `/api/pages/<id>/mkdir` | 页面目录新建文件夹（仅本机） |
| POST | `/api/pages/<id>/delete` | 删除页面内文件/文件夹（仅本机） |
| GET / POST | `/api/todo` | 待办列表 / 添加 |
| PUT / DELETE | `/api/todo/<id>` | 更新 / 删除待办 |

## 安全与数据

- **路径穿越防护**：`safe_join_soft` 规范化路径并校验前缀，上传文件名经 `basename` 检查。
- **黑名单保护**：黑名单目录禁止上传、新建、移动、重命名。
- **本机操作限制**：待办、自定义页面的创建/编辑/上传/删除/贴首页均由 Flask `is_local_client()`（及 nginx `allow/deny`）限定仅本机。
- **隐藏文件过滤**：点文件（`.` 开头）与 `index.html` 不在文件浏览列表中显示。
- **数据文件**：`site/files/`、`site/custom/`、`site/custom_pages.json`、`site/todo.json` 均已加入 `.gitignore`，不入库。
