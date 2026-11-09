# 買い物の合計を出す小さな計算機です。
def total_price(goods):
    """商品ごとの小計を足して、税込みの合計を返します。"""
    sum_all = 0
    for entry in goods:
        unit = entry["price"]
        qty = entry["count"]
        sum_all += unit * qty
    charge = sum_all * 10 // 100
    return sum_all + charge


def cheapest(goods):
    """いちばん安い商品の名前を返します。"""
    low = None
    for entry in goods:
        if low is None or entry["price"] < low["price"]:
            low = entry
    return low["name"]
