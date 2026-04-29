"""
web_search.py — 联网搜索模块
==============================
支持多搜索引擎，统一接口。

API 搜索（需要 API Key）：
  - Tavily
  - 智谱 (Zhipu) WebSearch
  - Bocha
  - Querit

本地搜索（免费，无需 Key，解析网页结果）：
  - Bing
  - Google
  - Baidu
"""

import re
import json
import httpx
from html import unescape
from typing import Optional
from urllib.parse import quote_plus

# ============================================================
# 搜索结果格式
# ============================================================

class SearchResult:
    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self):
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def format_results_for_prompt(results: list[SearchResult], query: str) -> str:
    """将搜索结果格式化为注入 system prompt 的文本"""
    if not results:
        return ""
    
    lines = [f"[联网搜索结果 · 关键词: {query}]"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r.title}")
        lines.append(f"    来源: {r.url}")
        lines.append(f"    摘要: {r.snippet}")
    lines.append("\n请基于以上搜索结果回答用户的问题。如果搜索结果不相关，可以忽略并使用自身知识回答。")
    return "\n".join(lines)


# ============================================================
# 搜索引擎注册表
# ============================================================

SEARCH_ENGINES = {
    # API 搜索
    "tavily":  {"name": "Tavily",  "type": "api", "needs_key": True},
    "zhipu":   {"name": "智谱",    "type": "api", "needs_key": True},
    "bocha":   {"name": "Bocha",   "type": "api", "needs_key": True},
    "querit":  {"name": "Querit",  "type": "api", "needs_key": True},
    # 本地搜索
    "bing":    {"name": "Bing",    "type": "local", "needs_key": False},
    "google":  {"name": "Google",  "type": "local", "needs_key": False},
    "baidu":   {"name": "Baidu",   "type": "local", "needs_key": False},
}


def get_engine_list() -> list[dict]:
    """返回所有引擎信息（前端设置页用）"""
    return [
        {"id": k, "name": v["name"], "type": v["type"], "needs_key": v["needs_key"]}
        for k, v in SEARCH_ENGINES.items()
    ]


# ============================================================
# 统一搜索入口
# ============================================================

async def web_search(
    query: str,
    engine: str = "tavily",
    api_key: str = "",
    max_results: int = 5,
) -> list[SearchResult]:
    """
    统一搜索接口
    engine: tavily / zhipu / bocha / querit / bing / google / baidu
    """
    max_results = max(1, min(max_results, 20))  # 限制在 1-20 范围内
    try:
        if engine == "tavily":
            return await _search_tavily(query, api_key, max_results)
        elif engine == "zhipu":
            return await _search_zhipu(query, api_key, max_results)
        elif engine == "bocha":
            return await _search_bocha(query, api_key, max_results)
        elif engine == "querit":
            return await _search_querit(query, api_key, max_results)
        elif engine == "bing":
            return await _search_bing_local(query, max_results)
        elif engine == "google":
            return await _search_google_local(query, max_results)
        elif engine == "baidu":
            return await _search_baidu_local(query, max_results)
        else:
            print(f"⚠️ 未知搜索引擎: {engine}")
            return []
    except httpx.TimeoutException as e:
        print(f"⏰ 搜索超时 [{engine}]: {e}")
        return []
    except httpx.HTTPStatusError as e:
        print(f"❌ 搜索 HTTP 错误 [{engine}] status={e.response.status_code}: {e}")
        return []
    except httpx.RequestError as e:
        print(f"❌ 搜索网络错误 [{engine}]: {e}")
        return []
    except (KeyError, AttributeError, TypeError, ValueError) as e:
        # 通常是引擎返回 schema 变化导致的解析失败
        print(f"❌ 搜索结果解析失败 [{engine}] (可能是 API schema 变化): {type(e).__name__}: {e}")
        return []
    except Exception as e:
        print(f"❌ 搜索失败 [{engine}] {type(e).__name__}: {e}")
        return []


# ============================================================
# API 搜索引擎实现
# ============================================================

async def _search_tavily(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    """Tavily Search API — https://api.tavily.com"""
    if not api_key:
        print("⚠️ Tavily API Key 未设置")
        return []
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post("https://api.tavily.com/search", json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        })
        resp.raise_for_status()
        data = resp.json()
    
    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", "")[:300],
        ))
    return results


async def _search_zhipu(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    """智谱 WebSearch API — https://open.bigmodel.cn/api/paas/v4/web_search"""
    if not api_key:
        print("⚠️ 智谱 API Key 未设置")
        return []
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "search_engine": "search_std",
                "max_results": max_results,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    
    results = []
    for item in data.get("search_result", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("content", "")[:300],
        ))
    return results


async def _search_bocha(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    """Bocha Search API — https://api.bochaai.com"""
    if not api_key:
        print("⚠️ Bocha API Key 未设置")
        return []
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "count": max_results,
                "summary": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    
    results = []
    # 防御：上游可能返回 {"data": null} 或 {"data": {"webPages": null}}，链式 .get 会 AttributeError
    data_field = data.get("data") or {}
    web_pages_field = data_field.get("webPages") if isinstance(data_field, dict) else None
    web_pages = (web_pages_field or {}).get("value", []) if isinstance(web_pages_field, dict) else []
    for item in (web_pages or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        try:
            results.append(SearchResult(
                title=item.get("name", "") or "",
                url=item.get("url", "") or "",
                snippet=(item.get("snippet", "") or "")[:300],
            ))
        except Exception as e:
            print(f"   ⚠️ Bocha 单条结果解析失败，跳过: {e}")
            continue
    return results


async def _search_querit(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    """Querit Search API — https://api.querit.ai"""
    if not api_key:
        print("⚠️ Querit API Key 未设置")
        return []
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.querit.ai/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "num_results": max_results,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    
    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("snippet", item.get("content", ""))[:300],
        ))
    return results


# ============================================================
# 本地搜索引擎实现（解析网页 HTML）
# ============================================================

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def _clean_html(text: str) -> str:
    """清理 HTML 标签和实体"""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def _search_bing_local(query: str, max_results: int) -> list[SearchResult]:
    """Bing 本地搜索 — 解析 bing.com 搜索结果页"""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results + 5}"
    
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        html = resp.text
    
    results = []
    # Bing results: <li class="b_algo">...<h2><a href="...">Title</a></h2>...<p class="b_lineclamp...">snippet</p>
    blocks = re.findall(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL)
    for block in blocks[:max_results]:
        title_match = re.search(r'<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>', block, re.DOTALL)
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        if title_match:
            results.append(SearchResult(
                title=_clean_html(title_match.group(2)),
                url=title_match.group(1),
                snippet=_clean_html(snippet_match.group(1))[:300] if snippet_match else "",
            ))
    return results


async def _search_google_local(query: str, max_results: int) -> list[SearchResult]:
    """Google 本地搜索 — 解析 google.com 搜索结果页"""
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={max_results + 5}&hl=zh-CN"
    
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        html = resp.text
    
    results = []
    # Google results: <div class="g">...<a href="url"><h3>title</h3></a>...<span>snippet</span>
    blocks = re.findall(r'<div class="[^"]*g[^"]*">(.*?)</div>\s*(?=<div class="|$)', html, re.DOTALL)
    if not blocks:
        blocks = re.findall(r'<div class="g">(.*?)</div></div></div>', html, re.DOTALL)
    
    for block in blocks[:max_results + 5]:
        link_match = re.search(r'<a[^>]*href="(https?://[^"]*)"[^>]*>', block)
        title_match = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
        # Snippet is usually in a span or div after the URL
        snippet_match = re.search(r'<span[^>]*>((?:(?!<span).)*?)</span>\s*$', block, re.DOTALL)
        if not snippet_match:
            snippet_match = re.search(r'<div[^>]*data-sncf[^>]*>(.*?)</div>', block, re.DOTALL)
        
        if link_match and title_match:
            href = link_match.group(1)
            if href.startswith('https://www.google.com') or href.startswith('/'):
                continue
            results.append(SearchResult(
                title=_clean_html(title_match.group(1)),
                url=href,
                snippet=_clean_html(snippet_match.group(1))[:300] if snippet_match else "",
            ))
        if len(results) >= max_results:
            break
    
    return results


async def _search_baidu_local(query: str, max_results: int) -> list[SearchResult]:
    """Baidu 本地搜索 — 解析 baidu.com 搜索结果页"""
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={max_results + 5}"
    
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        html = resp.text
    
    results = []
    # Baidu results: <div class="result c-container ...">...<h3><a href="...">title</a></h3>...<span class="content-right_...">snippet</span>
    blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*c-container[^"]*"[^>]*>(.*?)</div>\s*<!--', html, re.DOTALL)
    if not blocks:
        blocks = re.findall(r'<div[^>]*class="result c-container[^"]*"[^>]*>(.*?)</div>\s*<div', html, re.DOTALL)
    
    for block in blocks[:max_results + 5]:
        title_match = re.search(r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h3>', block, re.DOTALL)
        snippet_match = re.search(r'<span[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL)
        if not snippet_match:
            snippet_match = re.search(r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        
        if title_match:
            results.append(SearchResult(
                title=_clean_html(title_match.group(2)),
                url=title_match.group(1),  # Baidu uses redirect URLs
                snippet=_clean_html(snippet_match.group(1))[:300] if snippet_match else "",
            ))
        if len(results) >= max_results:
            break
    
    return results
