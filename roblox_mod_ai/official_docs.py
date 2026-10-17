"""Read-through, allowlisted Roblox official documentation retrieval for small agents.

Grounding source: create.roblox.com/docs/llms.txt and per-page .md files.
Only returns links and excerpts actually fetched. No fabricated API signatures.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse
import httpx

INDEX_URL = "https://create.roblox.com/docs/llms.txt"
ALLOWED_HOST = "create.roblox.com"

class RobloxOfficialDocs:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client
        self.last_error: str | None = None

    @staticmethod
    def safe_url(url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname == ALLOWED_HOST
                and parsed.path.startswith("/docs/") and
                not parsed.username and not parsed.password and not parsed.fragment
                and not parsed.query and parsed.port is None)

    def _get(self, url: str) -> str:
        if not self.safe_url(url):
            raise ValueError("Only canonical Roblox Creator documentation URLs permitted")
        if self.client is not None:
            response = self.client.get(url, follow_redirects=False, timeout=9)
        else:
            with httpx.Client(timeout=9, follow_redirects=False) as client:
                response = client.get(url)
        response.raise_for_status()
        if len(response.content) > 2_000_000: raise ValueError("Document too large")
        return response.text

    def search(self, query: str, limit: int = 6, with_excerpt: bool = True) -> dict:
        words = re.findall(r"[a-zA-Z0-9_가-힣]{2,}", query.lower())[:10]
        if not words: return {"results": [], "source": INDEX_URL, "error": "Empty documentation query"}
        limit = max(1, min(int(limit), 8))
        try:
            index = self._get(INDEX_URL)
            results = []
            for line in index.splitlines():
                # llms.txt links are either absolute or docs-root relative.
                for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)|https://create\.roblox\.com/docs/[^\s)]+", line):
                    if isinstance(href, tuple): href = next((x for x in href if x),"")
                    href = href.rstrip(".,")
                    if href.startswith("/docs/"): href="https://create.roblox.com"+href
                    if not self.safe_url(href): continue
                    score=sum(2 if word in href.lower() else 1 if word in line.lower() else 0 for word in words)
                    if score: results.append((score,href,line[:240]))
            unique = {}
            for score,url,desc in sorted(results,key=lambda x:-x[0]):
                if url not in unique: unique[url]={"url":url,"description":desc,"score":score}
                if len(unique)>=limit: break
            output = list(unique.values())
            if with_excerpt:
                for item in output[:3]:
                    page=item["url"]
                    if not page.endswith(".md"): page=page.rstrip("/")+".md"
                    if self.safe_url(page):
                        try:
                            text=self._get(page)
                            # excerpt bounded, no executing instructions from fetched text
                            item["excerpt"]=text[:1300]
                        except (httpx.HTTPError,ValueError):
                            item["excerpt"]=""
            self.last_error=None
            return {"results":output,"source":INDEX_URL,"error":None}
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            self.last_error=type(exc).__name__+": "+str(exc)[:180]
            return {"results":[],"source":INDEX_URL,"error":self.last_error}
