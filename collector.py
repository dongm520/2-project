import os, requests, dotenv, feedparser, sqlite3
from bs4 import BeautifulSoup
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate

dotenv.load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "news.db")
FAISS_PATH = os.path.join(BASE_DIR, "vector_store")

# API 클라이언트 및 모델 설정
llm = ChatOpenAI(model="gpt-3.5-turbo")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# 수집 대상 (타빌리 제외, 지정 소스만 관리)
TARGET_SITES = {"BBC": "https://www.bbc.com/korean"}
RSS_FEEDS = {
    "한경RSS": "https://www.hankyung.com/feed/all-news",
    "매경RSS": "https://www.mk.co.kr/rss/50100032/" # 팀원 소스 추가
}

def summarize_text(text):
    if len(text) < 200: return text
    prompt = ChatPromptTemplate.from_template(
        "너는 뉴스 요약 전문가야. 다음 뉴스 기사 내용을 핵심 위주로 3~5문장으로 요약해줘. "
        "중요한 수치, 날짜, 고유 명사는 반드시 포함해야 해:\n\n{context}"
    )
    chain = prompt | llm
    try:
        response = chain.invoke({"context": text[:3000]})
        return response.content
    except Exception as e:
        print(f"❗ 요약 중 오류 발생: {e}")
        return text

def save_to_db(table_name, title, link, content):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, link TEXT UNIQUE, content TEXT)")
    try:
        cur.execute(f"INSERT INTO {table_name} (title, link, content) VALUES (?, ?, ?)", (title, link, content))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def get_article_content(url):
    """팀원분의 로직을 결합하여 본문 추출 성능 강화"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        # 기사 본문만 있는 영역을 찾기 위한 Selector (팀원분 코드 참고)
        selectors = [".news_cnt_detail_wrap", ".art_txt", ".article_txt", "#article_body", "#articleBodyContents"]
        
        for sel in selectors:
            body = soup.select_one(sel)
            if body:
                return body.get_text(" ", strip=True)

        # Selector로 못 찾을 경우 기존 방식 사용
        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except: return ""

def run_collector():
    print("🌐 지정된 소스에서 수집 시작...")
    
    # 1. 사이트 크롤링 (BBC 등)
    for name, main_url in TARGET_SITES.items():
        try:
            res = requests.get(main_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            links = {href if href.startswith("http") else "https://www.bbc.com" + href 
                     for a in soup.find_all("a", href=True) if "/korean/" in (href := a['href']) and len(href) > 20}
            
            for link in links:
                content = get_article_content(link)
                if len(content) > 200:
                    summary = summarize_text(content)
                    save_to_db("news", f"[{name}] {link.split('/')[-1]}", link, summary)
        except Exception as e: print(f"❗ {name} 오류: {e}")

    # 2. RSS 수집 (매경, 한경 등)
    for name, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:20]: # 너무 많지 않게 제한
            content = get_article_content(entry.link)
            if len(content) > 200:
                summary = summarize_text(content)
                save_to_db("rssnew", entry.title, entry.link, summary)
    print("✨ 수집 및 요약 완료!")

def build_vector_db():
    print("\n🧠 요약된 데이터 기반 임베딩 시작...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    all_docs = []
    for table in ["news", "rssnew"]:
        try:
            cur.execute(f"SELECT title, content, link FROM {table}")
            for title, content, link in cur.fetchall():
                all_docs.append(Document(page_content=f"제목: {title}\n요약내용: {content}", metadata={"source": link}))
        except: continue
    conn.close()

    if not all_docs: return
    
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = splitter.split_documents(all_docs)
    vector_db = FAISS.from_documents(docs, embeddings)
    vector_db.save_local(FAISS_PATH)
    print(f"✅ 벡터 저장소 업데이트 완료!")

if __name__ == "__main__":
    run_collector()
    build_vector_db()