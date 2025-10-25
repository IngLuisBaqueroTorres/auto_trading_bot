# Para este proyecto se necesita instalar lo siguiente
* iqoptionapi
* pandas
* python-dotenv

pip install -r requirements.txt


# Uso
* python3 main.py
# 🧠 Auto Trading Bot (IQ Option)

Bot de trading automatizado que utiliza indicadores técnicos (RSI + EMAs) para identificar oportunidades de compra y venta en IQ Option.

## 🚀 Características

- Estrategia basada en cruce de EMAs y niveles extremos de RSI.
- Conexión automática al entorno real o demo.
- Modular: fácilmente extendible con nuevas estrategias.
- Pares de divisas configurables.

## 🛠️ Requisitos

- Python 3.10+
- IQOptionAPI
- Cuenta de IQ Option

## ⚠️ Disclaimer
Este proyecto es educativo. No se garantiza rendimiento ni beneficios. Usar bajo tu propio riesgo.

## 📦 Instalación

```bash
git clone https://github.com/tuusuario/auto_trading_bot.git
cd auto_trading_bot
pip install -r requirements.txt


Ejecuta tu bot normalmente durante el día:

python main.py


Al finalizar la jornada, detén el bot y ejecuta:

python analyze_results.py


Verás un resumen como este en consola:

📊 === RESUMEN DE OPERACIONES ===
🕒 Desde: 2025-10-07 07:05:12 hasta 2025-10-07 18:55:23
💼 Total de operaciones: 42
✅ Ganadas: 26 | ❌ Perdidas: 16
🎯 Tasa de acierto: 61.90%
💰 Ganancia neta: 12.50 (1.25%)
📉 Drawdown máximo: -3.10%
⏱️ Promedio entre operaciones: 15.2 min

Y además se abrirá una gráfica del balance 📈 donde verás claramente los momentos de ganancia o pérdida.