# backend_refactored.py

import os
import time
from dotenv import load_dotenv
import pandas as pd
import json
import openai
import tiktoken
import hashlib
import asyncio
from threading import Thread

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback


# ============================================================
# ENV
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

openai.api_key = os.getenv("OPENAI_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(BASE_DIR, "data")
VECTOR_STORE = os.path.join(BASE_DIR, "vector_store")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

os.makedirs(CACHE_DIR, exist_ok=True)

TAB1_CACHE = os.path.join(CACHE_DIR, "tab1_report.json")
ASSET_HASH_FILE = os.path.join(CACHE_DIR, "asset_hash.txt")

emb = OpenAIEmbeddings()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

vector_db = FAISS.load_local(
    VECTOR_STORE,
    emb,
    allow_dangerous_deserialization=True
)


# ============================================================
# Models
# ============================================================

class AskRequest(BaseModel):
    question: str
    mode: str


# ============================================================
# Numeric Summary
# ============================================================

def numeric_summary():

    if not os.path.exists(DATA_DIR):
        return ""

    parts = []

    for f in os.listdir(DATA_DIR):

        p = os.path.join(DATA_DIR, f)

        try:

            if f.endswith(".csv"):
                try:
                    df = pd.read_csv(p, encoding="utf-8")
                except:
                    df = pd.read_csv(p, encoding="cp949")

            elif f.endswith(".xlsx"):
                df = pd.read_excel(p)

            else:
                continue

            df.columns = df.columns.str.strip()

            parts.append(
                f"[파일:{f}]\n{df.head(5).to_string()}"
            )

        except:
            continue

    return "\n\n".join(parts)


# ============================================================
# Text Summary
# ============================================================

def summarize_text(text, lines=6):

    if not text:
        return ""

    prompt = ChatPromptTemplate.from_template(
"""
다음 내용을 {lines}줄로 요약하세요.

{text}
"""
    )

    chain = prompt | llm

    result = chain.invoke(
        {"text": text, "lines": lines}
    )

    return result.content


# ============================================================
# Asset Hash
# ============================================================

def text_hash(text):

    return hashlib.sha256(text.encode()).hexdigest()


# ============================================================
# Tab1 Pre-generate
# ============================================================

def generate_tab1_report():

    print("자동 보고서 생성 시작...")

    q = "한국 취업시장 전반 분석 보고서 작성"

    docs_scores = vector_db.similarity_search_with_score(q, k=5)

    best_score = None
    fallback_used = False
    tavily_tokens = 0
    article_context = ""

    if docs_scores:

        best_score = float(docs_scores[0][1])

        if best_score <= 0.35:
            article_context = "\n\n".join(
                d.page_content for d, _ in docs_scores
            )
        else:
            fallback_used = True

    else:
        fallback_used = True

    if fallback_used and TAVILY_KEY:
        article_context = "TAVILY 사용됨"
        tavily_tokens = 1

    article_summary = summarize_text(article_context, 6)
    numeric_context = summarize_text(numeric_summary(), 6)

    full_context = f"""
[기사 요약]
{article_summary}

[수치 데이터]
{numeric_context}
"""

    prompt = ChatPromptTemplate.from_template(
"""
자료:
{context}

질문:
{question}
"""
    )

    chain = prompt | llm

    start = time.time()

    with get_openai_callback() as cb:

        result = chain.invoke({
            "context": full_context,
            "question": q
        })

        answer = result.content

    latency = round(time.time() - start, 3)
    storage_summary = summarize_text(answer, 25)

    data = {
        "answer": answer,
        "storage_summary": storage_summary,
        "best_score": best_score,
        "fallback_used": fallback_used,
        "stats": {
            "completion_tokens": cb.total_tokens,
            "total_tokens": cb.total_tokens,
            "cost": cb.total_cost,
            "tavily_tokens": tavily_tokens,
            "latency": latency
        }
    }

    with open(TAB1_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print("자동 보고서 생성 완료")


# ============================================================
# Background Asset Build
# ============================================================

def build_assets_if_needed(text):

    h = text_hash(text)

    if os.path.exists(ASSET_HASH_FILE):

        with open(ASSET_HASH_FILE) as f:
            prev = f.read().strip()

        if prev == h:
            return

    with open(ASSET_HASH_FILE, "w") as f:
        f.write(h)

    print("다운로드 자산 갱신 완료")


# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
def startup_event():

    Thread(target=generate_tab1_report).start()


# ============================================================
# Get Cached Report
# ============================================================

@app.get("/report")
def get_report():

    if not os.path.exists(TAB1_CACHE):
        return {"ready": False}

    with open(TAB1_CACHE, encoding="utf-8") as f:
        data = json.load(f)

    return {"ready": True, "data": data}


# ============================================================
# ASK (기존 유지)
# ============================================================

@app.post("/ask")
def ask(req: AskRequest):

    try:

        q = req.question.strip()

        docs_scores = vector_db.similarity_search_with_score(q, k=5)

        best_score = None
        fallback_used = False
        tavily_tokens = 0
        article_context = ""

        if docs_scores:

            best_score = float(docs_scores[0][1])

            if best_score <= 0.35:
                article_context = "\n\n".join(
                    d.page_content for d, _ in docs_scores
                )
            else:
                fallback_used = True

        else:
            fallback_used = True

        if fallback_used and TAVILY_KEY:
            article_context = "TAVILY 사용됨"
            tavily_tokens = 1

        article_summary = summarize_text(article_context, 6)
        numeric_context = summarize_text(numeric_summary(), 6)

        full_context = f"""
[기사 요약]
{article_summary}

[수치 데이터]
{numeric_context}
"""

        prompt = ChatPromptTemplate.from_template(
"""
자료:
{context}

질문:
{question}
"""
        )

        chain = prompt | llm

        start = time.time()

        with get_openai_callback() as cb:

            result = chain.invoke({
                "context": full_context,
                "question": q
            })

            answer = result.content

        latency = round(time.time() - start, 3)
        storage_summary = summarize_text(answer, 25)

        return {
            "success": True,
            "answer": answer,
            "storage_summary": storage_summary,
            "best_score": best_score,
            "fallback_used": fallback_used,
            "stats": {
                "prompt_tokens": None,
                "completion_tokens": cb.total_tokens,
                "total_tokens": cb.total_tokens,
                "cost": cb.total_cost,
                "tavily_tokens": tavily_tokens,
                "latency": latency
            }
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# STREAM (탭2 유지)
# ============================================================

@app.get("/ask_stream")
async def ask_stream(question: str):

    async def event_generator():

        enc = tiktoken.encoding_for_model("gpt-4o-mini")

        q = question.strip()

        docs_scores = vector_db.similarity_search_with_score(q, k=5)

        best_score = None
        fallback_used = False
        tavily_tokens = 0
        article_context = ""

        if docs_scores:

            best_score = float(docs_scores[0][1])

            if best_score <= 0.35:
                article_context = "\n\n".join(
                    d.page_content for d, _ in docs_scores
                )
            else:
                fallback_used = True

        else:
            fallback_used = True

        if fallback_used and TAVILY_KEY:
            article_context = "TAVILY 사용됨"
            tavily_tokens = 1

        article_summary = summarize_text(article_context, 6)
        numeric_context = summarize_text(numeric_summary(), 6)

        system_context = f"""
[기사 요약]
{article_summary}

[수치 데이터]
{numeric_context}
"""

        messages = [
            {"role": "system", "content": system_context},
            {"role": "user", "content": q}
        ]

        prompt_tokens = len(enc.encode(system_context + q))
        collected = ""

        start = time.time()

        stream = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            stream=True
        )

        for chunk in stream:

            delta = chunk.choices[0].delta
            token = delta.content

            if token:
                collected += token
                yield f"data: {token}\n\n"

        latency = round(time.time() - start, 3)
        completion_tokens = len(enc.encode(collected))

        input_price = 0.15 / 1_000_000
        output_price = 0.60 / 1_000_000

        cost = (
            prompt_tokens * input_price +
            completion_tokens * output_price
        )

        meta = json.dumps({

            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": cost,
            "tavily_used": fallback_used,
            "tavily_tokens": tavily_tokens,
            "latency": latency,
            "final_text": collected
        })

        yield f"data: __END__{meta}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )