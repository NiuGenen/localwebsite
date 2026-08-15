---
name: local-features
description: Maintain the "本地功能库" (local features library). Use when the user wants to add, search, or manage practical commands and tips in the local features library, or mentions the features.sh script.
---

# 本地功能库（实用功能）

把实用命令、小技巧以「标题 + 内容」的形式存入本地功能库，供日后搜索复用。本技能自带 `features.sh` 脚本（与本文件同目录），通过该脚本的 HTTP 接口完成所有操作。

## 依赖

- **脚本**：本目录下的 `features.sh`（提供 `search` 与 `add` 两个子命令，可执行权限）
- **环境变量**：`LOCALWEB_FEATURES_URL`，本地网站地址（默认 `http://127.0.0.1:8080`，可覆盖）

## 脚本用法

先定位脚本所在目录（即本技能目录 `skill/local-features/`），然后执行：

```bash
FEATURES_SH="$(dirname "$(find skill/local-features -name features.sh 2>/dev/null | head -1)")/features.sh"
"$FEATURES_SH"                     # 显示用法
"$FEATURES_SH" search [关键字]      # 可读列表搜索；无关键字显示全部
"$FEATURES_SH" add <标题> <内容>    # 添加一条功能
```

若 `features.sh` 已在 PATH 中，也可直接调用 `features.sh ...`。

> 下文工作流中的 `features.sh` 均指上述解析出的脚本（或在 PATH 中的同名脚本）。

- 关键字自动做 URL 编码，标题/内容由脚本用 `json.dumps` 转义（引号、反斜杠、换行无需手动处理）
- 非 0 退出码 = 出错（服务未启动、缺参数、服务端校验失败等）

## 工作流

### 1. 确认本地网站是否存在

操作前必须先确认本地网站服务在线，避免误判或误报错误：

```bash
features.sh search
```

- 若脚本正常列出内容：服务可用，继续后续步骤。
- 若脚本提示「无法连接 ...（服务未启动？）」或退出码非 0：本地网站未运行。此时**不要继续添加**，先告知用户需要启动本地网站服务，待其启动后再重试。

（备选：`curl -s -o /dev/null -w "%{http_code}" "$LOCALWEB_FEATURES_URL"` 直接检查首页 HTTP 状态码。）

### 2. 组装内容

决定要收录的「命令」——命令本体、关键选项、适用场景与提示。

- **标题**：简短概括，如「查看网络速度」「查看AMD显卡占用率」
- **内容**：纯文本（不支持 Markdown），可多行，写入完整可用的命令与必要说明，例如：

  ```
  sudo nethogs
  ```

  或带说明的多行内容：

  ```
  统计各连接占用带宽
  sudo nethogs -t -d 1
  退出：Ctrl+C
  ```

- 服务端校验：标题必填且 ≤100 字符，内容必填且 ≤5000 字符；超限会报错，需精简后重试。

### 3. 先搜索查重

`features.sh search <关键字>`，确认库中还没有同名/同功能条目，避免重复收录。

### 4. 执行添加

`features.sh add "<标题>" "<内容>"`

- 内容包含换行/引号时直接放在双引号参数里，脚本自动处理转义。
- 成功会打印「已创建: <标题>」；失败会打印服务端错误信息。

### 5. 回读确认

`features.sh search <标题关键字>`，确认新条目已入库且内容正确。

## 常见用法示例

```bash
# 添加一条命令
features.sh add "查看网络速度" "sudo nethogs"

# 搜索已有内容
features.sh search nethogs

# 列出库中全部内容
features.sh search
```

## 注意事项

- 该功能库仅允许 localhost 访问，脚本需在本地网站所在的机器上运行。
- 添加是即时的（直接走 HTTP 接口），无需重启任何服务。
- 标题与内容均为纯文本，不要写 Markdown 语法标记。
