import streamlit as st
import requests, time
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap
from PIL import ImageFont

API_URL = "http://127.0.0.1:8000/ask"
FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"

st.set_page_config(page_title="취업 동향 분석", layout="wide")

# 세션 변수
if "last_answer" not in st.session_state:
    st.session_state.last_answer = None
if "last_pdf" not in st.session_state:
    st.session_state.last_pdf = None
if "stats_log" not in st.session_state:
    st.session_state.stats_log = []

# ---------------------
# HTML 카드 리포트 생성
# ---------------------
def render_html_report(text):
    card_html = f"""
    <div style="
        border: 2px solid #1f77b4;
        padding: 20px;
        border-radius: 12px;
        background-color: #f7f9fc;
        box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        ">
        <h3 style="color:#1f77b4;">📊 국내 취업 동향 분석 리포트</h3>
        <p style="white-space:pre-wrap; font-size:16px; line-height:1.5; color:#333;">
            {text}
        </p>
    </div>
    """
    return card_html

# ---------------------
# 이미지 생성
# ---------------------
def make_image(text):
    img = Image.new("RGB", (900, 1100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 18)

    d.rectangle([25, 25, 875, 1070], outline="black", width=3)
    d.text((50, 50), "📊 국내 취업 동향 분석 보고서", font=font, fill=(20, 20, 150))

    y = 120
    for line in textwrap.wrap(text, width=50):
        d.text((50, y), line, font=font, fill="black")
        y += 28

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------
# 메뉴
# ---------------------
menu = st.sidebar.radio("📋 메뉴", ["💬 분석 챗봇", "📊 운영 통계"])

# ---------------------
# 분석 챗봇
# ---------------------
if menu == "💬 분석 챗봇":
    st.title("📈 국내 취업 동향 분석")

    q = st.text_input("질문을 입력하세요.")

    if st.button("분석 요청"):
        start = time.time()
        res = requests.post(API_URL, json={"question": q})

        # 오류 방지
        if res.status_code != 200:
            st.error("백엔드 오류 발생")
            st.write(res.text)
            st.stop()

        try:
            data = res.json()
        except:
            st.error("JSON 파싱 오류")
            st.write(res.text)
            st.stop()

        end = time.time()

        st.session_state.last_answer = data["answer"]
        st.session_state.last_pdf = data["pdf_path"]

        st.session_state.stats_log.append({
            "latency": round(end - start, 3),
            "total_tokens": data["stats"]["total_tokens"],
            "total_cost": data["stats"]["total_cost"],
            "timestamp": time.strftime("%H:%M:%S"),
        })

    # ---------------------
    # 💡 탭 UI 제공
    # ---------------------
    if st.session_state.last_answer:
        tab1, tab2, tab3 = st.tabs(["📝 텍스트 분석", "🧾 HTML 리포트", "🖼 이미지/PDF 다운로드"])

        # --- 텍스트 분석 ---
        with tab1:
            st.subheader("📘 분석 결과")
            st.write(st.session_state.last_answer)

        # --- HTML 카드형 리포트 ---
        with tab2:
            html_block = render_html_report(st.session_state.last_answer)
            st.markdown(html_block, unsafe_allow_html=True)

        # --- 이미지 다운로드 탭 ---
        with tab3:
            img_bytes = make_image(st.session_state.last_answer)
            st.image(img_bytes)

            st.download_button("이미지 다운로드", img_bytes, "report.png", mime="image/png")
            st.download_button("PDF 다운로드",
                data=open(st.session_state.last_pdf, "rb").read(),
                file_name="report.pdf",
                mime="application/pdf")

# ---------------------
# 운영 통계 대시보드 (고도화)
# ---------------------
elif menu == "📊 운영 통계":
    st.title("📊 운영 통계 대시보드")

    if st.session_state.stats_log:
        df = pd.DataFrame(st.session_state.stats_log)

        # KPI 영역
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평균 지연시간", f"{df['latency'].mean():.3f}s")
        c2.metric("최대 지연시간", f"{df['latency'].max():.3f}s")
        c3.metric("총 토큰 사용량", f"{df['total_tokens'].sum():,}")
        c4.metric("누적 비용", f"${df['total_cost'].sum():.5f}")

        st.divider()

        # 차트 2종
        st.subheader("📈 지연시간 변화 추이")
        st.line_chart(df.set_index("timestamp")["latency"])

        st.subheader("📦 토큰 사용량 추이")
        st.bar_chart(df.set_index("timestamp")["total_tokens"])

        # 원본 데이터
        st.subheader("📋 Raw Logs")
        st.dataframe(df, use_container_width=True)

    else:
        st.info("아직 통계 데이터가 없습니다.")
