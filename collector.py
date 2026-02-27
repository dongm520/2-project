import os, requests, dotenv, feedparser, sqlite3
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document

dotenv.load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "news.db")
FAISS_PATH = os.path.join(BASE_DIR, "vector_store")

# 수집 대상
TARGET_SITES = {"BBC": "https://www.bbc.com/korean"}
RSS_FEEDS = {"한경RSS": "https://www.hankyung.com/feed/all-news"}

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
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        # 기사 본문일 확률이 높은 태그들만 추출
        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except: return ""

def run_collector():
    print("🌐 수집 시작...")
    stats = {"news": {"total": 0, "new": 0}, "rssnew": {"total": 0, "new": 0}}

    for name, main_url in TARGET_SITES.items():
        try:
            res = requests.get(main_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            
            links = set()
            for a in soup.find_all("a", href=True):
                href = a['href']
                # BBC 코리아의 다양한 기사 패턴 허용 (article, news, topics 등)
                if "/korean/" in href and (len(href) > 20): 
                    full_url = href if href.startswith("http") else "https://www.bbc.com" + href
                    links.add(full_url)
            
            print(f"🔎 {name}에서 발견된 링크 수: {len(links)}개") # 디버깅용

            for link in links:
                stats["news"]["total"] += 1
                content = get_article_content(link)
                # 글자 수 제한을 조금 낮춰서 더 잘 수집되게 조정 (300 -> 100)
                if len(content) > 100: 
                    is_new = save_to_db("news", f"[{name}] {link.split('/')[-1]}", link, content)
                    if is_new: stats["news"]["new"] += 1
                else:
                    print(f"⚠️ 내용 부족으로 제외: {link[:50]}...")

        except Exception as e:
            print(f"❗ {name} 접속 오류: {e}")

    # RSS 생략 (기존과 동일)
    for name, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            stats["rssnew"]["total"] += 1
            content = get_article_content(entry.link)
            if len(content) > 100:
                is_new = save_to_db("rssnew", entry.title, entry.link, content)
                if is_new: stats["rssnew"]["new"] += 1

    print(f"\n✨ 완료! [news]: {stats['news']['new']}개 추가됨")

def build_vector_db():
    print("\n🧠 통합 임베딩 프로세스 시작...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    all_docs = []
    
    for table in ["news", "rssnew"]:
        try:
            cur.execute(f"SELECT title, content, link FROM {table}")
            for title, content, link in cur.fetchall():
                all_docs.append(Document(page_content=f"제목: {title}\n내용: {content}", metadata={"source": link}))
        except: continue
    conn.close()

    if not all_docs:
        print("❌ 임베딩할 데이터가 없습니다.")
        return

    # 1. 텍스트 분할
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    docs = splitter.split_documents(all_docs)
    print(f"✂️ 총 {len(docs)}개의 조각으로 나누었습니다.")

    # 2. 임베딩 진행 (나누어서 처리)
    embeddings = OpenAIEmbeddings()
    
    print("🚀 API 부하 방지를 위해 나누어서 임베딩을 진행합니다...")
    
    # 첫 번째 묶음(100개 조각)으로 벡터 DB 초기 생성
    batch_size = 100 
    vector_db = FAISS.from_documents(docs[:batch_size], embeddings)
    
    # 나머지 조각들을 배치(Batch) 단위로 추가
    for i in range(batch_size, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        vector_db.add_documents(batch)
        print(f"⏳ 임베딩 진행 중... ({i + len(batch)} / {len(docs)})")

    # 3. 로컬 저장
    vector_db.save_local(FAISS_PATH)
    print(f"✅ 통합 벡터 저장소 생성 완료! 총 {len(docs)} 조각 저장됨.")

if __name__ == "__main__":
    run_collector()
    build_vector_db()