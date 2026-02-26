# ============================
# data_db.py
# ============================
import os, hashlib, requests, dotenv
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document

dotenv.load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_PATH = os.path.join(BASE_DIR, "vector_store")
os.makedirs(FAISS_PATH, exist_ok=True)
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

def crawl(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        return soup.get_text(separator=" ", strip=True)
    except:
        return ""

def cache_key(url):
    return os.path.join(CACHE_DIR, hashlib.md5(url.encode()).hexdigest() + ".txt")

def get_cached_or_crawl(url):
    key = cache_key(url)
    if os.path.exists(key):
        return open(key, "r", encoding="utf-8").read()

    text = crawl(url)
    with open(key, "w", encoding="utf-8") as f:
        f.write(text)
    return text

def build_vector_db():
    docs = []
    for _, urls in TARGET_SITES.items():
        for url in urls:
            text = get_cached_or_crawl(url)
            if len(text) < 300:
                continue
            splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
            chunks = splitter.split_documents([Document(page_content=text)])
            docs.extend(chunks)

    vector_db = FAISS.from_documents(docs, embeddings)
    vector_db.save_local(FAISS_PATH)
    return vector_db

def load_vector_db():
    return FAISS.load_local(
        FAISS_PATH,
        embeddings,
        allow_dangerous_deserialization=True
    )

if __name__ == "__main__":
    build_vector_db()
