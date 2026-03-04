import os, requests, dotenv, feedparser, sqlite3
from bs4 import BeautifulSoup
from tavily import TavilyClient # Tavily 추가
from langchain_openai import ChatOpenAI, OpenAIEmbeddings # 요약용 LLM 추가
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate

dotenv.load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "news.db")
FAISS_PATH = os.path.join(BASE_DIR, "vector_store")

# API 클라이언트 및 모델 설정
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
llm = ChatOpenAI(model="gpt-3.5-turbo") # 요약에 사용할 모델
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# 수집 대상
TARGET_SITES = {"BBC": "https://www.bbc.com/korean"}
RSS_FEEDS = {"한경RSS": "https://www.hankyung.com/feed/all-news"}

# --- [신규 추가] LLM 요약 함수 ---
def summarize_text(text):
    if len(text) < 200: return text # 너무 짧으면 요약 없이 반환
    
    prompt = ChatPromptTemplate.from_template(
        "너는 뉴스 요약 전문가야. 다음 뉴스 기사 내용을 핵심 위주로 3~5문장으로 요약해줘. "
        "중요한 수치, 날짜, 고유 명사는 반드시 포함해야 해:\n\n{context}"
    )
    chain = prompt | llm
    try:
        # 토큰 절약을 위해 본문 앞부분 위주로 전달
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
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except: return ""

# --- [신규 추가] Tavily 기반 수집 함수 ---
def run_tavily_collector(query):
    print(f"🔍 Tavily 스마트 검색 수집 시작: {query}")
    try:
        # Tavily의 advanced 검색은 본문을 정제해서 가져오므로 효율적입니다.
        response = tavily.search(query=query, search_depth="advanced", max_results=5)
        new_count = 0
        for result in response['results']:
            title = result['title']
            link = result['url']
            raw_content = result.get('content', "")
            
            if len(raw_content) > 100:
                # 1. 요약 수행
                summary = summarize_text(raw_content)
                # 2. 요약된 데이터를 SQLite에 저장 (news 테이블)
                if save_to_db("news", f"[Tavily] {title}", link, summary):
                    new_count += 1
        print(f"✅ Tavily를 통해 {new_count}개의 정제된 기사를 요약 저장했습니다.")
    except Exception as e:
        print(f"❗ Tavily 수집 중 오류: {e}")

def run_collector():
    print("🌐 기존 소스 및 Tavily 수집 시작...")
    stats = {"news": {"total": 0, "new": 0}, "rssnew": {"total": 0, "new": 0}}

    # 1. 기존 BBC 크롤링 (요약 단계 추가)
    for name, main_url in TARGET_SITES.items():
        try:
            res = requests.get(main_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            links = set()
            for a in soup.find_all("a", href=True):
                href = a['href']
                if "/korean/" in href and (len(href) > 20): 
                    full_url = href if href.startswith("http") else "https://www.bbc.com" + href
                    links.add(full_url)
            
            for link in links:
                content = get_article_content(link)
                if len(content) > 100:
                    # 저장 전 요약 단계 추가
                    summary = summarize_text(content)
                    if save_to_db("news", f"[{name}] {link.split('/')[-1]}", link, summary):
                        stats["news"]["new"] += 1
        except Exception as e:
            print(f"❗ {name} 접속 오류: {e}")

    # 2. 기존 RSS 수집 (요약 단계 추가)
    for name, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            content = get_article_content(entry.link)
            if len(content) > 100:
                summary = summarize_text(content)
                if save_to_db("rssnew", entry.title, entry.link, summary):
                    stats["rssnew"]["new"] += 1

    # 3. Tavily 수집 추가 (원하는 키워드 설정)
    run_tavily_collector("최신 IT 및 AI 기술 트렌드")

    print(f"\n✨ 수집 및 요약 완료! [news]: {stats['news']['new']}개, [rssnew]: {stats['rssnew']['new']}개")

def build_vector_db():
    print("\n🧠 요약된 데이터 기반 임베딩 시작...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    all_docs = []
    
    # DB에 저장된 요약 데이터들을 가져와서 Document 객체로 변환
    for table in ["news", "rssnew"]:
        try:
            cur.execute(f"SELECT title, content, link FROM {table}")
            for title, content, link in cur.fetchall():
                all_docs.append(Document(page_content=f"제목: {title}\n요약내용: {content}", metadata={"source": link}))
        except: continue
    conn.close()

    if not all_docs:
        print("❌ 임베딩할 데이터가 없습니다.")
        return

    # 요약본이므로 chunk_size를 기존 800에서 500 정도로 조정하면 더 밀도 있게 저장됩니다.
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = splitter.split_documents(all_docs)
    
    print(f"🚀 총 {len(docs)}개의 요약 조각을 임베딩합니다...")
    batch_size = 100 
    vector_db = FAISS.from_documents(docs[:batch_size], embeddings)
    
    for i in range(batch_size, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        vector_db.add_documents(batch)
        print(f"⏳ 진행 중... ({i + len(batch)} / {len(docs)})")

    vector_db.save_local(FAISS_PATH)
    print(f"✅ 요약 데이터 기반 벡터 저장소 업데이트 완료!")

if __name__ == "__main__":
    run_collector()
    build_vector_db()