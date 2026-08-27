#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理面板缓存守卫：换了面板文件，浏览器必须立刻看得到。

背景（2026-08 的真实事故）：
面板改版把 index.html / style.css / app.js 等 8 个文件整套换掉并部署上线，
打开页面却还是老样子。原因不在文件，在于 StaticFiles 默认不发 Cache-Control,
浏览器于是按启发式规则自己决定缓存多久——一个几个月没动的 style.css 能被
缓存好几天，期间一次条件请求都不发。面板的 js/pages/*.js 是动态 import 的,
URL 挂不上 ?v=版本号, 只能由服务端统一声明。

本脚本断言三件事（不需要数据库、不需要网络）：
  1. /admin（面板首页）带 no-cache;
  2. /admin/css/*、/admin/js/* 等静态资源带 no-cache;
  3. 带 ETag 的条件请求回 304 时，Cache-Control 仍在——否则 304 一旦被
     当成「可以长期缓存」, 前面两条就白设了。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("API_KEY", "test-key-not-used")
os.environ.setdefault("DATABASE_URL", "postgresql://kiwi:kiwi@127.0.0.1:5432/unused")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}{('：' + detail) if detail else ''}")
        FAILED.append(name)


def has_no_cache(resp):
    return "no-cache" in resp.headers.get("cache-control", "").lower()


def main_test():
    print("\n=== 管理面板缓存守卫 ===")
    # 不用 with, 就不会触发 lifespan/startup, 因此不连数据库。
    client = TestClient(main.app)

    # ---- 场景 1：面板首页 ----
    r = client.get("/admin")
    check("场景1 /admin 返回 HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
          f"status={r.status_code} type={r.headers.get('content-type')}")
    check("场景1 /admin 带 no-cache", has_no_cache(r),
          f"Cache-Control={r.headers.get('cache-control')!r}")

    # ---- 场景 2：静态资源 ----
    for path in ("/admin/css/style.css", "/admin/js/app.js", "/admin/js/pages/dashboard.js"):
        r = client.get(path)
        check(f"场景2 {path} 可访问", r.status_code == 200, f"status={r.status_code}")
        check(f"场景2 {path} 带 no-cache", has_no_cache(r),
              f"Cache-Control={r.headers.get('cache-control')!r}")

    # ---- 场景 3：304 也要带 Cache-Control ----
    r = client.get("/admin/css/style.css")
    etag = r.headers.get("etag")
    check("场景3 静态资源发了 ETag", bool(etag), "没有 ETag 就没法做条件请求")
    if etag:
        r304 = client.get("/admin/css/style.css", headers={"If-None-Match": etag})
        check("场景3 相同 ETag 回 304", r304.status_code == 304, f"status={r304.status_code}")
        check("场景3 304 仍带 no-cache", has_no_cache(r304),
              f"Cache-Control={r304.headers.get('cache-control')!r}")

    # ---- 场景 3.5：自带字体走强缓存，不跟着 no-cache 每次问 ----
    r = client.get("/admin/fonts/ibm-plex-mono-latin-400-normal.woff2")
    check("场景3.5 自带等宽字体可访问", r.status_code == 200, f"status={r.status_code}")
    cc = r.headers.get("cache-control", "")
    check("场景3.5 字体走 immutable 强缓存", "immutable" in cc and "no-cache" not in cc,
          f"Cache-Control={cc!r}")

    # ---- 场景 4：面板文件齐全（改版新增的两个模块真的在仓库里）----
    panel = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin-panel")
    for rel in ("js/search.js", "js/wizard.js"):
        check(f"场景4 {rel} 存在", os.path.isfile(os.path.join(panel, rel)))

    # ---- 场景 5：侧栏路由指向的页面文件都在 ----
    routes_js = open(os.path.join(panel, "js", "routes.js"), encoding="utf-8").read()
    import re
    keys = re.findall(r"\{\s*key:\s*'([a-z0-9_]+)'", routes_js)
    check("场景5 解析出侧栏页面", len(keys) >= 10, f"只解析到 {len(keys)} 个")
    missing = [k for k in keys if not os.path.isfile(os.path.join(panel, "js", "pages", f"{k}.js"))]
    check("场景5 每个侧栏项都有对应页面文件", not missing, f"缺失：{missing}")

    # ---- 场景 6：pages/ 下没有没人引用的孤儿页面 ----
    page_files = {f[:-3] for f in os.listdir(os.path.join(panel, "js", "pages")) if f.endswith(".js")}
    orphans = sorted(page_files - set(keys))
    check("场景6 没有孤儿页面文件", not orphans, f"无人引用：{orphans}")

    # ---- 票 P：项目页按数据显隐的静态接线守卫 ----
    expected_nav_keys = {
        "dashboard", "providers", "websearch", "tools", "persona", "profile",
        "memories", "categories", "metabolism", "dream", "calendar",
        "compression", "handoff", "projects", "gateway", "sync", "security",
        "rawconfig",
    }
    expected_lede_keys = {
        "providers", "websearch", "tools", "persona", "profile", "memories",
        "categories", "metabolism", "dream", "calendar", "compression",
        "handoff", "projects", "gateway", "sync", "security", "rawconfig",
    }
    ledes_block = routes_js.split("export const LEDES = {", 1)[1].split("};", 1)[0]
    lede_keys = set(re.findall(r"^\s*([a-z0-9_]+):", ledes_block, re.MULTILINE))
    project_nav = re.search(
        r"\{\s*key:\s*'projects'[^}]*hideWhenEmpty:\s*'/sync/projects'[^}]*\}",
        routes_js,
        re.DOTALL,
    )
    check(
        "T-P-01 项目导航显隐声明且 key/LEDES 集合不漂移",
        bool(project_nav) and set(keys) == expected_nav_keys and lede_keys == expected_lede_keys,
        f"hideWhenEmpty={bool(project_nav)} nav={sorted(keys)} ledes={sorted(lede_keys)}",
    )

    style_css = open(os.path.join(panel, "css", "style.css"), encoding="utf-8").read()
    hidden_rule = re.search(
        r"\.nav-item\[hidden\]\s*\{(?P<body>[^}]*)\}", style_css, re.DOTALL
    )
    hidden_rule_body = hidden_rule.group("body") if hidden_rule else ""
    check(
        "T-P-02 hidden 属性覆盖 nav-item 的 flex 显示",
        bool(hidden_rule)
        and re.search(r"display\s*:\s*none\s*!important\s*;", hidden_rule_body) is not None,
        "缺少 .nav-item[hidden] { display:none !important; }",
    )

    app_js = open(os.path.join(panel, "js", "app.js"), encoding="utf-8").read()
    fetch_visibility = re.search(
        r"fetchVisibility\s*:\s*async\s+\w+\s*=>\s*\{(?P<body>.*?)\n\s*\}",
        app_js,
        re.DOTALL,
    )
    fetch_visibility_body = fetch_visibility.group("body") if fetch_visibility else ""
    catch_block = re.search(r"catch\s*\{(?P<body>[^}]*)\}", fetch_visibility_body, re.DOTALL)
    catch_body = catch_block.group("body") if catch_block else ""
    check(
        "T-P-03 项目查询失败保持导航显示",
        "./nav-visibility.mjs" in app_js
        and bool(catch_block)
        and "return false" in catch_body
        and "hidden = true" not in catch_body,
        "缺少显隐模块接线，或 catch 分支没有 fail-open 显示",
    )

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 项未通过：")
        for name in FAILED:
            print(f"   - {name}")
        return 1
    print("✅ 管理面板缓存守卫全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
