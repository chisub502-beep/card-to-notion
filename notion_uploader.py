"""
Notion API 연동: 파싱된 거래내역을 부가세 장부 DB에 기입
"""
import requests
from config import NOTION_DATABASE_ID, NOTION_API_VERSION


def create_entry(item: dict, notion_key: str) -> dict:
    """
    거래내역 1건을 Notion DB에 추가한다.

    Args:
        item: 거래내역 딕셔너리
        notion_key: Notion Integration 토큰

    Returns:
        {"success": bool, "가맹점명": str, "error": str or None}
    """
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }

    # Notion 페이지 properties 구성
    properties = {
        "가맹점명": {"title": [{"text": {"content": str(item.get("가맹점명", ""))}}]},
        "합계금액": {"number": int(item.get("합계금액", 0))},
        "공급가액": {"number": int(item.get("공급가액", 0))},
        "부가세": {"number": int(item.get("부가세", 0))},
        "분류상태": {"select": {"name": "AI자동분류"}},
    }

    # 거래일 (YYYY-MM-DD)
    if item.get("거래일"):
        properties["거래일"] = {"date": {"start": item["거래일"]}}

    # Select 타입 필드들
    select_fields = ["귀속월", "증빙구분", "계정과목", "매입세액공제", "사용자"]
    for field in select_fields:
        val = item.get(field)
        if val and str(val).strip():
            properties[field] = {"select": {"name": str(val).strip()}}

    # 적요 (있으면 추가)
    if item.get("적요"):
        properties["적요"] = {
            "rich_text": [{"text": {"content": str(item["적요"])}}]
        }

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return {
                "success": True,
                "가맹점명": item.get("가맹점명", ""),
                "error": None,
            }
        else:
            error_body = resp.json() if resp.text else {}
            return {
                "success": False,
                "가맹점명": item.get("가맹점명", ""),
                "error": f"HTTP {resp.status_code}: {error_body.get('message', resp.text[:200])}",
            }
    except Exception as e:
        return {
            "success": False,
            "가맹점명": item.get("가맹점명", ""),
            "error": str(e),
        }


def upload_all(items: list[dict], notion_key: str) -> dict:
    """
    거래내역 전체를 Notion DB에 업로드한다.

    Returns:
        {"success": int, "fail": int, "errors": list[dict]}
    """
    success_count = 0
    fail_count = 0
    errors = []

    for item in items:
        result = create_entry(item, notion_key)
        if result["success"]:
            success_count += 1
        else:
            fail_count += 1
            errors.append(result)

    return {
        "success": success_count,
        "fail": fail_count,
        "total": len(items),
        "errors": errors,
    }


def check_duplicate(item: dict, notion_key: str) -> bool:
    """
    거래일 + 가맹점명 + 합계금액 조합으로 중복 여부를 확인한다.
    (Notion API filter 사용)

    Returns:
        True = 이미 존재 (중복), False = 신규
    """
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }

    payload = {
        "filter": {
            "and": [
                {
                    "property": "거래일",
                    "date": {"equals": item.get("거래일", "")},
                },
                {
                    "property": "합계금액",
                    "number": {"equals": int(item.get("합계금액", 0))},
                },
                {
                    "property": "가맹점명",
                    "title": {"equals": str(item.get("가맹점명", ""))},
                },
                {
                    "property": "사용자",
                    "select": {"equals": str(item.get("사용자", ""))},
                },
            ]
        },
        "page_size": 1,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return len(data.get("results", [])) > 0
        return False
    except Exception:
        return False


def upload_with_dedup(items: list[dict], notion_key: str) -> dict:
    """
    중복 체크 후 신규 건만 업로드한다.

    Returns:
        {"success": int, "fail": int, "skipped": int, "errors": list}
    """
    success_count = 0
    fail_count = 0
    skipped_count = 0
    errors = []

    for item in items:
        # 중복 체크
        if check_duplicate(item, notion_key):
            skipped_count += 1
            continue

        result = create_entry(item, notion_key)
        if result["success"]:
            success_count += 1
        else:
            fail_count += 1
            errors.append(result)

    return {
        "success": success_count,
        "fail": fail_count,
        "skipped": skipped_count,
        "total": len(items),
        "errors": errors,
    }
