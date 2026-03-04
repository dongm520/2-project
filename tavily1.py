import streamlit as st
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from tavily import TavilyClient
from openai import OpenAI

# 1. 페이지 설정
st.set_page_config(page_title="AI 에이전트 취업 동향 분석", layout="wide", page_icon="🤖")

# 2. API 및 환경 변수 로드
load_dotenv()
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# [중요] 3. 실시간 토큰 로그 저장을 위한 세션 상태 초기화
# 브라우저를 새로고침하기 전까지 실행 데이터가 유지됩니다.
if 'token_history' not in st.session_state:
    st.session_state['token_history'] = []  # 토큰량 저장용 리스트
if 'time_history' not in st.session_state:
    st.session_state['time_history'] = []   # 실행 시간 저장용 리스트

# 4. AI 특화 분석 함수 (실제 토큰 데이터 반환)
def get_ai_analysis(query, focus_instruction):
    try:
        with st.spinner(f'🌐 {query} 관련 실시간 데이터를 분석 중...'):
            # Tavily 검색 (강사님 가이드: 1000자 제한 적용)
            search_res = tavily.search(
                query=f"{query} AI 에이전트 채용 트렌드 전자신문", 
                max_results=3, 
                include_raw_content=True
            )
            
            context = ""
            sources = []
            for res in search_res['results']:
                context += f"제목: {res.get('title')}\n내용: {res.get('content')[:1000]}\n\n"
                sources.append({"title": res.get('title'), "url": res.get('url')})

            # LLM 요청
            prompt = f"AI 기술 전문 컨설턴트로서 '{focus_instruction}' 보고서를 작성하세요.\n\n내용:\n{context}"
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            # 실제 사용된 토큰 정보 추출
            usage = response.usage
            current_time = datetime.now().strftime("%H:%M:%S")
            
            # 세션 상태에 실제 데이터 기록
            st.session_state['token_history'].append(usage.total_tokens)
            st.session_state['time_history'].append(current_time)
            
            return response.choices[0].message.content, usage, sources
    except Exception as e:
        st.error(f"오류 발생: {e}")
        return None, None, None

# 5. 사이드바 구성
with st.sidebar:
    st.header("🤖 메뉴 선택")
    category = st.radio(
        "분석 카테고리",
        ["🚀 AI 에이전트 채용 동향", "💻 기술 스택 메트로맵", "📊 AI 산업 고용 지표", "⚙️ 토큰 및 시스템"]
    )
    st.divider()
    st.caption("실시간으로 API 사용량을 추적하고 시각화합니다.")

# 6. 메인 화면 구성
st.title(f"🔍 {category}")

if category == "🚀 AI 에이전트 채용 동향":
    st.subheader("최신 AI 에이전트 기업 취업 동향")
    if st.button("트렌드 분석 시작", key="btn_ai_trend"):
        report, usage, sources = get_ai_analysis("AI 에이전트 도입 기업 및 채용", "국내외 시장 흐름 요약")
        if report:
            st.markdown(report)
            st.success(f"✅ 실제 사용 토큰: {usage.total_tokens}")
            with st.expander("🔗 참고 출처"):
                for s in sources: st.write(f"- [{s['title']}]({s['url']})")

elif category == "💻 기술 스택 메트로맵":
    st.subheader("AI 에이전트 개발 필수 기술 역량")
    if st.button("기술 스택 분석", key="btn_stack"):
        report, usage, sources = get_ai_analysis("LangChain AutoGPT RAG 기술 역량", "필수 기술 스택 비중")
        if report:
            st.markdown(report)
            st.info(f"✅ 이번 실행에 {usage.total_tokens} 토큰이 사용되었습니다.")

elif category == "📊 AI 산업 고용 지표":
    st.subheader("AI 산업 취업률 및 고용 변화")
    if st.button("지표 데이터 분석", key="btn_ai_stat"):
        report, usage, sources = get_ai_analysis("2026년 1월 2월 AI 소프트웨어 취업 통계", "취업률 수치 및 표 정리")
        if report:
            st.markdown(report)
            st.warning(f"✅ 실제 사용 토큰: {usage.total_tokens}")

elif category == "⚙️ 토큰 및 시스템":
    st.subheader("⚙️ 실시간 토큰 최적화 모니터링")
    st.write("강사님 가이드: 정크 사이즈 제거(1000자 제한)를 통한 실제 비용 관리 현황")
    
    if st.session_state['token_history']:
        # 1. 상단 지표 (Metric)
        col1, col2 = st.columns(2)
        total_accumulated = sum(st.session_state['token_history'])
        avg_tokens = total_accumulated // len(st.session_state['token_history'])
        
        col1.metric("누적 사용 토큰", f"{total_accumulated:,}")
        col2.metric("평균 사용량", f"{avg_tokens:,}")

        # 2. 실제 데이터 기반 그래프 시각화
        st.write("### 📈 실시간 토큰 사용 로그")
        chart_df = pd.DataFrame({
            '시간': st.session_state['time_history'],
            '토큰 사용량': st.session_state['token_history']
        })
        st.area_chart(chart_df.set_index('시간'))
        
        # 3. 데이터 요약 표
        st.write("### 📜 상세 로그")
        st.table(chart_df)
    else:
        st.info("아직 분석 데이터가 없습니다. 다른 메뉴에서 먼저 분석을 진행해 주세요!")