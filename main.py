import os
import re
import time
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI()

LOA_API_KEY = os.getenv("LOA_API_KEY")
LOA_BASE = "https://developer-lostark.game.onstove.com"

CACHE_SECONDS = 60
market_cache = {}
market_options_cache = {"time": 0, "data": None}


class ChatRequest(BaseModel):
    message: Optional[str] = None
    msg: Optional[str] = None


def loa_headers():
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"bearer {LOA_API_KEY}",
    }


def format_gold(value):
    if value is None:
        return "-"
    return f"{int(value):,}G"


def normalize(text):
    return re.sub(r"\s+", "", str(text or "")).strip()


def get_character_profile(name: str):
    url = f"{LOA_BASE}/armories/characters/{name}/profiles"
    res = requests.get(url, headers=loa_headers(), timeout=10)

    if res.status_code == 404:
        return None

    res.raise_for_status()
    return res.json()


def get_combat_power_from_html(name: str):
    url = f"https://lostark.game.onstove.com/Profile/Character/{name}"

    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        item_blocks = soup.select(".level-info2__item")

        for block in item_blocks:
            label = block.get_text(" ", strip=True)

            if "전투력" in label:
                spans = block.select("span")
                if len(spans) >= 2:
                    value_text = spans[1].get_text("", strip=True).replace(",", "")
                    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value_text)

                    if match:
                        num = match.group(1)
                        if "." in num:
                            integer, decimal = num.split(".", 1)
                            return f"{int(integer):,}.{decimal}"
                        return f"{int(num):,}"

        return None

    except Exception:
        return None


def get_gem_lowest_price(item_name: str):
    url = f"{LOA_BASE}/auctions/items"

    payload = {
        "ItemLevelMin": 0,
        "ItemLevelMax": 0,
        "ItemGradeQuality": None,
        "SkillOptions": [],
        "EtcOptions": [],
        "Sort": "BUY_PRICE",
        "CategoryCode": 210000,
        "CharacterClass": "",
        "ItemTier": 4,
        "ItemGrade": "",
        "ItemName": item_name,
        "PageNo": 1,
        "SortCondition": "ASC"
    }

    res = requests.post(url, headers=loa_headers(), json=payload, timeout=10)
    res.raise_for_status()

    data = res.json()
    items = data.get("Items", [])

    if not items:
        return None

    first = items[0]
    auction_info = first.get("AuctionInfo", {})

    return {
        "name": first.get("Name", item_name),
        "price": auction_info.get("BuyPrice"),
        "grade": first.get("Grade"),
        "icon": first.get("Icon")
    }


def get_market_options():
    now = time.time()

    if market_options_cache["data"] and now - market_options_cache["time"] < 3600:
        return market_options_cache["data"]

    try:
        res = requests.get(f"{LOA_BASE}/markets/options", headers=loa_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()

        market_options_cache["time"] = now
        market_options_cache["data"] = data

        return data

    except Exception as e:
        print("[MARKET OPTIONS ERROR]", str(e), flush=True)
        return None


def extract_market_categories():
    options = get_market_options()
    categories = []

    if not options:
        return categories

    raw_categories = []

    if isinstance(options, dict):
        raw_categories = options.get("Categories", [])
    elif isinstance(options, list):
        for block in options:
            if isinstance(block, dict) and "Categories" in block:
                raw_categories.extend(block.get("Categories", []))
            elif isinstance(block, dict) and "Code" in block:
                raw_categories.append(block)

    def walk(category, parent_name=""):
        if not isinstance(category, dict):
            return

        code = category.get("Code")
        name = category.get("CodeName", "")
        full_name = f"{parent_name} {name}".strip()

        if code:
            categories.append({
                "code": code,
                "name": full_name
            })

        for sub in category.get("Subs", []) or []:
            walk(sub, full_name)

    for category in raw_categories:
        walk(category)

    return categories


def find_market_category_codes(keywords=None):
    categories = extract_market_categories()
    keywords = keywords or []

    if not categories:
        return []

    if not keywords:
        return [x["code"] for x in categories]

    matched = []

    for category in categories:
        category_name = normalize(category["name"])

        for keyword in keywords:
            if normalize(keyword) in category_name:
                matched.append(category["code"])
                break

    return list(dict.fromkeys(matched))


def get_market_price(item_name: str, keywords=None):
    cache_key = f"{item_name}:{','.join(keywords or [])}"
    now = time.time()

    if cache_key in market_cache:
        cached_time, cached_value = market_cache[cache_key]
        if now - cached_time < CACHE_SECONDS:
            return cached_value

    preferred_codes = find_market_category_codes(keywords)

    fallback_codes = [
        50000,
        50010,
        50020,
        50030,
        50040,
        40000,
        40010,
        40020,
        30000,
        30010,
        60000,
        70000,
        90000,
    ]

    all_codes = find_market_category_codes([])

    category_codes = []
    category_codes.extend(preferred_codes)
    category_codes.extend(fallback_codes)
    category_codes.extend(all_codes)

    category_codes = list(dict.fromkeys([x for x in category_codes if x]))

    url = f"{LOA_BASE}/markets/items"
    target_normalized = normalize(item_name)
    found_candidates = []

    for category_code in category_codes:
        payload = {
            "Sort": "CURRENT_MIN_PRICE",
            "CategoryCode": category_code,
            "ItemName": item_name,
            "PageNo": 1,
            "SortCondition": "ASC"
        }

        try:
            res = requests.post(url, headers=loa_headers(), json=payload, timeout=8)

            print(
                "[MARKET SEARCH]",
                item_name,
                "category:",
                category_code,
                "status:",
                res.status_code,
                flush=True
            )

            if res.status_code != 200:
                continue

            data = res.json()
            items = data.get("Items", [])

            print(
                "[MARKET RESULT]",
                item_name,
                "category:",
                category_code,
                "count:",
                len(items),
                flush=True
            )

            if not items:
                continue

            for item in items:
                name = item.get("Name", "")
                price = item.get("CurrentMinPrice")

                if price is None:
                    continue

                name_normalized = normalize(name)

                if name_normalized == target_normalized:
                    market_cache[cache_key] = (now, price)
                    return price

                if target_normalized in name_normalized or name_normalized in target_normalized:
                    found_candidates.append(price)

        except Exception as e:
            print("[MARKET ERROR]", item_name, "category:", category_code, str(e), flush=True)
            continue

    if found_candidates:
        price = min(found_candidates)
        market_cache[cache_key] = (now, price)
        return price

    market_cache[cache_key] = (now, None)
    return None


def get_market_prices():
    material_items = [
        "운명의 파괴석",
        "운명의 파괴석 결정",
        "운명의 수호석",
        "운명의 수호석 결정",
        "운명의 돌파석",
        "위대한 운명의 돌파석",
        "아비도스 융화 재료",
        "상급 아비도스 융화 재료",
        "명예의 파편 주머니(소)",
        "명예의 파편 주머니(중)",
        "명예의 파편 주머니(대)",
        "운명의 파편 주머니(소)",
        "운명의 파편 주머니(중)",
        "운명의 파편 주머니(대)",
        "용암의 숨결",
        "빙하의 숨결",
        "에스더의 기운",
    ]

    results = {}

    for name in material_items:
        results[name] = get_market_price(
            name,
            ["재련", "강화", "재료", "파편", "돌파", "숨결", "융화"]
        )

    return results


def get_engraving_prices():
    engraving_names = [
        "원한",
        "아드레날린",
        "돌격대장",
        "예리한 둔기",
        "질량 증가",
        "저주받은 인형",
        "기습의 대가",
        "각성",
        "타격의 대가",
        "전문의",
    ]

    results = []

    for name in engraving_names:
        item_name = f"유물 {name} 각인서"
        price = get_market_price(item_name, ["각인서", "각인"])

        results.append({
            "name": name,
            "itemName": item_name,
            "price": price
        })

    return results


def command_help():
    return """🤖 진로아 명령어

/캐릭 캐릭터명
캐릭터 기본 정보를 조회합니다.

/보석
주요 4티어 보석 최저 즉시구매가를 조회합니다.

/시세
주요 재련 재료 시세를 조회합니다.

/유각
주요 유물 각인서 시세를 조회합니다.

/명령어
사용 가능한 명령어를 확인합니다."""


def command_market():
    prices = get_market_prices()

    return f"""📦 주요 재료 시세

운명의 파괴석: {format_gold(prices.get("운명의 파괴석"))}
운명의 파괴석 결정: {format_gold(prices.get("운명의 파괴석 결정"))}
운명의 수호석: {format_gold(prices.get("운명의 수호석"))}
운명의 수호석 결정: {format_gold(prices.get("운명의 수호석 결정"))}
운명의 돌파석: {format_gold(prices.get("운명의 돌파석"))}
위대한 운명의 돌파석: {format_gold(prices.get("위대한 운명의 돌파석"))}
아비도스 융화 재료: {format_gold(prices.get("아비도스 융화 재료"))}
상급 아비도스 융화 재료: {format_gold(prices.get("상급 아비도스 융화 재료"))}

명예의 파편: {format_gold(prices.get("명예의 파편 주머니(소)"))}(소) / {format_gold(prices.get("명예의 파편 주머니(중)"))}(중) / {format_gold(prices.get("명예의 파편 주머니(대)"))}(대)
운명의 파편: {format_gold(prices.get("운명의 파편 주머니(소)"))}(소) / {format_gold(prices.get("운명의 파편 주머니(중)"))}(중) / {format_gold(prices.get("운명의 파편 주머니(대)"))}(대)

용암의 숨결: {format_gold(prices.get("용암의 숨결"))}
빙하의 숨결: {format_gold(prices.get("빙하의 숨결"))}
에스더의 기운: {format_gold(prices.get("에스더의 기운"))}"""


def command_engraving():
    items = get_engraving_prices()

    lines = ["📘 유각 시세", ""]

    for item in items:
        lines.append(f"{item['name']}: {format_gold(item['price'])}")

    return "\n".join(lines)


@app.get("/")
def home():
    return {"status": "진로아 FastAPI 서버 실행 중"}


@app.get("/character/{name}")
def character(name: str):
    profile = get_character_profile(name)

    if not profile:
        return {
            "success": False,
            "message": f"'{name}' 캐릭터 정보를 찾지 못했어요."
        }

    combat_power = get_combat_power_from_html(name)

    return {
        "success": True,
        "name": profile.get("CharacterName"),
        "server": profile.get("ServerName"),
        "job": profile.get("CharacterClassName"),
        "level": profile.get("CharacterLevel"),
        "itemLevel": profile.get("ItemAvgLevel"),
        "expeditionLevel": profile.get("ExpeditionLevel"),
        "guild": profile.get("GuildName") or "-",
        "title": profile.get("Title") or "-",
        "image": profile.get("CharacterImage"),
        "combatPower": combat_power or "-",
    }


@app.get("/gems")
def gems():
    gem_names = [
        "10레벨 겁화의 보석",
        "10레벨 작열의 보석",
        "9레벨 겁화의 보석",
        "9레벨 작열의 보석",
        "8레벨 겁화의 보석",
        "8레벨 작열의 보석",
    ]

    results = []

    for name in gem_names:
        try:
            data = get_gem_lowest_price(name)
            results.append({
                "name": name,
                "price": data["price"] if data else None
            })
        except Exception:
            results.append({
                "name": name,
                "price": None
            })

    return {
        "success": True,
        "items": results
    }


@app.post("/chat")
def chat(req: ChatRequest):
    msg = (req.message or req.msg or "").strip()

    if msg in ["/명령어", "/도움말", "/help"]:
        return {"reply": command_help()}

    if msg.startswith("/캐릭"):
        name = msg.replace("/캐릭", "", 1).strip()

        if not name:
            return {"reply": "캐릭터명을 입력해주세요.\n예: /캐릭 진황"}

        data = character(name)

        if not data["success"]:
            return {"reply": data["message"]}

        reply = f"""[{data["name"]}]
서버: {data["server"]}
직업: {data["job"]}
아이템레벨: {data["itemLevel"]}
전투레벨: {data["level"]}
원정대레벨: {data["expeditionLevel"]}
길드: {data["guild"]}
전투력: {data["combatPower"]}"""

        return {"reply": reply}

    if msg == "/보석":
        data = gems()

        lines = ["💎 보석 최저 즉시구매가"]

        for item in data["items"]:
            lines.append(f"{item['name']}: {format_gold(item['price'])}")

        return {"reply": "\n".join(lines)}

    if msg == "/시세":
        return {"reply": command_market()}

    if msg == "/유각":
        return {"reply": command_engraving()}

    return {"reply": command_help()}