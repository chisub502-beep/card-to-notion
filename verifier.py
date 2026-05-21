"""
2차 AI 검증: 동일 PDF에서 요약 정보만 독립 추출하여 1차 결과와 교차검증
"""
import json
import base64
import anthropic
from config import CLAUDE_MODEL


def verify_statement(pdf_bytes: bytes, api_key: str) -> dict:
    """
    같은 PDF에서 총 이용금액, 총 거래건수, 이용기간만 별도로 추출한다.
    1차 파싱과 완전히 독립적인 프롬프트를 사용한다.

    Returns:
        {"총액": int, "건수": int, "기간_시작": str, "기간_종료": str}
    """
    client = anthropic.Anthropic(api_key=api_key)
    pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = """이 카드 명세서에서 아래 요약 정보만 추출하세요.

## 추출 항목
1. 총 이용금액: 명세서에 표시된 총 결제금액 합계 (정수, 콤마 제거)
2. 총 거래건수: 개별 거래 내역의 총 건수 (직접 세어서)
3. 이용기간 시작일: YYYY-MM-DD
4. 이용기간 종료일: YYYY-MM-DD

## 규칙
- 총 이용금액은 명세서 상단이나 하단에 있는 "이용금액 합계", "총 이용금액", "청구금액" 등을 참고
- 만약 명세서에 합계가 명시되어 있지 않으면, 개별 거래를 직접 더해서 계산
- 취소/환불 건은 차감하여 계산
- 연회비, 이자 등 부가 청구도 포함
- 거래건수는 개별 거래 행을 하나씩 세어서 (요약행 제외)

## 출력 형식
JSON만 출력, 다른 텍스트 없이:
{"총액": 1234000, "건수": 23, "기간_시작": "2026-01-01", "기간_종료": "2026-01-31"}"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
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
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    summary = json.loads(raw_text)

    # 타입 보정
    if isinstance(summary.get("총액"), str):
        summary["총액"] = int(summary["총액"].replace(",", ""))
    else:
        summary["총액"] = int(summary.get("총액", 0))

    summary["건수"] = int(summary.get("건수", 0))

    return summary


def cross_check(parsed_items: list[dict], summary: dict) -> dict:
    """
    1차 파싱 결과와 2차 검증 결과를 비교한다.

    Returns:
        {
            "금액_일치": bool,
            "건수_일치": bool,
            "추출합계": int,
            "명세서총액": int,
            "금액차이": int,
            "추출건수": int,
            "명세서건수": int,
            "검증통과": bool,
            "메시지": str,
        }
    """
    item_total = sum(item.get("합계금액", 0) for item in parsed_items)
    item_count = len(parsed_items)

    amount_match = item_total == summary["총액"]
    count_match = item_count == summary["건수"]

    # 금액 허용 오차: 10원 이내 (반올림 차이 허용)
    amount_close = abs(item_total - summary["총액"]) <= 10

    messages = []
    if amount_match or amount_close:
        messages.append(f"✅ 금액 일치: {item_total:,}원")
    else:
        diff = item_total - summary["총액"]
        sign = "+" if diff > 0 else ""
        messages.append(
            f"⚠️ 금액 불일치: 추출 {item_total:,}원 vs 명세서 {summary['총액']:,}원 (차이 {sign}{diff:,}원)"
        )

    if count_match:
        messages.append(f"✅ 건수 일치: {item_count}건")
    else:
        messages.append(
            f"⚠️ 건수 불일치: 추출 {item_count}건 vs 명세서 {summary['건수']}건"
        )

    passed = (amount_match or amount_close) and count_match

    return {
        "금액_일치": amount_match or amount_close,
        "건수_일치": count_match,
        "추출합계": item_total,
        "명세서총액": summary["총액"],
        "금액차이": item_total - summary["총액"],
        "추출건수": item_count,
        "명세서건수": summary["건수"],
        "검증통과": passed,
        "메시지": "\n".join(messages),
        "기간": f"{summary.get('기간_시작', '?')} ~ {summary.get('기간_종료', '?')}",
    }
