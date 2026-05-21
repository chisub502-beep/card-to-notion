"""
1차 AI: 카드 명세서 PDF → 거래내역 JSON 추출
- PDF 비밀번호 자동 해제 (pikepdf)
- 페이지별 분할 처리로 999건까지 지원
- 카드사 자동 추출
"""
import json
import base64
from io import BytesIO

import anthropic
import pikepdf
import fitz  # PyMuPDF

from config import CLAUDE_MODEL


# ─── PDF 비밀번호 해제 ───
def decrypt_pdf(pdf_bytes: bytes, password: str = "") -> bytes:
    """
    비밀번호가 걸린 PDF를 해제하여 반환.
    password가 빈 문자열이면 비밀번호 없는 PDF로 간주.
    """
    try:
        pdf = pikepdf.open(BytesIO(pdf_bytes), password=password)
        output = BytesIO()
        pdf.save(output)
        pdf.close()
        return output.getvalue()
    except pikepdf.PasswordError:
        raise ValueError("PDF 비밀번호가 올바르지 않습니다. 다시 확인해주세요.")


# ─── PDF → 페이지별 이미지 변환 ───
def pdf_to_images(pdf_bytes: bytes, dpi: int = 300) -> list[bytes]:
    """PDF를 페이지별 PNG 이미지로 변환"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))

    doc.close()
    return images


# ─── 카드사 자동 감지 ───
def detect_card_company(pdf_bytes: bytes) -> str:
    """PDF 텍스트에서 카드사명을 감지"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    # 첫 2페이지만 확인 (카드사 로고/이름은 보통 앞쪽)
    text = ""
    for i in range(min(2, len(doc))):
        text += doc.load_page(i).get_text()
    doc.close()

    text = text.upper()
    card_companies = {
        "삼성카드": ["삼성카드", "SAMSUNG CARD"],
        "현대카드": ["현대카드", "HYUNDAI CARD"],
        "신한카드": ["신한카드", "SHINHAN CARD"],
        "KB국민카드": ["KB국민카드", "국민카드", "KB CARD", "KOOKMIN"],
        "롯데카드": ["롯데카드", "LOTTE CARD"],
        "하나카드": ["하나카드", "HANA CARD"],
        "우리카드": ["우리카드", "WOORI CARD"],
        "NH농협카드": ["NH농협", "NH카드", "농협카드"],
        "BC카드": ["BC카드", "BC CARD"],
        "IBK기업은행": ["IBK", "기업은행"],
    }

    for company, keywords in card_companies.items():
        for kw in keywords:
            if kw.upper() in text:
                return company

    return ""  # 감지 실패 시 빈 문자열


# ─── Claude Vision으로 거래내역 추출 ───
SYSTEM_PROMPT = """당신은 한국 사업자용 부가세 신고 전문 세무회계사입니다.
카드 명세서 이미지에서 개별 거래내역을 정확하게 추출하세요.

## 추출 규칙
1. 금액의 콤마(,)는 제거하고 정수로 변환
2. 할부 건은 총 결제금액(일시불 환산 금액) 기준
3. 취소/환불 건은 합계금액을 음수로 처리
4. 해외결제 건은 원화 환산 금액 사용
5. 연회비, 이자, 수수료 등 카드사 자체 청구 건도 포함
6. 명세서 요약/합계 행은 제외하고 개별 거래만 추출
7. 카드번호, 결제계좌 등 개인정보는 추출하지 않음
8. 매입세액공제는 계정과목이 "구분필요"이면 "확인필요", 아니면 "공제"로 설정

## 가맹점명 추출 주의사항
- "본인", "가족" 등 카드 소유자 구분 접두어는 제거하고 실제 가맹점명만 추출
- 예: "본인 스타벅스 강남점" → 가맹점명은 "스타벅스 강남점"
- 예: "본인 네이버페이" → 가맹점명은 "네이버페이"
- 가맹점명 옆의 카드번호 뒷자리(예: "1234"), 승인번호는 가맹점명에 포함하지 않음
- 글자가 불분명하면 맥락상 가장 그럴듯한 가맹점명으로 추론 (예: "스타벅○" → "스타벅스")
- 가맹점명을 정확히 읽을 수 없으면 최대한 가까운 텍스트 + "(확인필요)" 표시

## 계정과목 분류 기준
- 주유소, 세차 → 차량유지비
- 음식점, 카페 (사업 관련) → 복리후생비
- 접대성 음식점, 술자리 → 접대비
- 통신비, 인터넷 → 통신비
- 문구, 사무용품 → 소모품비
- 택시, 교통, 주차 → 여비교통비
- 수수료, 배달비 → 지급수수료
- 광고, 홍보 → 광고선전비
- 도서, 인쇄 → 도서인쇄비
- 교육, 강의 → 교육훈련비
- 판단 어려운 것 → 구분필요

## 반드시 무시할 항목 (절대 거래내역으로 추출하지 마세요)
- 총청구금액, 총결제금액, 청구금액 합계, 결제대금, 이번 달 결제금액 등 합계/요약 행
- "일시불 합계", "할부 합계", "해외이용 합계" 등 소계 행
- "전월 미결제", "이월금액", "선결제", "선입금" 등 잔액 관련 행
- "결제일", "출금예정", "자동이체" 등 결제 안내 행
- 포인트/마일리지 적립/사용 안내
- 이용한도, 잔여한도 정보
- 금융서비스/대출/리볼빙 안내
- 연체이자, 지연배상금 안내
- 가맹점명 없이 금액만 있는 요약 행

핵심: 실제 "가맹점에서 결제한 개별 거래"만 추출하세요. 카드사가 표시하는 합산/요약/안내 행은 모두 제외합니다.

## 출력 형식
반드시 JSON 배열만 반환하세요. 다른 텍스트, 설명, 마크다운 코드블록(```)을 포함하지 마세요.
거래내역이 없는 페이지라면 빈 배열 []을 반환하세요."""


def call_claude_vision(
    images: list[bytes],
    api_key: str,
    user_name: str,
    card_company: str = "",
) -> list[dict]:
    """
    Claude API에 이미지를 페이지 배치로 보내고 거래내역 JSON을 받음.
    배치 크기: 3페이지씩 (컨텍스트 제한 고려)
    """
    client = anthropic.Anthropic(api_key=api_key)
    batch_size = 3
    all_transactions = []

    for batch_start in range(0, len(images), batch_size):
        batch_images = images[batch_start : batch_start + batch_size]

        content = []
        for img_bytes in batch_images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                }
            )

        # 사용자/카드사 정보를 프롬프트에 포함
        extra_info = f'\n사용자: "{user_name}"'
        if card_company:
            extra_info += f'\n카드사: "{card_company}"'

        example = {
            "거래일": "2026-01-15",
            "가맹점명": "GS칼텍스 강남주유소",
            "합계금액": 52000,
            "공급가액": 47273,
            "부가세": 4727,
            "귀속월": "2026-01",
            "증빙구분": "사업자카드",
            "계정과목": "차량유지비",
            "매입세액공제": "공제",
            "카드번호뒷자리": "1234",
            "사용자": user_name,
        }

        content.append(
            {
                "type": "text",
                "text": (
                    f"위 이미지에서 카드 거래내역을 추출해주세요."
                    f"{extra_info}\n\n"
                    f"각 거래는 아래 형식의 JSON 객체로:\n"
                    f"{json.dumps(example, ensure_ascii=False)}\n\n"
                    f"추가 지시:\n"
                    f"- 카드번호뒷자리: 명세서에 표시된 카드번호 끝 4자리 숫자 (예: 1234). 보이지 않으면 빈 문자열.\n"
                    f"- 카드사: 명세서 발행 카드사명 (예: 삼성카드, 현대카드, 신한카드 등). 보이지 않으면 빈 문자열.\n"
                    f"해당 페이지의 모든 거래를 빠짐없이 추출하세요."
                ),
            }
        )

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16384,  # ← 충분한 토큰 확보 (기존 4096/8192 → 16384)
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )

        response_text = response.content[0].text.strip()

        # 마크다운 코드블록 제거
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

        try:
            transactions = json.loads(response_text)
            if isinstance(transactions, list):
                all_transactions.extend(transactions)
        except json.JSONDecodeError:
            continue

    return all_transactions


# ─── 메인 파싱 함수 ───
def parse_statement(
    pdf_bytes: bytes,
    user_name: str,
    api_key: str,
    password: str = "",
) -> dict:
    """
    메인 진입점.
    PDF (암호화 포함) → 이미지 변환 → Claude Vision → 거래내역 리스트

    Returns:
        {"items": list[dict], "card_company": str}
    """
    # 1. 비밀번호 해제 (필요 시)
    if password:
        pdf_bytes = decrypt_pdf(pdf_bytes, password)
    else:
        # 비밀번호 없이 열어보고, 실패하면 예외 전달
        try:
            decrypt_pdf(pdf_bytes, "")
        except Exception:
            raise ValueError(
                "이 PDF는 비밀번호가 설정되어 있습니다. "
                "비밀번호를 입력해주세요 (보통 생년월일 6자리)."
            )

    # 2. 카드사 자동 감지
    card_company = detect_card_company(pdf_bytes)

    # 3. PDF → 페이지별 이미지 변환
    images = pdf_to_images(pdf_bytes, dpi=300)
    if not images:
        return {"items": [], "card_company": card_company}

    # 4. Claude Vision으로 거래내역 추출
    items = call_claude_vision(images, api_key, user_name, card_company)

    # 5. 후처리: 필수 필드 보정 + 금액 정수 변환
    required_fields = [
        "거래일", "가맹점명", "합계금액", "공급가액",
        "부가세", "귀속월", "증빙구분", "계정과목",
        "매입세액공제", "사용자",
    ]
    for item in items:
        for field in required_fields:
            if field not in item:
                item[field] = "" if field != "합계금액" else 0

        # 사용자 강제 세팅
        item["사용자"] = user_name

        # 카드사: 자동감지 > AI추출 > 빈값 순으로 우선
        if card_company:
            item["카드사"] = card_company
        elif not item.get("카드사"):
            item["카드사"] = ""

        # 카드번호뒷자리: 숫자 4자리만 남기기
        raw_card_num = str(item.get("카드번호뒷자리", "")).strip()
        digits = "".join(c for c in raw_card_num if c.isdigit())
        item["카드번호뒷자리"] = digits[-4:] if len(digits) >= 4 else digits

        # 분류상태 세팅
        item["분류상태"] = "AI자동분류"

        # 금액 필드 정수 변환
        for money_field in ["합계금액", "공급가액", "부가세"]:
            val = item.get(money_field, 0)
            if isinstance(val, str):
                val = val.replace(",", "").replace(" ", "")
                try:
                    val = int(float(val))
                except ValueError:
                    val = 0
            item[money_field] = int(val)

    return {"items": items, "card_company": card_company}
