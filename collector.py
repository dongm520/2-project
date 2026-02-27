import requests
from bs4 import BeautifulSoup
import sqlite3
import time

def setup_db():
    conn = sqlite3.connect("news.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, content TEXT, url TEXT UNIQUE
        )
    """)
    conn.commit()
    return conn

def collect_from_bbc_extended():
    conn = setup_db()
    cursor = conn.cursor()
    
    # 1. 수집할 카테고리 리스트 (메인, 뉴스, 비즈니스, 과학, 기술)
    categories = [
        "https://www.bbc.com/korean",
        "https://www.bbc.com/korean/news",
        "https://www.bbc.com/korean/topics/c7zp57yyz2jt", # 비즈니스(경제)
        "https://www.bbc.com/korean/topics/cnq68n6wgzdt", # 과학
        "https://www.bbc.com/korean/topics/cg7267dz901t"  # 기술(IT)
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    all_article_urls = set()

    # 2. 각 카테고리 페이지를 돌며 기사 링크 먼저 수집
    for cat_url in categories:
        try:
            print(f"🔍 카테고리 스캔 중: {cat_url}")
            res = requests.get(cat_url, headers=headers)
            soup = BeautifulSoup(res.text, "lxml")
            links = soup.select('a[href*="/korean/articles/"]')
            
            for l in links:
                full_url = "https://www.bbc.com" + l['href'] if not l['href'].startswith('http') else l['href']
                all_article_urls.add(full_url)
            time.sleep(1) # 카테고리 전환 시 휴식
        except Exception as e:
            print(f"❌ {cat_url} 접속 오류: {e}")

    print(f"✅ 총 {len(all_article_urls)}개의 고유 기사 링크를 찾았습니다.")

    # 3. 수집된 모든 링크를 하나씩 방문하여 본문 추출
    success_count = 0
    for url in all_article_urls:
        # 중복 체크: 이미 DB에 있는 URL인지 확인
        cursor.execute("SELECT url FROM job_news WHERE url = ?", (url,))
        if cursor.fetchone():
            continue

        try:
            time.sleep(0.8) # 차단 방지를 위한 미세한 대기
            article_res = requests.get(url, headers=headers)
            article_soup = BeautifulSoup(article_res.text, "lxml")
            
            title_tag = article_soup.find("h1")
            content_tags = article_soup.select("main p")
            
            if title_tag and content_tags:
                title = title_tag.get_text(strip=True)
                content = " ".join([p.get_text(strip=True) for p in content_tags])
                
                cursor.execute("INSERT OR IGNORE INTO job_news (title, content, url) VALUES (?, ?, ?)", 
                               (title, content, url))
                success_count += 1
                print(f"🚀 [{success_count}] 저장 완료: {title[:15]}...")
                
                # 10개 단위로 중간 저장
                if success_count % 10 == 0:
                    conn.commit()
        except Exception as e:
            print(f"❌ 기사 수집 실패 ({url}): {e}")

    conn.commit()
    print(f"\n✨ 작업 완료! 새로 추가된 기사: {success_count}개")
    conn.close()

if __name__ == "__main__":
    collect_from_bbc_extended()