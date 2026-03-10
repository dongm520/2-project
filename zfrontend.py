# frontend.py (RAG + Tavily 완전 대응 개선 버전)

import streamlit as st
import requests
import os
import pandas as pd
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="일기일회 AI 취업 컨설턴트", layout="wide", page_icon="🤖")

API_URL = "http://127.0.0.1:8000/analyze"

# ===============================================================
# Session State 초기화 (로드맵 단계 및 대화 유지)
# ===============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "token_history" not in st.session_state:
    st.session_state.token_history = []
if "time_history" not in st.session_state:
    st.session_state.time_history = []
if "current_step" not in st.session_state:
    st.session_state.current_step = 1  # 로드맵 현재 단계 (1단계부터 시작)

# ===============================================================
# Sidebar 구성
# ===============================================================
with st.sidebar:
    logo_path = r"C:\workAI\Project2\일기일회1.png"
    if os.path.exists(logo_path):
        st.image(logo_path, caption="일기일회: 소중한 단 한 번의 인연")
    
    st.divider()
    
    # 1️⃣ 메뉴 선택
    menu = st.radio("📌 메뉴 선택", ["🔍 일반 트렌드 분석", "🎯 개인 맞춤 취업대비"])
    
    st.divider()

    # 2️⃣ 데이터 수집 범위 (새로 추가된 기능)
    st.subheader("📅 데이터 수집 범위")
    date_range = st.selectbox("수집 기간 설정", ["3개월", "6개월", "1년"], index=1)
    days_map = {"3개월": 90, "6개월": 180, "1년": 365}
    selected_days = days_map[date_range]

    st.divider()
    
    roadmap_step = 0
    quick_query = None
    
    # 🎯 개인 맞춤 취업대비 로직
    if menu == "🎯 개인 맞춤 취업대비":
        st.subheader("👤 목표 직무 설정")
        target_job = st.text_input("희망 직무를 입력하세요", placeholder="예: 데이터 분석가")
        
        if not target_job:
            st.warning("직무를 입력하면 로드맵이 시작됩니다.")
        else:
            st.success(f"**{target_job}** 로드맵 진행 중")
            st.divider()
            st.subheader("🚀 취업 로드맵")

            # --- 단계별 버튼 노출 로직 ---
            # 1단계: 항상 표시
            if st.button("Step 1: 직무 시장 현황 분석"):
                roadmap_step = 1
                quick_query = f"현재 '{target_job}' 직무의 시장 상황과 채용 트렌드를 {date_range} 데이터를 바탕으로 분석해줘."
                st.session_state.current_step = 2 # 다음 단계 해제

            # 2단계: 1단계를 실행했어야 표시
            if st.session_state.current_step >= 2:
                if st.button("Step 2: 핵심 기술 & 자소서 전략"):
                    roadmap_step = 2
                    quick_query = f"'{target_job}' 직무 합격을 위한 필수 기술 스택과 자소서 핵심 문구 예시를 알려줘."
                    st.session_state.current_step = 3

            # 3단계: 2단계를 실행했어야 표시
            if st.session_state.current_step >= 3:
                if st.button("Step 3: 실전 면접 대비 가이드"):
                    roadmap_step = 3
                    quick_query = f"'{target_job}' 면접에서 자주 나오는 기술 질문들과 답변 전략을 세워줘."
                    st.session_state.current_step = 4

            # 4단계: 3단계를 실행했어야 표시
            if st.session_state.current_step >= 4:
                if st.button("Step 4: 마스터 로드맵 리포트"):
                    roadmap_step = 4
                    quick_query = f"지금까지의 대화를 종합해서 '{target_job}' 취업을 위한 최종 로드맵 리포트를 만들어줘."

    # 🔍 일반 트렌드 분석 로직 (버튼 3개 복구)
    else:
        st.subheader("💡 빠른 트렌드 분석")
        if st.button("📈 실시간 채용 핫이슈"):
            quick_query = f"최근 {date_range} 동안 가장 화제가 된 채용 뉴스 3가지를 알려줘."
        if st.button("🏢 주요 기업 기술 스택"):
            quick_query = f"최근 {date_range} 트렌드를 반영한 주요 IT 기업들의 기술 스택 변화를 분석해줘."
        if st.button("🎓 신입 채용 시장 전망"):
            quick_query = f"올해 상반기 신입 사원 채용 시장의 전망과 준비 전략을 알려줘."

    st.divider()
    if st.button("🗑️ 대화 및 단계 초기화"):
        st.session_state.messages = []
        st.session_state.current_step = 1
        st.rerun()

# ===============================================================
# 메인 화면 UI
# ===============================================================
st.title(f"💼 {menu}")
st.caption(f"현재 설정된 데이터 수집 범위: 최근 {date_range}")

# 대화 내용 표시
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 입력 처리
final_query = st.chat_input("질문을 입력하거나 왼쪽 버튼을 눌러주세요.") or quick_query

if final_query:
    st.session_state.messages.append({"role": "user", "content": final_query})
    with st.chat_message("user"):
        st.markdown(final_query)

    with st.chat_message("assistant"):
        with st.spinner("전문가 데이터를 분석하고 보고서를 작성 중입니다..."):
            try:
                history_data = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[-6:]]
                
                payload = {
                    "query": final_query,
                    "focus": "취업 전략",
                    "days": selected_days, # 선택된 기간 전달
                    "step": roadmap_step,
                    "history": history_data
                }
                
                response = requests.post(API_URL, json=payload)
                
                if response.status_code == 200:
                    res = response.json()
                    report = res["report"]
                    usage = res["usage"]
                    
                    st.markdown(report)
                    
                    # 출처 표시
                    if "sources" in res and res["sources"]:
                        with st.expander("🔗 분석에 참고한 데이터 소스"):
                            for s in res["sources"]:
                                st.write(f"- [{s['title']}]({s['url']})")

                    st.session_state.messages.append({"role": "assistant", "content": report})
                    st.session_state.token_history.append(usage["total_tokens"])
                    st.session_state.time_history.append(usage["timestamp"])
                else:
                    st.error("백엔드 서버와 통신 중 오류가 발생했습니다.")
            except Exception as e:
                st.error(f"연결 오류: {str(e)}")

# ===============================================================
# 하단 대시보드
# ===============================================================
if st.session_state.token_history:
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric("데이터 범위", date_range)
    col2.metric("누적 토큰 사용", f"{sum(st.session_state.token_history):,}")
    col3.metric("로드맵 진행", f"{st.session_state.current_step-1} / 4 단계")