# 本地文件站（Local File Station）

一个基于 **Nginx + Flask** 的局域网文件共享网站，提供文件浏览与管理、Markdown 阅读（含图表渲染与简易客户端阅读器）、Word 在线阅读、多机局域网共享、自定义阅读页面、待办事项、临时文本、实用功能等功能。

## 功能特性

- **文件浏览**：自定义文件浏览器（替代 Nginx autoindex），解决中文文件名对齐问题，支持完整长文件名显示与响应式布局。
- **文件操作**：多文件上传（带实时进度条，上传上限由 nginx `client_max_body_size` 控制，默认 1GB）、新建文件夹、剪切/粘贴移动文件、重命名（文件与文件夹均可）、**文件夹一键打包下载**（`/api/zip`，不压缩、流式下发，排除点文件与 `index.html`）。
- **文件阅读入口**：`md` 文件在文件浏览中带有「阅读」按钮，点击可直接在站内 Markdown 阅读页打开。
- **Word 在线阅读**：`.doc` / `.docx` 文件在文件浏览（本机与局域网共享）中带有「阅读」按钮，服务端转换为 HTML 后在页内阅读：`.docx` 用 Python 标准库提取（正文/标题/表格/内嵌图片）；`.doc` 用 **LibreOffice**（`soffice`)转换保真排版；结果按内容哈希缓存（`tmp_docs/`，不入库）。
- **Markdown 图表（Mermaid）**：```mermaid 代码块在本机 Markdown 阅读器、局域网共享阅读弹层与简易阅读器中，由离线 vendored 的 `mermaid.min.js` 渲染为图（支持 `block-beta` 等）；渲染结果以 `data:` 内嵌为 `<img>`，**右键可另存为 SVG**。
- **简易 Markdown 阅读（客户端）**：首页「简易阅读」卡片进入 `/mdreader.html`，**拖入本地 `.md` 文件**即时渲染阅读（支持文档内标题锚点跳转）；可**导出独立 HTML**（内联样式与图表、相对 `.md` 链接改写为 `.html`，导出后支持文档间相对路径跳转）。纯客户端、无需服务端、对局域网开放。
- **Markdown 阅读入口可见性**：顶部导航不再提供「Markdown阅读」入口，首页「Markdown 阅读」卡片**仅在 localhost 显示**；仍可直接访问 `/reader.html`，文件浏览中 md 文件的「阅读」按钮不受影响。
- **黑名单目录保护**：`binary-translation` 目录禁止上传、移动、重命名等修改操作（仍可浏览下载）。
- **Markdown 阅读**：文件列表选择 + Markdown 渲染 + 代码高亮，显示完整文件名；支持**图片渲染**与**相对链接**（图片/链接按当前文档所在目录解析，`[链接](其他.md)` 可在阅读器内直接跳转）；阅读工具栏提供**复制全文**（一键复制原始 Markdown 源码）。
- **自定义页面**：创建独立的 Markdown 阅读页（标题 + markdown 简介 + 文档清单），组织若干相关文档集中阅读。
  - 每个页面内置**文件浏览器**：上传文档（`.md`）/图片（png/jpg/jpeg/gif/webp/bmp）、新建文件夹、删除、子目录导航。
  - markdown 中可引用同目录图片（`![](pic.png)`）与相对链接（含 `../` 退级）。
  - 页面可**贴到首页**形成导航卡片（仅本机可操作，卡片对所有访客可见）。
  - 阅读视图同样提供**复制全文**按钮。
  - **创建 / 编辑 / 上传 / 删除 / 贴首页** 均**仅限本机**；查看对所有局域网用户开放。
- **自定义网页卡片**：在首页添加自定义网页卡片（标题 + 内容简介 + 目标网页链接），统一使用 🌐 logo；点击「进入网页」按钮**新标签页**打开目标地址（支持外链 `http(s)://` 与站内 `/` 相对路径）。**仅本机可添加/编辑/删除**，卡片对所有局域网访客可见（服务端持久化 `data/app.db` 的 `links` 表）。
- **多机局域网共享**：局域网内任意机器可运行 `scripts/peer.py`（仅 Python 标准库）以只读方式共享一个目录，并每 30s 向中心站心跳注册；中心站「局域网共享」门户（`peers.html`）汇总在线机器与其共享目录，供访客统一浏览下载。
  - 目录列表由中心站**服务端转发**（`/api/peers/<id>/tree`，无 CORS 问题）；文件**下载直连各机器**（`http://<机器IP>:<端口>/files/...`，不占中心站带宽，支持 Range 断点续传/视频拖进度条）。
  - 远程 `.md` 文件可在网页内**直接阅读**（`/api/peers/<id>/file` 经中心站读取，支持代码高亮与相对图片/链接解析到该节点）。
  - 远程 `.doc` / `.docx` 文件同样可**在线阅读**（`/api/peers/<id>/doc` 经中心站转换）。
  - 远程目录支持**一键打包下载**（节点 `/api/zip`，不压缩、流式，排除点文件与 `index.html`，超过 1GB 禁止并提示）。
  - 门户页提供 `peer.py` 下载与运行说明；各机器本地照常管理目录内容，网页端只读。
  - 注册密钥 `PEER_SECRET` 校验，防止局域网内他人伪造共享源；密钥对门户访客可见（便于自服务部署）。
  - **防火墙自处理**：peer.py 检测本机 firewalld/ufw，root 运行时自动放行所选端口（关闭时自动移除），普通用户运行时打印放行命令提示。
  - 在线判定 `PEER_TTL`（默认 90s，即 3 个心跳周期）；**主动关闭** peer.py 时会向中心站发送下线通知立即移除，否则超过 TTL 未心跳的节点会被**自动清除**（不再保留离线机器信息）。
  - 门户页**只显示在线机器**，不提供离线展示。
- **临时文本**：随手记录临时文本（标题 + 文本内容），服务端持久化（`data/app.db` 的 `temp_notes` 表），按添加顺序展示、**新增排最上**；进入编辑模式可对每条**编辑/删除**。**页面与 API 均仅限 localhost**，首页卡片仅在 localhost 显示。
- **待办事项**：服务端持久化（`data/app.db` 的 `todos` 表），支持添加、行内编辑、删除、优先级（高/中/低，点击循环切换）、**状态标记**（未完成项循环：开始 → 进行中 → 暂停 → 进行中；暂停时点击状态按钮恢复进行中，或点击旁侧 `×` 重置为未开始；进行中排最前、暂停居中，蓝色/橙色高亮，并带分组标题条区分）、按时间/名称/优先级排序、完成沉底置灰。**仅限 localhost 访问**。
- **实用功能**：以卡片形式记录实用命令与小技巧（`features.html`），服务端持久化（`data/app.db` 的 `features` 表），支持**按标题/内容搜索**（服务端过滤）、瀑布流多栏卡片布局。
  - **创建 / 编辑 / 删除**均**仅限本机**：页面与 `/api/features` 均由 nginx 限定 localhost；进入页面后可点「创建」新增，点「编辑」进入编辑模式后每张卡片出现「编辑」「删除」按钮（默认不显示）。
  - 附带维护脚本 `skill/local-features/features.sh`（`search` / `add` 子命令，走 HTTP 接口）及配套 `local-features` 技能，供智能体维护功能库。
- **内容宽度调节**：首页滑条调节内容区宽度（900–1800px），通过 `localStorage` 记住，全站生效。
- **本机访问判定**：首页「待办事项」「自定义页面」「实用功能」「自定义网页」「临时文本」「Markdown 阅读」的管理入口仅在 localhost 访问时显示。
- **每周周报**：周报列表和详情页对局域网开放，按项目或人员查看提交内容；所有人员可提交或选择已有人员修改内容，周报和项目配置仅限 localhost 管理，并支持 Markdown 导出和零依赖只读 Python 客户端。
  - 周报页的“管理默认项目”入口仅 localhost 可见，可维护默认项目名称、必填状态和顺序；创建新周报时自动复制当时的默认项目，详情页仍可单独编辑当前周报项目。
- **首页分组**：Markdown 阅读、待办事项、自定义页面、实用功能和临时文本入口集中在「本机功能」分组，位于默认卡片（含置顶阅读页）与自定义网页卡片之间；仅本机显示，访问判定失败时保持隐藏。

## 架构

| 组件 | 端口 | 职责 |
|---|---|---|
| Nginx | 8080 | 静态页面、`/files/` autoindex、`/peer.py` 脚本下发、`/api/` 反向代理到 Flask、todo/features/temp 页与 API 仅限 localhost |
| backend.py（Flask） | 5000 | 提供全部 JSON API（文件浏览、上传、打包下载、doc/docx 转 HTML、自定义页面、待办、临时文本、实用功能、局域网共享节点注册与转发、本机判定） |

## 目录结构

```
.
├── nginx.conf          # Nginx 配置
├── backend.py          # Flask 后端（全部 API）
├── storage.py          # SQLite 存储、事务与旧 JSON 导入
├── data/               # SQLite 数据库与迁移备份（gitignored，不对外提供静态访问）
├── venv/               # Python 虚拟环境（Flask）
├── scripts/            # 管理脚本
│   ├── migrate_sqlite.py   # 停止旧后端后执行的一次性迁移
│   ├── backup_sqlite.py    # SQLite 在线一致性备份
│   ├── start.sh            # 启动脚本（Flask + Nginx）
│   ├── stop.sh             # 停止脚本
│   ├── setup-systemd.sh    # 配置开机自启
│   ├── check-services.sh   # 检测服务状态
│   ├── disable-systemd.sh  # 取消开机自启
│   ├── unsetup-systemd.sh  # 移除 systemd 服务
│   ├── weekly.py           # 周报只读 HTTP 客户端
│   └── peer.py             # 局域网共享节点脚本（可分发到各机器运行）
└── site/
    ├── index.html      # 首页（内容宽度滑条、待办/自定义页面/实用功能/自定义网页/简易阅读/临时文本入口、贴首页卡片）
    ├── files/
    │   └── index.html  # 文件浏览器（SPA，含 md 阅读入口）
    ├── reader.html     # Markdown 阅读器（支持图片与相对链接；导航不提供入口，仅 localhost 卡片/直接 URL）
    ├── mdreader.html   # 简易 Markdown 阅读器（客户端拖拽 + 导出独立 HTML，入口为首页卡片）
    ├── docreader.html  # Word（.doc/.docx）在线阅读器（服务端转 HTML）
    ├── peers.html      # 局域网共享门户（peer.py 下载与运行说明 + 在线机器列表）
    ├── peer.html       # 远程机器只读文件浏览器（列表 + 下载 + 目录打包 + md/doc 网页阅读）
    ├── pages.html      # 自定义页面列表（创建、贴首页）
    ├── custom.html     # 自定义页面查看（页面文件浏览器 + 阅读）
    ├── todo.html       # 待办事项页面
    ├── temp.html       # 临时文本页面（仅本机）
    ├── features.html   # 实用功能页面（卡片列表 + 搜索 + 本机编辑模式）
    ├── info.html       # 关于页
    ├── files/          # 共享文件目录（gitignored）
    ├── custom/         # 自定义页面文件目录（gitignored）
    ├── js/             # 前端脚本（layout.js、todo.js、temp.js、pages.js、custom.js、features.js、pinned.js、homecards.js、fulltext.js、peers.js、peer.js、mdreader.js、docreader.js、md-diagram.js、mermaid.min.js 等）
    └── css/style.css   # 全局样式
└── skill/
    └── local-features/ # 本地功能库技能（features.sh 维护脚本 + SKILL.md）
```

## 快速开始

依赖：Nginx、Python3 + venv（Flask）。Word（.doc）在线阅读需额外安装 **LibreOffice**（`sudo apt-get install -y libreoffice`）。

```bash
./venv/bin/python3 scripts/migrate_sqlite.py --archive-legacy  # 首次启动前初始化/导入；旧后端必须已停止
./scripts/start.sh     # 启动 Flask 后端 + Nginx
./scripts/stop.sh      # 停止服务
```

- 本机访问：<http://localhost:8080>
- 局域网访问：<http://服务器局域网IP:8080>
- **待办事项、临时文本、实用功能与自定义页面的创建/管理需使用 `http://localhost:8080` 访问**（仅限本机）。
- 自定义页面查看对局域网用户开放；待办、临时文本与实用功能页面/API 仅限本机。

> 注：本项目使用的 Nginx 位于 `~/nginx_install/usr/sbin/nginx`（由 `apt download nginx nginx-common nginx-core` 下载后用 `dpkg-deb -x` 解压到 home）。

## SQLite 存储与迁移

六类元数据分别保存在 `todos`、`features`、`temp_notes`、`links`、`peers`、`pages` 表中。上传文件和自定义页面文档仍在文件系统中；API 路径、返回字段和前端使用方式保持兼容。

- 每条记录独立存储；保留 ID、原始顺序、时间和额外旧字段。旧待办缺少 `status` 时，按原有 `in_progress` 规则补齐。
- 每个请求独立连接；修改操作使用 `BEGIN IMMEDIATE` 覆盖读改写，提交或失败回滚。节点地址有唯一约束，过期清理与心跳串行提交。
- WAL 允许读写并行，但写事务仍串行；锁等待最多 5 秒，超时返回 HTTP 503 与 `Retry-After: 1`。同字段更新仍采用最后提交者覆盖的行为。
- 使用 `synchronous=FULL`；不要把数据库放到 NFS/SMB 等网络文件系统。自定义页面目录的删除不属于数据库事务，仍采用原有“先删除元数据，再清理目录”的行为。

升级已有实例时，先停止**实际运行的所有旧 Flask 进程**（手动启动与 systemd 启动需分别确认），再执行：

```bash
./venv/bin/python3 scripts/migrate_sqlite.py --archive-legacy
```

迁移在单个事务中导入六类数据，先备份原始字节到 `data/legacy-json-<唯一标识>/`；无效 JSON、非法字段或重复 ID/节点地址会导致导入回滚，原文件保留。不存在的源文件作为空表处理。数据库记录迁移版本，重复运行不会覆盖后续修改；修复失败的源数据后可以重试。

`--archive-legacy` 会核对源文件和备份的 SHA-256，然后移除静态目录内的旧 JSON；发现源文件在迁移后变化会拒绝移除。省略此参数可暂时保留源文件，但它们不再参与运行时读写。新 Nginx 配置同时阻止六类旧 JSON 及 `.json.tmp` 的静态访问。

迁移成功后启动新后端，并测试、重载 Nginx 配置。首次部署的空目录也应先运行迁移命令初始化数据库；后端不会在收到请求时自动导入旧文件。指定其他路径时，迁移工具和后端统一使用 `LOCALWEBSITE_DB`，或为迁移工具指定 `--database`。

在线备份使用 SQLite backup API，不能只复制仍在使用的 `app.db` 而遗漏 WAL：

```bash
./venv/bin/python3 scripts/backup_sqlite.py data/backups/app-20260911.db
./venv/bin/python3 -m unittest discover -s tests -v
```

备份命令拒绝覆盖已有文件。恢复时停止后端，先完整保留当前数据库及其 `-wal`、`-shm` 文件，再将备份恢复到没有旧 WAL/SHM 的数据库路径，最后启动后端。回退到旧代码只可使用迁移时的 JSON 备份；切换后的 SQLite 新增修改不会自动回写旧 JSON。

## 配置说明

### backend.py

| 配置项 | 说明 |
|---|---|
| `LOCALWEBSITE_DB`（环境变量） | SQLite 文件路径，默认项目内 `data/app.db`；必须放本地磁盘且位于静态目录之外 |
| `LOCAL_IPS` | 本机判定集合（待办/实用功能/自定义页面管理访问控制，默认仅回环地址 `127.0.0.1` / `::1`） |
| `BLOCKED_PATHS` | 禁止修改的目录黑名单（相对 `files/`，前缀匹配） |
| `PRIORITIES` | 待办优先级白名单（`high` / `medium` / `low`） |
| `PEER_SECRET` | 节点注册密钥（`openssl rand -hex 16` 生成；门户页对访客展示，便于自服务部署） |
| `PEER_TTL` | 节点在线判定阈值秒数（默认 90，需大于心跳间隔） |
| `CUSTOM_DIR` | 自定义页面文件根目录（`site/custom/`） |
| `DOC_EXTS` / `IMAGE_EXTS` | 自定义页面上传允许的文档（`.md`）与图片扩展名（png/jpg/jpeg/gif/webp/bmp，不含 svg） |
| `TMP_DOWNLOAD_DIR` | 文件夹打包临时目录（`tmp_downloads/`，不入库） |
| `MAX_ZIP_SIZE` | 文件夹打包下载大小上限（1GB） |
| `TMP_DOCS_DIR` | 文档（`.doc`/`.docx`）转 HTML 结果缓存目录（`tmp_docs/`，不入库） |
| `MAX_DOC_BYTES` | 在线阅读文档大小上限（50MB） |

### nginx.conf

- `/todo.html`、`/features.html`、`/temp.html` 与 `/api/todo`、`/api/features`、`/api/temp`：仅允许 `127.0.0.1`、`::1`（其余 `deny all`）
- `/peer.py`、`/weekly.py`：直接下发对应的零依赖 Python 脚本（单一来源，供各机器下载运行）
- `/api/`：反向代理到 Flask，`client_max_body_size 1g`（上传大小限制，可调）；上传缓冲目录 `client_body_temp_path` 位于磁盘（`nginx_client_body/`），避免大文件上传占用系统内存

## 多机共享使用说明

在任意局域网机器上（需 Python 3），一键下载并运行（共享脚本所在目录，`sudo` 以便自动放行防火墙端口）：

```bash
curl -O http://<服务器IP>:8080/peer.py && sudo python3 peer.py
```

也可先只下载、再按需选择运行方式（`central`、`secret`、`name`、端口均已内置默认值，无需填写）：

| 方式 | 命令 | 说明 |
|---|---|---|
| 1 | `python3 peer.py` | 共享脚本所在目录，机器名取本机主机名 |
| 2 | `python3 peer.py --dir /path/to/share` | 指定共享目录，机器名默认 |
| 3 | `python3 peer.py --dir /path/to/share --name "我的机器"` | 指定共享目录与机器名 |

- 端口未指定时自动从 9000 起探测可用端口；默认每 30s 心跳注册，机器上线/离线约 1 分钟内反映（离线节点会被自动清除）。
- 如需连接其他中心站或更换密钥，用 `--central` / `--secret` 覆盖；更多参数见 `python3 peer.py --help`。
- 密钥与运行命令也可在中心站「局域网共享」页面（`/peers.html`）直接查看复制。

### 防火墙（重要）

多数 Linux 发行版默认开启 firewalld/ufw，仅放行少数端口（如 ssh），其余端口一律拦截——这是「节点显示在线但无法浏览/下载」的常见原因。

- **以 root 运行** `sudo python3 peer.py`：脚本会自动放行所选端口（优雅关闭时自动移除规则）。
- **以普通用户运行**：脚本会打印放行命令，按提示手动执行一次即可，例如端口 9000：

  ```bash
  # firewalld（CentOS/Rocky/Fedora 等）
  sudo firewall-cmd --permanent --add-port=9000/tcp
  sudo firewall-cmd --reload

  # ufw（Ubuntu/Debian 等）
  sudo ufw allow 9000/tcp
  ```

  自定义 `--port` 时请将命令中的 9000 换成实际端口。

## API 一览

### 周报只读脚本

局域网机器只需 Python 3，无需安装第三方依赖：

```bash
curl -O http://<服务器IP>:8080/weekly.py
python3 weekly.py help                                 # 显示脚本支持的操作
python3 weekly.py                                      # 显示最新 5 个周报
python3 weekly.py list --limit 10                     # 显示最新 10 个
python3 weekly.py list --json                         # 输出可供程序处理的 JSON
python3 weekly.py people <周报ID>                     # 查看已提交人员，每行一个姓名
python3 weekly.py people <周报ID> --json              # 以 JSON 数组输出人员列表
python3 weekly.py export                              # 导出最新周报到终端
python3 weekly.py export <周报ID>                     # 导出指定周报到终端
python3 weekly.py export <周报ID> > 本周周报.md        # 使用 shell 重定向保存
python3 weekly.py export <周报ID> --view person -o 按人员.md
python3 weekly.py export <周报ID> --person 张三        # 仅导出指定人员的内容
python3 weekly.py export --start-time 20260101 --end-time 20261231  # 导出与时间段有交集的全部周报
python3 weekly.py export --month 202608                # 导出与 2026 年 8 月有交集的周报
python3 weekly.py export --year 2026 --person 张三     # 导出张三在 2026 年相关周报中的内容
```

时间段导出按周报开始日期从早到晚排列。只要周报日期与指定时间段有部分重叠便会纳入；
使用 `--person` 时，会跳过该人员没有提交的周报。`--month` 和 `--year` 分别是整月、整年的快捷写法。

脚本默认连接 `http://192.168.8.65:8080`。连接其他部署地址时，在子命令之前添加
`--server http://<服务器IP>:8080`，或设置环境变量 `WEEKLY_SERVER`。所有命令均为只读操作。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/files?path=` | 列出目录内容（含每项 `blocked` 标志） |
| GET | `/api/doc?path=` | 将本机 `.doc`/`.docx` 转 HTML（docx 用 stdlib、doc 用 LibreOffice，按内容缓存） |
| GET | `/api/zip?path=` | 打包下载目录为 zip（不压缩、流式，排除点文件与 index.html） |
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
| GET / POST | `/api/features` | 实用功能列表（支持 `?q=` 服务端搜索）/ 创建（仅本机） |
| GET / POST | `/api/temp` | 临时文本列表 / 新增（均仅本机） |
| PUT / DELETE | `/api/temp/<id>` | 编辑 / 删除临时文本（仅本机） |
| PUT / DELETE | `/api/features/<id>` | 更新 / 删除实用功能（仅本机） |
| GET / POST | `/api/links` | 首页自定义网页卡片列表（开放）/ 添加（仅本机） |
| PUT / DELETE | `/api/links/<id>` | 更新 / 删除首页自定义网页卡片（仅本机） |
| GET / POST | `/api/weekly?limit=N` | 周报列表（开放；GET 可用正整数 `limit` 限制数量，省略则返回全部）/ 创建周报（仅本机） |
| GET | `/api/weekly/<id>/people` | 指定周报的已提交人员名称列表（开放） |
| GET / POST | `/api/weekly/default-projects` | 默认项目列表（开放）/ 添加默认项目（仅本机） |
| PUT / DELETE | `/api/weekly/default-projects/<project_id>` | 修改或删除默认项目（仅本机） |
| GET / PUT / DELETE | `/api/weekly/<id>` | 周报详情（开放）/ 修改或删除（仅本机） |
| POST | `/api/weekly/<id>/projects` | 添加周报项目（仅本机） |
| PUT / DELETE | `/api/weekly/<id>/projects/<project_id>` | 修改或删除项目（仅本机） |
| GET / POST | `/api/weekly/<id>/submissions` | 查看提交 / 新增或按版本修改人员提交（开放） |
| GET | `/api/weekly/<id>/export?view=project\|person&person=姓名` | 导出 Markdown，可选仅导出指定人员（开放） |
| POST | `/api/peers/register` | 节点心跳注册（开放，校验 `PEER_SECRET`，按 `host+port` 去重 upsert） |
| POST | `/api/peers/unregister` | 节点主动下线通知（开放，校验 `PEER_SECRET`，按 `host+port` 移除） |
| GET | `/api/peers` | 在线共享节点列表（开放；离线节点自动清除，不保留记录） |
| GET | `/api/peers/<id>/tree?path=` | 服务端转发节点目录列表（开放；节点离线返回 503） |
| GET | `/api/peers/<id>/file?path=` | 读取节点 `.md` 文件内容用于网页阅读（开放，仅限 `.md`，>5MB 拒绝） |
| GET | `/api/peers/<id>/doc?path=` | 读取节点 `.doc`/`.docx` 并转 HTML（开放，经中心站转换，>50MB 拒绝） |
| DELETE | `/api/peers/<id>` | 移除节点（仅本机） |

修改已有周报提交时，请将详情接口返回的 `id` 和 `revision` 分别作为
`submission_id`、`expected_revision` 提交。保存成功后 `revision` 自动加一；如果内容已被
其他请求修改，接口返回 HTTP 409，客户端应重新加载最新内容。新增提交从 `revision: 1`
开始，同一周报内已有的人员名称必须通过修改流程保存。

### 节点 HTTP 接口（peer.py）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/peertree?path=` | 目录 JSON 列表（与 `/api/files` 同构） |
| GET | `/api/zip?path=&check=1` | 打包下载目录（不压缩、流式；`check=1` 仅检查大小；>1GB 返回 413） |
| GET | `/files/*` | 文件下载（支持 Range/206、HEAD，只读） |
| GET | `/` | 服务信息 |

## 安全与数据

- **路径穿越防护**：`safe_join_soft` 规范化路径并校验前缀，上传文件名经 `basename` 检查。
- **黑名单保护**：黑名单目录禁止上传、新建、移动、重命名。
- **本机操作限制**：待办、实用功能、自定义网页卡片、自定义页面的创建/编辑/上传/删除/贴首页均由 Flask `is_local_client()`（及 nginx `allow/deny`）限定仅本机；首页自定义网页卡片列表读取对所有局域网访客开放。
- **节点注册鉴权**：局域网共享节点必须携带 `PEER_SECRET` 注册，否则 403；目录列表转发仅访问注册表中存在的节点（`host/port` 只取自注册表），路径由节点侧再次校验防穿越。
- **隐藏文件过滤**：点文件（`.` 开头）与 `index.html` 不在文件浏览列表中显示。
- **数据文件**：`site/files/`、`site/custom/`、`data/` 均已加入 `.gitignore`。六类元数据保存在 `data/app.db`，旧 JSON 只在迁移时读取。
