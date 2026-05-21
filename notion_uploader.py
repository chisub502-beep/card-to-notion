"""
Notion API 연동: 파싱된 거래내역을 부가세 장부 DB에 기입
- 카드사 컬럼 지원 추가
- 중복 체크 포함
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
        "가맹점명": {
            "title": [{"text": {"content": str(item.get("가맹점명", ""))}}]
        },
        "합계금액": {"number": int(item.get("합계금액", 0))},
        "공급가액": {"number": int(item.get("공급가액", 0))},
        "부가세": {"number": int(item.get("부가세", 0))},
        "분류상태": {"select": {"name": item.get("분류상태", "AI자동분류")}},
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

    # ★ 카드사 (추가됨)
    if item.get("카드사") and str(item["카드사"]).strip():
        properties["카드사"] = {"select": {"name": str(item["카드사"]).strip()}}

    # 적요 (있으면 추가)
    if item.get("적요"):
        properties["적요"] = {
            "rich_text": [{"text": {"content": str(item["적요"])[:2000]}}]
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
                "error": f"HTTP {resp.status_code}: "
                f"{error_body.get('message', resp.text[:200])}",
            }
    except Exception as e:
        return {
            "success": False,
            "가맹점명": item.get("가맹점명", ""),
            "error": str(e),
        }


def check_duplicate(item: dict, notion_key: str) -> bool:
    """
    같은 거래일 + 가맹점명 + 합계금액 조합이 이미 DB에 있는지 확인.
    있으면 True (중복), 없으면 False.
    """
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }

    # 필터: 거래일 + 합계금액으로 중복 체크
    filter_conditions = {
        "and": [
            {
                "property": "합계금액",
                "number": {"equals": int(item.get("합계금액", 0))},
            },
        ]
    }

    # 거래일이 있으면 필터에 추가
    if item.get("거래일"):
        filter_conditions["and"].append(
            {
                "property": "거래일",
                "date": {"equals": item["거래일"]},
            }
        )

    payload = {"filter": filter_conditions, "page_size": 5}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            # 가맹점명까지 매칭 확인
            for page in results:
                title_prop = page.get("properties", {}).get("가맹점명", {})
                title_arr = title_prop.get("title", [])
                if title_arr:
                    existing_name = title_arr[0].get("text", {}).get("content", "")
                    if existing_name == str(item.get("가맹점명", "")):
                        return True  # 중복
        return False
    except Exception:
        return False  # 오류 시 중복 아닌 것으로 처리 (저장 진행)


def upload_all(items: list, notion_key: str) -> dict:
    """
    거래내역 전체를 Notion DB에 업로드한다.
    중복 체크 후 새 건만 추가.

    Args:
        items: 거래내역 딕셔너리 리스트
        notion_key: Notion Integration 토큰

    Returns:
        {"success": int, "fail": int, "skipped": int, "total": int, "errors": list}
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
