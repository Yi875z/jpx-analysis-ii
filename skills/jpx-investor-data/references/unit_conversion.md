# 先物単位換算ガイド

JPXの先物データは「枚数」で公表される。現物（億円）と合算するために換算が必要。

## 換算係数（目安）

| 先物種別 | 1枚あたり想定元本 | 備考 |
|---------|----------------|------|
| 日経225先物（ラージ） | 日経平均 × 1,000円 | 例: 38,000円 × 1,000 = 3,800万円/枚 |
| 日経225mini | 日経平均 × 100円 | ラージの1/10 |
| TOPIXラージ | TOPIX × 10,000円 | 例: 2,700 × 10,000 = 2,700万円/枚 |
| TOPIXmini | TOPIX × 1,000円 | ラージの1/10 |

## 換算式

```python
def futures_to_oku(net_lots, futures_type, index_value):
    """
    net_lots: ネット枚数（買建 - 売建）
    futures_type: 'nikkei225_large' / 'nikkei225_mini' / 'topix_large' / 'topix_mini'
    index_value: 当週末の指数終値
    returns: 億円換算値
    """
    multiplier = {
        'nikkei225_large': 1000,
        'nikkei225_mini': 100,
        'topix_large': 10000,
        'topix_mini': 1000,
    }
    yen_per_lot = index_value * multiplier[futures_type]
    total_yen = net_lots * yen_per_lot
    return total_yen / 1e8  # 億円
```

## 指数終値の取得

スクリプト内で `scripts/fetch_jpx.py` が指数終値も合わせて取得する。
取得できない場合はユーザーに入力を求める。
