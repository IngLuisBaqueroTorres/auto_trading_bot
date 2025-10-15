import pandas as pd
import mplfinance as mpf
import os
import time
from iqoptionapi.stable_api import IQ_Option

# --- Configuración del Backtest ---
from config import EMAIL, PASSWORD, PAIR

CANDLE_DURATION = 60
NUM_CANDLES = 1000


def fetch_historical_data(api, pair, duration, num_candles):
    """Obtiene datos históricos y los guarda en un CSV para reutilizarlos."""
    data_dir = "historical_data"
    os.makedirs(data_dir, exist_ok=True)

    file_path = os.path.join(data_dir, f"{pair}_{duration}s_{num_candles}c.csv")

    if os.path.exists(file_path):
        print(f"Cargando datos desde {file_path}...")
        df = pd.read_csv(file_path, index_col='time', parse_dates=True)
        return df

    print("Descargando nuevos datos históricos...")
    end_time = time.time()
    candles = api.get_candles(pair, duration, num_candles, end_time)

    df = pd.DataFrame(candles)
    df.rename(columns={
        "open": "open",
        "max": "high",
        "min": "low",
        "close": "close",
        "volume": "volume"
    }, inplace=True)
    df["time"] = pd.to_datetime(df["from"], unit="s")
    df.set_index('time', inplace=True)

    df.to_csv(file_path)
    print(f"Datos guardados en {file_path}")
    return df


def run_backtest(strategy_func, df_with_indicators):
    """Ejecuta la simulación de la estrategia sobre los datos históricos."""
    signals = []
    wins = 0
    losses = 0

    df = df_with_indicators.dropna().copy()
    last_signal = None  # ✅ Evita señales duplicadas consecutivas

    # Empezamos desde un índice seguro para tener suficientes datos previos
    for i in range(60, len(df)):
        subset = df.iloc[:i]
        current_candle_time = df.index[i - 1]
        signal = strategy_func(subset, last_signal, current_hour=current_candle_time.hour)


        if signal:
            entry_price = df['close'].iloc[i - 1]
            outcome_price = df['close'].iloc[i]

            # Resultado simple basado en la vela siguiente
            is_win = (signal == "BUY" and outcome_price > entry_price) or \
                     (signal == "SELL" and outcome_price < entry_price)

            if is_win:
                wins += 1
            else:
                losses += 1

            signals.append({
                'time': current_candle_time,
                'signal': signal,
                'price': entry_price
            })
            last_signal = signal  # ✅ Actualiza el último tipo de señal

    return signals, wins, losses


def plot_results(df, signals, strategy_name):
    """Grafica los resultados del backtest, incluso si no hay señales."""
    df = df.copy()
    df['buy_signal'] = float('nan')
    df['sell_signal'] = float('nan')

    for s in signals:
        if s['signal'] == 'BUY':
            df.loc[s['time'], 'buy_signal'] = s['price'] * 0.99
        elif s['signal'] == 'SELL':
            df.loc[s['time'], 'sell_signal'] = s['price'] * 1.01

    df_plot = df.iloc[59:].copy()

    # --- Indicadores principales ---
    add_plots = []
    if {'bb_high', 'bb_low'}.issubset(df_plot.columns):
        add_plots.append(mpf.make_addplot(df_plot[['bb_high', 'bb_low']], alpha=0.4))
    if 'ema200' in df_plot.columns:
        add_plots.append(mpf.make_addplot(df_plot['ema200'], color='purple', width=1.0))
    if 'ema20' in df_plot.columns:
        add_plots.append(mpf.make_addplot(df_plot['ema20'], color='orange', width=0.7))

    # --- Añadir señales si existen ---
    if not df_plot['buy_signal'].isnull().all():
        add_plots.append(mpf.make_addplot(
            df_plot['buy_signal'], type='scatter', marker='^', color='g', markersize=100))
    if not df_plot['sell_signal'].isnull().all():
        add_plots.append(mpf.make_addplot(
            df_plot['sell_signal'], type='scatter', marker='v', color='r', markersize=100))

    if not signals:
        print("\n⚠️  No se detectaron oportunidades claras con la estrategia actual.")
        print("📉 Se muestra el gráfico con los indicadores para análisis visual.\n")

    mpf.plot(
        df_plot,
        type='candle',
        style='yahoo',
        title=f'Backtest de la Estrategia: {strategy_name} en {PAIR}',
        ylabel='Precio',
        addplot=add_plots,
        figsize=(15, 7),
        datetime_format='%Y-%m-%d %H:%M',  # Formato explícito para fecha y hora
        xrotation=45,                     # Rota las etiquetas para que no se solapen
        show_nontrading=False             # Oculta los huecos de tiempo sin datos (fines de semana)
    )


if __name__ == "__main__":
    # --- SELECCIÓN DE ESTRATEGIA ---
    print("\n=== SELECCIONA LA ESTRATEGIA PARA EL BACKTEST ===")
    print("1) Estrategia OTC")
    print("2) Estrategia Normal")
    choice = input("Opción (1/2): ").strip()

    if choice == "1":
        from strategies.bb_rsi_otc import bb_rsi_otc_trend as selected_strategy, add_indicators
        strategy_name = "OTC Trend"
    else:  # Por defecto o si la opción es 2
        from strategies.bb_rsi_normal_trend import bb_rsi_normal_trend as selected_strategy, add_indicators
        strategy_name = "Normal Trend"

    print(f"\nUsando estrategia: {strategy_name}")

    print("Conectando a IQ Option...")
    API = IQ_Option(EMAIL, PASSWORD)
    API.connect()

    if not API.check_connect():
        raise ConnectionError("❌ No se pudo conectar a IQ Option. Verifica tus credenciales o conexión.")

    historical_df = fetch_historical_data(API, PAIR, CANDLE_DURATION, NUM_CANDLES)

    print("Calculando indicadores...")
    df_with_indicators = add_indicators(historical_df.copy())

    print("Ejecutando backtest...")
    signals, wins, losses = run_backtest(selected_strategy, df_with_indicators)

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    print("\n--- 📊 Resultados del Backtest ---")
    print(f"Estrategia: {strategy_name}")
    print(f"Total de Operaciones: {total_trades}")
    print(f"Aciertos (Wins): {wins}")
    print(f"Fallos (Losses): {losses}")
    print(f"Tasa de Éxito: {win_rate:.2f}%")
    print("----------------------------------")

    plot_results(df_with_indicators, signals, strategy_name)
