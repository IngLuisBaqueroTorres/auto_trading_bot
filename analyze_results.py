import os
import re
from datetime import datetime

def analyze_results():
    log_dir = "logs"
    today = datetime.now().strftime("%Y-%m-%d")
    log_filename = f"bot_{today}.log"
    log_path = os.path.join(log_dir, log_filename)

    if not os.path.exists(log_path):
        # Si no existe el de hoy, busca el más reciente
        logs = sorted(
            [f for f in os.listdir(log_dir) if f.startswith("bot_")],
            reverse=True
        )
        if logs:
            log_path = os.path.join(log_dir, logs[0])
            print(f"⚠️ No se encontró el log de hoy. Analizando el más reciente: {logs[0]}")
        else:
            print("❌ No se encontraron logs en la carpeta 'logs/'.")
            return

    print(f"📊 Analizando resultados desde: {log_path}")

    wins = 0
    losses = 0

    try:
        with open(log_path, "r", encoding="utf-8") as file:
            for line in file:
                # Buscamos los textos correctos que genera main.py
                if "Operación GANADA" in line:
                    wins += 1
                elif "Operación PERDIDA" in line:
                    losses += 1
    except Exception as e:
        print(f"⚠️ Error analizando resultados: {e}")
        return

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    print(f"""
📈 RESULTADOS DEL DÍA
──────────────────────────────
🧾 Total operaciones: {total_trades}
✅ Ganadas: {wins}
❌ Perdidas: {losses}
📊 Tasa de acierto: {win_rate:.2f}%
──────────────────────────────
""")

if __name__ == "__main__":
    analyze_results()
