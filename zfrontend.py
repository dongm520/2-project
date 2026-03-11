import streamlit as st
import requests
import os
import calendar
from datetime import datetime
from io import BytesIO
import json

from dotenv import load_dotenv
load_dotenv()

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader

from googleapiclient.discovery import build


st.set_page_config(
    page_title="일기일회 AI 취업 컨설턴트",
    layout="wide",
    page_icon="🤖"
)

API_URL = "http://127.0.0.1:8000/analyze"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
LOGO_PATH = r"C:\workAI\2_project\일기일회1.png"

# ===============================================================
# Session State
# ===============================================================
if "messages_trend" not in st.session_state:
    st.session_state.messages_trend = []

if "messages_job" not in st.session_state:
    st.session_state.messages_job = []

if "token_history" not in st.session_state:
    st.session_state.token_history = []

if "cost_history" not in st.session_state:
    st.session_state.cost_history = []

if "speed_history" not in st.session_state:
    st.session_state.speed_history = []

if "time_history" not in st.session_state:
    st.session_state.time_history = []

if "search_history" not in st.session_state:
    st.session_state.search_history = []

if "current_step" not in st.session_state:
    st.session_state.current_step = 1

if "target_job" not in st.session_state:
    st.session_state.target_job = ""

if "roadmap_step" not in st.session_state:
    st.session_state.roadmap_step = 0

if "rag_sources" not in st.session_state:
    st.session_state.rag_sources = []

if "youtube_videos" not in st.session_state:
    st.session_state.youtube_videos = []

if "youtube_videos_interview" not in st.session_state:
    st.session_state.youtube_videos_interview = []


# ===============================================================
# YouTube 검색
# ===============================================================
def search_youtube(query, max_results=3):
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_KEY)
        res = youtube.search().list(
            q=query,
            part="snippet",
            maxResults=max_results,
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
        return videos
    except Exception as e:
        st.error(f"유튜브 검색 오류: {e}")
        return []


# ===============================================================
# 참고 자료 표시
# ===============================================================
def display_sources(sources):
    if not sources:
        return

    has_none = any(not s.get("title") or s.get("title") == "None" for s in sources)
    named = [s for s in sources if s.get("title") and s.get("title") != "None"]

    lines = []
    for s in named:
        url = s.get("url", "")
        title = s.get("title", "")
        if url:
            lines.append(f"- [{title}]({url})")
        else:
            lines.append(f"- {title}")

    if has_none:
        lines.append("- 내부 크롤링 기사 자료")

    if lines:
        with st.expander("📎 참고 자료"):
            st.markdown("\n".join(lines))


# ===============================================================
# PDF 워터마크 콜백
# ===============================================================
def add_watermark(canv, doc):
    if not os.path.exists(LOGO_PATH):
        return

    canv.saveState()
    page_w, page_h = A4
    logo = ImageReader(LOGO_PATH)
    iw, ih = logo.getSize()
    aspect = ih / iw
    draw_w = 280
    draw_h = draw_w * aspect

    canv.setFillColorRGB(0, 0, 0, alpha=0.08)
    canv.drawImage(
        logo,
        x=(page_w - draw_w) / 2,
        y=(page_h - draw_h) / 2,
        width=draw_w,
        height=draw_h,
        mask="auto",
        preserveAspectRatio=True
    )
    canv.restoreState()


# ===============================================================
# PDF 생성 — 마지막 assistant 답변만
# ===============================================================
def create_chat_pdf(messages):

    pdfmetrics.registerFont(TTFont("NanumGothic", "fonts/NanumGothic.ttf"))

    base_style = ParagraphStyle(
        name="Base",
        fontName="NanumGothic",
        fontSize=11,
        leading=16
    )
    title_style = ParagraphStyle(
        name="Title",
        parent=base_style,
        alignment=TA_CENTER,
        fontSize=18,
        leading=22,
        spaceAfter=20
    )
    header_style = ParagraphStyle(
        name="Header",
        parent=base_style,
        fontSize=14,
        leading=20,
        spaceAfter=12
    )

    # 마지막 assistant 답변 추출
    last_answer = ""
    for m in reversed(messages):
        if m["role"] == "assistant":
            last_answer = m["content"]
            break

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = []

    # 제목
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(Paragraph("AI 취업 전략 로드맵 보고서", title_style))
    story.append(Paragraph(f"생성일: {today}", base_style))
    story.append(Spacer(1, 30))

    # 최종 답변
    story.append(Paragraph("📋 최종 로드맵 리포트", header_style))
    story.append(Spacer(1, 10))
    txt = last_answer.replace("\n", "<br/>")
    story.append(Paragraph(txt, base_style))
    story.append(Spacer(1, 20))

    story.append(PageBreak())

    # 참고 데이터
    story.append(Paragraph("🔗 참고 데이터 (출처)", header_style))

    has_none = any(
        not s.get("title") or s.get("title") == "None"
        for s in st.session_state.get("rag_sources", [])
    )
    named = [
        s for s in st.session_state.get("rag_sources", [])
        if s.get("title") and s.get("title") != "None"
    ]
    for s in named:
        src_line = f"- <b>{s['title']}</b><br/>{s.get('url', '')}"
        story.append(Paragraph(src_line, base_style))
        story.append(Spacer(1, 8))
    if has_none:
        story.append(Paragraph("- 내부 크롤링 기사 자료", base_style))
        story.append(Spacer(1, 8))

    doc.build(
        story,
        onFirstPage=add_watermark,
        onLaterPages=add_watermark
    )
    buf.seek(0)
    return buf


# ===============================================================
# 스트리밍 챗봇 처리 함수
# ===============================================================
def run_chat_stream(messages, final_query, selected_days):
    messages.append({"role": "user", "content": final_query})
    with st.chat_message("user"):
        st.markdown(final_query)

    with st.chat_message("assistant"):
        history_data = [
            {"role": m["role"], "content": m["content"]}
            for m in messages[-6:]
        ]
        payload = {
            "query": final_query,
            "focus": "취업 전략",
            "days": selected_days,
            "step": st.session_state.roadmap_step,
            "history": history_data
        }

        try:
            full_text = ""
            placeholder = st.empty()

            with requests.post(API_URL, json=payload, stream=True) as res:
                for raw_line in res.iter_lines():
                    if not raw_line:
                        continue
                    chunk = json.loads(raw_line)

                    if chunk["type"] == "meta":
                        st.session_state.rag_sources = chunk.get("sources", [])

                    elif chunk["type"] == "text":
                        full_text += chunk["content"]
                        placeholder.markdown(full_text + "▌")

                    elif chunk["type"] == "usage":
                        st.session_state.token_history.append(chunk["total_tokens"])
                        st.session_state.cost_history.append(chunk["cost"])
                        st.session_state.speed_history.append(chunk["tokens_per_sec"])
                        st.session_state.time_history.append(chunk["timestamp"])

            placeholder.markdown(full_text)
            messages.append({"role": "assistant", "content": full_text})

        except Exception as e:
            st.error(f"스트리밍 오류: {e}")

    display_sources(st.session_state.rag_sources)
    st.rerun()


# ===============================================================
# Sidebar
# ===============================================================
with st.sidebar:

    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, caption="일기일회: 소중한 단 한 번의 인연")

    st.divider()

    st.subheader("📅 데이터 수집 범위")
    date_range = st.selectbox(
        "수집 기간 설정",
        ["3개월", "6개월", "1년"],
        index=1
    )

    days_map = {"3개월": 90, "6개월": 180, "1년": 365}
    selected_days = days_map[date_range]

    st.divider()

    st.subheader("👤 목표 직무 설정")
    target_job = st.text_input(
        "희망 직무를 입력하세요",
        placeholder="예: 데이터 분석가",
        key="target_job"
    )
    if not target_job:
        st.warning("직무를 입력하면 로드맵이 시작됩니다.")
    else:
        st.success(f"**{target_job}** 로드맵 진행 중")

    st.divider()

    if st.button("🗑️ 대화 및 단계 초기화"):
        st.session_state.messages_trend = []
        st.session_state.messages_job = []
        st.session_state.current_step = 1
        st.session_state.roadmap_step = 0
        st.session_state.pop("target_job", None)
        st.session_state.youtube_videos = []
        st.session_state.youtube_videos_interview = []
        st.session_state.token_history = []
        st.session_state.cost_history = []
        st.session_state.speed_history = []
        st.session_state.time_history = []
        st.session_state.rag_sources = []
        st.rerun()

    st.divider()

    # 달력
    now = datetime.now()
    cal = calendar.monthcalendar(now.year, now.month)
    month_name = now.strftime("%Y년 %m월")

    st.subheader(f"🗓 {month_name}")

    cal_html = """
<style>
.cal-table { width:100%; border-collapse:collapse; font-size:13px; text-align:center; }
.cal-table th { color:#888; padding:4px 0; }
.cal-table td { padding:4px 0; color:#eee; }
.cal-table td.today { background:#4a90d9; border-radius:50%; color:white; font-weight:bold; }
.cal-table td.empty { color:transparent; }
.cal-table td.sun { color:#ff6b6b; }
.cal-table td.sat { color:#74b9ff; }
</style>
<table class="cal-table">
<tr><th>일</th><th>월</th><th>화</th><th>수</th><th>목</th><th>금</th><th>토</th></tr>
"""

    today_day = now.day
    for week in cal:
        cal_html += "<tr>"
        for i, day in enumerate(week):
            if day == 0:
                cal_html += '<td class="empty">·</td>'
            elif day == today_day:
                cal_html += f'<td class="today">{day}</td>'
            elif i == 0:
                cal_html += f'<td class="sun">{day}</td>'
            elif i == 6:
                cal_html += f'<td class="sat">{day}</td>'
            else:
                cal_html += f'<td>{day}</td>'
        cal_html += "</tr>"

    cal_html += "</table>"
    st.markdown(cal_html, unsafe_allow_html=True)


# ===============================================================
# 메인 타이틀
# ===============================================================
st.title("💼 일기일회 AI 취업 컨설턴트")
st.caption(f"현재 설정된 데이터 수집 범위: 최근 {date_range}")

# ===============================================================
# 메인 탭
# ===============================================================
tab_trend, tab_job, tab_youtube = st.tabs(
    ["🔍 일반 트렌드 분석", "🎯 개인 맞춤 취업대비", "▶ 유튜브 영상 추천"]
)

# ---------------------------------------------------------------
# 탭 1: 일반 트렌드 분석
# ---------------------------------------------------------------
with tab_trend:

    st.subheader("💡 빠른 트렌드 분석")
    col1, col2, col3 = st.columns(3)
    quick_query_trend = None

    with col1:
        if st.button("📈 실시간 채용 핫이슈"):
            quick_query_trend = f"최근 {date_range} 동안 가장 화제가 된 채용 뉴스 3가지를 알려줘."
    with col2:
        if st.button("🏢 주요 기업 기술 스택"):
            quick_query_trend = f"최근 {date_range} 트렌드를 반영한 주요 IT 기업들의 기술 스택 변화를 분석해줘."
    with col3:
        if st.button("🎓 신입 채용 시장 전망"):
            quick_query_trend = f"올해 상반기 신입 사원 채용 시장의 전망과 준비 전략을 알려줘."

    st.divider()

    messages_trend = st.session_state.messages_trend
    for message in messages_trend:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if messages_trend and messages_trend[-1]["role"] == "assistant":
        display_sources(st.session_state.rag_sources)

    trend_input = st.chat_input(
        "질문을 입력하거나 위 버튼을 눌러주세요.",
        key="chat_input_trend"
    )

    final_query_trend = trend_input or quick_query_trend
    if final_query_trend:
        run_chat_stream(messages_trend, final_query_trend, selected_days)

# ---------------------------------------------------------------
# 탭 2: 개인 맞춤 취업대비
# ---------------------------------------------------------------
with tab_job:

    if not target_job:
        st.warning("사이드바에서 희망 직무를 먼저 입력해주세요.")
    else:
        messages_job = st.session_state.messages_job
        quick_query_job = None

        for message in messages_job:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if messages_job and messages_job[-1]["role"] == "assistant":
            display_sources(st.session_state.rag_sources)

        if st.session_state.roadmap_step == 0:
            if st.button("Step 1: 직무 시장 현황 분석"):
                st.session_state.roadmap_step = 1
                quick_query_job = (
                    f"현재 '{target_job}' 직무의 시장 상황과 채용 트렌드를 "
                    f"{date_range} 데이터를 바탕으로 분석해줘."
                )
                st.session_state.current_step = 2

        elif st.session_state.roadmap_step == 1:
            if st.button("Step 2: 핵심 기술 & 자소서 전략"):
                st.session_state.roadmap_step = 2
                quick_query_job = (
                    f"'{target_job}' 직무 합격을 위한 필수 기술 스택과 "
                    f"자소서 핵심 문구 예시를 알려줘."
                )
                st.session_state.current_step = 3

        elif st.session_state.roadmap_step == 2:
            if st.button("Step 3: 실전 면접 대비 가이드"):
                st.session_state.roadmap_step = 3
                quick_query_job = (
                    f"'{target_job}' 면접에서 자주 나오는 기술 질문들과 "
                    f"답변 전략을 세워줘."
                )
                st.session_state.current_step = 4

        elif st.session_state.roadmap_step == 3:
            if st.button("Step 4: 마스터 로드맵 리포트"):
                st.session_state.roadmap_step = 4
                quick_query_job = (
                    f"지금까지의 대화를 종합해서 '{target_job}' 취업을 위한 "
                    f"최종 로드맵 리포트를 만들어줘."
                )

        job_input = st.chat_input(
            "질문을 입력하거나 위 버튼을 눌러주세요.",
            key="chat_input_job"
        )

        final_query_job = job_input or quick_query_job
        if final_query_job:
            run_chat_stream(messages_job, final_query_job, selected_days)

        if st.session_state.roadmap_step == 4 and st.session_state.messages_job:
            st.divider()
            pdf_file = create_chat_pdf(st.session_state.messages_job)
            st.download_button(
                label="📄 로드맵 대화 PDF 다운로드",
                data=pdf_file,
                file_name=f"JAB_NAVI_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )

# ---------------------------------------------------------------
# 탭 3: 유튜브 영상 추천
# ---------------------------------------------------------------
with tab_youtube:

    if not target_job:
        st.warning("사이드바에서 희망 직무를 먼저 입력해주세요.")
    else:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button(f"🔍 '{target_job}' 직무 영상 검색"):
                st.session_state.youtube_videos = search_youtube(
                    f"{target_job} 취업 직무 소개", max_results=3
                )
        with col_btn2:
            if st.button(f"🎤 '{target_job}' 면접 준비 영상 검색"):
                st.session_state.youtube_videos_interview = search_youtube(
                    f"{target_job} 면접 준비 합격", max_results=3
                )

        if st.session_state.youtube_videos:
            st.subheader(f"📌 {target_job} 직무 관련 영상")
            cols = st.columns(3)
            for i, v in enumerate(st.session_state.youtube_videos):
                with cols[i % 3]:
                    st.markdown(f"**{v['title']}**")
                    st.caption(v['channel'])
                    st.components.v1.iframe(
                        f"https://www.youtube.com/embed/{v['video_id']}",
                        height=200
                    )

        if st.session_state.youtube_videos_interview:
            st.subheader(f"🎤 {target_job} 면접 준비 영상")
            cols = st.columns(3)
            for i, v in enumerate(st.session_state.youtube_videos_interview):
                with cols[i % 3]:
                    st.markdown(f"**{v['title']}**")
                    st.caption(v['channel'])
                    st.components.v1.iframe(
                        f"https://www.youtube.com/embed/{v['video_id']}",
                        height=200
                    )

# ===============================================================
# 시스템 모니터링
# ===============================================================
if st.session_state.token_history:

    st.divider()

    total_tokens = sum(st.session_state.token_history)
    total_cost = sum(st.session_state.cost_history)
    avg_speed = (
        round(sum(st.session_state.speed_history) / len(st.session_state.speed_history), 1)
        if st.session_state.speed_history else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("데이터 범위", date_range)
    col2.metric("누적 토큰 사용", f"{total_tokens:,}")
    col3.metric("평균 답변 속도", f"{avg_speed} t/s")
    col4.metric("누적 비용", f"${total_cost:.4f}")