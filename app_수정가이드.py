"""
============================================================
  app.py 수정 가이드
  아래 내용을 기존 app.py에 반영하세요.
============================================================

■ 수정 1: 사이드바에 비밀번호 입력 필드 추가
  ──────────────────────────────────────────
  기존 사이드바 코드 (user selectbox 아래)에 추가:
"""

# ─── [추가] 사이드바에 넣을 코드 ───
with st.sidebar:
    st.header("⚙️ 설정")
    user = st.selectbox("사용자 선택", USERS)

    # ★ 아래 2줄 추가
    pdf_password = st.text_input(
        "PDF 비밀번호 (카드사 명세서 암호)", type="password",
        help="보통 생년월일 6자리 (예: 900101)"
    )

    st.divider()
    # ... (이하 기존 코드 유지)


"""
■ 수정 2: parse_statement 호출부 변경
  ──────────────────────────────────
  기존:
    items = parse_statement(pdf_bytes, user)
  또는:
    items = parse_statement(pdf_bytes, user, ANTHROPIC_KEY)

  변경:
"""

# ─── [변경] 파싱 호출 코드 ───
try:
    result = parse_statement(pdf_bytes, user, ANTHROPIC_KEY, password=pdf_password)
    items = result["items"]
    card_company = result["card_company"]

    if card_company:
        st.success(f"📇 감지된 카드사: **{card_company}**")

    st.info(f"✅ 총 {len(items)}건 추출 완료")

except ValueError as e:
    st.error(f"⚠️ {str(e)}")
    st.stop()
except Exception as e:
    st.error(f"파싱 실패: {e}")
    st.stop()


"""
■ 수정 3: notion_uploader.py의 create_entry() 함수에서
  ──────────────────────────────────────────────────────
  Notion에 저장할 때 "카드사" 속성도 함께 보내도록 추가.

  기존 properties 딕셔너리에 아래 추가:

    if item.get("카드사"):
        properties["카드사"] = {
            "select": {"name": item["카드사"]}
        }
"""
