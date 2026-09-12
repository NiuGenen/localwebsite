#!/usr/bin/env python3
"""通过 HTTP 只读访问本地文件站的每周周报。"""

import argparse
import calendar
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_SERVER = "http://192.168.8.65:8080"
DEFAULT_TIMEOUT = 10.0


class WeeklyClientError(Exception):
    pass


def api_url(server, path, query=None):
    server = server.strip().rstrip("/")
    if not server.startswith(("http://", "https://")):
        raise WeeklyClientError("服务器地址必须以 http:// 或 https:// 开头")
    url = server + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def request_bytes(server, path, timeout, query=None, accept="application/json"):
    url = api_url(server, path, query)
    request = urllib.request.Request(url, headers={"Accept": accept})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            message = payload.get("error", "") if isinstance(payload, dict) else ""
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        detail = f"：{message}" if message else ""
        raise WeeklyClientError(f"HTTP {exc.code}{detail}") from exc
    except urllib.error.URLError as exc:
        raise WeeklyClientError(f"无法连接服务器：{exc.reason}") from exc
    except TimeoutError as exc:
        raise WeeklyClientError("连接服务器超时") from exc


def request_json(server, path, timeout, query=None):
    raw = request_bytes(server, path, timeout, query)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeeklyClientError("服务器返回了无效的 JSON") from exc


def print_report_list(reports):
    if not reports:
        print("暂无周报。")
        return
    headers = ("ID", "开始日期", "结束日期", "标题")
    rows = [headers]
    rows.extend((str(item.get("id", "")), str(item.get("week_start", "")),
                 str(item.get("week_end", "")), str(item.get("title", "")))
                for item in reports)
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    for row_index, row in enumerate(rows):
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            print("  ".join("-" * width for width in widths))


def print_people(people):
    if not people:
        print("暂无人员提交。")
        return
    for name in people:
        print(name)


def latest_report_id(server, timeout):
    reports = request_json(server, "/api/weekly", timeout, {"limit": 1})
    if not isinstance(reports, list):
        raise WeeklyClientError("服务器返回的周报列表格式无效")
    if not reports:
        raise WeeklyClientError("暂无周报可导出")
    report_id = reports[0].get("id") if isinstance(reports[0], dict) else None
    if not isinstance(report_id, str) or not report_id:
        raise WeeklyClientError("服务器返回的最新周报 ID 无效")
    return report_id


def parse_compact_date(value, option):
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise WeeklyClientError(f"{option} 必须是有效的 YYYYMMDD 日期") from exc


def export_period(args):
    explicit = args.start_time is not None or args.end_time is not None
    aliases = int(args.month is not None) + int(args.year is not None)
    if explicit and (args.start_time is None or args.end_time is None):
        raise WeeklyClientError("--start-time 和 --end-time 必须同时使用")
    if int(explicit) + aliases > 1:
        raise WeeklyClientError("时间段、--month 和 --year 只能选择一种")
    if args.report_id and (explicit or aliases):
        raise WeeklyClientError("周报 ID 不能与时间段参数同时使用")
    if args.month is not None:
        try:
            month = datetime.strptime(args.month, "%Y%m")
        except (TypeError, ValueError) as exc:
            raise WeeklyClientError("--month 必须是有效的 YYYYMM") from exc
        last_day = calendar.monthrange(month.year, month.month)[1]
        return month.date(), month.replace(day=last_day).date()
    if args.year is not None:
        if len(args.year) != 4 or not args.year.isdigit():
            raise WeeklyClientError("--year 必须是有效的 YYYY")
        year = int(args.year)
        if year < 1:
            raise WeeklyClientError("--year 必须是有效的 YYYY")
        return datetime(year, 1, 1).date(), datetime(year, 12, 31).date()
    if explicit:
        start = parse_compact_date(args.start_time, "--start-time")
        end = parse_compact_date(args.end_time, "--end-time")
        if start > end:
            raise WeeklyClientError("开始日期不能晚于结束日期")
        return start, end
    return None


def reports_in_period(server, timeout, start, end):
    reports = request_json(server, "/api/weekly", timeout)
    if not isinstance(reports, list):
        raise WeeklyClientError("服务器返回的周报列表格式无效")
    selected = []
    for report in reports:
        if not isinstance(report, dict):
            raise WeeklyClientError("服务器返回的周报列表格式无效")
        try:
            report_start = datetime.strptime(report["week_start"], "%Y-%m-%d").date()
            report_end = datetime.strptime(report["week_end"], "%Y-%m-%d").date()
            report_id = report["id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise WeeklyClientError("服务器返回的周报日期或 ID 无效") from exc
        if not isinstance(report_id, str) or not report_id:
            raise WeeklyClientError("服务器返回的周报日期或 ID 无效")
        if report_start <= end and report_end >= start:
            selected.append((report_start, report_end, report))
    selected.sort(key=lambda item: (item[0], item[1], item[2].get("created", 0), item[2]["id"]))
    return [item[2] for item in selected]


def export_one(server, timeout, report_id, view, person=None):
    query = {"view": view}
    if person:
        query["person"] = person
    return request_bytes(
        server,
        "/api/weekly/" + urllib.parse.quote(report_id, safe="") + "/export",
        timeout,
        query,
        "text/markdown",
    )


def export_range(args, start, end):
    reports = reports_in_period(args.server, args.timeout, start, end)
    if not reports:
        raise WeeklyClientError("指定时间段内没有周报可导出")
    documents = []
    for report in reports:
        report_id = report["id"]
        if args.person:
            people = request_json(
                args.server,
                "/api/weekly/" + urllib.parse.quote(report_id, safe="") + "/people",
                args.timeout,
            )
            if not isinstance(people, list) or not all(isinstance(name, str) for name in people):
                raise WeeklyClientError("服务器返回的人员列表格式无效")
            if args.person not in people:
                continue
        documents.append(export_one(args.server, args.timeout, report_id, args.view, args.person))
    if not documents:
        raise WeeklyClientError("指定时间段内没有该人员的周报内容：" + args.person)
    return b"\n\n---\n\n".join(document.rstrip(b"\n") for document in documents) + b"\n"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.environ.get("WEEKLY_SERVER", DEFAULT_SERVER),
                        help=f"周报服务器地址（默认：{DEFAULT_SERVER}；可用 WEEKLY_SERVER 覆盖）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"请求超时秒数（默认：{DEFAULT_TIMEOUT:g}）")
    parser.set_defaults(command="list", limit=5, as_json=False)
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="列出最近的周报")
    list_parser.add_argument("--limit", type=int, default=5, help="显示数量（默认：5）")
    list_parser.add_argument("--json", dest="as_json", action="store_true", help="输出原始 JSON")

    subparsers.add_parser("help", help="显示脚本支持的操作")

    people_parser = subparsers.add_parser("people", help="列出指定周报中的人员")
    people_parser.add_argument("report_id", help="周报 ID")
    people_parser.add_argument("--json", dest="as_json", action="store_true", help="输出原始 JSON")

    export_parser = subparsers.add_parser("export", help="获取周报 Markdown（默认最新周报）")
    export_parser.add_argument("report_id", nargs="?", help="周报 ID；省略时导出最新周报")
    export_parser.add_argument("--view", choices=("project", "person"), default="project",
                               help="按项目或人员组织内容（默认：project）")
    export_parser.add_argument("--person", help="仅导出指定人员的内容")
    export_parser.add_argument("--start-time", help="时间段开始日期，格式 YYYYMMDD")
    export_parser.add_argument("--end-time", help="时间段结束日期，格式 YYYYMMDD")
    export_parser.add_argument("--month", help="按整月导出，格式 YYYYMM")
    export_parser.add_argument("--year", help="按整年导出，格式 YYYY")
    export_parser.add_argument("-o", "--output", type=Path, help="保存路径；省略时输出到终端")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.command = "list"
    if args.timeout <= 0:
        print("错误：timeout 必须大于 0", file=sys.stderr)
        return 2
    try:
        if args.command == "help":
            build_parser().print_help()
        elif args.command == "list":
            if args.limit <= 0:
                raise WeeklyClientError("limit 必须是正整数")
            reports = request_json(args.server, "/api/weekly", args.timeout, {"limit": args.limit})
            if not isinstance(reports, list):
                raise WeeklyClientError("服务器返回的周报列表格式无效")
            if args.as_json:
                print(json.dumps(reports, ensure_ascii=False, indent=2))
            else:
                print_report_list(reports)
        elif args.command == "people":
            people = request_json(
                args.server,
                "/api/weekly/" + urllib.parse.quote(args.report_id, safe="") + "/people",
                args.timeout,
            )
            if not isinstance(people, list) or not all(isinstance(name, str) for name in people):
                raise WeeklyClientError("服务器返回的人员列表格式无效")
            if args.as_json:
                print(json.dumps(people, ensure_ascii=False, indent=2))
            else:
                print_people(people)
        elif args.command == "export":
            if args.person is not None:
                args.person = " ".join(args.person.split())
                if not args.person:
                    raise WeeklyClientError("--person 不能为空")
            period = export_period(args)
            if period:
                markdown = export_range(args, *period)
            else:
                report_id = args.report_id or latest_report_id(args.server, args.timeout)
                markdown = export_one(args.server, args.timeout, report_id, args.view, args.person)
            if args.output:
                args.output.write_bytes(markdown)
            else:
                sys.stdout.buffer.write(markdown)
        return 0
    except (WeeklyClientError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
