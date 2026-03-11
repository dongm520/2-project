# backend.py  (옵션 D 적용 버전 - RAG + 조건부 실시간 크롤링)
# + PDF 생성 기능 완전 제거 (프론트에서 PDF 1개만 생성하기 위함)
# + 스트리밍 응답 지원 + 토큰/비용 추적

import os
import json
import time
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from tavily import TavilyClient
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)
tavily = TavilyClient(api_key=TAVILY_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_DIR = os.path.join(BASE_DIR, "vector_store")
DATA_DIR = os.path.join(BASE_DIR, "data")

# gpt-4o-mini 가격 ($/1M 토큰)
PRICE_INPUT = 0.150
PRICE_OUTPUT = 0.600

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)


# ------------------------------------------------------------
# Request 모델
# ------------------------------------------------------------
class AnalysisRequest(BaseModel):
    query: str
    focus: str
    days: int
    step: int = 0
    history: list = []


# ------------------------------------------------------------
# 벡터스토어 로드
# ------------------------------------------------------------
def load_vector_store():
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=OPENAI_KEY
    )
    vector = FAISS.load_local(
        VECTOR_DIR,
        embeddings,
        allow_dangerous_deserialization=True
    )
    return vector


VECTOR_DB = load_vector_store()


# ------------------------------------------------------------
# RAG 검색 (score 포함)
# ------------------------------------------------------------
def search_rag(query):
    docs_scores = VECTOR_DB.similarity_search_with_score(query, k=4)

    rag_context = ""
    rag_sources = []
    rag_top_score = None

    for idx, (doc, score) in enumerate(docs_scores):
        if idx == 0:
            rag_top_score = float(score)

        rag_context += f"[RAG]\n{doc.page_content}\n\n"
        rag_sources.append({
            "title": doc.metadata.get("title"),
            "url": doc.metadata.get("url"),
            "score": float(score)
        })

    return rag_context, rag_sources, rag_top_score


# ------------------------------------------------------------
# Tavily 실시간 검색
# ------------------------------------------------------------
def live_search(query, days):
    try:
        res = tavily.search(
            query=query,
            max_results=3,
            include_raw_content=False,
            days=days
        )
        ctx = ""
        src = []
        for item in res["results"]:
            ctx += f"[실시간 검색]\n제목: {item['title']}\n내용: {item['content']}\n\n"
            src.append({"title": item["title"], "url": item["url"]})
        return ctx, src

    except:
        return "", []


# ------------------------------------------------------------
# 스트리밍 생성기
# ------------------------------------------------------------
def stream_generator(query, focus, context, history, sources, rag_score, run_live):
    messages = [{
        "role": "system",
        "content": f"당신은 AI 취업 컨설턴트입니다. '{focus}' 관점으로 분석하세요."
    }]

    if history:
        messages.extend(history[-6:])

    messages.append({
        "role": "user",
        "content": f"---데이터---\n{context}\n\n---질문---\n{query}"
    })

    # 메타 정보를 첫 청크로 전송
    meta = {
        "type": "meta",
        "sources": sources,
        "rag_score": rag_score,
        "live_search_used": run_live,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    yield json.dumps(meta, ensure_ascii=False) + "\n"

    # 스트리밍 텍스트 청크 전송
    start_time = time.time()

    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.4,
        stream=True,
        stream_options={"include_usage": True}
    )

    for chunk in stream:
        # 텍스트 청크
        if chunk.choices and chunk.choices[0].delta.content:
            yield json.dumps(
                {"type": "text", "content": chunk.choices[0].delta.content},
                ensure_ascii=False
            ) + "\n"

        # 마지막 청크 — usage 포함
        if chunk.usage:
            elapsed = time.time() - start_time
            input_tokens = chunk.usage.prompt_tokens
            output_tokens = chunk.usage.completion_tokens
            total_tokens = chunk.usage.total_tokens
            cost = (input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT) / 1_000_000
            tokens_per_sec = round(output_tokens / elapsed, 1) if elapsed > 0 else 0

            usage_meta = {
                "type": "usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost": round(cost, 6),
                "tokens_per_sec": tokens_per_sec,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            yield json.dumps(usage_meta, ensure_ascii=False) + "\n"


# ------------------------------------------------------------
# 메인 분석 API (스트리밍)
# ------------------------------------------------------------
@app.post("/analyze")
def analyze(req: AnalysisRequest):
    try:
        # 1) RAG
        rag_ctx, rag_sources, rag_score = search_rag(req.query)

        # 2) 조건부 실시간 검색
        run_live = rag_score >= 0.55
        live_ctx, live_sources = (
            live_search(req.query, req.days)
            if run_live else ("", [])
        )

        context = rag_ctx + "\n" + live_ctx
        sources = rag_sources + live_sources

        # 3) 스트리밍 응답 반환
        return StreamingResponse(
            stream_generator(
                req.query,
                req.focus,
                context,
                req.history,
                sources,
                rag_score,
                run_live
            ),
            media_type="text/plain"
        )

    except Exception as e:
        return {"error": str(e)}