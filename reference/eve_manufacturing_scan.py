#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eve_manufacturing_scan.py

Ищет профитные возможности производства (не капиталка, только Tech I и
Tech II — без фракционных/офицерских/дедспейс/сторилайн предметов) среди
модулей, аммо, дронов и ригов, перебирая ВСЕ такие T1/T2 предметы и считая
для каждого стоимость постройки против текущей рыночной цены — по бай- и
по селл-ордерам, для закупки материалов и для продажи готового товара.

Источники данных:
  - Список кандидатов (не капитал) — дерево /markets/groups/ в ESI,
    официальный публичный эндпоинт, без сторонних дампов.
  - Фильтр T1/T2 — meta_group_id из ref-data.everef.net/types/{id}
    (1 = Tech I, 2 = Tech II; всё остальное отсеивается).
  - Стоимость материалов постройки — api.everef.net/v1/industry/cost
    (официальный публичный API EVE Ref). Материалы покупаются только по
    sell-ордеру (моментальная закупка, FUZZWORK_JITA_SELL_MIN, только Jita) —
    без варианта "через свой buy-ордер".
  - Цена продажи готового товара — собственный полный скан ордербука
    региона Jita (The Forge), станция Jita IV - Moon 4.
  - Среднесуточный объём в ISK (фильтр неликвида) — /markets/{region}/history/
    в ESI, среднее за последние N дней (average_price × volume), считается
    ТОЛЬКО для позиций, уже прошедших фильтр профита/маржи — чтобы не делать
    тысячи лишних запросов по всем кандидатам.
  - Стоимость инвента (опционально) — та же логика, что в eve_invention.py:
    для T2-позиции ищется исходный T1 чертёж (через bulk-справочник
    ref-data.everef.net/blueprints), перебираются все варианты декриптора
    (+ вариант без декриптора), берётся вариант с минимальной ожидаемой
    ценой за 1 ран (materials+decryptor / success_prob / runs), и эта сумма
    вычитается из профита. Считается ТОЛЬКО для позиций, уже прошедших
    фильтры профита/маржи/ликвидности — иначе пришлось бы опрашивать 5 хабов
    по каждому материалу/декриптору для тысяч кандидатов.

Экономика (закупка сырья и продажа товара — всегда моментально, без своих ордеров):
  - Закупка материалов — instant по sell-ордеру, без брокерки.
  - Продажа готового товара — instant в лучший buy-ордер, без брокерки, но
    с налогом с продажи (sales tax).

Фильтры в конфиге:
  - t2_only (bool) — если true, из кандидатов остаются ТОЛЬКО Tech II
    предметы (meta_group_id == 2), T1 отсеивается. Категории (модули, аммо,
    дроны, риги) НЕ сужаются — ищем по всем четырём корневым группам, как
    и при t2_only=false, разница только в tech-уровне (T1+T2 vs только T2).
  - rigs_only (bool) — если true, кандидаты ограничиваются ТОЛЬКО ригами.
    Риги — не отдельный корень market-групп, а вложенная ветка (Ship
    Equipment -> Ship and Module Modifications -> Rigs), поэтому ищется узел
    с именем "Rigs" на любой глубине дерева, а не среди корневых групп.
    Независим от t2_only — можно включить оба сразу (риги, только T2) или
    только rigs_only (риги T1+T2).
  - min_daily_isk_volume (string) — минимальный среднесуточный оборот
    товара в ISK, ниже которого позиция считается неликвидом и отсеивается.
    Задаётся строкой, разделители "_" для читаемости, например "5_000_000".
    "0" или пустая строка — фильтр выключен.
  - include_invention_cost (bool) — если true, из профита T2-позиций
    вычитается ожидаемая (с учётом шанса неудачи) стоимость инвента по
    самому дешёвому найденному варианту декриптора. Если для T2-предмета не
    нашёлся исходный T1 чертёж (bulk-справочник недоступен/не нашёл пару) —
    вычет считается равным 0 для этой позиции, с пометкой в выводе.
    Упрощение: цена инвента размазывается по руну как "1 ран инвента = 1
    единица продукта на выходе" — верно для большинства модулей/ригов, но
    может быть неточным для аммо/дронов, где 1 производственный ран даёт
    несколько единиц (в выводе такие позиции стоит перепроверять вручную).
  - invention_assumed_science_skill_level / invention_assumed_encryption_skill_level
    (int, 0-5) — уровни скиллов по умолчанию, если не задан invention_token.
  - invention_token (string, опционально) — ESI-токен со scope
    esi-skills.read_skills.v1, чтобы использовать реальные уровни скиллов
    персонажа вместо assumed-значений (как в eve_invention.py).
  - rank_by (string, default "profit_per_day") — по какой метрике ранжировать и
    сортировать результаты:
      "profit_per_day" — ISK в сутки с ОДНОГО производственного слота, занятого
        этой позицией (profit_per_unit * units_per_day, где units_per_day берётся
        из времени job'а, которое отдаёт Industry Cost API). Правильно учитывает,
        что 100% маржи за 10 дней постройки может быть хуже, чем 50% маржи за
        2 дня — слот один, и чем дольше он занят, тем меньше оборотов вы успеете
        сделать в единицу времени.
      "margin" — старое поведение: сортировка по проценту маржи, без учёта
        времени постройки.
    Независимо от rank_by, в выводе по каждой позиции печатаются И маржа, И
    ISK/сутки — отличается только порядок сортировки/топ.
  - invention_index_workers (int, default 40) — конкурентность при сборке
    обратного индекса продукт->чертёж (разовая операция по всем ~5000
    чертежам игры, см. build_blueprint_reverse_index).
  - invention_pricing_workers (int, default 10) — конкурентность по ПОЗИЦИЯМ
    при расчёте стоимости инвента (шаг 5, только для уже отфильтрованных
    результатов). Внутри каждой позиции цены материалов/декрипторов уже сами
    по себе опрашиваются параллельно (5 хабов на цену, до ~16 цен на позицию),
    так что при invention_pricing_workers=10 одновременно может быть до
    нескольких сотен HTTP-запросов в моменте — если увидите массовые ошибки
    в логе, снизьте это значение.

Использование:
    python eve_manufacturing_scan.py
"""

import argparse
import base64
import concurrent.futures
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

ESI_BASE = "https://esi.evetech.net/latest"
INDUSTRY_COST_URL = "https://api.everef.net/v1/industry/cost"
REF_DATA_BASE = "https://ref-data.everef.net"

DEFAULT_CONFIG_PATH = "config_manufacturing.json"
CACHE_DIR = ".eve_cache"

DEFAULT_CONFIG = {
    "me": 0,
    "sales_tax": 3.37,
    "broker_fee": 2.5,
    "min_profit": 1000000,
    "min_margin": 0.0,
    "top": 40,
    "workers": 15,
    "cache_ttl_hours": 24,
    "orders_cache_ttl_hours": 3,
    # --- фильтры ---
    "t2_only": False,
    "rigs_only": False,
    "min_daily_isk_volume": "0",
    "volume_history_days": 30,
    # "buy" — продажа мгновенно в лучший buy-ордер (как было раньше, по умолчанию).
    # "sell" — цена берётся с текущего лучшего sell-ордера (цена, по которой уже
    # продают конкуренты) — ближе к тому, что реально получится, если вы сами
    # встанете в очередь своим sell-ордером, а не продадите мгновенно.
    "sell_order_type": "buy",
    # "profit_per_day" (по умолчанию) — ранжирование по ISK/сутки с одного производственного
    # слота (учитывает время постройки: 50% маржи за 2 дня может обойти 100% маржи за 10 дней).
    # "margin" — старое поведение, ранжирование по проценту маржи без учёта времени.
    "rank_by": "profit_per_day",
    # --- стоимость инвента (опционально) ---
    "include_invention_cost": False,
    "invention_token": "",
    "invention_assumed_science_skill_level": 5,
    "invention_assumed_encryption_skill_level": 4,
    "invention_index_workers": 40,
    "invention_pricing_workers": 10,
}

JITA_REGION_ID = 10000002   # The Forge
JITA_STATION_ID = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant

# 5 хабов — используются ТОЛЬКО для расчёта стоимости инвента (материалы/декрипторы),
# как в eve_invention.py. Остальной скрипт (закупка сырья на постройку, продажа товара)
# по-прежнему работает только через Jita.
TRADE_HUBS = {
    "Jita":    {"region_id": 10000002, "station_id": 60003760},  # The Forge
    "Amarr":   {"region_id": 10000043, "station_id": 60008494},  # Domain
    "Dodixie": {"region_id": 10000032, "station_id": 60011866},  # Sinq Laison
    "Rens":    {"region_id": 10000030, "station_id": 60004588},  # Heimatar
    "Hek":     {"region_id": 10000042, "station_id": 60005686},  # Metropolis
}

# Статы декрипторов: Probability Multiplier (%), Run Modifier, ME Modifier, TE Modifier
# Источник: https://wiki.eveuniversity.org/Invention (таблица Decryptor Stats)
DECRYPTORS = {
    "Accelerant Decryptor":             {"prob_mult": 20,  "runs": 1, "me": 2,  "te": 10},
    "Attainment Decryptor":             {"prob_mult": 80,  "runs": 4, "me": -1, "te": 4},
    "Augmentation Decryptor":           {"prob_mult": -40, "runs": 9, "me": -2, "te": 2},
    "Optimized Attainment Decryptor":   {"prob_mult": 90,  "runs": 2, "me": 1,  "te": -2},
    "Optimized Augmentation Decryptor": {"prob_mult": -10, "runs": 7, "me": 2,  "te": 0},
    "Parity Decryptor":                 {"prob_mult": 50,  "runs": 3, "me": 1,  "te": -2},
    "Process Decryptor":                {"prob_mult": 10,  "runs": 0, "me": 3,  "te": 6},
    "Symmetry Decryptor":               {"prob_mult": 0,   "runs": 2, "me": 1,  "te": 8},
}

# Базовые ME/TE у любого свежеизобретённого Т2 БПЦ (до модификатора декриптора)
BASE_ME = 2
BASE_TE = 4

# Корневые market-группы, которые нас интересуют (не корабли, не структуры)
# Одинаковый набор для t2_only=true и t2_only=false — t2_only сужает только
# tech-уровень (meta_group_id), а не категории.
ROOT_GROUP_WHITELIST = {"ship equipment", "ammunition & charges", "drones"}
# rigs_only не использует этот список — риги ищутся отдельно по имени узла "Rigs"
# на любой глубине дерева (см. build_candidate_type_ids), т.к. это не отдельный корень.
# Подветки любого уровня, которые исключаем целиком (капитальные модули и т.п.)
EXCLUDE_NAME_SUBSTRINGS = ["capital", "supercapital"]


# --------------------------------------------------------------------------
# Конфиг
# --------------------------------------------------------------------------

def parse_isk_string(value) -> float:
    """
    Парсит число ISK, заданное строкой с разделителями "_" для читаемости
    (например "5_000_000" -> 5000000.0). Пустая строка/None/"0" -> 0.0.
    Также принимает обычное число (int/float) на случай, если пользователь
    впишет его без кавычек в json.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("_", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        print(f"[!] Не удалось распарсить min_daily_isk_volume='{value}', считаю как 0 (фильтр выключен).",
              file=sys.stderr)
        return 0.0


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"[!] Файл конфига '{path}' не найден. Создал пример со значениями по умолчанию — "
              f"открой его при желании и запусти скрипт снова.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    merged["min_daily_isk_volume_parsed"] = parse_isk_string(merged.get("min_daily_isk_volume"))
    return merged


def decode_character_id_from_token(token: str) -> Optional[int]:
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        sub = payload.get("sub", "")
        if sub.startswith("CHARACTER:EVE:"):
            return int(sub.split(":")[-1])
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------
# Простой файловый кэш с TTL — для тяжёлых этапов (скан хабов, кандидаты,
# результаты Industry Cost API, bulk-справочник чертежей). Каждый блок
# кэшируется отдельным json-файлом в .eve_cache/, свежесть проверяется по
# mtime файла.
# --------------------------------------------------------------------------

def cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.json")


def cache_load(name: str, ttl_hours: float):
    path = cache_path(name)
    if not os.path.exists(path):
        return None
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    if age_hours > ttl_hours:
        print(f"[i] Кэш '{name}' устарел ({age_hours:.1f}ч > {ttl_hours}ч), пересчитываю.", file=sys.stderr)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[i] Использую кэш '{name}' (возраст {age_hours:.1f}ч из {ttl_hours}ч)", file=sys.stderr)
        return data
    except Exception as e:
        print(f"[!] Не удалось прочитать кэш '{name}': {e}", file=sys.stderr)
        return None


def cache_save(name: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def http_get_json(url: str, token: Optional[str] = None, timeout: int = 30):
    headers = {"Accept": "application/json", "User-Agent": "eve-manufacturing-scan"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        resp_headers = dict(resp.getheaders())
    return json.loads(body), resp_headers


def http_post_json(url: str, payload, token: Optional[str] = None, timeout: int = 30):
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": "eve-manufacturing-scan"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# --------------------------------------------------------------------------
# Шаг 1: список кандидатов (не капитал) через дерево market groups
# --------------------------------------------------------------------------

def fetch_market_group(gid: int) -> Optional[dict]:
    try:
        data, _ = http_get_json(f"{ESI_BASE}/markets/groups/{gid}/?datasource=tranquility")
        return data
    except Exception as e:
        print(f"[!] Не удалось получить market group {gid}: {e}", file=sys.stderr)
        return None


# Meta group ID в EVE Ref: 1 = Tech I, 2 = Tech II (Storyline=3, Faction=4, Officer=5, Deadspace=6 и т.д. — исключаем)
ALLOWED_META_GROUP_IDS_FULL = {1, 2}
# При t2_only=true — берём только T2 (не T1), категории при этом не трогаем
ALLOWED_META_GROUP_IDS_T2_ONLY = {2}


def fetch_type_meta_group(tid: int) -> Optional[int]:
    try:
        data, _ = http_get_json(f"{REF_DATA_BASE}/types/{tid}")
    except Exception:
        return None
    return data.get("meta_group_id")


def filter_t1_t2(candidate_ids: list, workers: int, allowed_meta_group_ids: set) -> list:
    """Оставляет только допустимые meta-группы (T1/T2, либо только T2), отсеивая
    фракционные/офицерские/дедспейс/сторилайн и т.п."""
    print(f"[i] Фильтрую {len(candidate_ids)} кандидатов по meta_group_id "
          f"(разрешено: {sorted(allowed_meta_group_ids)})...", file=sys.stderr)
    kept = []
    dropped = 0
    no_meta = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for tid, meta in zip(candidate_ids, ex.map(fetch_type_meta_group, candidate_ids)):
            if meta is None:
                no_meta += 1
                continue
            if meta in allowed_meta_group_ids:
                kept.append(tid)
            else:
                dropped += 1
    print(f"[i] Оставлено: {len(kept)}. Отсеяно (не подходит под meta-фильтр): "
          f"{dropped}. Без meta_group_id (пропущены на всякий случай): {no_meta}.", file=sys.stderr)
    return kept


def build_candidate_type_ids(workers: int, t2_only: bool, rigs_only: bool) -> list:
    print("[i] Качаю список всех market groups...", file=sys.stderr)
    all_ids, _ = http_get_json(f"{ESI_BASE}/markets/groups/?datasource=tranquility")

    groups = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for gid, data in zip(all_ids, ex.map(fetch_market_group, all_ids)):
            if data:
                groups[gid] = data

    children_by_parent = {}
    for gid, g in groups.items():
        parent = g.get("parent_group_id")
        if parent:
            children_by_parent.setdefault(parent, []).append(gid)

    if rigs_only:
        # Риги — НЕ отдельный корень, а вложенная ветка: Ship Equipment ->
        # Ship and Module Modifications -> Rigs -> (Shield/Armor/... Rigs).
        # Ищем узел с именем "Rigs" на любой глубине дерева, а не среди корней.
        start_nodes = [gid for gid, g in groups.items() if g["name"].strip().lower() == "rigs"]
        matched_names = [groups[gid]["name"] for gid in start_nodes]
        print(f"[i] Найдены узлы 'Rigs' в дереве категорий: {matched_names} (gid: {start_nodes})",
              file=sys.stderr)
        if not start_nodes:
            print("[!] Не нашёл ни одного узла с именем 'Rigs' в дереве — возможно CCP "
                  "переименовали группу.", file=sys.stderr)
    else:
        roots = [gid for gid, g in groups.items() if not g.get("parent_group_id")]
        start_nodes = [gid for gid in roots if groups[gid]["name"].strip().lower() in ROOT_GROUP_WHITELIST]
        matched_names = [groups[gid]["name"] for gid in start_nodes]
        print(f"[i] Найдены корневые группы: {matched_names}", file=sys.stderr)
        if not start_nodes:
            print(f"[!] Не нашёл ни одной ожидаемой корневой группы ({sorted(ROOT_GROUP_WHITELIST)}) — "
                  f"возможно CCP переименовали группы.", file=sys.stderr)

    def is_excluded(name: str) -> bool:
        low = name.lower()
        return any(sub in low for sub in EXCLUDE_NAME_SUBSTRINGS)

    candidate_ids = set()
    stack = list(start_nodes)
    while stack:
        gid = stack.pop()
        g = groups.get(gid)
        if not g:
            continue
        if is_excluded(g["name"]):
            continue  # пропускаем всю подветку (капиталка и т.п.)
        candidate_ids.update(g.get("types", []) or [])
        stack.extend(children_by_parent.get(gid, []))

    print(f"[i] Кандидатов (не капитал, модули/аммо/дроны/риги, все meta-уровни): {len(candidate_ids)}",
          file=sys.stderr)

    allowed_meta = ALLOWED_META_GROUP_IDS_T2_ONLY if t2_only else ALLOWED_META_GROUP_IDS_FULL
    return filter_t1_t2(sorted(candidate_ids), workers, allowed_meta)


def resolve_names_by_id(type_ids: list) -> dict:
    ids = sorted(set(type_ids))
    names = {}
    url = f"{ESI_BASE}/universe/names/?datasource=tranquility"
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        try:
            result = http_post_json(url, chunk)
        except urllib.error.HTTPError as e:
            print(f"[!] Ошибка резолва имён (батч {i}): {e}", file=sys.stderr)
            continue
        for item in result:
            names[item["id"]] = item["name"]
    return names


# --------------------------------------------------------------------------
# Шаг 2: полный скан ордербука Jita (для цены продажи готового товара)
# --------------------------------------------------------------------------

@dataclass
class HubStats:
    sell_price: Optional[float] = None
    sell_volume: int = 0
    buy_price: Optional[float] = None
    buy_volume: int = 0


def fetch_page(region_id: int, page: int):
    params = urllib.parse.urlencode({"datasource": "tranquility", "order_type": "all", "page": page})
    return http_get_json(f"{ESI_BASE}/markets/{region_id}/orders/?{params}")


def fetch_region_full(region_id: int, workers: int) -> list:
    first_data, first_headers = fetch_page(region_id, 1)
    total_pages = int(first_headers.get("X-Pages", 1))
    all_orders = list(first_data)
    if total_pages <= 1:
        return all_orders

    def worker(page: int):
        for attempt in range(3):
            try:
                data, headers = fetch_page(region_id, page)
                remain = headers.get("X-Esi-Error-Limit-Remain")
                if remain is not None and int(remain) < 15:
                    time.sleep(2)
                return data
            except urllib.error.HTTPError as e:
                if e.code in (420, 429, 500, 502, 503):
                    time.sleep(3 * (attempt + 1))
                    continue
                return []
            except Exception:
                time.sleep(1 * (attempt + 1))
        return []

    pages = list(range(2, total_pages + 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for result in ex.map(worker, pages):
            all_orders.extend(result)
    return all_orders


def build_type_hub_stats(orders: list, station_id: int) -> dict:
    stats = {}
    for o in orders:
        if o.get("location_id") != station_id:
            continue
        tid = o["type_id"]
        hs = stats.get(tid)
        if hs is None:
            hs = HubStats()
            stats[tid] = hs
        price, vol = o["price"], o["volume_remain"]
        if o["is_buy_order"]:
            if hs.buy_price is None or price > hs.buy_price:
                hs.buy_price, hs.buy_volume = price, vol
            elif price == hs.buy_price:
                hs.buy_volume += vol
        else:
            if hs.sell_price is None or price < hs.sell_price:
                hs.sell_price, hs.sell_volume = price, vol
            elif price == hs.sell_price:
                hs.sell_volume += vol
    return stats


def scan_jita_prices(workers: int) -> dict:
    """dict[type_id] -> {"sell_price": float|None, "buy_price": float|None} — только Jita."""
    t0 = time.time()
    print(f"[i] Jita: качаю весь ордербук региона {JITA_REGION_ID}...", file=sys.stderr)
    orders = fetch_region_full(JITA_REGION_ID, workers)
    print(f"[i] Jita: {len(orders)} ордеров за {time.time()-t0:.1f} сек.", file=sys.stderr)
    hub_stats = build_type_hub_stats(orders, JITA_STATION_ID)
    return {tid: {"sell_price": hs.sell_price, "buy_price": hs.buy_price} for tid, hs in hub_stats.items()}


# --------------------------------------------------------------------------
# Шаг 3: стоимость постройки через EVE Ref Industry Cost API
# --------------------------------------------------------------------------

import re as _re

_ISO8601_DURATION_RE = _re.compile(
    r"P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?"
)


def parse_iso8601_duration_seconds(s: Optional[str]) -> Optional[float]:
    """Парсит длительность вида 'PT194H19M33S' (как отдаёт EVE Ref Industry Cost API
    в поле manufacturing.time) в секунды. Возвращает None, если строка не распознана."""
    if not s:
        return None
    m = _ISO8601_DURATION_RE.fullmatch(s)
    if not m:
        return None
    parts = m.groupdict()
    years = float(parts["years"] or 0)
    months = float(parts["months"] or 0)
    days = float(parts["days"] or 0)
    hours = float(parts["hours"] or 0)
    minutes = float(parts["minutes"] or 0)
    seconds = float(parts["seconds"] or 0)
    total_days = years * 365 + months * 30 + days
    total_seconds = total_days * 86400 + hours * 3600 + minutes * 60 + seconds
    if total_seconds <= 0:
        return None
    return total_seconds


def fetch_manufacturing_cost(product_id: int, material_prices: str, me: int) -> Optional[dict]:
    params = urllib.parse.urlencode({
        "product_id": product_id,
        "me": me,
        "material_prices": material_prices,
    })
    url = f"{INDUSTRY_COST_URL}?{params}"
    try:
        data, _ = http_get_json(url, timeout=20)
    except urllib.error.HTTPError:
        return None  # нет чертежа на этот продукт и т.п. — пропускаем
    except Exception:
        return None
    mfg = data.get("manufacturing", {})
    return mfg.get(str(product_id))


# --------------------------------------------------------------------------
# Шаг 4 (только для позиций, прошедших фильтр профита/маржи): среднесуточный
# оборот в ISK через /markets/{region}/history/ — фильтр неликвида.
# --------------------------------------------------------------------------

def fetch_type_daily_isk_volume(type_id: int, region_id: int, days: int) -> Optional[float]:
    url = f"{ESI_BASE}/markets/{region_id}/history/?datasource=tranquility&type_id={type_id}"
    try:
        data, _ = http_get_json(url, timeout=20)
    except Exception:
        return None
    if not data:
        return None
    recent = data[-days:] if len(data) >= days else data
    if not recent:
        return None
    total_isk = sum((d.get("average", 0) or 0) * (d.get("volume", 0) or 0) for d in recent)
    return total_isk / len(recent)


def annotate_with_daily_isk_volume(type_ids: list, workers: int, days: int, ttl_hours: float) -> dict:
    """Возвращает dict[type_id] -> avg_daily_isk_volume|None, только для переданных type_ids
    (вызывается ПОСЛЕ фильтра профита/маржи, чтобы не дёргать history для тысяч кандидатов)."""
    cache_name = f"daily_isk_volume_{days}d"
    cached = cache_load(cache_name, ttl_hours) or {}
    cached = {int(k): v for k, v in cached.items()}

    missing = [tid for tid in type_ids if tid not in cached]
    if missing:
        print(f"[i] Считаю среднесуточный оборот (ISK) за {days}д для {len(missing)} позиций "
              f"(прошедших фильтр профита/маржи)...", file=sys.stderr)

        def worker(tid: int):
            return tid, fetch_type_daily_isk_volume(tid, JITA_REGION_ID, days)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for tid, val in ex.map(worker, missing):
                cached[tid] = val

        cache_save(cache_name, {str(k): v for k, v in cached.items()})

    return {tid: cached.get(tid) for tid in type_ids}


# --------------------------------------------------------------------------
# Шаг 5 (опционально, только для позиций, уже прошедших все фильтры выше):
# стоимость инвента — та же логика, что в eve_invention.py.
# --------------------------------------------------------------------------

def fetch_character_skill_levels(token: str, character_id: int) -> Optional[dict]:
    """dict[skill_type_id] -> trained_skill_level, либо None если недоступно."""
    url = f"{ESI_BASE}/characters/{character_id}/skills/"
    try:
        data, _ = http_get_json(url, token=token)
    except urllib.error.HTTPError as e:
        print(f"[!] Не удалось получить скиллы персонажа (нужен scope esi-skills.read_skills.v1): {e}",
              file=sys.stderr)
        return None
    return {s["skill_id"]: s["trained_skill_level"] for s in data.get("skills", [])}


def _fetch_hub_min_sell(type_id: int, hub_name: str, region_id: int, station_id: int) -> Optional[float]:
    """Минимальная sell-цена type_id в конкретном хабе (все страницы), либо None."""
    best_price = None
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "datasource": "tranquility",
            "order_type": "sell",
            "page": page,
            "type_id": type_id,
        })
        url = f"{ESI_BASE}/markets/{region_id}/orders/?{params}"
        try:
            data, headers = http_get_json(url, timeout=30)
            total_pages = int(headers.get("X-Pages", 1))
        except urllib.error.HTTPError as e:
            print(f"[!] Ошибка запроса ордеров ({hub_name}, type_id={type_id}): {e}", file=sys.stderr)
            return best_price
        except Exception:
            return best_price
        for o in data:
            if o["location_id"] == station_id:
                if best_price is None or o["price"] < best_price:
                    best_price = o["price"]
        if page >= total_pages:
            break
        page += 1
    return best_price


def get_best_sell_price(type_id: int) -> Optional[tuple]:
    """Возвращает (цена, хаб) с минимальной ценой sell-ордера среди 5 хабов, либо None.
    5 хабов опрашиваются параллельно (это IO-bound запросы, поток на хаб не тяжёлый)."""
    best_price = None
    best_hub = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(TRADE_HUBS)) as ex:
        futures = {
            ex.submit(_fetch_hub_min_sell, type_id, hub_name, meta["region_id"], meta["station_id"]): hub_name
            for hub_name, meta in TRADE_HUBS.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            hub_name = futures[fut]
            price = fut.result()
            if price is not None and (best_price is None or price < best_price):
                best_price = price
                best_hub = hub_name
    if best_price is None:
        return None
    return best_price, best_hub


def fetch_blueprint_data(type_id: int, retries: int = 3) -> Optional[dict]:
    url = f"{REF_DATA_BASE}/blueprints/{type_id}"
    for attempt in range(retries):
        try:
            data, _ = http_get_json(url, timeout=20)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (420, 429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            return None  # 404 и т.п. — у этого type_id просто нет чертежа, это нормально
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


def fetch_all_blueprint_ids(retries: int = 4) -> Optional[list]:
    """GET /blueprints — по документации EVE Ref отдаёт ТОЛЬКО список blueprint_type_id
    (array of int64), не сами данные. Данные по каждому чертежу тянутся отдельно
    через /blueprints/{id} (см. build_blueprint_reverse_index).

    Наблюдение: этот запрос стабильно (не случайно) возвращал заметно урезанный список
    (одно и то же меньшее число ID на разных запусках) — похоже на закэшированный где-то
    по пути (CDN/прокси) старый/неполный снимок, а не на обрыв соединения. Поэтому здесь
    добавлен cache-busting query-параметр, чтобы обойти промежуточный кэш."""
    for attempt in range(retries):
        cache_bust = f"?_cb={int(time.time()*1000)}_{attempt}"
        url = f"{REF_DATA_BASE}/blueprints{cache_bust}"
        try:
            data, _ = http_get_json(url, timeout=180)
            if not isinstance(data, list):
                print(f"[!] Ожидал список ID от {url}, получил {type(data)} — "
                      f"возможно EVE Ref поменяли формат ответа.", file=sys.stderr)
                return None
            print(f"[i] Получен список ID чертежей: {len(data)} шт. (попытка {attempt+1}). "
                  f"Если это число заметно меньше нескольких тысяч — вероятен обрыв/кэш "
                  f"по пути, будет ещё одна попытка.", file=sys.stderr)
            if len(data) >= 3000:
                return data
            print(f"[!] Подозрительно маленький список ({len(data)}) — пробую ещё раз "
                  f"с другим cache-busting параметром.", file=sys.stderr)
        except Exception as e:
            print(f"[!] Попытка {attempt+1}/{retries} получить список ID чертежей не удалась: {e}",
                  file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    print(f"[!] Не удалось получить полный список ID чертежей после {retries} попыток "
          f"(последний результат мог быть неполным). Стоимость инвента может считаться "
          f"неполно — часть T2-позиций не найдёт исходный чертёж.", file=sys.stderr)
    return data if 'data' in dir() and isinstance(data, list) else None


def build_blueprint_reverse_index(index_workers: int, ttl_hours: float) -> dict:
    """
    dict[product_type_id] -> blueprint_type_id, только для чертежей с invention-активностью.

    /blueprints отдаёт только список ID (не данные), поэтому приходится дёргать
    /blueprints/{id} по каждому чертежу отдельно (их в игре несколько тысяч,
    но это разовая операция с долгим кэшем — тот же порядок тяжести, что и
    фильтрация кандидатов по meta_group_id на Шаге 1).

    Автоматическая sanity-проверка: если закэшированный индекс подозрительно мал
    (меньше MIN_SANE_INDEX_SIZE записей — раньше это случалось из-за обрыва/кэша при
    скачивании полного списка ID), кэш считается недействительным и перестраивается
    сам, без ручного вмешательства — не нужно вручную чистить .eve_cache.
    """
    MIN_SANE_INDEX_SIZE = 2000  # ориентир: полный индекс обычно в районе нескольких тысяч

    cache_name = "blueprint_invention_reverse_index"
    cached = cache_load(cache_name, ttl_hours)
    if cached is not None:
        if len(cached) >= MIN_SANE_INDEX_SIZE:
            return {int(k): v for k, v in cached.items()}
        print(f"[!] Кэш '{cache_name}' подозрительно мал ({len(cached)} записей, ожидалось "
              f"от {MIN_SANE_INDEX_SIZE}+) — похоже на обрыв при прошлой сборке. "
              f"Пересобираю автоматически, без участия пользователя.", file=sys.stderr)

    blueprint_ids = fetch_all_blueprint_ids()
    if not blueprint_ids:
        return {}

    # Конкурентность для этого шага задаётся отдельно от общего workers через
    # invention_index_workers в конфиге — запросов тут на порядок больше (по одному
    # на каждый чертёж в игре), но, судя по практике, EVE Ref спокойно держит
    # десятки параллельных запросов без рейт-лимита (failed=0 наблюдалось даже
    # на скромных 8 потоках).
    inv_workers = max(1, index_workers)

    print(f"[i] Строю обратный индекс продукт->чертёж для инвента: качаю данные "
          f"{len(blueprint_ids)} чертежей по одному (разово, долгий кэш, {inv_workers} потоков)...",
          file=sys.stderr)

    # ВАЖНО: activities.invention.products хранит id ИЗОБРЕТЁННОГО ЧЕРТЕЖА (T2 BPC),
    # а не id конечного предмета — это два разных type_id (пример: Damage Control I
    # Blueprint инвентится в Damage Control II Blueprint [2049], а сам предмет
    # Damage Control II [2048] производится ИЗ ЭТОГО чертежа отдельным шагом
    # manufacturing). Поэтому строим индекс в два прохода:
    #   1) manufacturing_product_of[blueprint_id] -> item_type_id, для ВСЕХ чертежей
    #   2) invention_pairs: (T1_blueprint_id -> invented_T2_blueprint_id)
    # и только потом схлопываем через (1), чтобы получить item_type_id -> T1_blueprint_id.
    manufacturing_product_of = {}
    invention_pairs = []  # (source_bp_id, invented_blueprint_id)

    ok_count = 0
    failed_count = 0
    with_invention_count = 0

    def worker(bp_id: int):
        return bp_id, fetch_blueprint_data(bp_id)

    t0 = time.time()
    checked = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=inv_workers) as ex:
        for bp_id, bp_data in ex.map(worker, blueprint_ids):
            checked += 1
            if checked % 500 == 0:
                elapsed = time.time() - t0
                print(f"[i]   ...{checked}/{len(blueprint_ids)} чертежей проверено "
                      f"({elapsed:.0f} сек, ok={ok_count}, failed={failed_count}, "
                      f"с invention={with_invention_count})", file=sys.stderr)
            if not bp_data:
                failed_count += 1
                continue
            ok_count += 1
            activities = bp_data.get("activities", {})

            manufacturing = activities.get("manufacturing")
            if manufacturing:
                mfg_products = manufacturing.get("products", {})
                if mfg_products:
                    # Практически всегда ровно один продукт на manufacturing-активность
                    first_key = next(iter(mfg_products.keys()))
                    manufacturing_product_of[bp_id] = int(first_key)

            invention = activities.get("invention")
            if not invention:
                continue
            with_invention_count += 1
            inv_products = invention.get("products", {})
            for invented_bp_id_str in inv_products.keys():
                invention_pairs.append((bp_id, int(invented_bp_id_str)))

    # Второй проход — уже без сети, просто схлопываем invention_pairs через
    # manufacturing_product_of, полученный в первом проходе (данные по ВСЕМ
    # чертежам, включая T2, уже скачаны выше).
    reverse_index = {}
    unresolved = 0
    for source_bp_id, invented_bp_id in invention_pairs:
        item_id = manufacturing_product_of.get(invented_bp_id)
        if item_id is None:
            unresolved += 1
            continue
        reverse_index[item_id] = source_bp_id

    print(f"[i] Индекс построен за {time.time()-t0:.1f} сек: проверено {checked} чертежей "
          f"(успешно скачано {ok_count}, не удалось {failed_count}), из них с invention-активностью "
          f"{with_invention_count}, пар invention->manufacturing не удалось разрешить {unresolved}, "
          f"итоговых T2-предметов в индексе: {len(reverse_index)}.", file=sys.stderr)
    if failed_count > checked * 0.1:
        print(f"[!] Много неудачных запросов ({failed_count}/{checked}) — похоже на рейт-лимит "
              f"EVE Ref. Попробуйте снизить inv_workers в коде или запустить ещё раз позже "
              f"(частично собранный кэш сохранится, но лучше добиться низкого failed_count).",
              file=sys.stderr)
    cache_save(cache_name, {str(k): v for k, v in reverse_index.items()})
    return reverse_index


@dataclass
class InventionOption:
    decryptor_name: str
    decryptor_price: float
    success_prob: float
    runs: int
    me: int
    te: int
    materials_cost: float

    @property
    def cost_per_attempt(self) -> float:
        return self.materials_cost + self.decryptor_price

    @property
    def expected_cost_per_success(self) -> float:
        if self.success_prob <= 0:
            return float("inf")
        return self.cost_per_attempt / self.success_prob

    @property
    def expected_cost_per_run(self) -> float:
        if self.runs <= 0:
            return float("inf")
        return self.expected_cost_per_success / self.runs


def compute_cheapest_invention_option(
    blueprint_type_id: int,
    product_type_id: int,
    char_skills: Optional[dict],
    assumed_science_level: int,
    assumed_encryption_level: int,
) -> Optional[InventionOption]:
    """Перебирает все декрипторы (+ вариант без декриптора) для конкретного product_type_id,
    инвентящегося из blueprint_type_id, и возвращает вариант с минимальной expected_cost_per_run."""
    bp_data = fetch_blueprint_data(blueprint_type_id)
    if not bp_data:
        return None
    invention = bp_data.get("activities", {}).get("invention")
    if not invention:
        return None

    products_raw = invention.get("products", {})
    if not products_raw:
        return None
    # ВАЖНО: ключи products_raw — это id ИЗОБРЕТЁННОГО ЧЕРТЕЖА (T2 BPC), а не id
    # конечного предмета product_type_id (см. комментарий в build_blueprint_reverse_index) —
    # поэтому не ищем по product_type_id, а берём единственную (в подавляющем большинстве
    # случаев ровно одну) invention-запись как есть.
    product_info = next(iter(products_raw.values()))
    base_prob = product_info.get("probability")
    base_runs = product_info.get("quantity")
    if not base_prob or not base_runs:
        return None

    materials_raw = invention.get("materials", {})
    skills_raw = invention.get("required_skills", {})
    if not materials_raw:
        return None

    # Резолвим имена скиллов, чтобы отличить Encryption Methods от Science-скиллов
    skill_ids = list(skills_raw.keys())
    skill_names = resolve_names_by_id([int(sid) for sid in skill_ids]) if skill_ids else {}

    encryption_skill = None
    science_skills = []
    for sid_str in skill_ids:
        sid = int(sid_str)
        sname = skill_names.get(sid, "")
        if "encryption methods" in sname.lower():
            encryption_skill = sid
        else:
            science_skills.append(sid)

    def get_skill_level(skill_type_id: Optional[int], is_encryption: bool) -> int:
        if skill_type_id is None:
            return 0
        if char_skills and skill_type_id in char_skills:
            return char_skills[skill_type_id]
        return assumed_encryption_level if is_encryption else assumed_science_level

    encryption_level = get_skill_level(encryption_skill, True)
    science_levels = [get_skill_level(sid, False) for sid in science_skills[:2]]
    while len(science_levels) < 2:
        science_levels.append(0)

    skill_multiplier = 1 + (science_levels[0] + science_levels[1]) / 30 + encryption_level / 40

    material_ids = [int(tid_str) for tid_str in materials_raw.keys()]
    material_prices = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(material_ids))) as ex:
        futures = {ex.submit(get_best_sell_price, tid): tid for tid in material_ids}
        for fut in concurrent.futures.as_completed(futures):
            tid = futures[fut]
            price_info = fut.result()
            material_prices[tid] = price_info[0] if price_info else 0.0
    materials_cost = sum(material_prices[int(tid_str)] * m["quantity"] for tid_str, m in materials_raw.items())

    decryptor_prices = {}
    decryptor_name_list = list(DECRYPTORS.keys())
    try:
        ids_result = http_post_json(f"{ESI_BASE}/universe/ids/?datasource=tranquility&language=en",
                                     decryptor_name_list)
        decryptor_ids = {t["name"]: t["id"] for t in ids_result.get("inventory_types", [])}
    except Exception:
        decryptor_ids = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(decryptor_ids))) as ex:
        futures = {ex.submit(get_best_sell_price, did): dname for dname, did in decryptor_ids.items()}
        for fut in concurrent.futures.as_completed(futures):
            dname = futures[fut]
            price_info = fut.result()
            decryptor_prices[dname] = price_info[0] if price_info else None

    options = [InventionOption(
        decryptor_name="Без декриптора",
        decryptor_price=0.0,
        success_prob=min(1.0, base_prob * skill_multiplier),
        runs=base_runs,
        me=BASE_ME,
        te=BASE_TE,
        materials_cost=materials_cost,
    )]
    for dname, mods in DECRYPTORS.items():
        price = decryptor_prices.get(dname)
        if price is None:
            continue
        prob = min(1.0, base_prob * skill_multiplier * (1 + mods["prob_mult"] / 100))
        options.append(InventionOption(
            decryptor_name=dname,
            decryptor_price=price,
            success_prob=prob,
            runs=max(1, base_runs + mods["runs"]),
            me=BASE_ME + mods["me"],
            te=BASE_TE + mods["te"],
            materials_cost=materials_cost,
        ))

    if not options:
        return None
    return min(options, key=lambda o: o.expected_cost_per_run)


# --------------------------------------------------------------------------
# Расчёт профита
# --------------------------------------------------------------------------

@dataclass
class Opportunity:
    type_id: int
    name: str
    cost: float                # материалы по SELL_MIN, Jita (единственный вариант закупки)
    job_cost: float
    revenue: Optional[float]   # продажа в Jita в лучший buy-ордер (единственный вариант продажи)
    sales_tax: float
    daily_isk_volume: Optional[float] = None       # заполняется позже, только для прошедших фильтр
    invention_cost_per_unit: Optional[float] = None  # заполняется позже, только если include_invention_cost
    invention_decryptor: Optional[str] = None        # какой вариант декриптора оказался дешевле всего
    units_per_day: Optional[float] = None   # сколько единиц продукта даёт 1 job-слот в сутки (из времени job'а)
    job_time_days: Optional[float] = None   # длительность одного job'а в сутках (для справки в выводе)

    def profit(self) -> Optional[float]:
        if self.revenue is None:
            return None
        revenue_net = self.revenue * (1 - self.sales_tax / 100)
        return revenue_net - self.cost - self.job_cost

    def profit_per_day(self, profit_value: float) -> Optional[float]:
        """ISK/сутки с одного производственного слота, занятого этой позицией — ключевая
        метрика для сравнения опортьюнити с разным временем постройки: маржа сама по себе
        не учитывает, что 100% маржи за 10 дней хуже, чем 50% за 2 дня на том же слоте."""
        if self.units_per_day is None:
            return None
        return profit_value * self.units_per_day


def main():
    parser = argparse.ArgumentParser(
        description="Поиск профитного производства (не капитал) по всем модулям/аммо/дронам/ригам."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--refresh-cache", action="store_true",
                         help="Игнорировать весь кэш и пересчитать всё заново")
    cli = parser.parse_args()
    cfg = load_config(cli.config)

    workers = cfg["workers"]
    me = cfg["me"]
    sales_tax = cfg["sales_tax"]
    t2_only = bool(cfg.get("t2_only", False))
    rigs_only = bool(cfg.get("rigs_only", False))
    sell_order_type = str(cfg.get("sell_order_type", "buy")).strip().lower()
    if sell_order_type not in ("buy", "sell"):
        print(f"[!] sell_order_type='{sell_order_type}' не распознан (ожидалось 'buy' или 'sell'), "
              f"использую 'buy' по умолчанию.", file=sys.stderr)
        sell_order_type = "buy"
    revenue_price_key = "buy_price" if sell_order_type == "buy" else "sell_price"
    rank_by = str(cfg.get("rank_by", "profit_per_day")).strip().lower()
    if rank_by not in ("profit_per_day", "margin"):
        print(f"[!] rank_by='{rank_by}' не распознан (ожидалось 'profit_per_day' или 'margin'), "
              f"использую 'profit_per_day' по умолчанию.", file=sys.stderr)
        rank_by = "profit_per_day"

    def rank_key(opp: "Opportunity", profit_value: float, margin_pct_value: float) -> float:
        if rank_by == "margin":
            return margin_pct_value
        pd = opp.profit_per_day(profit_value)
        # Если время постройки неизвестно (API не отдал/не распарсилось) — не выкидываем
        # позицию, а просто отправляем в конец списка, чтобы не терять её молча.
        return pd if pd is not None else float("-inf")

    min_daily_isk_volume = cfg["min_daily_isk_volume_parsed"]
    volume_history_days = int(cfg.get("volume_history_days", 30))
    include_invention_cost = bool(cfg.get("include_invention_cost", False))
    ttl_static = 0 if cli.refresh_cache else cfg["cache_ttl_hours"]
    ttl_orders = 0 if cli.refresh_cache else cfg["orders_cache_ttl_hours"]

    if t2_only:
        print("[i] Режим t2_only=true: только Tech II (T1 отсеивается).", file=sys.stderr)
    if rigs_only:
        print("[i] Режим rigs_only=true: только риги, без модулей/аммо/дронов.", file=sys.stderr)
    if sell_order_type == "sell":
        print("[i] sell_order_type='sell': выручка считается по текущей лучшей sell-цене "
              "(цена конкурентов), а не по мгновенной продаже в buy-ордер.", file=sys.stderr)
    if min_daily_isk_volume > 0:
        print(f"[i] Фильтр неликвида включён: min_daily_isk_volume = {min_daily_isk_volume:,.0f} ISK/сутки "
              f"(среднее за {volume_history_days}д, Jita).", file=sys.stderr)
    if include_invention_cost:
        print("[i] Учёт стоимости инвента включён: для T2-позиций из профита будет вычтена "
              "ожидаемая цена самого дешёвого варианта инвента.", file=sys.stderr)

    # Шаг 1: кандидаты + названия (кэш, сутки — список товаров меняется редко)
    # имя кэша зависит от t2_only И rigs_only, чтобы не путать кэши разных режимов фильтрации
    candidates_cache_name = "candidates"
    candidates_cache_name += "_t2" if t2_only else "_t1t2"
    candidates_cache_name += "_rigs_only" if rigs_only else "_all_categories"
    cached = cache_load(candidates_cache_name, ttl_static)
    if cached:
        candidate_ids = cached["candidate_ids"]
        names = {int(k): v for k, v in cached["names"].items()}
    else:
        candidate_ids = build_candidate_type_ids(workers, t2_only, rigs_only)
        if not candidate_ids:
            print("[!] Кандидатов не найдено, останавливаюсь.", file=sys.stderr)
            return
        names = resolve_names_by_id(candidate_ids)
        cache_save(candidates_cache_name, {"candidate_ids": candidate_ids, "names": names})

    # Шаг 2: цены продажи в Jita (кэш, 3 часа — цены живые)
    cached = cache_load("jita_prices", ttl_orders)
    if cached:
        market_prices = {int(tid): v for tid, v in cached.items()}
    else:
        market_prices = scan_jita_prices(workers)
        cache_save("jita_prices", {str(tid): v for tid, v in market_prices.items()})

    # Шаг 3: стоимость постройки для каждого кандидата (кэш, 3 часа, ключ зависит от ME)
    # имя кэша с суффиксом _v2time, т.к. добавили парсинг времени job'а (схема данных изменилась,
    # старый кэш без units_per_day не годится)
    cache_name = f"industry_cost_sellonly_me{me}_v2time"
    cost_cache = cache_load(cache_name, ttl_orders) or {}
    cost_cache = {int(k): v for k, v in cost_cache.items()}

    missing_ids = [tid for tid in candidate_ids if tid not in cost_cache]
    if missing_ids:
        print(f"[i] Считаю стоимость постройки для {len(missing_ids)} новых товаров "
              f"через EVE Ref Industry Cost API (ME{me}, закупка сырья только по sell-ордеру), "
              f"{len(candidate_ids) - len(missing_ids)} уже в кэше...", file=sys.stderr)

        def compute_cost_only(tid: int):
            fast = fetch_manufacturing_cost(tid, "FUZZWORK_JITA_SELL_MIN", me)
            if fast is None:
                return tid, None
            units = fast.get("units", 1) or 1
            time_seconds = parse_iso8601_duration_seconds(fast.get("time"))
            time_days = (time_seconds / 86400) if time_seconds else None
            units_per_day = (units / time_days) if time_days and time_days > 0 else None
            return tid, {
                "cost": fast.get("total_material_cost", 0) / units,
                "job_cost": fast.get("total_job_cost", 0) / units,
                "units_per_day": units_per_day,
                "job_time_days": time_days,
            }

        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for tid, result in ex.map(compute_cost_only, missing_ids):
                cost_cache[tid] = result  # None тоже кэшируем — не пересчитывать нетронутые товары
        print(f"[i] Досчитал за {time.time()-t0:.1f} сек.", file=sys.stderr)
        cache_save(cache_name, {str(k): v for k, v in cost_cache.items()})

    opportunities = []
    for tid in candidate_ids:
        c = cost_cache.get(tid)
        if c is None:
            continue
        mp = market_prices.get(tid, {})
        opportunities.append(Opportunity(
            type_id=tid,
            name=names.get(tid, f"type_id {tid}"),
            cost=c["cost"],
            job_cost=c["job_cost"],
            revenue=mp.get(revenue_price_key),
            sales_tax=sales_tax,
            units_per_day=c.get("units_per_day"),
            job_time_days=c.get("job_time_days"),
        ))
    print(f"[i] Есть данные постройки+цены для {len(opportunities)} из {len(candidate_ids)} товаров.",
          file=sys.stderr)

    results = []
    for opp in opportunities:
        profit = opp.profit()
        if profit is None:
            continue
        margin_pct = (profit / opp.cost * 100) if opp.cost > 0 else 0
        if profit >= cfg["min_profit"] and margin_pct >= cfg["min_margin"]:
            results.append((opp, profit, margin_pct))

    results.sort(key=lambda r: rank_key(r[0], r[1], r[2]), reverse=True)

    # Шаг 4: фильтр неликвида по среднесуточному ISK-обороту — считаем ТОЛЬКО
    # для тех, кто уже прошёл профит/маржу (дёшево по API-запросам).
    if min_daily_isk_volume > 0 and results:
        type_ids_to_check = [opp.type_id for opp, _, _ in results]
        vol_map = annotate_with_daily_isk_volume(type_ids_to_check, workers, volume_history_days, ttl_orders)

        filtered = []
        dropped_illiquid = 0
        dropped_no_history = 0
        for opp, profit, margin_pct in results:
            vol = vol_map.get(opp.type_id)
            opp.daily_isk_volume = vol
            if vol is None:
                dropped_no_history += 1
                continue
            if vol >= min_daily_isk_volume:
                filtered.append((opp, profit, margin_pct))
            else:
                dropped_illiquid += 1
        print(f"[i] Фильтр неликвида: оставлено {len(filtered)}, отсеяно как неликвид "
              f"{dropped_illiquid}, без истории торгов (отсеяны на всякий случай) {dropped_no_history}.",
              file=sys.stderr)
        results = filtered

    # Шаг 5: вычет стоимости инвента — считаем ТОЛЬКО для тех, кто уже прошёл
    # все фильтры выше (дорогая операция: 5 хабов x материалы x 8 декрипторов на позицию).
    if include_invention_cost and results:
        invention_index_workers = int(cfg.get("invention_index_workers", 40))
        reverse_index = build_blueprint_reverse_index(invention_index_workers, ttl_static)

        token = cfg.get("invention_token") or None
        char_skills = None
        if token:
            char_id = decode_character_id_from_token(token)
            if char_id:
                print(f"[i] Токен для инвента принадлежит character_id={char_id}", file=sys.stderr)
                char_skills = fetch_character_skill_levels(token, char_id)
                if char_skills:
                    print(f"[i] Получены реальные скиллы персонажа ({len(char_skills)} шт.)", file=sys.stderr)

        assumed_sci = int(cfg.get("invention_assumed_science_skill_level", 5))
        assumed_enc = int(cfg.get("invention_assumed_encryption_skill_level", 4))
        invention_pricing_workers = int(cfg.get("invention_pricing_workers", 10))

        print(f"[i] Считаю стоимость инвента для {len(results)} позиций, прошедших предыдущие фильтры "
              f"({invention_pricing_workers} потоков)...", file=sys.stderr)

        def compute_one(item):
            opp, profit, margin_pct = item
            bp_type_id = reverse_index.get(opp.type_id)
            invention_cost_per_unit = 0.0
            decryptor_used = None
            if bp_type_id is not None:
                option = compute_cheapest_invention_option(
                    bp_type_id, opp.type_id, char_skills, assumed_sci, assumed_enc
                )
                if option is not None:
                    # Упрощение: 1 ран инвента = 1 единица продукта на выходе производства
                    # (верно для большинства модулей/ригов; для аммо/дронов может быть неточно).
                    invention_cost_per_unit = option.expected_cost_per_run
                    decryptor_used = option.decryptor_name
            return opp, profit, margin_pct, bp_type_id, invention_cost_per_unit, decryptor_used

        updated = []
        dropped_after_invention = 0
        no_blueprint_found = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=invention_pricing_workers) as ex:
            for opp, profit, margin_pct, bp_type_id, invention_cost_per_unit, decryptor_used in ex.map(
                compute_one, results
            ):
                if bp_type_id is None:
                    no_blueprint_found += 1
                else:
                    opp.invention_decryptor = decryptor_used

                opp.invention_cost_per_unit = invention_cost_per_unit
                new_profit = profit - invention_cost_per_unit
                new_margin = (new_profit / opp.cost * 100) if opp.cost > 0 else 0
                if new_profit >= cfg["min_profit"] and new_margin >= cfg["min_margin"]:
                    updated.append((opp, new_profit, new_margin))
                else:
                    dropped_after_invention += 1

        print(f"[i] Учёт инвента: осталось {len(updated)}, отсеяно после вычета стоимости инвента "
              f"{dropped_after_invention}, без найденного исходного T1-чертежа (вычет=0) "
              f"{no_blueprint_found}.", file=sys.stderr)
        updated.sort(key=lambda r: rank_key(r[0], r[1], r[2]), reverse=True)
        results = updated

    top_n = cfg["top"]

    header_extra = []
    if t2_only:
        header_extra.append("только T2")
    if rigs_only:
        header_extra.append("только риги")
    if min_daily_isk_volume > 0:
        header_extra.append(f"мин. оборот {min_daily_isk_volume:,.0f} ISK/сутки")
    if include_invention_cost:
        header_extra.append("с учётом стоимости инвента")
    header_extra.append(f"ранжирование: {'ISK/сутки с слота' if rank_by == 'profit_per_day' else 'маржа %'}")
    header_extra_str = f", {', '.join(header_extra)}" if header_extra else ""

    sell_desc = "instant (buy-ордер, Jita)" if sell_order_type == "buy" else "по текущей лучшей sell-цене (Jita)"
    sell_desc_header = "продажа по buy-ордеру" if sell_order_type == "buy" else "продажа по sell-цене конкурентов"

    print(f"\n=== Топ-{top_n} профитного производства (ME{me}, закупка сырья по sell-ордеру, "
          f"{sell_desc_header}, налог {sales_tax}%{header_extra_str}) ===")
    if not results:
        print("Ничего не прошло фильтры min_profit/min_margin/min_daily_isk_volume/invention — "
              "попробуй их снизить в конфиге.")
        return

    for i, (opp, profit, margin_pct) in enumerate(results[:top_n], start=1):
        vol_line = ""
        if opp.daily_isk_volume is not None:
            vol_line = f" | сред. оборот: {opp.daily_isk_volume:,.0f} ISK/сутки"
        inv_line = ""
        if include_invention_cost:
            if opp.invention_cost_per_unit:
                inv_line = f" | инвент: -{opp.invention_cost_per_unit:,.2f} ISK/шт ({opp.invention_decryptor})"
            else:
                inv_line = " | инвент: не найден исходный T1-чертёж (вычет=0)"
        time_line = ""
        pd = opp.profit_per_day(profit)
        if opp.job_time_days is not None and pd is not None:
            time_line = (f"\n   Время job'а: {opp.job_time_days:.2f} сут | "
                         f"Профит/сутки со слота: {pd:,.2f} ISK")
        print(
            f"{i}. [{opp.type_id}] {opp.name}\n"
            f"   Закупка материалов: instant (sell-ордер, Jita) | "
            f"Продажа: {sell_desc}{vol_line}{inv_line}\n"
            f"   Профит/шт.: {profit:,.2f} ISK (маржа {margin_pct:.1f}%) | "
            f"джоб-кост учтён: {opp.job_cost:,.2f}{time_line}\n"
        )

    sell_type_note = (
        "Продажа считается мгновенной (в buy-ордер) — реалистично для быстрой реализации, "
        "но обычно по худшей цене, чем если бы вы сами выставили sell-ордер и подождали."
        if sell_order_type == "buy" else
        "Продажа считается по текущей лучшей sell-цене конкурентов — ближе к тому, что получится, "
        "если встать в очередь своим ордером, НО это не учитывает, что пока вы строите (дни), "
        "эта цена может измениться, и не учитывает объём, который реально готовы купить по ней "
        "прямо сейчас (для этого смотрите min_daily_isk_volume)."
    )
    print(
        "\n[!] Материалы — только Jita, закупка всегда по sell-ордеру (моментально). "
        f"{sell_type_note} "
        "Профит — на 1 единицу продукта, без учёта объёма партии производства и времени постройки. "
        "ME0 — консервативная оценка (с исследованным чертежом расход материалов будет ниже, профит — выше). "
        "Среднесуточный оборот и стоимость инвента считаются только для позиций, уже прошедших "
        "предыдущие фильтры."
    )


if __name__ == "__main__":
    main()