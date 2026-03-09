# frontend.py (RAG + Tavily 완전 대응 개선 버전)

import streamlit as st
import requests
import os
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="일기일회 AI 컨설턴트", layout="wide", page_icon="🤖")

API_URL = "http://127.0.0.1:8000/analyze"


# ===============================================================
# Session State 초기화
# ===============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "token_history" not in st.session_state:
    st.session_state.token_history = []

if "time_history" not in st.session_state:
    st.session_state.time_history = []

if "search_history" not in st.session_state:
    st.session_state.search_history = []

if "rag_sources" not in st.session_state:
    st.session_state.rag_sources = []


# ===============================================================
# Sidebar
# ===============================================================
with st.sidebar:
    logo_path = r"C:\workAI\Project2\일기일회1.png"
    if os.path.exists(logo_path):
        st.image(logo_path)

    st.divider()

    period = st.radio("📅 데이터 수집 범위", ["최근 6개월", "최근 1년"])
    search_days = 180 if period == "최근 6개월" else 365

    st.divider()
    st.subheader("💡 빠른 분석 버튼")

    quick_query = None
    if st.button("📈 실시간 채용 트렌드"):
        quick_query = "현재 가장 활발한 국내 AI 에이전트 채용기업과 트렌드"
    if st.button("🛠 필수 기술 스택 Top 5"):
        quick_query = "국내 기업이 AI 에이전트 개발자에게 요구되는 핵심 기술 스택 5가지"
    if st.button("📉 산업별 고용 전망"):
        quick_query = "향후 1년간 한국 AI 산업 고용 변화 전망"

    st.divider()
    st.subheader("📜 최근 분석 기록")
    for item in st.session_state.search_history:
        st.caption(item)

    if st.button("🗑 전체 기록 초기화"):
        st.session_state.clear()
        st.rerun()


# ===============================================================
# 메인 UI — 채팅 구조 유지
# ===============================================================
st.title("💼 AI 취업 전략 컨설팅 센터")
st.markdown(f"**{period}** 데이터를 기반으로 인공지능 분야 취업 정보를 분석합니다.")

# 기존 메시지 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# 사용자 입력
user_input = st.chat_input("궁금한 점을 물어보세요!")
final_query = user_input or quick_query


# ===============================================================
# 🔥 메인 분석 처리
# ===============================================================
if final_query:

    # 1) 사용자 질문 출력
    st.session_state.messages.append({"role": "user", "content": final_query})
    with st.chat_message("user"):
        st.markdown(final_query)

    # 2) 응답 처리
    with st.chat_message("assistant"):
        with st.spinner("🔍 RAG + Tavily 검색 기반 분석 중... 잠시만 기다려주세요."):
            res = requests.post(
                API_URL,
                json={
                    "query": final_query,
                    "focus": "취업 전략 보고서",
                    "days": search_days
                }
            ).json()

        # 오류 처리
        if "error" in res:
            st.error(res["error"])
        else:
            report = res["report"]
            usage = res["usage"]
            timestamp = usage["timestamp"]

            unique_sources = []
            seen = set()

            # RAG + Tavily 출처 중복 제거
            for s in res["sources"]:
                sig = (s["title"], s["url"])
                if sig not in seen:
                    seen.add(sig)
                    unique_sources.append(s)

            # 보고서 출력(자동 접힘 옵션)
            st.markdown(report)

            with st.expander("🔗 RAG + Tavily 기반 정보 출처"):
                for s in unique_sources:
                    st.write(f"- [{s['title']}]({s['url']})")

            # 메시지 저장
            st.session_state.messages.append({"role": "assistant", "content": report})

            # 모니터링 로그 저장
            st.session_state.token_history.append(usage["total_tokens"])
            st.session_state.time_history.append(timestamp)
            st.session_state.search_history.insert(0, f"[{timestamp}] {final_query[:20]}...")

            # RAG 출처 저장
            st.session_state.rag_sources = unique_sources[:]


# ===============================================================
# 시스템 모니터링
# ===============================================================
st.divider()
with st.expander("📈 시스템 리소스 사용 모니터링"):
    if st.session_state.token_history:
        df = pd.DataFrame(
            {
                "시간": st.session_state.time_history,
                "사용 토큰량": st.session_state.token_history
            }
        )
        st.area_chart(df.set_index("시간"))
    else:
        st.info("아직 분석 기록이 없습니다.")
