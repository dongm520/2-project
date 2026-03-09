# backend.py  (옵션 D 적용 버전 - RAG + 조건부 실시간 크롤링)

import os
import json
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
from openai import OpenAI

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from pipeline import crawl_korean_news, crawl_global_news

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

VECTOR_DIR = "vector_store"
DATA_DIR = "data"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)


# ================================================================
# Request Model
# ================================================================
class AnalysisRequest(BaseModel):
    query: str
    focus: str
    days: int


# ================================================================
# Load Vector Store
# ================================================================
def load_vector_store():
    embeddings = OpenAIEmbeddings(api_key=OPENAI_KEY)
    vector = FAISS.load_local(VECTOR_DIR, embeddings, allow_dangerous_deserialization=True)
    return vector


VECTOR_DB = load_vector_store()


# ================================================================
# RAG 검색
# ================================================================
def search_rag_with_scores(query):
    embeddings = OpenAIEmbeddings(api_key=OPENAI_KEY)
    docs_scores = VECTOR_DB.similarity_search_with_score(query, k=4)

    rag_context = ""
    sources = []
    first_score = None

    for idx, (doc, score) in enumerate(docs_scores):
        if idx == 0:
            first_score = score  # 최상위 유사도 저장

        rag_context += f"[RAG 기사]\n{doc.page_content}\n\n"
        sources.append({
            "title": doc.metadata.get("title"),
            "url": doc.metadata.get("url"),
            "score": score
        })

    return rag_context, sources, first_score


# ================================================================
# Tavily + (조건부) 국내 실시간 검색
# ================================================================
def conditional_crawling(query, days, enable=True):
    if not enable:
        return "", []

    global_articles = crawl_global_news(query, days)
    korean_articles = crawl_korean_news(query)

    ctx = ""
    src = []

    for item in global_articles:
        ctx += f"[글로벌]\n제목: {item['title']}\n내용: {item['content']}\n\n"
        src.append({"title": item["title"], "url": item["url"]})

    for item in korean_articles:
        ctx += f"[국내]\n제목: {item['title']}\n내용: {item['content']}\n\n"
        src.append({"title": item["title"], "url": item["url"]})

    return ctx, src


# ================================================================
# ChatGPT 분석
# ================================================================
def analyze_with_ai(query, focus, context):
    prompt = (
        f"당신은 전문 취업 전략 분석가입니다.\n"
        f"'{focus}' 관점에서 아래 자료를 분석해 한국어로 보고서를 작성하세요.\n\n"
        f"--- 분석 자료 ---\n{context}\n"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.25
    )

    report = response.choices[0].message.content
    usage = response.usage
    timestamp = datetime.now().strftime("%H:%M:%S")

    return report, usage, timestamp


# ================================================================
# 메인 API — RAG + 조건부 실시간 검색
# ================================================================
@app.post("/analyze")
def analyze(req: AnalysisRequest):
    try:
        # 1) RAG 검색
        rag_ctx, rag_sources, rag_top_score = search_rag_with_scores(req.query)

        # 2) 조건부 실시간 검색 로직
        # ----------------------------------------------
        # score 높음(= 유사도 낮음) → 실시간 검색 실행
        # score 낮음(= RAG 신뢰도 높음) → 실시간 검색 OFF
        # ----------------------------------------------
        # 기준값 0.55 (조절 가능)
        run_live_search = False if rag_top_score < 0.55 else True

        live_ctx, live_sources = conditional_crawling(
            req.query,
            req.days,
            enable=run_live_search
        )

        # 3) 전체 context
        full_context = rag_ctx + "\n" + live_ctx
        sources = rag_sources + live_sources

        # 4) AI 분석
        report, usage, timestamp = analyze_with_ai(
            req.query,
            req.focus,
            full_context
        )

        return {
            "report": report,
            "usage": {
                "total_tokens": usage.total_tokens,
                "timestamp": timestamp
            },
            "sources": sources,
            "rag_score": rag_top_score,
            "live_search_used": run_live_search
        }

    except Exception as e:
        return {"error": str(e)}
