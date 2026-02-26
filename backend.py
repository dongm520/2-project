from fastapi import FastAPI, Body
from pydantic import BaseModel
import requests, os, hashlib, time
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langchain_community.callbacks.manager import get_openai_callback
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from typing import TypedDict
import dotenv

dotenv.load_dotenv()

app = FastAPI()

# ------------------------------
# OpenAI / Embedding
# ------------------------------
embeddings = OpenAIEmbeddings()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


# ------------------------------
# Font Setup (absolute path)
# ------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "NanumGothic.ttf")

USE_FONT = False
if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont("Nanum", FONT_PATH))
        USE_FONT = True
    except:
        USE_FONT = False


# ------------------------------
# Crawling
# ------------------------------
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
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        return soup.get_text(separator=" ", strip=True)
    except:
        return ""


# ------------------------------
# Caching
# ------------------------------
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

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


# ------------------------------
# Vector DB
# ------------------------------
def build_vector_db():
    docs = []
    for category, urls in TARGET_SITES.items():
        for url in urls:
            text = get_cached_or_crawl(url)
            if len(text) < 1000:
                continue
            splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
            chunks = splitter.split_documents([Document(page_content=text)])
            docs.extend(chunks)
    return FAISS.from_documents(docs, embeddings)

vector_db = build_vector_db()


# ------------------------------
# LangGraph State
# ------------------------------
class RAGState(TypedDict):
    question: str
    context: str
    answer: str


def search_node(state: RAGState):
    docs = vector_db.similarity_search(state["question"], k=5)
    state["context"] = "\n\n".join([d.page_content for d in docs]) if docs else "데이터 없음"
    return state

def summary_node(state: RAGState):
    template = ChatPromptTemplate.from_template("""
당신은 국내 취업 동향 분석 전문가입니다.
아래 문서를 기반으로 분석 보고서를 생성하세요.

1. 요약
2. 핵심 근거
3. 최신 고용 통계
4. 산업별 전망
5. 대응 전략

문서:
{context}

질문:
{question}
""")
    chain = template | llm
    res = chain.invoke({"context": state["context"], "question": state["question"]})
    state["answer"] = res.content
    return state


workflow = StateGraph(RAGState)
workflow.add_node("search", search_node)
workflow.add_node("summary", summary_node)
workflow.set_entry_point("search")
workflow.add_edge("search", "summary")
workflow.add_edge("summary", END)
app_graph = workflow.compile()


# ------------------------------
# PDF (Windows 한글 폰트 전용)
# ------------------------------


# Windows 기본 한글 폰트 경로 (Malgun Gothic)
WINDOWS_FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"

# 폰트 등록 (PDF용)
USE_FONT = False
if os.path.exists(WINDOWS_FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont("Malgun", WINDOWS_FONT_PATH))
        USE_FONT = True
    except:
        USE_FONT = False


def generate_pdf(text):
    filename = os.path.join(BASE_DIR, f"report_{int(time.time())}.pdf")

    try:
        c = canvas.Canvas(filename, pagesize=letter)

        # 윈도우 환경 한글 폰트 적용
        if USE_FONT:
            c.setFont("Malgun", 12)
        else:
            c.setFont("Helvetica", 12)

        x, y = 50, 750

        for line in text.split("\n"):
            c.drawString(x, y, line)
            y -= 16

            if y < 50:
                c.showPage()
                if USE_FONT:
                    c.setFont("Malgun", 12)
                else:
                    c.setFont("Helvetica", 12)
                y = 750

        c.save()
        return filename

    except Exception as e:
        return None


# ------------------------------
# API
# ------------------------------
class AskRequest(BaseModel):
    question: str

@app.post("/ask")
def ask_api(req: AskRequest = Body(...)):
    try:
        with get_openai_callback() as cb:
            state = {"question": req.question, "context": "", "answer": ""}
            result = app_graph.invoke(state)

        pdf_path = generate_pdf(result["answer"]) or ""

        return {
            "answer": result["answer"],
            "pdf_path": pdf_path,
            "stats": {
                "total_tokens": cb.total_tokens,
                "total_cost": cb.total_cost
            }
        }

    except Exception as e:
        return {"error": str(e)}
