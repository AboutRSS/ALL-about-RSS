# -*- coding: utf-8 -*-
"""
ALL-about-RSS 链接失效检查器 v3 (GitHub Actions 兼容)

设计：由 GitHub Actions（境外服务器）执行，避开本地网络限制。
- 全部主链接纳入，按类型分类处理
  - normal:   HTTP + 内容分析
  - github:   GitHub API 检查仓库
  - telegram: t.me 频道检查
  - twitter:  twitter/x 检查
- 并发检查 (ThreadPoolExecutor)
- 状态文件读写由 --status-dir 指定（CI 中指向 status 分支 checkout 目录，实现跨周累计）
- 生成待人工确认清单（连续 N 周期失效），供 Actions 上传为 artifact / 通知

用法:
  # 只解析验证（不检查 HTTP）
  python link_check.py --readme <README路径> --dry-run

  # 本地试跑（前 N 条）
  python link_check.py --readme <README路径> --status-dir <状态目录> --limit 50

  # 全量检查（CI 调用）
  python link_check.py --readme <README路径> --status-dir <状态目录>
"""
import argparse
import re
import sys
import os
import time
import datetime
import yaml
from collections import OrderedDict, Counter
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()

# ---------- Markdown 解析 ----------

MAIN_LINK_RE = re.compile(r"^[-*]\s+\[([^\]]+)\]\((https?://[^)\s]+)\)")
CROSSED_RE = re.compile(r"^[-*]\s+~~\[([^\]]+)\]\(([^)]+)\)~~")
ICON_LINK_RE = re.compile(r"^[-*]\s+\[!\[")


def clean_name(name):
    """清洗条目名称，去掉 HTML、~~ 删除线、'Wikipedia: ' 前缀，用作内容匹配关键词"""
    name = re.sub(r"<[^>]+>", "", name)  # 移除 HTML 标签
    name = name.replace("~~", "").strip()
    for prefix in ("Wikipedia: ", "Wiki: "):
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name.strip()


def host_match(host, domain):
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def classify_link(url):
    host = urlparse(url).netloc.lower()
    if host_match(host, "github.com") or host_match(host, "github.io"):
        return "github"
    if host_match(host, "t.me") or host_match(host, "telegram.org"):
        return "telegram"
    if host_match(host, "twitter.com") or host_match(host, "x.com"):
        return "twitter"
    return "normal"


def parse_main_links(readme_path):
    links = []
    category = "未分类"
    with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for idx, raw in enumerate(lines):
        line = raw.rstrip("\n")
        stripped = line.lstrip()

        heading = re.match(r"^#{1,6}\s+(.+)", stripped)
        if heading:
            category = heading.group(1).strip()

        if CROSSED_RE.match(stripped):
            continue
        if ICON_LINK_RE.match(stripped):
            continue
        m = MAIN_LINK_RE.match(stripped)
        if not m:
            continue
        name, url = m.group(1).strip(), m.group(2).strip()

        links.append({
            "name": name,
            "url": url,
            "host": urlparse(url).netloc,
            "type": classify_link(url),
            "line_no": idx + 1,
            "category": category,
            "keyword": clean_name(name),
            "original_line": line,
        })
    return links


# ---------- HTTP 检查 ----------

FOR_SALE_RE = re.compile("|".join(
    re.escape(kw) for kw in CONFIG["judge"]["for_sale_keywords"]
), re.IGNORECASE)


def check_http(url):
    """通用 HTTP 检查。CI 环境（境外）直接走系统网络，无需禁用代理。"""
    headers = {"User-Agent": CONFIG["network"]["user_agent"]}
    timeout = CONFIG["judge"]["http_timeout"]
    result = {
        "ok": False, "status_code": 0, "final_url": "", "title": "",
        "content_type": "", "for_sale": False, "error": "",
    }
    try:
        # CI 环境无本地网络限制；不再强制 proxies={}，避免个别环境 TypeError
        resp = requests.get(url, headers=headers, timeout=timeout,
                            allow_redirects=True)
        result["status_code"] = resp.status_code
        result["final_url"] = resp.url
        result["content_type"] = resp.headers.get("content-type", "")

        fail_codes = set(CONFIG["judge"]["fail_status"])
        if resp.status_code in fail_codes:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        if "html" in result["content_type"].lower():
            text = resp.text
            title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if title_m:
                result["title"] = re.sub(r"\s+", " ", title_m.group(1)).strip()
            if FOR_SALE_RE.search(text[:200000]):
                result["for_sale"] = True
        result["ok"] = True
        return result
    except requests.exceptions.SSLError:
        result["error"] = "SSL错误"
    except requests.exceptions.Timeout:
        result["error"] = "超时"
    except requests.exceptions.ConnectionError:
        result["error"] = "连接失败"
    except requests.exceptions.TooManyRedirects:
        result["error"] = "重定向过多"
    except Exception as e:
        result["error"] = type(e).__name__
    return result


# ---------- 分类检查 ----------

def check_github(link):
    url = link["url"]
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", url)
    if not m:
        return check_http(url)
    owner, repo = m.group(1), m.group(2)
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    result = {
        "ok": False, "status_code": 0, "final_url": "", "title": "",
        "content_type": "application/json", "for_sale": False, "error": "",
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": CONFIG["network"]["user_agent"],
    }
    # CI 环境中使用 GITHUB_TOKEN 提升 rate limit（5000/hour vs 60/hour）
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(api_url, headers=headers,
                            timeout=CONFIG["judge"]["http_timeout"])
        result["status_code"] = resp.status_code
        if resp.status_code == 200:
            data = resp.json()
            result["title"] = data.get("full_name", "")
            if data.get("archived"):
                result["error"] = "仓库已归档"
            else:
                result["ok"] = True
        elif resp.status_code == 404:
            result["error"] = "仓库不存在(404)"
        elif resp.status_code == 403:
            result["error"] = "API限流(403)"
        else:
            result["error"] = f"GitHub API {resp.status_code}"
    except Exception as e:
        result["error"] = type(e).__name__
    return result


def check_telegram(link):
    result = check_http(link["url"])
    if result.get("title") and any(k in result["title"] for k in ("Sorry", "Not Found", "isn't available", "unavailable")):
        result["ok"] = False
        result["error"] = "频道不可用"
    return result


def check_link(link):
    if link["type"] == "github":
        return check_github(link)
    elif link["type"] == "telegram":
        return check_telegram(link)
    else:
        return check_http(link)


# ---------- 内容判定 ----------

def judge_link(link, http):
    reason = []
    if not http["ok"]:
        reason.append(f"HTTP异常({http['error']})")
    if http["for_sale"]:
        reason.append("出现待售/停放信号")
    keyword = link["keyword"]
    if http["ok"] and http["title"] and keyword:
        if keyword.lower() not in http["title"].lower():
            reason.append(f"标题不含关键词[{keyword}]")

    if not http["ok"] or http["for_sale"]:
        verdict = "fail"
    elif reason and "标题不含关键词" in reason[0]:
        verdict = "unknown"
    else:
        verdict = "ok"
    return verdict, "; ".join(reason) if reason else "正常"


# ---------- 搜索引擎 URL ----------

def build_search_urls(link):
    mode = CONFIG["search"]["mode"]
    urls = []
    qs = []
    if mode in ("url", "both"):
        qs.append(f'"{link["url"]}"')
    if mode in ("name", "both"):
        qs.append(f'"{link["keyword"]}"')
    for engine in CONFIG["search"]["engines"]:
        for q in qs:
            urls.append(f"{engine}{quote(q)}")
    return urls


# ---------- 状态读写 ----------

def load_status(status_path):
    status = OrderedDict()
    if not os.path.exists(status_path):
        return status
    with open(status_path, "r", encoding="utf-8") as f:
        text = f.read()
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    for block in blocks:
        lines = block.split("\n")
        name = lines[0].strip()
        entry = {"name": name, "cycles": [], "status": "unknown"}
        for ln in lines:
            um = re.match(r"- \*\*URL\*\*: (.+)", ln.strip())
            if um:
                entry["url"] = um.group(1).strip()
            sm = re.match(r"- \*\*当前状态\*\*: (.+)", ln.strip())
            if sm:
                entry["status"] = sm.group(1).strip()
        for ln in lines:
            cm = re.match(r"- (\d{4}-\d{2}-\d{2}) \| (ok|fail|unknown)", ln.strip())
            if cm:
                entry["cycles"].append({"date": cm.group(1), "verdict": cm.group(2)})
        if "url" in entry:
            status[entry["url"]] = entry
    return status


def consecutive_fails(entry):
    count = 0
    for c in reversed(entry.get("cycles", [])):
        if c["verdict"] == "fail":
            count += 1
        else:
            break
    return count


def render_status(status):
    lines = ["# ALL-about-RSS 链接状态记录", "",
             "_本文件由 GitHub Actions 维护，存储在 status 分支。_", "",
             f"_更新于: {datetime.date.today().isoformat()}_", ""]
    for url, entry in status.items():
        lines.append(f"## {entry['name']}")
        lines.append(f"- **URL**: {url}")
        lines.append(f"- **当前状态**: {entry['status']}")
        lines.append("- **检查周期**:")
        for c in entry.get("cycles", []):
            lines.append(f"  - {c['date']} | {c['verdict']} | {c.get('note', '')}")
        lines.append("")
    return "\n".join(lines)


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser(description="ALL-about-RSS 链接失效检查器 v3")
    parser.add_argument("--readme", required=True, help="要检查的 README.md 路径")
    parser.add_argument("--status-dir", default=BASE_DIR, help="状态文件读写目录（CI 中为 status 分支 checkout 目录）")
    parser.add_argument("--limit", type=int, help="只检查前 N 个链接")
    parser.add_argument("--dry-run", action="store_true", help="只解析不检查 HTTP")
    parser.add_argument("--workers", type=int, help="并发线程数")
    parser.add_argument("--no-delay", action="store_true", help="禁用请求间延迟")
    args = parser.parse_args()

    today = datetime.date.today().isoformat()
    links = parse_main_links(args.readme)
    print(f"解析到主链接: {len(links)} 条")
    type_counter = Counter(l["type"] for l in links)
    print(f"类型分布: {dict(type_counter)}")

    if args.limit:
        links = links[:args.limit]
        print(f"(已限制为前 {args.limit} 条)")

    status_file = os.path.join(args.status_dir, CONFIG["status"]["file"])
    confirm_file = os.path.join(args.status_dir, CONFIG["status"]["confirm_file"])
    status = load_status(status_file)

    if args.dry_run:
        for link in links:
            print(f"  [{link['type']}] {link['name']} | {link['url']}")
        print("\n解析验证通过。")
        return

    confirm_threshold = CONFIG["judge"]["confirm_threshold"]
    to_confirm = []
    normal_count = 0
    fail_count = 0
    unknown_count = 0
    workers = args.workers or CONFIG["concurrency"]["workers"]
    delay = 0 if args.no_delay else CONFIG["concurrency"]["delay"]

    print(f"开始检查 ({workers} 并发)...")
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_link = {executor.submit(check_link, link): link for link in links}
        for i, future in enumerate(as_completed(future_to_link), 1):
            link = future_to_link[future]
            http = future.result()
            verdict, reason = judge_link(link, http)
            search_urls = build_search_urls(link)

            entry = status.get(link["url"])
            if entry is None:
                entry = {"name": link["name"], "url": link["url"], "cycles": [], "status": "unknown"}
                status[link["url"]] = entry
            entry["name"] = link["name"]
            entry["cycles"].append({
                "date": today,
                "verdict": verdict,
                "note": reason[:60],
            })

            if verdict == "ok":
                entry["status"] = "正常"
                normal_count += 1
            elif verdict == "fail":
                fails = consecutive_fails(entry)
                # 只有检查周期数 >= 阈值时，才判断为"待人工确认"
                # 避免首次运行（周期不足）就生成确认清单
                if len(entry["cycles"]) >= confirm_threshold and fails >= confirm_threshold:
                    entry["status"] = "待人工确认"
                    to_confirm.append(link)
                else:
                    entry["status"] = f"失效({fails}/{confirm_threshold})"
                fail_count += 1
            else:
                entry["status"] = "待观察(内容不确定)"
                unknown_count += 1

            if i % 100 == 0:
                elapsed = time.time() - start
                print(f"  已检查 {i}/{len(links)} | 用时 {elapsed:.0f}s ...")
            if delay:
                time.sleep(delay)

    elapsed = time.time() - start

    os.makedirs(args.status_dir, exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        f.write(render_status(status))
    print(f"\n状态已写入: {status_file} (用时 {elapsed:.0f}s)")

    if to_confirm:
        clines = ["# 待人工确认清单", "",
                  f"_以下条目已连续 {confirm_threshold} 周期失效，请人工确认后再在 master 分支 cross out。_", "",
                  f"_生成于: {today}_", ""]
        for link in to_confirm:
            clines.append(f"- [ ] {link['name']} | {link['url']}")
            su = build_search_urls(link)
            if su:
                clines.append(f"    - 搜索URL: {su[0]}")
        clines.append("")
        with open(confirm_file, "w", encoding="utf-8") as f:
            f.write("\n".join(clines))
        print(f"\n待人工确认 {len(to_confirm)} 条 -> {confirm_file}")
    elif os.path.exists(confirm_file):
        os.remove(confirm_file)

    print(f"\n结果汇总: 正常 {normal_count}, 失效 {fail_count}, 待观察 {unknown_count}, 待确认 {len(to_confirm)}")

    # 供 CI 判断是否产生了待确认条目（用于决定是否通知）
    sys.exit(1 if to_confirm else 0)


if __name__ == "__main__":
    main()
