# optimize_strategy.py
import pandas as pd
import json
import os

LOG_FILE = "results/backtest_10.csv"
CONFIG_PATH = "strategies/bot/self_adjusting_v5_config.json"

def optimize():
    if not os.path.exists(LOG_FILE):
        print("Ejecuta backtest primero")
        return

    df = pd.read_csv(LOG_FILE)
    if len(df) < 10:
        print("Menos de 10 trades")
        return

    wins = df[df['result'] == 'win']
    losses = df[df['result'] == 'loss']

    config = json.load(open(CONFIG_PATH))
    normal = config["NORMAL_PARAMS"]
    filters = config["FILTERS"]

    if len(wins) > 0:
        normal['RSI_OVERBOUGHT'] = int(wins[wins['direction'] == 'put']['rsi'].mean())
        normal['RSI_OVERSOLD'] = int(wins[wins['direction'] == 'call']['rsi'].mean())

    winrate = len(wins) / len(df)
    if winrate < 0.55:
        filters['CONFIRMATIONS_TO_ENTER'] += 1
    elif winrate > 0.70:
        filters['CONFIRMATIONS_TO_ENTER'] = max(1, filters['CONFIRMATIONS_TO_ENTER'] - 1)

    json.dump(config, open(CONFIG_PATH, 'w'), indent=4)
    print(f"Optimizado | Winrate: {winrate:.2%} | Conf: {filters['CONFIRMATIONS_TO_ENTER']}")

if __name__ == "__main__":
    optimize()