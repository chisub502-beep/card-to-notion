# 📒 카드명세서 → 부가세 장부 자동 입력

카드사 PDF 명세서를 업로드하면 AI가 거래내역을 분석하여 Notion 부가세 장부에 자동 입력하는 웹앱입니다.

## 기능

- **PDF 직접 인식**: 텍스트 추출 없이 Claude AI가 PDF 레이아웃을 직접 읽음
- **AI 이중 검증**: 1차 파싱 + 2차 독립 검증으로 금액/건수 교차확인
- **수정 가능**: AI 결과를 테이블에서 직접 수정 후 저장
- **중복 방지**: 같은 거래 자동 건너뛰기
- **3인 사용**: 한치섭 / 한정주 / 한치흥 각각 뷰 분리

## 사전 준비

### 1. Notion Integration 생성

1. https://www.notion.so/my-integrations 접속
2. "새 통합" 클릭
3. 이름: `카드장부` (아무거나)
4. 기능: "콘텐츠 읽기", "콘텐츠 삽입" 체크
5. 저장 → **Internal Integration Secret** 복사 (`ntn_` 으로 시작)

### 2. Notion DB에 Integration 연결

1. 부가세 신고용 장부 (2026) 페이지 열기
2. 우상단 `...` → `연결` → 위에서 만든 `카드장부` 선택

### 3. Anthropic API 키

- https://console.anthropic.com 에서 API 키 발급

## 로컬 실행

```bash
# 1. 저장소 클론 (또는 파일 복사)
cd card-to-notion

# 2. 패키지 설치
pip install -r requirements.txt

# 3. secrets 설정
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml 열어서 실제 키 입력

# 4. 실행
streamlit run app.py
```

브라우저에서 http://localhost:8501 접속

## Streamlit Cloud 배포 (가족 공유)

```
1. GitHub에 이 폴더를 push
   (⚠️ secrets.toml은 .gitignore에 추가!)

2. https://share.streamlit.io 접속 → GitHub 연결

3. 앱 배포:
   - Repository: 본인 repo
   - Branch: main
   - Main file path: app.py

4. Settings → Secrets 에 아래 내용 입력:
   ANTHROPIC_API_KEY = "sk-ant-실제키"
   NOTION_API_KEY = "ntn_실제키"
   APP_PASSWORD = "가족공유비밀번호"

5. 배포 완료 → URL을 가족에게 공유
```

## 파일 구조

```
card-to-notion/
├── app.py              ← Streamlit UI (메인)
├── pdf_parser.py       ← 1차 AI: PDF → 거래내역 추출
├── verifier.py         ← 2차 AI: 검증용 총액/건수 추출
├── notion_uploader.py  ← Notion API 연동 + 중복체크
├── config.py           ← 설정 (DB ID, 사용자, 계정과목 규칙)
├── requirements.txt    ← Python 패키지
├── README.md
└── .streamlit/
    └── secrets.toml.example  ← 시크릿 템플릿
```

## 비용 참고

- Claude Haiku: PDF 1건당 약 $0.01~0.03 (2회 호출)
- 월 3명 × 1~2건 = 월 $0.1~0.2 수준
