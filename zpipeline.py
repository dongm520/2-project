# pipeline.py  (A방식: 벡터스토어 생성 전 None 메타데이터 정리 적용)

import os
import json
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient
from dotenv import load_dotenv
from openai import OpenAI
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

load_dotenv()

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

tavily = TavilyClient(api_key=TAVILY_KEY)
client = OpenAI(api_key=OPENAI_KEY)

DATA_DIR = "data"
VECTOR_DIR = "vector_store"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(VECTOR_DIR, exist_ok=True)


# ===============================
# 국내 뉴스
# ===============================
def crawl_korean_news(query):
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 전자신문
    try:
        url = f"https://search.etnews.com{query}"
        soup = BeautifulSoup(requests.get(url, headers=headers).text, "html.parser")
        for art in soup.select("dl.clearfix")[:3]:
            t = art.select_one("dt > a")
            d = art.select_one("dd.txt")
            if t:
                url_val = t.get("href") or ""
                results.append({
                    "title": (t.get_text(strip=True) or "").strip(),
                    "url": url_val.strip(),
                    "content": (d.get_text(strip=True) if d else "").strip()
                })
    except:
        pass

    # 한국경제
    try:
        url = f"https://search.hankyung.com{query}"
        soup = BeautifulSoup(requests.get(url, headers=headers).text, "html.parser")
        for art in soup.select("ul.news_list > li")[:3]:
            t = art.select_one("h3.tit > a")
            d = art.select_one("p.txt")
            if t:
                url_val = t.get("href") or ""
                results.append({
                    "title": (t.get_text(strip=True) or "").strip(),
                    "url": url_val.strip(),
                    "content": (d.get_text(strip=True) if d else "").strip()
                })
    except:
        pass

    return results


# ===============================
# 글로벌 뉴스 (Tavily)
# ===============================
def crawl_global_news(query, days=180):
    raw = tavily.search(query=query, max_results=3, include_raw_content=True, days=days)
    results = []
    for r in raw["results"]:
        results.append({
            "title": ("[글로벌] " + (r.get("title") or "")).strip(),
            "url": (r.get("url") or "").strip(),
            "content": (r.get("content") or "")[:800].strip()
        })
    return results


# ===============================
# 기사 수집 + None 제거
# ===============================
def collect_articles(query="AI 취업 시장"):
    ko = crawl_korean_news(query)
    gl = crawl_global_news(query)

    articles = ko + gl

    # A 방식 핵심: URL/제목이 비어있으면 저장하지 않음
    cleaned = []
    for a in articles:
        if a["title"] and a["url"]:      # 둘 다 있어야 DB에 넣음
            cleaned.append(a)

    json_path = os.path.join(DATA_DIR, "articles.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"[✔] 정제된 기사 저장 완료: {json_path}")
    return cleaned


# ===============================
# 벡터스토어 생성
# ===============================
def build_vector_db():
    json_path = os.path.join(DATA_DIR, "articles.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError("articles.json 없음. 먼저 collect_articles 실행하세요.")

    with open(json_path, encoding="utf-8") as f:
        docs = json.load(f)

    texts = [(d["title"] + "\n" + d["content"]).strip() for d in docs]
    metadatas = [{"title": d["title"], "url": d["url"]} for d in docs]

    embeddings = OpenAIEmbeddings(api_key=OPENAI_KEY)
    vector = FAISS.from_texts(texts, embeddings, metadatas=metadatas)

    vector.save_local(VECTOR_DIR)
    print("[✔] 벡터스토어 생성 완료:", VECTOR_DIR)


# ===============================
# 전체 실행
# ===============================
if __name__ == "__main__":
    collect_articles()
    build_vector_db()
    print("\n[🏁 파이프라인 전체 완료]")
