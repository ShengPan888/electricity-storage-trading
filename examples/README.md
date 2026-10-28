# 可公开的合成样例

`synthetic_predictions.csv` 的96行价格全部由本项目 `demo()` 函数人为生成。
它不包含官方比赛的原始数据、预测结果或隐藏标签，也不构成比赛收益证据。

没有比赛数据也可以运行：

```shell
python run.py backtest --predictions examples/synthetic_predictions.csv --output outputs/example
```

或者重新生成并运行整个合成演示：

```shell
python run.py demo
```
