"""Official Roblox docs RAG: index-ranked real Creator Hub Markdown pages.

The index is request-scoped/cached. Page excerpts are exact observed content and
URLs are allowlisted; inaccessible pages are never turned into invented evidence.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse
import httpx

INDEX_URL = "https://create.roblox.com/docs/llms.txt"
ALLOWED_HOST = "create.roblox.com"
_STOP = {"roblox", "game", "games", "make", "create", "system", "script", "using",
         "inside", "the", "and", "for", "with", "code", "experience", "studio"}

class RobloxOfficialDocs:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client
        self.last_error: str | None = None
        self._index: str | None = None
        self._page_cache: dict[str, str] = {}

    @staticmethod
    def safe_url(url: str) -> bool:
        parsed=urlparse(url)
        return parsed.scheme=="https" and parsed.hostname==ALLOWED_HOST and (
            parsed.path.startswith("/docs/") and not parsed.username and not parsed.password
            and not parsed.fragment and not parsed.query and parsed.port is None
        )

    def _get(self,url: str)->str:
        if not self.safe_url(url):
            raise ValueError("Only canonical Roblox Creator documentation URLs permitted")
        if url in self._page_cache:
            return self._page_cache[url]
        if self.client is not None:
            r=self.client.get(url,follow_redirects=False,timeout=4.0)
        else:
            with httpx.Client(timeout=4.0,follow_redirects=False) as c:
                r=c.get(url)
        r.raise_for_status()
        if len(r.content)>2_000_000:
            raise ValueError("Official documentation page larger than 2 MB")
        self._page_cache[url]=r.text
        return r.text

    @staticmethod
    def _words(text: str)->set[str]:
        return {word for word in re.findall(r"[a-z0-9_가-힣]{3,}",text.casefold())
                if word not in _STOP}

    @staticmethod
    def _best_excerpt(text: str, query_words: set[str], max_len: int=1300) -> str:
        # Return an exact contiguous substring near the most relevant heading,
        # not synthesized page text or a truncated unrelated navigation header.
        if len(text)<=max_len: return text
        blocks=[(len(query_words & RobloxOfficialDocs._words(line)), offset)
                for offset,line in ((m.start(),m.group(0)) for m in re.finditer(r"[^\n]+", text))
                if line.strip()]
        if not blocks: return text[:max_len]
        _, start=max(blocks)
        return text[start:start+max_len]

    def search(self,query: str,limit: int=6,with_excerpt: bool=True)->dict:
        tokens=self._words(query)
        if not tokens:
            return {"results":[],"source":INDEX_URL,"error":"Empty documentation query"}
        limit=max(1,min(int(limit),8))
        try:
            if self._index is None:
                self._index=self._get(INDEX_URL)
            ranked=[]
            for line in self._index.splitlines():
                match=re.search(r"\[([^\]]+)\]\((/docs/[^)]+|https://create\.roblox\.com/docs/[^)]+)\)",line)
                if not match: continue
                href=match.group(2)
                if href.startswith("/docs/"): href="https://create.roblox.com"+href
                if not self.safe_url(href): continue
                urlwords=self._words(href.replace("/"," ").replace("-"," "))
                labelwords=self._words(match.group(1)+" "+line.split(":",1)[-1])
                exact=sum(4 for word in tokens if word in urlwords)
                label=sum(1 for word in tokens if word in labelwords)
                score=exact+label
                if score:
                    ranked.append((score,href,line[:280]))
            ranked.sort(key=lambda x:(-x[0],x[1]))
            unique={}
            for score,url,description in ranked:
                if url not in unique:
                    unique[url]={"url":url,"description":description,"score":score}
                if len(unique)>=limit: break
            results=list(unique.values())
            if with_excerpt:
                for item in results[:min(2,limit)]:
                    page=item["url"]
                    if not page.endswith(".md"): page=page.rstrip("/")+".md"
                    try:
                        body=self._get(page)
                        item["excerpt"]=self._best_excerpt(body,tokens)
                    except (httpx.HTTPError,ValueError):
                        item["excerpt"]=""
            self.last_error=None
            return {"results":results,"source":INDEX_URL,"error":None}
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            self.last_error=f"{type(exc).__name__}: {str(exc)[:180]}"
            return {"results":[],"source":INDEX_URL,"error":self.last_error}
