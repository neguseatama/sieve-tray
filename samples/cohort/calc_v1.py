# 買い物の合計を出す小さな計算機です。
def total_price(items):
    """商品ごとの小計を足して、税込みの合計を返します。"""
    total = 0
    for it in items:
        price = it["price"]
        count = it["count"]
        total += price * count
    tax = total * 10 // 100
    return total + tax


def cheapest(items):
    """いちばん安い商品の名前を返します。"""
    best = None
    for it in items:
        if best is None or it["price"] < best["price"]:
            best = it
    return best["name"]
