#!/bin/bash
# 实用功能命令行工具：通过 HTTP 接口搜索 / 创建功能（仅本机可访问）
# 用法:
#   features.sh                     显示用法
#   features.sh search [关键字]      搜索功能（可读列表），无关键字显示全部
#   features.sh add <标题> <内容>    创建功能
#
# 可通过环境变量 LOCALWEB_FEATURES_URL 覆盖默认地址（默认 http://127.0.0.1:8080）

LOCALWEB_FEATURES_URL="${LOCALWEB_FEATURES_URL:-http://127.0.0.1:8080}"

usage() {
    cat <<EOF
用法:
  $0 search [关键字]    搜索功能（可读列表），无关键字显示全部
  $0 add <标题> <内容>   创建功能

环境变量:
  LOCALWEB_FEATURES_URL  接口地址（默认 http://127.0.0.1:8080）
EOF
}

json_readable() {
    python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("无法解析服务端返回的数据", file=sys.stderr)
    sys.exit(1)
if not isinstance(data, list):
    print(data.get("error", "未知错误"), file=sys.stderr)
    sys.exit(1)
if not data:
    print("（无匹配内容）")
    sys.exit(0)
for i, f in enumerate(data, 1):
    print(str(i) + ". " + f.get("title", ""))
    content = (f.get("content") or "").replace("\n", "\n    ")
    if content:
        print("    " + content)
    print()
'
}

do_search() {
    local keyword="$1"
    local url="$LOCALWEB_FEATURES_URL/api/features"
    local args=(-s)
    if [ -n "$keyword" ]; then
        args+=(-G --data-urlencode "q=$keyword")
    fi
    local resp code
    resp="$(curl "${args[@]}" -w $'\n%{http_code}' "$url" 2>/dev/null)"
    code="${resp##*$'\n'}"
    resp="${resp%$'\n'*}"
    if [ -z "$code" ] || [ "$code" = "000" ]; then
        echo "错误: 无法连接 $LOCALWEB_FEATURES_URL （服务未启动？）" >&2
        exit 1
    fi
    if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
        printf '%s\n' "$resp" | json_readable
    else
        printf '%s\n' "$resp" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("错误: "+d.get("error",("HTTP %s"%sys.argv[1])))' "$code"
        exit 1
    fi
}

do_add() {    local title="$1" content="$2"
    if [ -z "$title" ]; then
        echo "错误: 标题不能为空" >&2
        exit 1
    fi
    if [ -z "$content" ]; then
        echo "错误: 内容不能为空" >&2
        exit 1
    fi
    local payload
    payload="$(python3 -c 'import json,sys;print(json.dumps({"title":sys.argv[1],"content":sys.argv[2]}))' "$title" "$content")" || exit 1
    local resp code
    resp="$(curl -s -X POST -H 'Content-Type: application/json' -d "$payload" -w $'\n%{http_code}' "$LOCALWEB_FEATURES_URL/api/features" 2>/dev/null)"
    code="${resp##*$'\n'}"
    resp="${resp%$'\n'*}"
    if [ -z "$code" ] || [ "$code" = "000" ]; then
        echo "错误: 无法连接 $LOCALWEB_FEATURES_URL （服务未启动？）" >&2
        exit 1
    fi
    if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
        printf '%s\n' "$resp" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("已创建: "+d.get("title",""))'
    else
        printf '%s\n' "$resp" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("错误: "+d.get("error",("HTTP %s"%sys.argv[1])))' "$code"
        exit 1
    fi
}

cmd="$1"
shift 2>/dev/null || true
case "$cmd" in
    search)
        do_search "$1"
        ;;
    add)
        if [ $# -lt 2 ]; then
            echo "错误: add 需要标题和内容两个参数" >&2
            usage >&2
            exit 1
        fi
        do_add "$1" "$2"
        ;;
    "")
        usage
        ;;
    *)
        echo "未知命令: $cmd" >&2
        usage >&2
        exit 1
        ;;
esac
