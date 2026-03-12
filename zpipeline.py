# pipeline.py
# zpipeline 기반 통합 파이프라인
# - 국내 뉴스 크롤링 (전자신문, 한국경제)
# - BBC 크롤링 + RSS 수집 (한경, 매경)
# - Tavily 글로벌 뉴스
# - data/ 폴더 CSV/XLSX → 자연어 문장 변환 후 임베딩

import os
import json
import requests
import sqlite3
import feedparser
import pandas as pd
import glob

from bs4 import BeautifulSoup
from tavily import TavilyClient
from dotenv import load_dotenv
from openai import OpenAI
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate

load_dotenv()

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

tavily = TavilyClient(api_key=TAVILY_KEY)
client = OpenAI(api_key=OPENAI_KEY)
llm = ChatOpenAI(model="gpt-3.5-turbo", api_key=OPENAI_KEY)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small", api_key=OPENAI_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VECTOR_DIR = os.path.join(BASE_DIR, "vector_store")
DB_PATH = os.path.join(BASE_DIR, "news.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(VECTOR_DIR, exist_ok=True)


# ===============================================================
# 뉴스 수집
# ===============================================================

# ---------------------------------------------------------------
# 기사 본문 추출
# ---------------------------------------------------------------
def get_article_content(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        selectors = [
            ".news_cnt_detail_wrap", ".art_txt", ".article_txt",
            "#article_body", "#articleBodyContents"
        ]
        for sel in selectors:
            body = soup.select_one(sel)
            if body:
                return body.get_text(" ", strip=True)

        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except:
        return ""


# ---------------------------------------------------------------
# 기사 요약
# ---------------------------------------------------------------
def summarize_text(text):
    if len(text) < 200:
        return text
    prompt = ChatPromptTemplate.from_template(
        "너는 뉴스 요약 전문가야. 다음 뉴스 기사 내용을 핵심 위주로 3~5문장으로 요약해줘. "
        "중요한 수치, 날짜, 고유 명사는 반드시 포함해야 해:\n\n{context}"
    )
    chain = prompt | llm
    try:
        response = chain.invoke({"context": text[:3000]})
        return response.content
    except Exception as e:
        print(f"❗ 요약 오류: {e}")
        return text


# ---------------------------------------------------------------
# DB 저장
# ---------------------------------------------------------------
def save_to_db(table_name, title, link, content):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS {table_name} "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, link TEXT UNIQUE, content TEXT)"
    )
    try:
        cur.execute(
            f"INSERT INTO {table_name} (title, link, content) VALUES (?, ?, ?)",
            (title, link, content)
        )
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------
# 1. 국내 뉴스 크롤링 (전자신문, 한국경제)
# ---------------------------------------------------------------
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
                results.append({
                    "title": (t.get_text(strip=True) or "").strip(),
                    "url": (t.get("href") or "").strip(),
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
                results.append({
                    "title": (t.get_text(strip=True) or "").strip(),
                    "url": (t.get("href") or "").strip(),
                    "content": (d.get_text(strip=True) if d else "").strip()
                })
    except:
        pass

    return results


# ---------------------------------------------------------------
# 2. BBC 크롤링
# ---------------------------------------------------------------
def crawl_bbc():
    results = []
    try:
        res = requests.get(
            "https://www.bbc.com/korean",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        soup = BeautifulSoup(res.text, "html.parser")
        links = {
            href if href.startswith("http") else "https://www.bbc.com" + href
            for a in soup.find_all("a", href=True)
            if "/korean/" in (href := a["href"]) and len(href) > 20
        }
        for link in list(links)[:5]:
            content = get_article_content(link)
            if len(content) > 200:
                summary = summarize_text(content)
                title = f"[BBC] {link.split('/')[-1]}"
                save_to_db("news", title, link, summary)
                results.append({"title": title, "url": link, "content": summary})
        print(f"[✔] BBC 크롤링 완료: {len(results)}건")
    except Exception as e:
        print(f"❗ BBC 오류: {e}")
    return results


# ---------------------------------------------------------------
# 3. RSS 수집 (한경, 매경)
# ---------------------------------------------------------------
RSS_FEEDS = {
    "한경RSS": "https://www.hankyung.com/feed/all-news",
    "매경RSS": "https://www.mk.co.kr/rss/50100032/"
}

def crawl_rss():
    results = []
    for name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                content = get_article_content(entry.link)
                if len(content) > 200:
                    summary = summarize_text(content)
                    save_to_db("rssnew", entry.title, entry.link, summary)
                    results.append({
                        "title": f"[{name}] {entry.title}",
                        "url": entry.link,
                        "content": summary
                    })
            print(f"[✔] {name} RSS 수집 완료")
        except Exception as e:
            print(f"❗ {name} RSS 오류: {e}")
    return results


# ---------------------------------------------------------------
# 4. Tavily 글로벌 뉴스
# ---------------------------------------------------------------
def crawl_global_news(query, days=180):
    results = []
    try:
        raw = tavily.search(query=query, max_results=3, include_raw_content=True, days=days)
        for r in raw["results"]:
            results.append({
                "title": ("[글로벌] " + (r.get("title") or "")).strip(),
                "url": (r.get("url") or "").strip(),
                "content": (r.get("content") or "")[:800].strip()
            })
        print(f"[✔] Tavily 글로벌 뉴스 수집 완료: {len(results)}건")
    except Exception as e:
        print(f"❗ Tavily 오류: {e}")
    return results


# ---------------------------------------------------------------
# 전체 뉴스 수집 + 정제
# ---------------------------------------------------------------
def collect_all_news(query="AI 취업 시장"):
    print("\n[1] 뉴스 수집 시작...")

    ko = crawl_korean_news(query)
    bbc = crawl_bbc()
    rss = crawl_rss()
    gl = crawl_global_news(query)

    articles = ko + bbc + rss + gl

    # title/url 없는 항목 제거
    cleaned = [a for a in articles if a.get("title") and a.get("url")]

    json_path = os.path.join(DATA_DIR, "articles.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"[✔] 정제된 기사 저장 완료: {len(cleaned)}건 → {json_path}")
    return cleaned


# ===============================================================
# 수치 데이터 → 자연어 문장 변환
# ===============================================================

def numeric_to_sentences(df, filename):
    """DataFrame을 자연어 문장 리스트로 변환"""
    sentences = []
    fname = os.path.splitext(filename)[0]

    # 컬럼명 정리
    df.columns = [str(c).strip() for c in df.columns]

    for _, row in df.iterrows():
        parts = []
        for col in df.columns:
            val = row[col]
            if pd.isna(val) or str(val).strip() in ("", "nan", "None"):
                continue
            parts.append(f"{col}: {val}")

        if parts:
            sentence = f"[{fname}] " + ", ".join(parts) + "."
            sentences.append(sentence)

    return sentences


def load_numeric_data():
    """data/ 폴더의 모든 CSV, XLSX를 자연어 문장으로 변환"""
    print("\n[2] 수치 데이터 로딩 시작...")
    all_sentences = []

    # CSV
    for path in glob.glob(os.path.join(DATA_DIR, "*.csv")):
        filename = os.path.basename(path)
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            sentences = numeric_to_sentences(df, filename)
            all_sentences.extend(sentences)
            print(f"[✔] CSV 로드 완료: {filename} ({len(sentences)}문장)")
        except Exception as e:
            print(f"❗ CSV 오류 ({filename}): {e}")

    # XLSX
    for path in glob.glob(os.path.join(DATA_DIR, "*.xlsx")):
        filename = os.path.basename(path)
        try:
            xl = pd.ExcelFile(path)
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                sentences = numeric_to_sentences(df, f"{filename}_{sheet}")
                all_sentences.extend(sentences)
                print(f"[✔] XLSX 로드 완료: {filename} / {sheet} ({len(sentences)}문장)")
        except Exception as e:
            print(f"❗ XLSX 오류 ({filename}): {e}")

    print(f"[✔] 수치 데이터 총 {len(all_sentences)}문장 변환 완료")
    return all_sentences


# ===============================================================
# 벡터스토어 생성
# ===============================================================

def build_vector_db(articles, numeric_sentences):
    print("\n[3] 벡터스토어 생성 시작...")

    all_docs = []

    # 뉴스 기사 → Document
    for a in articles:
        text = (a["title"] + "\n" + a["content"]).strip()
        if text:
            all_docs.append(Document(
                page_content=text,
                metadata={"title": a["title"], "url": a["url"]}
            ))

    # DB(BBC, RSS) → Document
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for table in ["news", "rssnew"]:
        try:
            cur.execute(f"SELECT title, content, link FROM {table}")
            for title, content, link in cur.fetchall():
                all_docs.append(Document(
                    page_content=f"제목: {title}\n요약: {content}",
                    metadata={"title": title, "url": link}
                ))
        except:
            continue
    conn.close()

    # 수치 데이터 문장 → Document
    for sentence in numeric_sentences:
        all_docs.append(Document(
            page_content=sentence,
            metadata={"title": "수치데이터", "url": ""}
        ))

    if not all_docs:
        print("❗ 임베딩할 문서가 없습니다.")
        return

    # 청킹
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunked = splitter.split_documents(all_docs)

    # FAISS 생성
    vector = FAISS.from_documents(chunked, embeddings)
    vector.save_local(VECTOR_DIR)

    print(f"[✔] 벡터스토어 생성 완료: {len(chunked)}청크 → {VECTOR_DIR}")


# ===============================================================
# 전체 실행
# ===============================================================
if __name__ == "__main__":
    articles = collect_all_news()
    numeric_sentences = load_numeric_data()
    build_vector_db(articles, numeric_sentences)
    print("\n[🏁 파이프라인 전체 완료]")