"""
2차 AI 검증: 동일 PDF에서 요약 정보만 독립 추출하여 1차 결과와 교차검증
- 1차(pdf_parser)와 완전히 독립적인 프롬프트 사용
- PDF를 이미지로 변환하여 처리 (암호 해제된 PDF 전제)
"""
import json
import base64
from io import BytesIO

import anthropic
import fitz  # PyMuPDF

from config import CLAUDE_MODEL


def verify_statement(pdf_bytes: bytes, api_key: str) -> dict:
    """
    같은 PDF에서 총 이용금액, 총 거래건수, 이용기간만 별도로 추출한다.
    1차 파싱과 완전히 독립적인 프롬프트를 사용한다.

    Args:
        pdf_bytes: 비밀번호가 이미 해제된 PDF 바이트
        api_key: Anthropic API 키

    Returns:
        {"총액": int, "건수": int, "기간_시작": str, "기간_종료": str}
    """
    client = anthropic.Anthropic(api_key=api_key)

    # PDF → 이미지 변환 (첫 2페이지 + 마지막 페이지만 — 요약 정보 위치)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_to_check = set()
    pages_to_check.add(0)  # 첫 페이지
    if len(doc) > 1:
        pages_to_check.add(1)  # 두 번째 페이지
    if len(doc) > 2:
        pages_to_check.add(len(doc) - 1)  # 마지막 페이지

    content = []
    zoom = 300 / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in sorted(pages_to_check):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=matrix)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        })
    doc.close()

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

    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = response.content[0].text.strip()

    # 마크다운 코드블록 제거
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    summary = json.loads(raw_text)

    # 타입 보정
    if isinstance(summary.get("총액"), str):
        summary["총액"] = int(summary["총액"].replace(",", "").replace(" ", ""))
    else:
        summary["총액"] = int(summary.get("총액", 0))

    summary["건수"] = int(summary.get("건수", 0))

    return summary


def cross_check(parsed_items: list, summary: dict) -> dict:
    """
    1차 파싱 결과와 2차 검증 결과를 비교한다.

    Args:
        parsed_items: 1차 파싱 거래내역 리스트 (list[dict])
        summary: 2차 검증 요약 ({"총액": int, "건수": int, ...})

    Returns:
        {
            "금액_일치": bool,
            "건수_일치": bool,
            "추출합계": int,
            "추출건수": int,
            "명세서총액": int,
            "명세서건수": int,
            "차이": int,
            "건수차이": int,
        }
    """
    try:
        # 1차 결과 합산
        item_total = 0
        for item in parsed_items:
            val = item.get("합계금액", 0)
            if isinstance(val, str):
                val = val.replace(",", "").replace(" ", "")
                try:
                    val = int(float(val))
                except ValueError:
                    val = 0
            item_total += int(val)

        item_count = len(parsed_items)

        # 2차 검증 결과
        stmt_total = int(summary.get("총액", 0))
        stmt_count = int(summary.get("건수", 0))

        return {
            "금액_일치": item_total == stmt_total,
            "건수_일치": item_count == stmt_count,
            "추출합계": item_total,
            "추출건수": item_count,
            "명세서총액": stmt_total,
            "명세서건수": stmt_count,
            "차이": item_total - stmt_total,
            "건수차이": item_count - stmt_count,
        }

    except Exception:
        # 어떤 오류가 나도 기본값 반환 (app.py에서 KeyError 방지)
        return {
            "금액_일치": False,
            "건수_일치": False,
            "추출합계": 0,
            "추출건수": 0,
            "명세서총액": 0,
            "명세서건수": 0,
            "차이": 0,
            "건수차이": 0,
        }
