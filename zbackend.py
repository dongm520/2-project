# backend.py  (옵션 D 적용 버전 - RAG + 조건부 실시간 크롤링)

import os
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient # 타빌리 다시 추가
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)
tavily = TavilyClient(api_key=TAVILY_KEY)

# collector.py 경로와 일치
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_DIR = os.path.join(BASE_DIR, "vector_store")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

class AnalysisRequest(BaseModel):
    query: str
    focus: str
    days: int
    step: int = 0
    history: list = []

# ================================================================
# 1. 내부 자료 검색 (RAG)
# ================================================================
def search_internal_rag(query):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", api_key=OPENAI_KEY)
    if not os.path.exists(VECTOR_DIR):
        return "", [], 1.0 # 폴더 없으면 점수 1.0(유사도 낮음) 반환
    
    vector_db = FAISS.load_local(VECTOR_DIR, embeddings, allow_dangerous_deserialization=True)
    docs_scores = vector_db.similarity_search_with_score(query, k=3)
    
    ctx = ""
    src = []
    for idx, (doc, score) in enumerate(docs_scores):
        ctx += f"[내부 DB 자료]\n{doc.page_content}\n\n"
        src.append({"title": f"내부 수집 자료 {idx+1}", "url": doc.metadata.get("source"), "score": float(score)})
    
    top_score = float(docs_scores[0][1]) if docs_scores else 1.0
    return ctx, src, top_score

# ================================================================
# 2. 타빌리 실시간 검색 (Live Search)
# ================================================================
def search_tavily_live(query):
    try:
        search_res = tavily.search(query=query, max_results=3, include_raw_content=False)
        ctx = ""
        src = []
        for res in search_res['results']:
            ctx += f"[실시간 웹 정보]\n제목: {res.get('title')}\n내용: {res.get('content')}\n\n"
            src.append({"title": res.get('title'), "url": res.get('url'), "score": 0.0})
        return ctx, src
    except:
        return "", []

# ================================================================
# 3. 통합 AI 분석 로직
# ================================================================
def analyze_with_ai(query, focus, context, step, history):
    step_instructions = {
        0: f"'{focus}' 관점에서 아래 자료를 분석하여 보고서를 작성하세요.",
        1: "사용자가 희망하는 직무의 현재 시장 상황과 채용 트렌드를 분석하여 '현황 보고서'를 작성하세요.",
        2: "해당 직무의 필수 기술을 정리하고, 이력서/자소서에 활용할 수 있는 구체적인 문구 예시를 작성하세요.",
        3: "서류 합격 후의 면접 전략(예상 질문 및 답변 가이드)을 작성하세요.",
        4: "이전 모든 단계를 종합하여 최종 '취업 로드맵 요약본'을 작성하세요."
    }

    instruction = step_instructions.get(step, step_instructions[0])
    messages = [{"role": "system", "content": f"당신은 AI 취업 컨설턴트입니다. 미션: {instruction}"}]
    
    if history:
        messages.extend(history[-6:])

    messages.append({
        "role": "user", 
        "content": f"--- 참고 데이터 ---\n{context}\n\n--- 질문 ---\n{query}\n\n전문적인 보고서를 작성하세요."
    })

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.4
    )
    return response.choices[0].message.content, response.usage, datetime.now().strftime("%H:%M:%S")

# ================================================================
# 4. 메인 API 엔드포인트
# ================================================================
@app.post("/analyze")
def analyze(req: AnalysisRequest):
    try:
        # 1단계: 내부 DB에서 먼저 찾기
        rag_ctx, rag_sources, top_score = search_internal_rag(req.query)

        # 2단계: 내부 자료가 부족하거나(score > 0.5) 최신성이 필요할 때 타빌리 가동
        # (취업 현황 분석 단계인 step 1에서는 타빌리를 더 적극적으로 사용하도록 설정 가능)
        run_tavily = True if top_score > 0.5 or req.step == 1 else False
        
        live_ctx, live_sources = ("", [])
        if run_tavily:
            live_ctx, live_sources = search_tavily_live(req.query)

        # 3단계: 모든 정보 통합
        full_context = rag_ctx + "\n" + live_ctx
        all_sources = rag_sources + live_sources

        # 4단계: AI 분석
        report, usage, timestamp = analyze_with_ai(
            req.query, req.focus, full_context, req.step, req.history
        )

        return {
            "report": report,
            "usage": {"total_tokens": usage.total_tokens, "timestamp": timestamp},
            "sources": all_sources,
            "live_search_used": run_tavily
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)