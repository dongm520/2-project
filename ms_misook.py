import streamlit as st
import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from tavily import TavilyClient
from openai import OpenAI

#==========================================================================
# 1. 환경 설정 및 API 로드
#==========================================================================
load_dotenv()
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="일기일회 AI 컨설턴트", layout="wide", page_icon="🤖")

#==========================================================================
# 2. 데이터 보존 (세션 상태 초기화 - KeyError 방지를 위해 최상단 배치)
#==========================================================================
if 'token_history' not in st.session_state:
    st.session_state['token_history'] = []
if 'time_history' not in st.session_state:
    st.session_state['time_history'] = []
if 'search_history' not in st.session_state:
    st.session_state['search_history'] = []
if 'messages' not in st.session_state:
    st.session_state['messages'] = []

#==========================================================================
# 3. 국내 뉴스 크롤링 엔진 (전자신문, 한국경제)
#==========================================================================
def crawl_korean_news(query):
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    # 전자신문
    try:
        et_url = f"https://search.etnews.com{query}"
        res = requests.get(et_url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        articles = soup.select('dl.clearfix')[:3]
        for art in articles:
            title_tag = art.select_one('dt > a')
            desc_tag = art.select_one('dd.txt')
            if title_tag:
                results.append({
                    "title": f"[전자신문] {title_tag.get_text(strip=True)}",
                    "url": title_tag['href'],
                    "content": desc_tag.get_text(strip=True) if desc_tag else ""
                })
    except: pass

    # 한국경제
    try:
        hk_url = f"https://search.hankyung.com{query}"
        res = requests.get(hk_url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        articles = soup.select('ul.news_list > li')[:3]
        for art in articles:
            title_tag = art.select_one('h3.tit > a')
            desc_tag = art.select_one('p.txt')
            if title_tag:
                results.append({
                    "title": f"[한국경제] {title_tag.get_text(strip=True)}",
                    "url": title_tag['href'],
                    "content": desc_tag.get_text(strip=True) if desc_tag else ""
                })
    except: pass

    return results

#==========================================================================
# 4. 핵심 분석 엔진
#==========================================================================
def get_ai_analysis(query, focus_instruction, search_days):
    try:
        with st.status(f"🚀 '{query}' 심층 분석 중...", expanded=True) as status:
            # 글로벌 검색
            st.write("🔍 글로벌 트렌드 수집 중...")
            search_res = tavily.search(query=query, max_results=2, include_raw_content=True, days=search_days)
            
            context = ""
            sources = []
            for res in search_res['results']:
                context += f"제목: {res.get('title')}\n내용: {res.get('content')[:500]}\n\n"
                sources.append({"title": f"[글로벌] {res.get('title')}", "url": res.get('url')})

            # 국내 검색
            st.write("📰 국내 언론사 기사 파싱 중...")
            ko_news = crawl_korean_news(query)
            for kn in ko_news:
                context += f"제목: {kn['title']}\n내용: {kn['content']}\n\n"
                sources.append({"title": kn['title'], "url": kn['url']})

            # 보고서 생성
            st.write("🧠 통합 보고서 작성 중...")
            prompt = f"AI 전문가로서 다음 내용을 요약하고 '{focus_instruction}' 관점에서 한국어로 보고서를 작성하세요.\n\n{context}"
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            usage = response.usage
            current_time = datetime.now().strftime("%H:%M:%S")
            
            # 히스토리 업데이트
            st.session_state['token_history'].append(usage.total_tokens)
            st.session_state['time_history'].append(current_time)
            st.session_state['search_history'].insert(0, f"[{current_time}] {query[:10]}...")
            st.session_state['search_history'] = st.session_state['search_history'][:3]
            
            status.update(label="✅ 분석이 완료되었습니다!", state="complete", expanded=False)
            return response.choices[0].message.content, usage, sources
    except Exception as e:
        st.error(f"오류 발생: {e}")
        return None, None, None

#==========================================================================
# 5. 사이드바 구성 (로고, 설정, 추천 버튼) UI
#==========================================================================
with st.sidebar:
    # [로고 배치] 지정하신 경로에서 이미지를 불러옵니다.
    logo_path = r"C:\workAI\Project2\일기일회1.png"
    if os.path.exists(logo_path):
        st.image(logo_path, use_container_width=True)
    
    st.divider()
    st.header("⚙️ 분석 설정")
    period = st.radio("📅 데이터 수집 범위", ["최근 6개월", "최근 1년"], index=0)
    search_days = 180 if period == "최근 6개월" else 365
    
    st.divider()
    st.subheader("💡 빠른 분석 버튼")
    st.caption("클릭 시 즉시 챗봇이 분석을 시작합니다.")

    btn_query = None
    if st.button("📈 실시간 채용 트렌드"):
        btn_query = "현재 가장 활발한 국내 AI 에이전트 채용기업과 트렌드"
    if st.button("🛠 필수 기술 스택 Top 5"):
        btn_query = "국내 기업이 AI 에이전트 개발자에게 요구되는 핵심 기술 스택 5가지"
    if st.button("📉 산업별 고용 전망"):
        btn_query = "향후 1년간 한국 AI 산업 고용 변화 전망"

    st.divider()
    st.subheader("📜 최근 분석 기록")
    for item in st.session_state['search_history']:
        st.caption(item)
    
    if st.button("🗑 대화 기록 초기화"):
        st.session_state['messages'] = []
        st.session_state['search_history'] = []
        st.rerun()

#==========================================================================
# 6. 메인 화면
#==========================================================================
st.title("💼 AI 취업 전략 컨설팅 센터")
st.markdown(f"**{period}** 데이터를 기반으로 인공지능 분야의 취업 정보를 분석합니다.")

# 대화 내용 출력 구역
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 입력 처리 (채팅창 입력 OR 사이드바 버튼 클릭)
user_input = st.chat_input("궁금한 점을 물어보세요!")
final_query = user_input or btn_query

if final_query:
    # 1. 사용자 질문 기록
    st.session_state.messages.append({"role": "user", "content": final_query})
    with st.chat_message("user"):
        st.markdown(final_query)

    # 2. AI 답변 생성
    with st.chat_message("assistant"):
        report, usage, sources = get_ai_analysis(final_query, "취업 전략 보고서", search_days)
        if report:
            st.markdown(report)
            with st.expander("🔗 정보 출처 및 관련 기사"):
                for s in sources: st.write(f"- [{s['title']}]({s['url']})")
            
            # 답변 기록 및 토큰 정보
            st.session_state.messages.append({"role": "assistant", "content": report})
            st.caption(f"📊 분석 리소스 사용량: {usage.total_tokens} tokens")

#==========================================================================
# 7. 시스템 모니터링 (토큰 사용량 차트)
#==========================================================================
st.divider()
with st.expander("📈 시스템 실시간 성능 모니터링"):
    if st.session_state['token_history']:
        chart_df = pd.DataFrame({
            '시간': st.session_state['time_history'], 
            '사용 토큰량': st.session_state['token_history']
        })
        st.area_chart(chart_df.set_index('시간'))
    else:
        st.info("아직 분석 데이터가 쌓이지 않았습니다.")