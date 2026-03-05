# backend.py

import os
import time
from dotenv import load_dotenv
import pandas as pd
import json
import openai
import tiktoken
import asyncio

from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics


# ============================================================
# ENV + INIT
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

emb = OpenAIEmbeddings()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

vector_db = FAISS.load_local(
    VECTOR_STORE, emb, allow_dangerous_deserialization=True
)


# ============================================================
# Models
# ============================================================
class AskRequest(BaseModel):
    question: str
    mode: str  # chat or report


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
            parts.append(f"[파일:{f}]\n{df.head(5).to_string()}")
        except:
            continue

    return "\n\n".join(parts)


def summarize_text(text, lines=6):
    if not text:
        return ""

    prompt = ChatPromptTemplate.from_template("""
다음 내용을 {lines}줄로 핵심만 요약하세요.

{text}
""")
    chain = prompt | llm
    result = chain.invoke({"text": text, "lines": lines})
    return result.content


# ============================================================
# NON-STREAM ENDPOINT (기존)
# ============================================================
@app.post("/ask")
def ask(req: AskRequest):

    try:
        q = req.question.strip()

        docs_scores = vector_db.similarity_search_with_score(q, k=5)
        fallback_used = False
        best_score = None
        article_context = ""

        if docs_scores:
            best_score = float(docs_scores[0][1])
            article_context = "\n\n".join(d.page_content for d, _ in docs_scores)

            if best_score > 0.5 and req.mode == "chat":
                fallback_used = True
        else:
            fallback_used = True

        if fallback_used and TAVILY_KEY:
            article_context = "TAVILY 사용됨"

        article_summary = summarize_text(article_context, 6)
        numeric_context = summarize_text(numeric_summary(), 6)

        full_context = f"""
[기사 요약]
{article_summary}

[수치 데이터]
{numeric_context}
"""

        prompt = ChatPromptTemplate.from_template("""
자료:
{context}

질문:
{question}
""")

        chain = prompt | llm

        with get_openai_callback() as cb:
            result = chain.invoke({"context": full_context, "question": q})
            answer = result.content

        storage_summary = summarize_text(answer, 25)

        # PDF 생성
        pdf_path = os.path.join(BASE_DIR, f"report_{int(time.time())}.pdf")
        pdf = SimpleDocTemplate(pdf_path)
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        style = ParagraphStyle(name="Korean", fontName="HYSMyeongJo-Medium", fontSize=11)
        story = []
        for line in answer.split("\n"):
            story.append(Paragraph(line, style))
            story.append(Spacer(1, 0.18 * inch))
        pdf.build(story)

        return {
            "success": True,
            "answer": answer,
            "storage_summary": storage_summary,
            "pdf_path": pdf_path,
            "best_score": best_score,
            "fallback_used": fallback_used,
            "stats": {
                "tokens": cb.total_tokens,
                "cost": cb.total_cost
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# STREAM ENDPOINT (SSE + 토큰 단위 + 토큰카운트)
# ============================================================
@app.get("/ask_stream")
async def ask_stream(question: str):

    async def event_generator():
        enc = tiktoken.encoding_for_model("gpt-4o-mini")

        prompt_tokens = len(enc.encode(question))
        collected = ""

        tavily_used = False

        stream = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": question}],
            stream=True
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            token = delta.content
            if token:
                collected += token
                yield f"data: {token}\n\n"

        completion_tokens = len(enc.encode(collected))

        input_price = 0.15 / 1_000_000
        output_price = 0.60 / 1_000_000
        cost = prompt_tokens * input_price + completion_tokens * output_price

        meta = json.dumps({
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": cost,
            "tavily_used": tavily_used,
            "final_text": collected
        })

        yield f"data: __END__{meta}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
