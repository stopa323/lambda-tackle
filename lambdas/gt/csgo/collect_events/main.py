import aiohttp
import asyncio
import datetime
import re

from boto3.dynamodb.conditions import Attr
from bs4 import BeautifulSoup
from hashlib import sha256
from os import environ
from uuid import uuid4


DYNAMO_TABLE_NAME = environ.get("DYNAMO_TABLE_NAME")

if DYNAMO_TABLE_NAME:
    import boto3

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(DYNAMO_TABLE_NAME)

URL = "https://en.game-tournaments.com/csgo/matches"


async def fetch_page() -> str:
    print(f"Fetching CS:GO event list page ({URL})")
    async with aiohttp.ClientSession() as session:
        response = await session.request("GET", url=URL)
        page_html = await response.text()
        return page_html


def parse_events(html: str):
    root = BeautifulSoup(html, features="html.parser")

    results = []
    for match_table in root.find_all("table", {"class": "matches"}):
        for match in match_table.find_all("tr"):
            date_tag = match.find("span", {"class": "sct"})
            date = date_tag.attrs["data-time"]

            name_tag = match.find("a", {"class": "mlink"})
            link = name_tag.attrs["href"]

            title = name_tag.attrs["title"]
            title = normalize_event_name(title)
            if "tbd" in title:
                continue

            match_obj = build_match_object(title, date, link)
            inject_match_sha(match_obj)

            results.append(match_obj)
            print(match_obj)
    return results


def build_match_object(name: str, date: str, url: str) -> dict:
    match_obj = {
        "id": str(uuid4()),
        "dataSource": "game-tournaments",
        "gameName": "CS:GO",
        "eventName": name,
        "eventURL": url,
        "eventTimestamp": int(datetime.datetime.strptime(date, "%Y-%m-%d %H:%M:%S").timestamp() * 1000),
    }
    return match_obj


def inject_match_sha(match: dict):
    sha_seed = f"{match['gameName']}{match['eventName']}"
    match["eventSHA"] = sha256(sha_seed.encode()).hexdigest()


def normalize_event_name(name: str):
    name = re.search(r'match\s(.*)\sagainst\s(.*)', name.lower())
    if not name:
        print(f"Could not normalize event name: {name}")
        return
    return f"{name.group(1)} - {name.group((2))}"


def upsert_db_item(event):
    response = table.scan(
        FilterExpression=Attr("dataSource").eq("game-tournaments") &
                         Attr("eventSHA").eq(event["eventSHA"]))
    if response["Items"]:
        table.delete_item(Key={"id": response["Items"][0]["id"]})

    # Todo: Consider using update
    table.put_item(Item=event)


def handler(event, ctx):
    loop = asyncio.get_event_loop()
    html_page = loop.run_until_complete(fetch_page())
    results = parse_events(html_page)

    if DYNAMO_TABLE_NAME:
        for r in results:
            upsert_db_item(r)

    return {"statusCode": 200}
