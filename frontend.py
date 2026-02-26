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

if "last_answer" not in st.session_state:
    st.session_state.last_answer = None
if "last_pdf" not in st.session_state:
    st.session_state.last_pdf = None
if "stats_log" not in st.session_state:
    st.session_state.stats_log = []

def make_image(text):
    img = Image.new("RGB", (900, 1100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 18)

    d.rectangle([25, 25, 875, 1070], outline="black", width=3)
    d.text((50, 50), "📊 국내 취업 동향 분석 보고서", font=font, fill=(20,20,150))

    y = 120
    for line in textwrap.wrap(text, width=50):
        d.text((50, y), line, font=font, fill="black")
        y += 28

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

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

        # JSONDecodeError 방지
        if res.status_code != 200:
            st.error("백엔드 오류 발생 (status != 200)")
            st.write(res.text)
            st.stop()

        try:
            data = res.json()
        except:
            st.error("백엔드가 JSON을 반환하지 않았습니다.")
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

    # 이전 분석 내용 유지
    if st.session_state.last_answer:
        st.subheader("📘 분석 결과")
        st.write(st.session_state.last_answer)

        img_bytes = make_image(st.session_state.last_answer)
        st.image(img_bytes)

        st.download_button("이미지 다운로드", img_bytes, "report.png", mime="image/png")
        st.download_button("PDF 다운로드",
                           data=open(st.session_state.last_pdf, "rb").read(),
                           file_name="report.pdf",
                           mime="application/pdf")

# ---------------------
# 운영 통계 대시보드
# ---------------------
elif menu == "📊 운영 통계":
    st.title("📊 운영 통계 대시보드")

    if st.session_state.stats_log:
        df = pd.DataFrame(st.session_state.stats_log)

        c1, c2, c3 = st.columns(3)
        c1.metric("평균 지연시간", f"{df['latency'].mean():.3f}s")
        c2.metric("총 토큰 사용량", f"{df['total_tokens'].sum():,}")
        c3.metric("누적 비용", f"${df['total_cost'].sum():.5f}")

        st.line_chart(df.set_index("timestamp")["latency"])
        st.dataframe(df)
    else:
        st.info("아직 통계 데이터가 없습니다.")
