"""
📒 카드명세서 → 부가세 장부 자동 입력
Streamlit 웹앱 메인
"""
import streamlit as st
import pandas as pd
from pdf_parser import parse_statement
from verifier import verify_statement, cross_check
from notion_uploader import upload_with_dedup
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

# ─── 사이드바: 사용자 선택 ───
with st.sidebar:
    st.header("⚙️ 설정")
    user = st.selectbox("사용자 선택", USERS)
    st.divider()
    st.markdown("**사용법**")
    st.markdown(
        "1. 사용자 선택\n"
        "2. 카드 명세서 PDF 업로드\n"
        "3. AI 분석 결과 확인\n"
        "4. 필요시 수정 후 저장"
    )
    st.divider()
    st.caption("AI 분류는 참고용입니다.\n계정과목과 매입세액공제는\n반드시 확인 후 저장하세요.")

# ─── PDF 업로드 ───
uploaded = st.file_uploader(
    "카드 명세서 PDF를 올려주세요",
    type=["pdf"],
    help="카드사에서 발송한 이용대금 명세서 PDF 파일",
)

if uploaded is not None:
    pdf_bytes = uploaded.read()
    file_size_mb = len(pdf_bytes) / (1024 * 1024)
    st.info(f"📄 **{uploaded.name}** ({file_size_mb:.1f} MB) — 사용자: **{user}**")

    # ─── 분석 시작 ───
    if st.button("🔍 AI 분석 시작", type="primary", use_container_width=True):

        # API 키 확인
        if not ANTHROPIC_KEY or not NOTION_KEY:
            st.error("API 키가 설정되지 않았습니다. secrets.toml 또는 환경변수를 확인하세요.")
            st.stop()

        # ── 1차: AI 파싱 ──
        with st.status("AI가 명세서를 분석하고 있습니다...", expanded=True) as status:
            st.write("📖 1차: PDF에서 거래내역 추출 중...")
            try:
                items = parse_statement(pdf_bytes, user, ANTHROPIC_KEY)
                st.write(f"→ {len(items)}건 추출 완료")
            except Exception as e:
                st.error(f"파싱 실패: {e}")
                st.stop()

            # ── 2차: 독립 검증 ──
            st.write("🔎 2차: 검증용 요약 정보 추출 중...")
            try:
                summary = verify_statement(pdf_bytes, ANTHROPIC_KEY)
                check = cross_check(items, summary)
                st.write(f"→ 검증 완료")
            except Exception as e:
                st.warning(f"검증 추출 실패 (파싱 결과는 유효): {e}")
                check = None

            status.update(label="분석 완료!", state="complete", expanded=False)

        # ── 검증 결과 표시 ──
        if check:
            st.subheader("📊 검증 결과")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("추출 건수", f"{check['추출건수']}건",
                          delta=None if check["건수_일치"]
                          else f"명세서: {check['명세서건수']}건",
                          delta_color="off")
            with col2:
                st.metric("추출 합계", f"{check['추출합계']:,}원",
                          delta=None if check["금액_일치"]
                          else f"차이: {check['금액차이']:+,}원",
                          delta_color="off")
            with col3:
                st.metric("이용 기간", check.get("기간", "-"))

            if check["검증통과"]:
                st.success("✅ 검증 통과 — 금액과 건수가 일치합니다.")
            else:
                st.warning(
                    "⚠️ 검증 불일치가 있습니다. 아래 테이블을 꼼꼼히 확인해주세요.\n\n"
                    + check["메시지"]
                )

        # ── 결과 테이블 (수정 가능) ──
        st.subheader("📋 추출 결과")
        st.caption("셀을 클릭하여 직접 수정할 수 있습니다. 수정 후 아래 저장 버튼을 누르세요.")

        df = pd.DataFrame(items)

        # 컬럼 순서 정리
        col_order = [
            "거래일", "가맹점명", "합계금액", "공급가액", "부가세",
            "계정과목", "매입세액공제", "증빙구분", "귀속월", "사용자",
        ]
        existing_cols = [c for c in col_order if c in df.columns]
        extra_cols = [c for c in df.columns if c not in col_order]
        df = df[existing_cols + extra_cols]

        # 계정과목, 매입세액공제 드롭다운 설정
        column_config = {
            "합계금액": st.column_config.NumberColumn("합계금액", format="%d"),
            "공급가액": st.column_config.NumberColumn("공급가액", format="%d"),
            "부가세": st.column_config.NumberColumn("부가세", format="%d"),
            "계정과목": st.column_config.SelectboxColumn(
                "계정과목",
                options=[
                    "소모품비", "복리후생비", "접대비", "차량유지비", "통신비",
                    "지급수수료", "광고선전비", "여비교통비", "도서인쇄비",
                    "교육훈련비", "구분필요",
                ],
            ),
            "매입세액공제": st.column_config.SelectboxColumn(
                "매입세액공제",
                options=["공제", "불공제", "확인필요"],
            ),
            "증빙구분": st.column_config.SelectboxColumn(
                "증빙구분",
                options=["사업자카드", "세금계산서", "현금영수증", "간이영수증"],
            ),
            "사용자": st.column_config.SelectboxColumn(
                "사용자",
                options=USERS,
            ),
        }

        edited_df = st.data_editor(
            df,
            column_config=column_config,
            use_container_width=True,
            num_rows="dynamic",  # 행 추가/삭제 가능
            key="result_editor",
        )

        # session_state에 저장 (버튼 클릭 시 사용)
        st.session_state["edited_items"] = edited_df.to_dict("records")

# ─── Notion 저장 버튼 ──
if "edited_items" in st.session_state and st.session_state["edited_items"]:
    st.divider()

    col_left, col_right = st.columns([3, 1])
    with col_left:
        dedup = st.checkbox("🔄 중복 건 자동 건너뛰기", value=True,
                            help="같은 날짜 + 가맹점 + 금액이 이미 장부에 있으면 건너뜁니다")
    with col_right:
        save_btn = st.button(
            "💾 Notion에 저장",
            type="primary",
            use_container_width=True,
        )

    if save_btn:
        items_to_save = st.session_state["edited_items"]

        with st.spinner(f"{len(items_to_save)}건을 Notion에 저장하는 중..."):
            result = upload_with_dedup(items_to_save, NOTION_KEY)

        # 결과 표시
        if result["fail"] == 0:
            msg = f"✅ 저장 완료: **{result['success']}건** 성공"
            if result.get("skipped", 0) > 0:
                msg += f" / {result['skipped']}건 중복 건너뜀"
            st.success(msg)
            st.balloons()
            # 저장 완료 후 상태 초기화
            del st.session_state["edited_items"]
        else:
            st.warning(
                f"⚠️ {result['success']}건 성공 / {result['fail']}건 실패"
                + (f" / {result.get('skipped', 0)}건 중복 건너뜀" if result.get("skipped") else "")
            )
            if result["errors"]:
                with st.expander("실패 상세 보기"):
                    for err in result["errors"]:
                        st.error(f"**{err['가맹점명']}**: {err['error']}")
