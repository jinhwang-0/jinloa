import os
import re
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

LOA_API_KEY = os.getenv("LOA_API_KEY")
LOA_BASE = "https://developer-lostark.game.onstove.com"


class ChatRequest(BaseModel):
    message: str


def loa_headers():
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"bearer {LOA_API_KEY}",
    }


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


def format_gold(value):
    if value is None:
        return "-"
    return f"{int(value):,}G"


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
    msg = req.message.strip()

    if msg.startswith("/캐릭"):
        name = msg.replace("/캐릭", "").strip()

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

        return {
            "reply": "\n".join(lines)
        }

    return {
        "reply": "지원하지 않는 명령어예요.\n사용 가능:\n/캐릭 캐릭터명\n/보석"
    }