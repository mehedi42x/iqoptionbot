"""IQ Option active_id map (the ids used by the candle-generated stream)."""

ASSETS = [
    {"id": 1, "name": "EURUSD", "group": "Forex"},
    {"id": 2, "name": "GBPUSD", "group": "Forex"},
    {"id": 3, "name": "EURJPY", "group": "Forex"},
    {"id": 4, "name": "USDJPY", "group": "Forex"},
    {"id": 5, "name": "AUDCAD", "group": "Forex"},
    {"id": 6, "name": "NZDUSD", "group": "Forex"},
    {"id": 7, "name": "USDRUB", "group": "Forex"},
    {"id": 9, "name": "USDCHF", "group": "Forex"},
    {"id": 10, "name": "EURGBP", "group": "Forex"},
    {"id": 11, "name": "USDCAD", "group": "Forex"},
    {"id": 12, "name": "AUDUSD", "group": "Forex"},
    {"id": 13, "name": "GBPJPY", "group": "Forex"},
    {"id": 14, "name": "EURCHF", "group": "Forex"},
    {"id": 15, "name": "AUDJPY", "group": "Forex"},
    {"id": 16, "name": "CADCHF", "group": "Forex"},
    {"id": 17, "name": "GBPAUD", "group": "Forex"},
    {"id": 76, "name": "BTCUSD", "group": "Crypto"},
    {"id": 77, "name": "ETHUSD", "group": "Crypto"},
    {"id": 82, "name": "LTCUSD", "group": "Crypto"},
    {"id": 99, "name": "XRPUSD", "group": "Crypto"},
    {"id": 816, "name": "GOLD", "group": "Commodity"},
    {"id": 817, "name": "SILVER", "group": "Commodity"},
    {"id": 1861, "name": "EURUSD-OTC", "group": "OTC"},
    {"id": 1862, "name": "EURGBP-OTC", "group": "OTC"},
    {"id": 1863, "name": "USDCHF-OTC", "group": "OTC"},
    {"id": 1864, "name": "EURJPY-OTC", "group": "OTC"},
    {"id": 1865, "name": "NZDUSD-OTC", "group": "OTC"},
    {"id": 1866, "name": "GBPUSD-OTC", "group": "OTC"},
    {"id": 1867, "name": "GBPJPY-OTC", "group": "OTC"},
    {"id": 1868, "name": "USDJPY-OTC", "group": "OTC"},
    {"id": 1869, "name": "AUDUSD-OTC", "group": "OTC"},
    {"id": 1870, "name": "USDCAD-OTC", "group": "OTC"},
    {"id": 1871, "name": "AUDCAD-OTC", "group": "OTC"},
]

BY_ID = {a["id"]: a for a in ASSETS}


def name_for(active_id: int) -> str:
    a = BY_ID.get(int(active_id))
    return a["name"] if a else f"ACTIVE-{active_id}"
