# ============================
# data_db.py  (RSS 포함 버전)
# ============================
import os, hashlib, requests, dotenv, feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document

dotenv.load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_PATH = os.path.join(BASE_DIR, "vector_store")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

os.makedirs(FAISS_PATH, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

embeddings = OpenAIEmbeddings()

TARGET_SITES = {
    "IT": [
        "https://www.jobkorea.co.kr",
        "https://www.saramin.co.kr",
    ],
    "정부통계": [
        "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7013",
        "https://www.moel.go.kr/news/enews/report/enewsList.do",
    ],
    "경제지표": [
        "https://www.bok.or.kr/portal/main/main.do",
        "https://www.index.go.kr/unify/idx-info.do?idxCd=8038",
    ],
}

RSS_FEEDS = {
    "한경RSS": "https://www.hankyung.com/feed/all-news"
}

# ---------------------------------
# 기본 HTML 크롤링
# ---------------------------------
def crawl(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        # 불필요한 태그 제거
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()

        return soup.get_text(separator=" ", strip=True)
    except:
        return ""

# ---------------------------------
# RSS 파싱
# ---------------------------------
def crawl_rss(feed_url):
    docs = []
    feed = feedparser.parse(feed_url)

    for entry in feed.entries:
        link = entry.get("link")
        title = entry.get("title", "")
        if not link:
            continue

        article_text = get_cached_or_crawl(link)
        if len(article_text) < 300:
            continue

        full_text = f"{title}\n\n{article_text}"

        docs.append(
            Document(
                page_content=full_text,
                metadata={
                    "source": feed_url,
                    "link": link,
                    "title": title,
                },
            )
        )
    return docs

# ---------------------------------
# 캐싱
# ---------------------------------
def cache_key(url):
    return os.path.join(
        CACHE_DIR,
        hashlib.md5(url.encode()).hexdigest() + ".txt"
    )

def get_cached_or_crawl(url):
    key = cache_key(url)
    if os.path.exists(key):
        return open(key, "r", encoding="utf-8").read()

    text = crawl(url)
    with open(key, "w", encoding="utf-8") as f:
        f.write(text)
    return text

# ---------------------------------
# 벡터 DB 생성
# ---------------------------------
def build_vector_db():
    docs = []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120
    )

    # 1️⃣ 일반 사이트
    for category, urls in TARGET_SITES.items():
        for url in urls:
            text = get_cached_or_crawl(url)
            if len(text) < 300:
                continue

            base_doc = Document(
                page_content=text,
                metadata={"category": category, "source": url}
            )

            chunks = splitter.split_documents([base_doc])
            docs.extend(chunks)

    # 2️⃣ RSS 사이트
    for category, feed_url in RSS_FEEDS.items():
        rss_docs = crawl_rss(feed_url)
        for doc in rss_docs:
            doc.metadata["category"] = category

        chunks = splitter.split_documents(rss_docs)
        docs.extend(chunks)

    vector_db = FAISS.from_documents(docs, embeddings)
    vector_db.save_local(FAISS_PATH)
    return vector_db

# ---------------------------------
# 벡터 DB 로드
# ---------------------------------
def load_vector_db():
    return FAISS.load_local(
        FAISS_PATH,
        embeddings,
        allow_dangerous_deserialization=True
    )

if __name__ == "__main__":
    build_vector_db()