import os
import re
import time
import random
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

CACHE_SECONDS = 600
market_cache = {}
auction_cache = {}


class ChatRequest(BaseModel):
    message: Optional[str] = None
    msg: Optional[str] = None


FOODS = [
    "김치찌개", "된장찌개", "부대찌개", "순두부찌개", "청국장",
    "제육볶음", "불고기", "비빔밥", "돌솥비빔밥", "김밥",
    "라면", "떡볶이", "순대", "튀김", "오므라이스",
    "돈까스", "치즈돈까스", "카레", "우동", "냉모밀",
    "짜장면", "짬뽕", "볶음밥", "탕수육", "마라탕",
    "쌀국수", "팟타이", "분짜", "월남쌈", "파스타",
    "피자", "햄버거", "샌드위치", "샐러드", "스테이크",
    "초밥", "회덮밥", "연어덮밥", "가츠동", "규동",
    "텐동", "라멘", "야끼소바", "타코야끼", "오코노미야끼",
    "삼겹살", "목살", "돼지갈비", "소갈비", "곱창",
    "막창", "닭갈비", "찜닭", "닭볶음탕", "치킨",
    "족발", "보쌈", "감자탕", "뼈해장국", "설렁탕",
    "갈비탕", "순대국", "돼지국밥", "콩나물국밥", "육개장",
    "칼국수", "수제비", "잔치국수", "비빔국수", "냉면",
    "쫄면", "만두국", "떡국", "낙지볶음", "오징어볶음",
    "고등어구이", "삼치구이", "갈치조림", "아구찜", "해물찜",
    "샤브샤브", "월남쌈 샤브", "훠궈", "양꼬치", "케밥",
    "타코", "부리또", "브리또볼", "리조또", "그라탕",
    "토스트", "베이글", "브런치", "오므렛", "팬케이크",
    "닭강정", "김치볶음밥", "참치마요덮밥", "스팸마요덮밥", "컵밥"
]


MARKET_ITEMS = {
    "운명의 파괴석": 50010,
    "운명의 파괴석 결정": 50010,
    "운명의 수호석": 50010,
    "운명의 수호석 결정": 50010,
    "운명의 돌파석": 50010,
    "위대한 운명의 돌파석": 50010,
    "아비도스 융화 재료": 50010,
    "상급 아비도스 융화 재료": 50010,
    "명예의 파편 주머니(소)": 50010,
    "명예의 파편 주머니(중)": 50010,
    "명예의 파편 주머니(대)": 50010,
    "운명의 파편 주머니(소)": 50010,
    "운명의 파편 주머니(중)": 50010,
    "운명의 파편 주머니(대)": 50010,
    "용암의 숨결": 50010,
    "빙하의 숨결": 50010,
    "에스더의 기운": 50000,
}


ENGRAVING_NAMES = [
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


def command_food(kind: str):
    food = random.choice(FOODS)
    return f"🍽️ {kind} 추천\n\n오늘은 {food} 어때?"


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


def get_market_price(item_name: str, category_code: int):
    cache_key = f"{category_code}:{item_name}"
    now = time.time()

    if cache_key in market_cache:
        cached_time, cached_value = market_cache[cache_key]
        if now - cached_time < CACHE_SECONDS:
            return cached_value

    url = f"{LOA_BASE}/markets/items"

    payload = {
        "Sort": "CURRENT_MIN_PRICE",
        "CategoryCode": category_code,
        "ItemName": item_name,
        "PageNo": 1,
        "SortCondition": "ASC"
    }

    try:
        res = requests.post(url, headers=loa_headers(), json=payload, timeout=8)

        if res.status_code != 200:
            market_cache[cache_key] = (now, None)
            return None

        data = res.json()
        items = data.get("Items", [])

        if not items:
            market_cache[cache_key] = (now, None)
            return None

        target_normalized = normalize(item_name)

        exact_item = None
        candidates = []

        for item in items:
            name = item.get("Name", "")
            price = item.get("CurrentMinPrice")
            if price is None:
                continue

            name_normalized = normalize(name)

            if name_normalized == target_normalized:
                exact_item = item
                break

            if target_normalized in name_normalized or name_normalized in target_normalized:
                candidates.append(item)

        target = exact_item or (candidates[0] if candidates else items[0])
        price = target.get("CurrentMinPrice")

        market_cache[cache_key] = (now, price)
        return price

    except Exception:
        market_cache[cache_key] = (now, None)
        return None


def get_gem_lowest_price(item_name: str):
    cache_key = f"210000:{item_name}"
    now = time.time()

    if cache_key in auction_cache:
        cached_time, cached_value = auction_cache[cache_key]
        if now - cached_time < CACHE_SECONDS:
            return cached_value

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

    try:
        res = requests.post(url, headers=loa_headers(), json=payload, timeout=8)
        res.raise_for_status()

        data = res.json()
        items = data.get("Items", [])

        if not items:
            auction_cache[cache_key] = (now, None)
            return None

        first = items[0]
        auction_info = first.get("AuctionInfo", {})
        price = auction_info.get("BuyPrice")

        auction_cache[cache_key] = (now, price)
        return price

    except Exception:
        auction_cache[cache_key] = (now, None)
        return None


def get_market_prices():
    results = {}

    for name, category_code in MARKET_ITEMS.items():
        results[name] = get_market_price(name, category_code)

    return results


def get_engraving_prices():
    results = []

    for name in ENGRAVING_NAMES:
        item_name = f"유물 {name} 각인서"
        price = get_market_price(item_name, 40000)

        results.append({
            "name": name,
            "itemName": item_name,
            "price": price
        })

    return results


def command_help():
    return """🤖 진로아 명령어

.캐릭 캐릭터명 / /캐릭 캐릭터명
캐릭터 기본 정보를 조회합니다.

.보석 / /보석
주요 4티어 보석 최저 즉시구매가를 조회합니다.

.시세 / /시세
주요 재련 재료 시세를 조회합니다.

.유각 / /유각
주요 유물 각인서 시세를 조회합니다.

.경매 금액 / /경매 금액
4인/8인 경매 계산을 합니다.
예: .경매 165000

.점메추 / /점메추
점심 메뉴를 추천합니다.

.저메추 / /저메추
저녁 메뉴를 추천합니다.

.명령어 / /명령어
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


def command_auction(msg: str):
    raw = (
        msg.replace("/경매", "", 1)
           .replace(".경매", "", 1)
           .strip()
           .replace(",", "")
    )

    if not raw or not raw.isdigit():
        return "거래소 시세를 입력해주세요.\n예: .경매 165000 또는 /경매 165000"

    price = int(raw)

    receive = price * 0.95

    four_break = int(receive * 3 / 4)
    four_bid = int(four_break * 0.91)

    eight_break = int(receive * 7 / 8)
    eight_bid = int(eight_break * 0.91)

    return f"""⚖️ 경매 계산기

거래소 시세: {format_gold(price)}

👥 4인 레이드
입찰추천 : {format_gold(four_bid)}
손익분기 : {format_gold(four_break)}

👥 8인 레이드
입찰추천 : {format_gold(eight_bid)}
손익분기 : {format_gold(eight_break)}

거래소 수수료 5% 반영"""


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
        price = get_gem_lowest_price(name)
        results.append({
            "name": name,
            "price": price
        })

    return {
        "success": True,
        "items": results
    }


@app.post("/chat")
def chat(req: ChatRequest):
    msg = (req.message or req.msg or "").strip()

    if msg.startswith("."):
        msg = "/" + msg[1:]

    known_commands = [
        "/명령어", "/도움말", "/help",
        "/캐릭", "/보석", "/시세", "/유각",
        "/경매", "/점메추", "/저메추"
    ]

    if not any(msg == cmd or msg.startswith(cmd + " ") for cmd in known_commands):
        return {"reply": ""}

    if msg in ["/명령어", "/도움말", "/help"]:
        return {"reply": command_help()}

    if msg.startswith("/캐릭"):
        name = msg.replace("/캐릭", "", 1).strip()

        if not name:
            return {"reply": "캐릭터명을 입력해주세요.\n예: .캐릭 진황"}

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

    if msg.startswith("/경매"):
        return {"reply": command_auction(msg)}

    if msg == "/점메추":
        return {"reply": command_food("점심 메뉴")}

    if msg == "/저메추":
        return {"reply": command_food("저녁 메뉴")}

    return {"reply": ""}