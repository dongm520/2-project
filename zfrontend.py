# frontend.py
# Streamlit 렌더링 - UI 관리

import streamlit as st
import requests
import os
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv()

st.set_page_config(
    page_title="Job Navi 취업 컨설턴트",
    layout="wide",
    page_icon="🤖"
)

API_URL = "http://127.0.0.1:8000"
LOGO_PATH = "images/잡나비.png"


# ===============================================================
# Session State
# ===============================================================
defaults = {
    "messages_trend": [],
    "messages_job": [],
    "token_history": [],
    "cost_history": [],
    "speed_history": [],
    "time_history": [],
    "current_step": 1,
    "roadmap_step": 0,
    "rag_sources": [],
    "youtube_videos": [],
    "youtube_videos_interview": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ===============================================================
# 백엔드 호출 헬퍼
# ===============================================================
def api_get(endpoint):
    try:
        res = requests.get(f"{API_URL}{endpoint}")
        return res.json()
    except Exception as e:
        st.error(f"API 오류: {e}")
        return {}


def api_post(endpoint, payload):
    try:
        res = requests.post(f"{API_URL}{endpoint}", json=payload)
        return res.json()
    except Exception as e:
        st.error(f"API 오류: {e}")
        return {}


# ===============================================================
# 차트 렌더링
# ===============================================================
@st.cache_data
def fetch_chart_data():
    return api_get("/chart-data")


def render_main_chart():
    data = fetch_chart_data()
    if "error" in data or not data:
        st.error("차트 데이터를 불러올 수 없습니다.")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=data["labels"], y=data["emp_values"],
            name="취업자 (천명)",
            mode="lines+markers",
            line=dict(color="#4a90d9", width=2),
            marker=dict(size=6)
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=data["labels"], y=data["rate_values"],
            name="고용률 (%)",
            mode="lines+markers",
            line=dict(color="#f39c12", width=2, dash="dash"),
            marker=dict(size=6)
        ),
        secondary_y=True
    )
    fig.update_layout(
        title="분기별 취업자 수 및 고용률 (2021~2025)",
        xaxis_title="분기",
        legend=dict(x=0, y=1.1, orientation="h"),
        height=350,
        margin=dict(l=20, r=20, t=60, b=40)
    )
    fig.update_yaxes(title_text="취업자 (천명)", secondary_y=False)
    fig.update_yaxes(title_text="고용률 (%)", secondary_y=True)
    st.plotly_chart(fig, width="stretch")


# ===============================================================
# 참고 자료 표시
# ===============================================================
def display_sources(sources):
    if not sources:
        return

    has_none = any(not s.get("title") or s.get("title") == "None" for s in sources)
    named = [s for s in sources if s.get("title") and s.get("title") != "None"]

   # 동일 title 중복 제거
    seen = set()
    deduped = []
    for s in named:
        if s.get("title") not in seen:
            seen.add(s.get("title"))
            deduped.append(s)
    named = deduped

    lines = []
    for s in named:
        url = s.get("url", "")
        title = s.get("title", "")
        lines.append(f"- [{title}]({url})" if url else f"- {title}")
    if has_none:
        lines.append("- 내부 크롤링 기사 자료")

    if lines:
        with st.expander("📎 참고 자료"):
            st.markdown("\n".join(lines))


# ===============================================================
# 스트리밍 챗봇
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

            with requests.post(f"{API_URL}/analyze", json=payload, stream=True) as res:
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

    now = datetime.now()
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH)
        st.markdown(
            f"<p style='text-align:center; font-size:20px; color:#222222; font-weight:600;'>"
            f"{now.strftime('%Y년 %m월 %d일')}</p>",
            unsafe_allow_html=True
        )

    st.divider()

    st.subheader("📅 데이터 수집 범위")
    date_range = st.selectbox("수집 기간 설정", ["3개월", "6개월", "1년"], index=1)
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
        for k, v in defaults.items():
            st.session_state[k] = v if not isinstance(v, list) else []
        st.session_state.pop("target_job", None)
        st.rerun()


# ===============================================================
# 메인 타이틀
# ===============================================================
st.title("💼 Job Navi 취업 컨설턴트")
st.caption(f"현재 설정된 데이터 수집 범위: 최근 {date_range}")

# ===============================================================
# 메인 탭
# ===============================================================
tab_trend, tab_job, tab_recruit, tab_youtube = st.tabs(
    ["🔍 일반 트렌드 분석", "🎯 개인 맞춤 취업대비", "📋 채용 공고 바로가기", "▶ 유튜브 영상 추천"]
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
        if st.button("🔮 최근 유망 직종 분석"):
            quick_query_trend = (
                f"최근 {date_range} 기간 정보를 바탕으로 현재 가장 주목받고 있는 유망 직종 3가지를 분석해줘. "
                f"각 직종별로 성장 배경, 필요 역량, 평균 연봉 수준을 포함해서 5줄 이내로 요약해서 설명해줘."
    )
    with col3:
        if st.button("🎓 신입 채용 시장 전망"):
            quick_query_trend = f"{date_range}동안 신입 사원 채용 시장의 전망과 준비 전략을 요약해서 알려줘."

    st.divider()

    if not st.session_state.messages_trend:
        render_main_chart()
        st.divider()

    messages_trend = st.session_state.messages_trend
    for message in messages_trend:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if messages_trend and messages_trend[-1]["role"] == "assistant":
        display_sources(st.session_state.rag_sources)

    trend_input = st.chat_input("질문을 입력하거나 위 버튼을 눌러주세요.", key="chat_input_trend")
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
                    f"자소서 핵심 문구를 키워드 중심으로 알려줘."
                )
                st.session_state.current_step = 3

        elif st.session_state.roadmap_step == 2:
            if st.button("Step 3: 실전 면접 대비 가이드"):
                st.session_state.roadmap_step = 3
                quick_query_job = (
                    f"'{target_job}' 면접에서 자주 나올 기술 질문 3가지와 "
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

        job_input = st.chat_input("질문을 입력하거나 위 버튼을 눌러주세요.", key="chat_input_job")
        final_query_job = job_input or quick_query_job
        if final_query_job:
            run_chat_stream(messages_job, final_query_job, selected_days)

        if st.session_state.roadmap_step == 4 and st.session_state.messages_job:
            st.divider()

            # 마지막 assistant 답변 추출
            last_answer = ""
            for m in reversed(st.session_state.messages_job):
                if m["role"] == "assistant":
                    last_answer = m["content"]
                    break

            # 백엔드에서 PDF 받기
            try:
                pdf_res = requests.post(
                    f"{API_URL}/pdf",
                    json={
                        "last_answer": last_answer,
                        "rag_sources": st.session_state.rag_sources
                    }
                )
                st.download_button(
                    label="📄 로드맵 대화 PDF 다운로드",
                    data=pdf_res.content,
                    file_name=f"JAB_NAVI_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"PDF 생성 오류: {e}")

# ---------------------------------------------------------------
# 탭 3: 채용 공고 바로가기
# ---------------------------------------------------------------
with tab_recruit:

    if not target_job:
        st.warning("사이드바에서 희망 직무를 먼저 입력해주세요.")
    else:
        st.subheader(f"🔎 '{target_job}' 관련 채용 공고")
        st.caption("아래 버튼을 클릭하면 해당 사이트의 검색 결과로 이동합니다.")
        st.divider()

        job_encoded = quote(target_job)

        col1, col2, col3 = st.columns(3)

        with col1:
            _, center, _ = st.columns([1, 2, 1])
            with center:
                st.link_button(
                    "💼 사람인에서 검색",
                    f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={job_encoded}",
                    width="stretch"
                )
                if os.path.exists("images/사람인.avif"):
                    st.image("images/사람인.avif", width="stretch")

        with col2:
            _, center, _ = st.columns([1, 2, 1])
            with center:
                st.link_button(
                    "💼 잡코리아에서 검색",
                    f"https://www.jobkorea.co.kr/Search/?stext={job_encoded}",
                    width="stretch"
                )
                if os.path.exists("images/잡코리아.avif"):
                    st.image("images/잡코리아.avif", width="stretch")

        with col3:
            _, center, _ = st.columns([1, 2, 1])
            with center:
                st.link_button(
                    "💼 원티드에서 검색",
                    f"https://www.wanted.co.kr/search?query={job_encoded}",
                    width="stretch"
                )
                if os.path.exists("images/원티드.png"):
                    st.image("images/원티드.png", width="stretch")

# ---------------------------------------------------------------
# 탭 4: 유튜브 영상 추천
# ---------------------------------------------------------------
with tab_youtube:

    if not target_job:
        st.warning("사이드바에서 희망 직무를 먼저 입력해주세요.")
    else:
        col_btn1, col_btn2 = st.columns(2)

        with col_btn1:
            if st.button(f"🔍 '{target_job}' 직무 영상 검색"):
                result = api_post("/youtube", {
                    "query": f"{target_job} 취업 직무 소개",
                    "max_results": 3
                })
                st.session_state.youtube_videos = result.get("videos", [])

        with col_btn2:
            if st.button(f"🎤 '{target_job}' 면접 준비 영상 검색"):
                result = api_post("/youtube", {
                    "query": f"{target_job} 면접 준비 합격",
                    "max_results": 3
                })
                st.session_state.youtube_videos_interview = result.get("videos", [])

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