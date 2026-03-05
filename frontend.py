# frontend.py

import streamlit as st
import requests
import time
import pandas as pd
import json
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS

API_URL = "http://127.0.0.1:8000/ask"
API_STREAM_URL = "http://127.0.0.1:8000/ask_stream"
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"

# ============================================
# Session State
# ============================================
if "tab1_answer" not in st.session_state:
    st.session_state.tab1_answer = None
if "tab1_summary" not in st.session_state:
    st.session_state.tab1_summary = None
if "tab1_pdf" not in st.session_state:
    st.session_state.tab1_pdf = None

if "tab2_history" not in st.session_state:
    st.session_state.tab2_history = []

if "stats" not in st.session_state:
    st.session_state.stats = []

# ============================================
# 이미지 생성 (줄바꿈 최적화)
# ============================================
def create_image(text):

    if not text.strip():
        text = "내용이 없습니다."

    width = 1000
    margin = 70

    try:
        font = ImageFont.truetype(FONT_PATH, 24)
        title_font = ImageFont.truetype(FONT_PATH, 32)
    except:
        font = ImageFont.load_default()
        title_font = font

    temp_img = Image.new("RGB", (width, 5000), "white")
    draw = ImageDraw.Draw(temp_img)

    max_width = width - margin * 2
    lines = []
    words = text.split(" ")

    cur = ""
    for w in words:
        test = cur + w + " "
        if draw.textlength(test, font=font) < max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w + " "
    if cur:
        lines.append(cur)

    y = 160
    line_height = font.getbbox("가")[3] + 18
    height = y + line_height * len(lines) + 120

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    draw.text((margin, 60), "📊 요약 이미지", font=title_font, fill="black")

    for line in lines:
        draw.text((margin, y), line, font=font, fill="black")
        y += line_height

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# ============================================
# Tab1
# ============================================
def tab1():
    st.title("📌 자동 보고서 생성")

    if st.session_state.tab1_answer is None:

        with st.spinner("생성 중..."):

            r = requests.post(API_URL, json={
                "question": "한국 고용시장 전반 분석 보고서 작성",
                "mode": "report"
            })

            data = r.json()

            st.session_state.tab1_answer = data["answer"]
            st.session_state.tab1_summary = data["storage_summary"]
            st.session_state.tab1_pdf = data["pdf_path"]

            st.session_state.stats.append({
                "mode": "report",
                "tokens": data["stats"]["tokens"],
                "cost": data["stats"]["cost"],
                "tavily": data["fallback_used"]
            })

    st.write(st.session_state.tab1_answer)


# ============================================
# Tab2 (Streaming)
# ============================================
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

        placeholder = st.chat_message("assistant")
        out = placeholder.empty()
        collected = ""

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cost = 0
        tavily_used = False

        with requests.get(API_STREAM_URL, params={"question": q}, stream=True) as r:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw: 
                    continue
                if not raw.startswith("data: "):
                    continue

                data = raw.replace("data: ", "")

                if data.startswith("__END__"):
                    meta = json.loads(data.replace("__END__", ""))
                    prompt_tokens = meta["prompt_tokens"]
                    completion_tokens = meta["completion_tokens"]
                    total_tokens = meta["total_tokens"]
                    cost = meta["cost"]
                    tavily_used = meta["tavily_used"]
                    collected_final = meta["final_text"]
                    break

                collected += data
                out.write(collected)

        st.session_state.tab2_history.append(("assistant", collected))

        st.session_state.stats.append({
            "mode": "stream",
            "prompt": q,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "tavily": tavily_used
        })


# ============================================
# Tab3 (합본 PDF + 이미지/음성 요약본)
# ============================================
def tab3():
    st.title("📄 다운로드 센터")

    if not st.session_state.tab1_answer:
        st.info("먼저 탭1을 실행하세요.")
        return

    # ■■■ 1) 탭1 + 탭2 전체 합본 텍스트 생성 ■■■
    merged_text = "=== [자동 보고서] ===\n"
    merged_text += st.session_state.tab1_answer + "\n\n"
    merged_text += "=== [대화 기록] ===\n"

    for role, msg in st.session_state.tab2_history:
        merged_text += f"[{role}] {msg}\n\n"

    # ■■■ 2) 이미지 & 음성용 요약본 생성 ■■■
    r = requests.post(API_URL, json={
        "question": f"다음 내용을 12줄 요약:\n{merged_text}",
        "mode": "report"
    })
    summary = r.json()["answer"]

    # ■■■ 3) PDF 생성(합본 그대로) ■■■
    pdf_buf = BytesIO()
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.units import inch

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    style = ParagraphStyle(name="Korean", fontName="HYSMyeongJo-Medium", fontSize=11)

    doc = SimpleDocTemplate(pdf_buf)
    story = []
    for line in merged_text.split("\n"):
        story.append(Paragraph(line, style))
        story.append(Spacer(1, 0.18 * inch))
    doc.build(story)
    pdf_buf.seek(0)

    st.download_button(
        "📥 합본 PDF 다운로드",
        pdf_buf.getvalue(),
        "merged_report.pdf",
        mime="application/pdf"
    )

    # ■■■ 4) 이미지 생성 (요약본) ■■■
    img_bytes = create_image(summary)
    st.download_button(
        "🖼 요약 이미지 다운로드",
        img_bytes,
        "summary.png",
        mime="image/png"
    )

    # ■■■ 5) 음성 파일 생성 (요약본) ■■■
    tts_buf = BytesIO()
    tts = gTTS(text=summary, lang="ko")
    tts.write_to_fp(tts_buf)
    tts_buf.seek(0)

    st.download_button(
        "🔊 요약 음성 다운로드 (MP3)",
        tts_buf,
        "summary.mp3",
        mime="audio/mpeg"
    )


# ============================================
# Tab4 (Stats)
# ============================================
def tab4():
    st.title("📊 디버깅 로그")
    if not st.session_state.stats:
        st.info("로그 없음")
        return
    st.dataframe(pd.DataFrame(st.session_state.stats))


# ============================================
# Menu (버튼을 메뉴 바로 아래로 이동한 버전)
# ============================================
def reset_all_logs():
    keys = [
        "tab1_answer", "tab1_summary", "tab1_pdf",
        "tab2_history", "stats"
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


# ============================================
with st.sidebar:
    st.title("🧊 국내 취업 동향 분석")

    with st.expander("분석 카테고리", expanded=True):
        menu = st.radio(
            "",
            ["자동 보고서", "챗봇", "다운로드", "디버깅 로그"],
            label_visibility="collapsed"
        )

    st.markdown("---")

    if st.button("🔄 모든 로그 초기화"):
        reset_all_logs()
        st.success("세션 초기화 완료!")


# ▼ 메뉴 선택 처리
if menu == "자동 보고서":
    tab1()
elif menu == "챗봇":
    tab2()
elif menu == "다운로드":
    tab3()
elif menu == "디버깅 로그":
    tab4()

