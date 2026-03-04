# ============================
# backend.py
# ============================
from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import TypedDict
import os, time, dotenv

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from langgraph.graph import StateGraph, END
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

from datadb import load_vector_db, FAISS_PATH

dotenv.load_dotenv()

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"
USE_FONT = False
if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont("Malgun", FONT_PATH))
        USE_FONT = True
    except:
        USE_FONT = False

vector_db = load_vector_db()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

class RAGState(TypedDict):
    question: str
    context: str
    answer: str

def search_node(state: RAGState):
    docs = vector_db.similarity_search(state["question"], k=5)
    state["context"] = "\n\n".join(d.page_content for d in docs) if docs else "데이터 없음"
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
graph = workflow.compile()

def generate_pdf(text):
    filename = os.path.join(BASE_DIR, f"report_{int(time.time())}.pdf")
    try:
        c = canvas.Canvas(filename, pagesize=letter)
        c.setFont("Malgun" if USE_FONT else "Helvetica", 12)

        x, y = 50, 750
        for line in text.split("\n"):
            c.drawString(x, y, line)
            y -= 16
            if y < 50:
                c.showPage()
                c.setFont("Malgun" if USE_FONT else "Helvetica", 12)
                y = 750

        c.save()
        return filename
    except:
        return ""

class AskRequest(BaseModel):
    question: str

@app.post("/ask")
def ask_api(req: AskRequest = Body(...)):
    with get_openai_callback() as cb:
        state = {"question": req.question, "context": "", "answer": ""}
        result = graph.invoke(state)

    pdf_path = generate_pdf(result["answer"])

    return {
        "answer": result["answer"],
        "pdf_path": pdf_path,
        "stats": {
            "total_tokens": cb.total_tokens,
            "total_cost": cb.total_cost
        }
    }
