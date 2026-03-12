# backend.py
# RAG + 조건부 실시간 크롤링 + 스트리밍 응답
# + YouTube 검색 / 차트 데이터 / PDF 생성 엔드포인트

import os
import json
import time
import re
from datetime import datetime
from io import BytesIO

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from tavily import TavilyClient
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

import pandas as pd

from googleapiclient.discovery import build

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    HRFlowable, Image as RLImage
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
LOGO_PATH = "images/잡나비.png"

PRICE_INPUT = 0.150
PRICE_OUTPUT = 0.600

client = OpenAI(api_key=OPENAI_KEY)
tavily = TavilyClient(api_key=TAVILY_KEY)

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


# ---------------------------------------------------------------
# Request 모델
# ---------------------------------------------------------------
class AnalysisRequest(BaseModel):
    query: str
    focus: str
    days: int
    step: int = 0
    history: list = []


class YoutubeRequest(BaseModel):
    query: str
    max_results: int = 3


class PdfRequest(BaseModel):
    last_answer: str
    rag_sources: list = []


# ---------------------------------------------------------------
# 벡터스토어 로드
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# RAG 검색
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# Tavily 실시간 검색
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# 스트리밍 생성기
# ---------------------------------------------------------------
def stream_generator(query, focus, context, history, sources, rag_score, run_live):
    messages = [{
        "role": "system",
        "content": f"당신은 전문 취업 컨설턴트입니다. '{focus}' 관점으로 분석하세요."
    }]

    if history:
        messages.extend(history[-6:])

    messages.append({
        "role": "user",
        "content": f"---데이터---\n{context}\n\n---질문---\n{query}"
    })

    meta = {
        "type": "meta",
        "sources": sources,
        "rag_score": rag_score,
        "live_search_used": run_live,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    yield json.dumps(meta, ensure_ascii=False) + "\n"

    start_time = time.time()

    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.4,
        stream=True,
        stream_options={"include_usage": True}
    )

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield json.dumps(
                {"type": "text", "content": chunk.choices[0].delta.content},
                ensure_ascii=False
            ) + "\n"

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


# ---------------------------------------------------------------
# PDF 마크다운 파서
# ---------------------------------------------------------------
def md_to_paragraphs(text, styles):
    """마크다운 텍스트를 reportlab Paragraph 리스트로 변환"""
    story = []
    lines = text.split("\n")

    for line in lines:
        line = line.rstrip()

        if not line:
            story.append(Spacer(1, 6))
            continue
        
        # #### 이상 제목 (h3 스타일로 통일)
        if re.match(r"^#{4,} ", line):
            content = re.sub(r"^#{4,} ", "", line)
            story.append(Spacer(1, 8))
            story.append(Paragraph(content, styles["h3"]))
            story.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.HexColor("#cccccc"), spaceAfter=6
            ))
            continue

        # ### 제목
        if line.startswith("### "):
            content = line[4:]
            story.append(Spacer(1, 8))
            story.append(Paragraph(content, styles["h3"]))
            story.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.HexColor("#cccccc"), spaceAfter=6
            ))
            continue

        # ## 제목
        if line.startswith("## "):
            content = line[3:]
            story.append(Spacer(1, 10))
            story.append(Paragraph(content, styles["h2"]))
            story.append(HRFlowable(
                width="100%", thickness=1,
                color=colors.HexColor("#888888"), spaceAfter=8
            ))
            continue

        # # 제목
        if line.startswith("# "):
            content = line[2:]
            story.append(Spacer(1, 12))
            story.append(Paragraph(content, styles["h1"]))
            story.append(HRFlowable(
                width="100%", thickness=1.5,
                color=colors.black, spaceAfter=10
            ))
            continue

        # 불릿 리스트
        if line.startswith("- ") or line.startswith("* "):
            content = line[2:]
            content = apply_inline(content)
            story.append(Paragraph(f"• {content}", styles["bullet"]))
            continue

        # 숫자 리스트
        num_match = re.match(r"^(\d+)\. (.+)", line)
        if num_match:
            num = num_match.group(1)
            content = apply_inline(num_match.group(2))
            story.append(Paragraph(f"{num}. {content}", styles["bullet"]))
            continue

        # 일반 텍스트
        content = apply_inline(line)
        story.append(Paragraph(content, styles["body"]))

    return story


def apply_inline(text):
    """인라인 마크다운 (bold, italic) → reportlab XML 태그 변환"""
    # ***bold italic***
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    # **bold**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # *italic*
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # `code`
    text = re.sub(r"`(.+?)`", r"<font name='Courier'>\1</font>", text)
    return text


# ---------------------------------------------------------------
# PDF 페이지 번호 + 헤더/푸터 콜백
# ---------------------------------------------------------------
class PageNumCanvas(rl_canvas.Canvas):
    def __init__(self, *args, **kwargs):
        rl_canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)

    def draw_page_elements(self, page_count):
        page_num = self._pageNumber
        page_w, page_h = A4

        # 표지는 번호 생략
        if page_num == 1:
            self._draw_watermark()
            return

        self._draw_watermark()

        # 상단 구분선
        self.setStrokeColor(colors.HexColor("#dddddd"))
        self.setLineWidth(0.5)
        self.line(2 * cm, page_h - 1.5 * cm, page_w - 2 * cm, page_h - 1.5 * cm)

        # 상단 우측 — 문서명
        self.setFont("NanumGothic", 8)
        self.setFillColor(colors.HexColor("#aaaaaa"))
        self.drawRightString(page_w - 2 * cm, page_h - 1.2 * cm, "취업 전략 로드맵 보고서")

        # 하단 구분선
        self.line(2 * cm, 1.5 * cm, page_w - 2 * cm, 1.5 * cm)

        # 하단 페이지 번호
        self.setFont("NanumGothic", 8)
        self.setFillColor(colors.HexColor("#aaaaaa"))
        self.drawCentredString(page_w / 2, 1.0 * cm, f"{page_num - 1} / {page_count - 1}")

    def _draw_watermark(self):
        if not os.path.exists(LOGO_PATH):
            return
        page_w, page_h = A4
        self.saveState()
        logo = ImageReader(LOGO_PATH)
        iw, ih = logo.getSize()
        aspect = ih / iw
        draw_w = 280
        draw_h = draw_w * aspect
        self.setFillColorRGB(0, 0, 0, alpha=0.05)
        self.drawImage(
            logo,
            x=(page_w - draw_w) / 2,
            y=(page_h - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            mask="auto",
            preserveAspectRatio=True
        )
        self.restoreState()


# ---------------------------------------------------------------
# PDF 스타일 정의
# ---------------------------------------------------------------
def get_pdf_styles():
    pdfmetrics.registerFont(TTFont("NanumGothic", "fonts/NanumGothic.ttf"))
    pdfmetrics.registerFont(TTFont("NanumGothicBold", "fonts/NanumGothicBold.ttf"))

    body = ParagraphStyle(
        name="body",
        fontName="NanumGothic",
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#333333"),
        spaceAfter=4
    )
    h1 = ParagraphStyle(
        name="h1",
        fontName="NanumGothicBold",
        fontSize=16,
        leading=22,
        textColor=colors.black,
        spaceAfter=4
    )
    h2 = ParagraphStyle(
        name="h2",
        fontName="NanumGothicBold",
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#222222"),
        spaceAfter=4
    )
    h3 = ParagraphStyle(
        name="h3",
        fontName="NanumGothicBold",
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#444444"),
        spaceAfter=4
    )
    bullet = ParagraphStyle(
        name="bullet",
        fontName="NanumGothic",
        fontSize=10,
        leading=15,
        leftIndent=14,
        textColor=colors.HexColor("#333333"),
        spaceAfter=3
    )
    cover_title = ParagraphStyle(
        name="cover_title",
        fontName="NanumGothicBold",
        fontSize=26,
        leading=34,
        alignment=TA_CENTER,
        textColor=colors.black,
        spaceAfter=12
    )
    cover_sub = ParagraphStyle(
        name="cover_sub",
        fontName="NanumGothic",
        fontSize=12,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#666666"),
        spaceAfter=6
    )
    source_style = ParagraphStyle(
        name="source",
        fontName="NanumGothic",
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#555555"),
        leftIndent=10,
        spaceAfter=4
    )

    return {
        "body": body, "h1": h1, "h2": h2, "h3": h3,
        "bullet": bullet, "cover_title": cover_title,
        "cover_sub": cover_sub, "source": source_style
    }


# ===============================================================
# API 엔드포인트
# ===============================================================

# ---------------------------------------------------------------
# 1. 메인 분석 (스트리밍)
# ---------------------------------------------------------------
@app.post("/analyze")
def analyze(req: AnalysisRequest):
    try:
        rag_ctx, rag_sources, rag_score = search_rag(req.query)
        run_live = rag_score >= 0.55
        live_ctx, live_sources = (
            live_search(req.query, req.days) if run_live else ("", [])
        )
        context = rag_ctx + "\n" + live_ctx
        sources = rag_sources + live_sources

        return StreamingResponse(
            stream_generator(
                req.query, req.focus, context,
                req.history, sources, rag_score, run_live
            ),
            media_type="text/plain"
        )
    except Exception as e:
        return JSONResponse({"error": str(e)})


# ---------------------------------------------------------------
# 2. YouTube 검색
# ---------------------------------------------------------------
@app.post("/youtube")
def youtube_search(req: YoutubeRequest):
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_KEY)
        res = youtube.search().list(
            q=req.query,
            part="snippet",
            maxResults=req.max_results,
            type="video",
            relevanceLanguage="ko"
        ).execute()
        videos = []
        for item in res["items"]:
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
            })
        return JSONResponse({"videos": videos[:req.max_results]})
    except Exception as e:
        return JSONResponse({"error": str(e), "videos": []})


# ---------------------------------------------------------------
# 3. 차트 데이터
# ---------------------------------------------------------------
@app.get("/chart-data")
def chart_data():
    try:
        raw = pd.read_excel("data/maindata.xlsx")
        quarter_cols = [c for c in raw.columns if "/" in str(c)]
        emp_cols = quarter_cols[0::2]
        rate_cols = quarter_cols[1::2]

        def to_label(c):
            year, q = str(c).split(".")
            qmap = {"1": "Q1", "2": "Q2", "3": "Q3", "4": "Q4"}
            qnum = qmap.get(q.replace("/4", ""), q)
            return f"{year} {qnum}"

        labels = [to_label(c) for c in emp_cols]
        emp_values = [
            float(v) if pd.notna(v) else None
            for v in [pd.to_numeric(raw.iloc[1][c], errors="coerce") for c in emp_cols]
        ]
        rate_values = [
            float(v) if pd.notna(v) else None
            for v in [pd.to_numeric(raw.iloc[1][c], errors="coerce") for c in rate_cols]
        ]
        return JSONResponse({
            "labels": labels,
            "emp_values": emp_values,
            "rate_values": rate_values
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


# ---------------------------------------------------------------
# 4. PDF 생성
# ---------------------------------------------------------------
@app.post("/pdf")
def generate_pdf(req: PdfRequest):
    try:
        styles = get_pdf_styles()
        today = datetime.now().strftime("%Y년 %m월 %d일")
        filename = f"JAB_NAVI_{datetime.now().strftime('%Y%m%d')}.pdf"

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=2.5 * cm,
            rightMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm
        )

        story = []
        page_w, page_h = A4

        # ── 표지 ──────────────────────────────────────────
        story.append(Spacer(1, page_h * 0.2))

        if os.path.exists(LOGO_PATH):
            story.append(RLImage(LOGO_PATH, width=100, height=100))
            story.append(Spacer(1, 20))

        story.append(Paragraph("취업 전략", styles["cover_title"]))
        story.append(Paragraph("로드맵 보고서", styles["cover_title"]))
        story.append(Spacer(1, 16))

        story.append(HRFlowable(
            width="60%", thickness=1.5,
            color=colors.HexColor("#333333"),
            hAlign="CENTER", spaceAfter=16
        ))

        story.append(Paragraph(today, styles["cover_sub"]))
        story.append(Paragraph("Powered by JAB NAVI", styles["cover_sub"]))

        story.append(PageBreak())

        # ── 본문 ──────────────────────────────────────────
        story.append(Spacer(1, 10))
        story += md_to_paragraphs(req.last_answer, styles)
        story.append(Spacer(1, 20))

        # ── 참고 자료 ──────────────────────────────────────
        has_none = any(
            not s.get("title") or s.get("title") == "None"
            for s in req.rag_sources
        )
        named = [
            s for s in req.rag_sources
            if s.get("title") and s.get("title") != "None"
        ]

        if named or has_none:
            story.append(PageBreak())
            story.append(Paragraph("참고 자료", styles["h2"]))
            story.append(HRFlowable(
                width="100%", thickness=1,
                color=colors.HexColor("#888888"), spaceAfter=10
            ))
            for s in named:
                title = s.get("title", "")
                url = s.get("url", "")
                line = f"<b>{title}</b><br/><font color='#777777'>{url}</font>"
                story.append(Paragraph(line, styles["source"]))
                story.append(Spacer(1, 4))
            if has_none:
                story.append(Paragraph("내부 크롤링 기사 자료", styles["source"]))

        doc.build(story, canvasmaker=PageNumCanvas)
        buf.seek(0)

        return Response(
            content=buf.read(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)})