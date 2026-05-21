"""
📒 카드명세서 → 부가세 장부 자동 입력
Streamlit 웹앱 메인
"""
import streamlit as st
import pandas as pd
from pdf_parser import parse_statement
from verifier import verify_statement, cross_check
from notion_uploader import upload_all
from config import USERS


# ─── 페이지 설정 ───
st.set_page_config(
    page_title="카드명세서 → 부가세 장부",
    page_icon="📒",
    layout="wide",
)


# ─── API 키 로드 (Streamlit Cloud: secrets.toml / 로컬: 환경변수) ───
def get_api_keys():
    try:
        anthropic_key = st.secrets["ANTHROPIC_API_KEY"]
        notion_key = st.secrets["NOTION_API_KEY"]
    except Exception:
        import os
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        notion_key = os.environ.get("NOTION_API_KEY", "")
    return anthropic_key, notion_key


ANTHROPIC_KEY, NOTION_KEY = get_api_keys()


# ─── 비밀번호 잠금 ───
def check_password():
    try:
        app_pw = st.secrets["APP_PASSWORD"]
    except Exception:
        return True  # 로컬 개발 시 비밀번호 없으면 통과

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        pw = st.text_input("🔒 비밀번호를 입력하세요", type="password")
        if pw:
            if pw == app_pw:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
        st.stop()


check_password()


# ─── 메인 UI ───
st.title("📒 카드명세서 → 부가세 장부")
st.caption("카드사 PDF 명세서를 업로드하면 AI가 분석하여 Notion 장부에 자동 입력합니다.")


# ─── 사이드바: 사용자 선택 + PDF 비밀번호 ───
with st.sidebar:
    st.header("⚙️ 설정")
    user = st.selectbox("사용자 선택", USERS)
    pdf_password = st.text_input(
        "PDF 비밀번호",
        type="password",
        help="카드사 명세서에 걸린 암호 (보통 생년월일 6자리, 예: 900101)",
    )
    st.divider()
    st.markdown("**사용법**")
    st.markdown(
        "1. 사용자 선택\n"
        "2. PDF 비밀번호 입력 (있는 경우)\n"
        "3. 카드 명세서 PDF 업로드\n"
        "4. AI 분석 결과 확인\n"
        "5. 필요시 수정 후 저장"
    )
    st.divider()
    st.caption(
        "AI 분류는 참고용입니다.\n"
        "계정과목과 매입세액공제는\n"
        "반드시 확인 후 저장하세요."
    )


# ─── PDF 업로드 ───
uploaded = st.file_uploader("카드 명세서 PDF 업로드", type="pdf")

if uploaded:
    pdf_bytes = uploaded.read()

    if st.button("🔍 AI 분석 시작", type="primary", use_container_width=True):
        # ── 1차: AI 파싱 ──
        try:
            with st.spinner("AI가 명세서를 읽고 있습니다... (페이지가 많으면 시간이 걸릴 수 있어요)"):
                result = parse_statement(
                    pdf_bytes,
                    user_name=user,
                    api_key=ANTHROPIC_KEY,
                    password=pdf_password,
                )
                items = result["items"]
                card_company = result["card_company"]
        except ValueError as e:
            st.error(f"⚠️ {str(e)}")
            st.stop()
        except Exception as e:
            st.error(f"파싱 실패: {e}")
            st.stop()

        if not items:
            st.warning("추출된 거래내역이 없습니다. PDF를 확인해주세요.")
            st.stop()

        # 카드사 감지 결과
        if card_company:
            st.success(f"📇 감지된 카드사: **{card_company}**")

        st.info(f"✅ 총 **{len(items)}건** 추출 완료")

        # ── 2차: 검증 (비밀번호 해제된 PDF 재사용) ──
        try:
            with st.spinner("검증 중..."):
                # 비밀번호 해제된 PDF로 검증
                from pdf_parser import decrypt_pdf
                decrypted_pdf = decrypt_pdf(pdf_bytes, pdf_password) if pdf_password else pdf_bytes
                summary = verify_statement(decrypted_pdf, ANTHROPIC_KEY)
                check = cross_check(items, summary)

            if check["금액_일치"] and check["건수_일치"]:
                st.success(
                    f"✅ 검증 통과 — {check['추출합계']:,}원 / {len(items)}건"
                )
            else:
                st.warning(
                    f"⚠️ 불일치 — 추출: {check['추출합계']:,}원, "
                    f"명세서: {check['명세서총액']:,}원 "
                    f"(차이: {check['차이']:+,}원)"
                )
        except Exception as e:
            st.warning(f"검증 스킵 (오류: {e}). 파싱 결과는 아래에서 직접 확인하세요.")

        # ── 결과 테이블 (수정 가능) ──
        st.subheader("📋 추출 결과")
        df = pd.DataFrame(items)

        # 컬럼 순서 정리
        desired_cols = [
            "거래일", "가맹점명", "합계금액", "공급가액", "부가세",
            "계정과목", "매입세액공제", "증빙구분", "사용자",
            "카드사", "카드번호뒷자리", "귀속월", "분류상태", "적요",
        ]
        cols = [c for c in desired_cols if c in df.columns]
        remaining = [c for c in df.columns if c not in cols]
        df = df[cols + remaining]

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
        )

        # 합계 표시
        total = edited_df["합계금액"].sum() if "합계금액" in edited_df.columns else 0
        st.metric("합계금액", f"{int(total):,}원")

        # ── session_state에 저장 ──
        st.session_state["edited_items"] = edited_df.to_dict("records")
        st.session_state["card_company"] = card_company


# ─── Notion 저장 버튼 ───
if "edited_items" in st.session_state:
    st.divider()
    if st.button(
        "✅ Notion에 저장",
        type="primary",
        use_container_width=True,
    ):
        items_to_save = st.session_state["edited_items"]

        progress_bar = st.progress(0, text="저장 중...")
        with st.spinner("Notion에 저장하는 중..."):
            results = upload_all(items_to_save, NOTION_KEY)

        progress_bar.progress(100, text="완료!")

        # 결과 표시
        col1, col2 = st.columns(2)
        col1.metric("성공", f"{results['success']}건")
        col2.metric("실패", f"{results['fail']}건")

        if results["errors"]:
            with st.expander("❌ 오류 상세"):
                for err in results["errors"]:
                    st.text(f"- {err.get('가맹점명', '?')}: {err.get('error', '?')}")

        if results["success"] > 0:
            st.balloons()

        # 저장 완료 후 세션 정리
        del st.session_state["edited_items"]
