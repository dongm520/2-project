import os, requests, feedparser, dotenv
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain.tools import tool

# ---------------------------------------------------------
# 환경 설정 & 디렉토리
# ---------------------------------------------------------
dotenv.load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "faiss_mk_rss")
os.makedirs(DB_PATH, exist_ok=True)

# Embeddings & LLM 준비
embeddings = OpenAIEmbeddings()
GLOBAL_LLM = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# RSS 주소
FEED_URL = "https://www.mk.co.kr/rss/50100032/"

# ---------------------------------------------------------
# RSS 기사 파싱
# ---------------------------------------------------------
def parse_feed_articles(feed_url, max_articles=50):
    feed = feedparser.parse(feed_url)
    articles = []

    for entry in feed.entries[:max_articles]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        date = entry.get("pubDate", "")
        description_html = entry.get("description", "").strip()

        # Description HTML 정리
        description = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)

        # 본문 수집 시도
        content = try_get_article_body(link)
        if not content or len(content) < 100:
            content = description

        full_text = f"제목: {title}\n\n{content}"

        articles.append(
            Document(
                page_content=full_text,
                metadata={"link": link, "date": date, "title": title}
            )
        )
    return articles

# LLM 요약 기능
# ---------------------------------------------------------
def summarize_text(text, max_sentences=3):
    prompt = (
        f"다음 텍스트를 {max_sentences}문장으로 핵심 요약해줘.\n\n"
        f"{text}"
    )
    return GLOBAL_LLM.invoke(prompt).content

# ---------------------------------------------------------
# Tavily 검색 + LLM 요약
# ---------------------------------------------------------
@tool
def search_web_integrated(query: str):
    """Tavily 검색 → LLM 요약"""
    search = TavilySearchResults(k=3)
    raw_data = search.run(query)

    refining_prompt = (
        f"다음 검색 결과를 바탕으로 '{query}'에 대해 3문장으로 요약하라:\n\n"
        f"{raw_data}"
    )
    summary = GLOBAL_LLM.invoke(refining_prompt).content
    return summary

# ---------------------------------------------------------
# MK 기사 본문 크롤링 (최신 selector 반영)
# ---------------------------------------------------------
def try_get_article_body(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=7)
        soup = BeautifulSoup(res.text, "html.parser")

        # 2024~2025 기준 MK 뉴스 본문 후보 CSS selector
        selectors = [
            ".news_cnt_detail_wrap",
            ".art_txt",
            ".article_txt",
            ".wrap_cont",
            "#article_body",
        ]

        for sel in selectors:
            body = soup.select_one(sel)
            if body:
                text = body.get_text(" ", strip=True)
                if len(text) > 50:  # 너무 짧으면 본문이 아닐 확률 ↑
                    return text

        return ""
    except:
        return ""

# ---------------------------------------------------------
# 임베딩 + 벡터DB 저장
# ---------------------------------------------------------
def embed_and_save(articles, chunk_size=400, chunk_overlap=50):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    docs = []
    for art in articles:
        docs.extend(splitter.split_documents([art]))

    vector_db = FAISS.from_documents(docs, embeddings)
    vector_db.save_local(DB_PATH)

    print(f"Vector DB 저장 완료! 총 {len(docs)}개의 조각(chunks).")
    return vector_db


# ---------------------------------------------------------
# 실행부
# ---------------------------------------------------------
if __name__ == "__main__":

    print("RSS 기사 수집 중...")

    articles = parse_feed_articles(FEED_URL, max_articles=50)
    print(f"기사 {len(articles)}개 수집 완료.")

    print("\n임베딩 및 벡터DB 저장 중...")
    embed_and_save(articles)