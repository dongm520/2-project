# pipeline.py
# 통합 파이프라인 — 중간 저장(DB/JSON) 없이 수집 즉시 벡터스토어로 직행
# - 국내 뉴스 크롤링 (전자신문, 한국경제)
# - BBC 크롤링 + RSS (한경, 매경)
# - Tavily 글로벌 뉴스
# - data/ 폴더 CSV/XLSX → 자연어 문장 변환

import os
import glob
import requests
import feedparser
import pandas as pd

from bs4 import BeautifulSoup
from tavily import TavilyClient
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate

load_dotenv()

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

tavily = TavilyClient(api_key=TAVILY_KEY)
llm = ChatOpenAI(model="gpt-3.5-turbo", api_key=OPENAI_KEY)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small", api_key=OPENAI_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VECTOR_DIR = os.path.join(BASE_DIR, "vector_store")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(VECTOR_DIR, exist_ok=True)


# ===============================================================
# 유틸
# ===============================================================

def get_article_content(url):
    """기사 본문 추출"""
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


def summarize_text(text):
    """기사 요약"""
    if len(text) < 200:
        return text
    prompt = ChatPromptTemplate.from_template(
        "너는 뉴스 요약 전문가야. 다음 뉴스 기사 내용을 핵심 위주로 3~5문장으로 요약해줘. "
        "중요한 수치, 날짜, 고유 명사는 반드시 포함해야 해:\n\n{context}"
    )
    chain = prompt | llm
    try:
        return chain.invoke({"context": text[:3000]}).content
    except Exception as e:
        print(f"❗ 요약 오류: {e}")
        return text


def make_doc(title, url, content):
    """Document 생성 헬퍼 — title/url 없으면 None 반환"""
    if not title or not url:
        return None
    return Document(
        page_content=(title + "\n" + content).strip(),
        metadata={"title": title, "url": url}
    )


def read_csv_safe(path):
    """인코딩 순차 시도로 CSV 읽기"""
    for encoding in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"❗ CSV 읽기 오류 ({os.path.basename(path)}): {e}")
            return None
    print(f"❗ CSV 인코딩 실패 ({os.path.basename(path)}): 모든 인코딩 시도 실패")
    return None


# ===============================================================
# 뉴스 수집
# ===============================================================

def crawl_korean_news(query):
    """전자신문, 한국경제 크롤링"""
    docs = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 전자신문
    try:
        soup = BeautifulSoup(
            requests.get(f"https://search.etnews.com{query}", headers=headers).text,
            "html.parser"
        )
        for art in soup.select("dl.clearfix")[:3]:
            t = art.select_one("dt > a")
            d = art.select_one("dd.txt")
            if t:
                doc = make_doc(
                    title=t.get_text(strip=True),
                    url=(t.get("href") or "").strip(),
                    content=(d.get_text(strip=True) if d else "")
                )
                if doc:
                    docs.append(doc)
    except:
        pass

    # 한국경제
    try:
        soup = BeautifulSoup(
            requests.get(f"https://search.hankyung.com{query}", headers=headers).text,
            "html.parser"
        )
        for art in soup.select("ul.news_list > li")[:3]:
            t = art.select_one("h3.tit > a")
            d = art.select_one("p.txt")
            if t:
                doc = make_doc(
                    title=t.get_text(strip=True),
                    url=(t.get("href") or "").strip(),
                    content=(d.get_text(strip=True) if d else "")
                )
                if doc:
                    docs.append(doc)
    except:
        pass

    print(f"[✔] 국내 뉴스 크롤링 완료")
    return docs


def crawl_bbc():
    """BBC 한국어 크롤링"""
    docs = []
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
                doc = make_doc(
                    title=f"[BBC] {link.split('/')[-1]}",
                    url=link,
                    content=summary
                )
                if doc:
                    docs.append(doc)
        print(f"[✔] BBC 크롤링 완료")
    except Exception as e:
        print(f"❗ BBC 오류: {e}")
    return docs


RSS_FEEDS = {
    "한경RSS": "https://www.hankyung.com/feed/all-news",
    "매경RSS": "https://www.mk.co.kr/rss/50100032/"
}


def crawl_rss():
    """RSS 수집 (한경, 매경)"""
    docs = []
    for name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries[:20]:
                content = get_article_content(entry.link)
                if len(content) > 200:
                    summary = summarize_text(content)
                    doc = make_doc(
                        title=f"[{name}] {entry.title}",
                        url=entry.link,
                        content=summary
                    )
                    if doc:
                        docs.append(doc)
                        count += 1
            print(f"[✔] {name} RSS 수집 완료")
        except Exception as e:
            print(f"❗ {name} RSS 오류: {e}")
    return docs


def crawl_global_news(query, days=180):
    """Tavily 글로벌 뉴스"""
    docs = []
    try:
        raw = tavily.search(query=query, max_results=3, include_raw_content=True, days=days)
        for r in raw["results"]:
            doc = make_doc(
                title=("[글로벌] " + (r.get("title") or "")).strip(),
                url=(r.get("url") or "").strip(),
                content=(r.get("content") or "")[:800].strip()
            )
            if doc:
                docs.append(doc)
        print(f"[✔] Tavily 글로벌 뉴스 완료")
    except Exception as e:
        print(f"❗ Tavily 오류: {e}")
    return docs


def collect_all_news(query="AI 취업 시장"):
    print("\n[1] 뉴스 수집 시작...")
    docs = []
    docs += crawl_korean_news(query)
    docs += crawl_bbc()
    docs += crawl_rss()
    docs += crawl_global_news(query)
    print(f"[✔] 뉴스 수집 완료")
    return docs


# ===============================================================
# 수치 데이터 → 자연어 문장
# ===============================================================

def numeric_to_sentences(df, filename):
    """DataFrame 행을 자연어 문장으로 변환"""
    sentences = []
    df.columns = [str(c).strip() for c in df.columns]

    for _, row in df.iterrows():
        parts = []
        for col in df.columns:
            val = row[col]
            if pd.isna(val) or str(val).strip() in ("", "nan", "None"):
                continue
            parts.append(f"{col}: {val}")
        if parts:
            sentences.append(f"[{filename}] " + ", ".join(parts) + ".")

    return sentences


def load_numeric_data():
    """data/ 폴더 CSV/XLSX → Document 리스트"""
    print("\n[2] 수치 데이터 로딩 시작...")
    docs = []

    # CSV
    for path in glob.glob(os.path.join(DATA_DIR, "*.csv")):
        filename = os.path.splitext(os.path.basename(path))[0]
        df = read_csv_safe(path)
        if df is None:
            continue
        try:
            sentences = numeric_to_sentences(df, filename)
            for s in sentences:
                docs.append(Document(
                    page_content=s,
                    metadata={"title": filename, "url": ""}
                ))
            print(f"[✔] CSV: {filename} ({len(sentences)}문장)")
        except Exception as e:
            print(f"❗ CSV 처리 오류 ({filename}): {e}")

    # XLSX
    for path in glob.glob(os.path.join(DATA_DIR, "*.xlsx")):
        filename = os.path.splitext(os.path.basename(path))[0]
        try:
            xl = pd.ExcelFile(path)
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                sentences = numeric_to_sentences(df, f"{filename}_{sheet}")
                for s in sentences:
                    docs.append(Document(
                        page_content=s,
                        metadata={"title": f"{filename}_{sheet}", "url": ""}
                    ))
                print(f"[✔] XLSX: {filename}/{sheet} ({len(sentences)}문장)")
        except Exception as e:
            print(f"❗ XLSX 오류 ({filename}): {e}")

    print(f"[✔] 수치 데이터 총 {len(docs)}개 Document 생성 완료")
    return docs


# ===============================================================
# 벡터스토어 생성
# ===============================================================

def build_vector_db(all_docs):
    print("\n[3] 벡터스토어 생성 시작...")

    if not all_docs:
        print("❗ 임베딩할 문서가 없습니다.")
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunked = splitter.split_documents(all_docs)

    vector = FAISS.from_documents(chunked, embeddings)
    vector.save_local(VECTOR_DIR)

    print(f"[✔] 벡터스토어 생성 완료: {len(chunked)}청크 → {VECTOR_DIR}")


# ===============================================================
# 전체 실행
# ===============================================================

if __name__ == "__main__":
    news_docs = collect_all_news()
    numeric_docs = load_numeric_data()
    build_vector_db(news_docs + numeric_docs)
    print("\n[🏁 파이프라인 전체 완료]")