# frontend_refactored.py

import streamlit as st
import requests
import time
import pandas as pd
import json
import hashlib
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import inch


API_URL = "http://127.0.0.1:8000/ask"
API_STREAM_URL = "http://127.0.0.1:8000/ask_stream"
API_REPORT_URL = "http://127.0.0.1:8000/report"

FONT_PATH = "C:/Windows/Fonts/malgun.ttf"


# ===============================================================
# Session State 초기화
# ===============================================================
if "tab1_answer" not in st.session_state:
    st.session_state.tab1_answer = None
if "tab1_summary" not in st.session_state:
    st.session_state.tab1_summary = None

if "tab2_history" not in st.session_state:
    st.session_state.tab2_history = []

if "stats" not in st.session_state:
    st.session_state.stats = []

if "merged_text" not in st.session_state:
    st.session_state.merged_text = ""

if "assets_hash" not in st.session_state:
    st.session_state.assets_hash = None

if "pdf_file" not in st.session_state:
    st.session_state.pdf_file = None
if "img_file" not in st.session_state:
    st.session_state.img_file = None
if "tts_file" not in st.session_state:
    st.session_state.tts_file = None

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "자동 보고서"


# ===============================================================
# Hash
# ===============================================================
def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ===============================================================
# 로그 초기화
# ===============================================================
def reset_all_logs():
    st.session_state.clear()
    st.success("모든 로그 초기화 완료. 새로고침 필요.")


# ===============================================================
# 이미지 생성
# ===============================================================
def create_image(text):

    width = 1000
    margin = 70

    try:
        font = ImageFont.truetype(FONT_PATH, 24)
        title_font = ImageFont.truetype(FONT_PATH, 32)
    except:
        font = ImageFont.load_default()
        title_font = font

    paragraphs = text.split("\n")

    processed_lines = []
    temp_img = Image.new("RGB", (width, 2000), "white")
    draw = ImageDraw.Draw(temp_img)

    max_width = width - margin * 2

    for para in paragraphs:
        words = para.split(" ")
        cur = ""
        for w in words:
            t = cur + w + " "
            if draw.textlength(t, font=font) <= max_width:
                cur = t
            else:
                processed_lines.append(cur)
                cur = w + " "
        if cur:
            processed_lines.append(cur)

    line_height = font.getbbox("가")[3] + 18
    y = 160
    height = y + line_height * len(processed_lines) + 200

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    draw.text((margin, 60), "📊 요약 이미지", font=title_font, fill="black")

    for line in processed_lines:
        draw.text((margin, y), line, font=font, fill="black")
        y += line_height

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return buf.getvalue()


# ===============================================================
# Asset 생성
# ===============================================================
def build_assets_if_needed(text):

    if not text:
        return

    h = text_hash(text)

    if st.session_state.assets_hash == h:
        return

    st.session_state.assets_hash = h

    r = requests.post(API_URL, json={
        "question": f"다음 내용을 20줄 요약:\n{text}",
        "mode": "report"
    })

    summary = r.json()["answer"]

    pdf_buf = BytesIO()

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))

    style = ParagraphStyle(
        name="Korean",
        fontName="HYSMyeongJo-Medium",
        fontSize=11
    )

    doc = SimpleDocTemplate(pdf_buf)
    story = []

    for line in text.split("\n"):
        story.append(Paragraph(line, style))
        story.append(Spacer(1, 0.18 * inch))

    doc.build(story)
    pdf_buf.seek(0)

    st.session_state.pdf_file = pdf_buf.getvalue()

    img_bytes = create_image(summary)
    st.session_state.img_file = img_bytes

    tts_buf = BytesIO()
    tts = gTTS(text=summary, lang="ko")
    tts.write_to_fp(tts_buf)
    tts_buf.seek(0)

    st.session_state.tts_file = tts_buf.getvalue()


# ===============================================================
# Tab1
# ===============================================================
def tab1():

    st.title("📌 자동 보고서")

    if st.session_state.tab1_answer is None:

        with st.spinner("보고서 로딩 중..."):

            while True:

                r = requests.get(API_REPORT_URL)
                data = r.json()

                if data["ready"]:
                    break

                time.sleep(1)

            report = data["data"]

            st.session_state.tab1_answer = report["answer"]
            st.session_state.tab1_summary = report["storage_summary"]

            st.session_state.stats.append({
                "mode": "report",
                "prompt": None,
                "prompt_tokens": None,
                "completion_tokens": report["stats"]["completion_tokens"],
                "total_tokens": report["stats"]["total_tokens"],
                "cost": report["stats"]["cost"],
                "tavily_used": report["fallback_used"],
                "tavily_tokens": report["stats"]["tavily_tokens"],
                "latency": report["stats"]["latency"]
            })

    st.write(st.session_state.tab1_answer)

    st.session_state.merged_text = (
        "=== [자동 보고서] ===\n"
        + st.session_state.tab1_answer + "\n\n"
    )


# ===============================================================
# Tab2
# ===============================================================
def tab2():

    st.title("💬 실시간 스트리밍 챗봇")

    for role, msg in st.session_state.tab2_history:
        with st.chat_message(role):
            st.write(msg)

    q = st.chat_input("질문 입력")

    if q:

        st.session_state.tab2_history.append(("user", q))

        with st.chat_message("user"):
            st.write(q)

        with st.spinner("답변 생성 중..."):

            placeholder = st.chat_message("assistant")
            out = placeholder.empty()

            collected_stream = ""
            first_token = False

            with requests.get(API_STREAM_URL, params={"question": q}, stream=True) as r:

                for raw in r.iter_lines(decode_unicode=True):

                    if not raw or not raw.startswith("data: "):
                        continue

                    data = raw.replace("data: ", "")

                    if data.startswith("__END__"):

                        meta = json.loads(data.replace("__END__", ""))

                        final_text = meta["final_text"]

                        st.session_state.tab2_history.append(("assistant", final_text))

                        st.session_state.stats.append({
                            "mode": "stream",
                            "prompt": q,
                            "prompt_tokens": meta["prompt_tokens"],
                            "completion_tokens": meta["completion_tokens"],
                            "total_tokens": meta["total_tokens"],
                            "cost": meta["cost"],
                            "tavily_used": meta["tavily_used"],
                            "tavily_tokens": meta["tavily_tokens"],
                            "latency": meta["latency"]
                        })

                        merged = st.session_state.merged_text
                        merged += f"[user] {q}\n\n[assistant] {final_text}\n\n"
                        st.session_state.merged_text = merged

                        break

                    if not first_token:
                        first_token = True

                    collected_stream += data
                    out.write(collected_stream)


# ===============================================================
# Tab3
# ===============================================================
def tab3():

    st.title("📄 다운로드 센터")

    if not st.session_state.merged_text:
        st.info("1번 또는 2번 탭을 먼저 사용하세요.")
        return

    build_assets_if_needed(st.session_state.merged_text)

    if st.session_state.pdf_file:

        st.download_button(
            "📥 합본 PDF 다운로드",
            st.session_state.pdf_file,
            "merged_report.pdf",
            mime="application/pdf"
        )

    if st.session_state.img_file:

        st.download_button(
            "🖼 요약 이미지 다운로드",
            st.session_state.img_file,
            "summary.png",
            mime="image/png"
        )

    if st.session_state.tts_file:

        st.download_button(
            "🔊 요약 음성 다운로드",
            st.session_state.tts_file,
            "summary.mp3",
            mime="audio/mpeg"
        )


# ===============================================================
# Tab4
# ===============================================================
def tab4():

    st.title("📊 디버깅 로그")

    if st.button("🔄 모든 로그 초기화"):
        reset_all_logs()

    if not st.session_state.stats:
        st.info("로그 없음")
        return

    df = pd.DataFrame(st.session_state.stats)

    desired_cols = [
        "mode", "prompt",
        "prompt_tokens", "completion_tokens", "total_tokens",
        "cost", "tavily_used", "tavily_tokens", "latency"
    ]

    for c in desired_cols:
        if c not in df.columns:
            df[c] = None

    df = df[desired_cols]

    st.dataframe(df)


# ===============================================================
# Sidebar
# ===============================================================
with st.sidebar:

    st.markdown("### 메뉴")

    tabs = ["자동 보고서", "챗봇", "다운로드", "디버깅 로그"]

    menu = st.radio(
        "",
        tabs,
        index=tabs.index(st.session_state.active_tab)
        if st.session_state.active_tab in tabs else 0
    )

    st.session_state.active_tab = menu

# ===============================================================
# Router
# ===============================================================
if st.session_state.active_tab == "자동 보고서":
    tab1()

elif st.session_state.active_tab == "챗봇":
    tab2()

elif st.session_state.active_tab == "다운로드":
    tab3()

elif st.session_state.active_tab == "디버깅 로그":
    tab4()