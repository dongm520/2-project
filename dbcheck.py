# ============================
# data_db_check.py (캐시 텍스트 저장 기능 추가)
# ============================

import os
from datadb import (
    FAISS_PATH,
    load_vector_db,
    TARGET_SITES,
    CACHE_DIR,
    get_cached_or_crawl,
)

OUTPUT_DIR = "cache_inspection_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def print_sep(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

# ------------------------------------------------------
# 1) 캐시 파일 목록 조회 + 내용 저장
# ------------------------------------------------------
def export_cache_files():
    print_sep("📌 [1] 캐시 텍스트 파일 내보내기")

    files = os.listdir(CACHE_DIR)
    if not files:
        print("❗ 캐시 파일 없음")
        return

    for f in files:
        cache_path = os.path.join(CACHE_DIR, f)
        out_path = os.path.join(OUTPUT_DIR, f)

        try:
            text = open(cache_path, "r", encoding="utf-8").read()
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(text)
            print(f"✔ 저장됨 → {out_path}")
        except Exception as e:
            print(f"❗ 저장 실패 {f}: {e}")

# ------------------------------------------------------
# 2) FAISS 상태 점검
# ------------------------------------------------------
def check_vectorstore_files():
    print_sep("📌 [2] FAISS 벡터스토어 파일 목록")
    if not os.path.exists(FAISS_PATH):
        print("❗ 벡터스토어 폴더 없음")
        return

    files = os.listdir(FAISS_PATH)
    if not files:
        print("❗ 벡터스토어 파일 없음")
        return

    for f in files:
        size = os.path.getsize(os.path.join(FAISS_PATH, f))
        print(f"- {f} ({size:,} bytes)")

# ------------------------------------------------------
# 3) 벡터스토어 문서 수 확인
# ------------------------------------------------------
def inspect_vector_db():
    print_sep("📌 [3] 벡터스토어 문서 수")
    try:
        db = load_vector_db()
        count = len(db.index_to_docstore_id)
        print(f"✔ 총 문서 수: {count:,}개")
    except Exception as e:
        print(f"❗ 벡터스토어 로드 실패: {e}")

# ------------------------------------------------------
# 4) URL 구조 확인
# ------------------------------------------------------
def show_target_urls():
    print_sep("📌 [4] 수집 대상 URL 구조")
    for category, urls in TARGET_SITES.items():
        print(f"[{category}]")
        for url in urls:
            print("  └", url)

# ------------------------------------------------------
# 5) 크롤링 품질 점검 + 캐시 저장
# ------------------------------------------------------
def check_crawling_quality(min_length=300):
    print_sep("📌 [5] 크롤링 품질 점검 (내용 부족 URL 탐지)")

    bad_urls = []
    good_urls = []

    for category, urls in TARGET_SITES.items():
        print(f"\n[{category}]")
        for url in urls:
            text = get_cached_or_crawl(url)
            length = len(text)

            # 캐시 내용 저장
            safe_name = url.replace("://", "_").replace("/", "_")
            outfile = os.path.join(OUTPUT_DIR, safe_name + ".txt")
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(text)

            if length < min_length:
                print(f"❗ 내용 부족 ({length} chars): {url}")
                bad_urls.append((url, length))
            else:
                print(f"✔ 정상 ({length} chars): {url}")
                good_urls.append((url, length))

    print_sep("📌 요약")
    print(f"정상 URL: {len(good_urls)}개")
    print(f"내용 부족 URL: {len(bad_urls)}개")

    if bad_urls:
        print("\n❗ 내용 부족 URL 목록:")
        for url, length in bad_urls:
            print(f"- {url} ({length} chars)")

# ------------------------------------------------------
# 전체 실행
# ------------------------------------------------------
def run_all_checks():
    print_sep("🔎 데이터DB 내부 상태 점검 시작")
    export_cache_files()
    check_vectorstore_files()
    inspect_vector_db()
    show_target_urls()
    check_crawling_quality(min_length=300)
    print_sep("🔍 점검 완료")


if __name__ == "__main__":
    run_all_checks()
