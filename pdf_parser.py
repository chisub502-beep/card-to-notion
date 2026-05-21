"""
1차 AI 파싱: 카드 명세서 PDF → 거래내역 JSON 추출
PDF를 Claude에 직접 전송하여 레이아웃 기반으로 파싱
"""
import json
import base64
import anthropic
from config import CLAUDE_MODEL, ACCOUNT_RULES, TAX_EXEMPT_RULES


def parse_statement(pdf_bytes: bytes, user_name: str, api_key: str) -> list[dict]:
    """
    카드 명세서 PDF를 Claude에 보내서 거래 건별 JSON을 추출한다.

    Args:
        pdf_bytes: PDF 파일의 바이너리 데이터
        user_name: 사용자 이름 (한치섭/한정주/한치흥)
        api_key: Anthropic API 키

    Returns:
        거래내역 딕셔너리 리스트
    """
    client = anthropic.Anthropic(api_key=api_key)
    pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = f"""이 카드사용 명세서 PDF에서 **모든 개별 거래 내역**을 추출하여 JSON 배열로 반환하세요.

## 추출 필드 (모든 필드 필수)
- 거래일: YYYY-MM-DD 형식 (연도가 없으면 명세서의 이용기간에서 추정)
- 가맹점명: 상호명 전체 (줄바꿈으로 잘려도 하나로 합쳐서)
- 합계금액: 결제 총액 (정수, 콤마 제거)
- 공급가액: 아래 면세 규칙에 해당하면 합계금액과 동일, 아닌 경우 round(합계금액 / 1.1) (정수)
- 부가세: 합계금액 - 공급가액 (정수)
- 귀속월: 거래일 기준 YYYY-MM 형식
- 증빙구분: "사업자카드"
- 계정과목: 아래 분류 기준 참고
- 매입세액공제: "확인필요"
- 사용자: "{user_name}"

## 계정과목 분류 기준
{ACCOUNT_RULES}

## 면세 거래 규칙
{TAX_EXEMPT_RULES}

## 중요 규칙
1. 금액의 콤마(,)는 제거하고 정수로 변환
2. 할부 건은 총 결제금액(일시불 환산 금액) 기준
3. 취소/환불 건은 합계금액을 음수로 처리
4. 해외결제 건은 원화 환산 금액 사용
5. 연회비, 이자, 수수료 등 카드사 자체 청구 건도 포함
6. 명세서 요약/합계 행은 제외하고 개별 거래만 추출
7. 카드번호, 결제계좌 등 개인정보는 추출하지 않음

## 출력 형식
JSON 배열만 출력하세요. 다른 텍스트, 설명, 마크다운 백틱 없이 순수 JSON만.
예시:
[
  {{
    "거래일": "2026-01-15",
    "가맹점명": "GS칼텍스 강남주유소",
    "합계금액": 52000,
    "공급가액": 47273,
    "부가세": 4727,
    "귀속월": "2026-01",
    "증빙구분": "사업자카드",
    "계정과목": "차량유지비",
    "매입세액공제": "확인필요",
    "사용자": "{user_name}"
  }}
]"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    raw_text = response.content[0].text.strip()

    # JSON 파싱 (백틱 감싸기 제거 대비)
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]  # 첫 줄 제거
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    items = json.loads(raw_text)

    # 기본 검증: 필수 필드 존재 여부
    required_fields = [
        "거래일", "가맹점명", "합계금액", "공급가액",
        "부가세", "귀속월", "증빙구분", "계정과목",
        "매입세액공제", "사용자",
    ]
    for item in items:
        for field in required_fields:
            if field not in item:
                item[field] = "" if field != "합계금액" else 0

        # 금액 필드 정수 변환 보정
        for money_field in ["합계금액", "공급가액", "부가세"]:
            val = item.get(money_field, 0)
            if isinstance(val, str):
                val = val.replace(",", "").replace(" ", "")
                try:
                    val = int(float(val))
                except ValueError:
                    val = 0
            item[money_field] = int(val)

    return items
