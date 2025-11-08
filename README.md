# 🧠 Auto Trading Bot (IQ Option)

Bot de trading automatizado para IQ Option con una interfaz gráfica completa, múltiples estrategias, y un sistema de auto-optimización.

## 🚀 Características

- **Interfaz Gráfica (GUI)**: Gestiona toda la aplicación desde una ventana amigable.
- **Múltiples Estrategias**: Elige entre varias estrategias predefinidas.
- **Estrategia Auto-Ajustable**: Una estrategia "BOT" que aprende y se optimiza después de cada sesión.
- **Configuración Dinámica**: Cambia parámetros como par, monto, stop-loss/win directamente desde la GUI.
- **Backtesting y Análisis**: Herramientas integradas para probar estrategias y analizar resultados.
- **Gestión Segura de Credenciales**: Usa un archivo `.env` para mantener tus datos seguros.

## 🛠️ Requisitos

- Python 3.10+
- Dependencias listadas en `requirements.txt`.
- Cuenta de IQ Option

## ⚠️ Disclaimer

Este proyecto es educativo. No se garantiza rendimiento ni beneficios. Usar bajo tu propio riesgo.

## 📦 Instalación y Configuración

```bash
git clone https://github.com/tuusuario/auto_trading_bot.git
cd auto_trading_bot
pip install -r requirements.txt
```

1.  **Crear archivo de entorno**:
    Copia el archivo de ejemplo `.env.example` a un nuevo archivo llamado `.env`.
    ```bash
    # En Windows
    copy .env.example .env
    # En Linux/macOS
    cp .env.example .env
    ```
2.  **Añadir credenciales**:
    Abre el nuevo archivo `.env` y rellena tu email y contraseña de IQ Option.

## ▶️ Uso

1.  **Iniciar la aplicación**:
    Ejecuta la interfaz gráfica.
    ```bash
    python gui_app.py
    ```
2.  **Configurar**:
    Usa el menú `☰ Menú` -> `⚙️ Configuración` para ajustar los parámetros de trading (monto, par, stop loss, etc.) y guarda los cambios.
3.  **Ejecutar**:
    - **Trading en vivo**: Ve a `📈 Estrategias`, selecciona una y haz clic en `▶ Iniciar Bot en Vivo`.
    - **Backtesting**: Usa la opción `⏪ Ejecutar Backtest` del menú.
    - **Análisis**: Usa la opción `📊 Analizar Resultados` para revisar el rendimiento de sesiones pasadas.

## 🧪 Backtesting (Línea de Comandos)

Para probar una estrategia con datos históricos desde la terminal, sigue estos pasos:

1.  **Generar datos de velas**:
    Este comando descarga los datos históricos necesarios para el backtest.
    ```bash
    py fetch_candles.py
    ```

2.  **Ejecutar el backtest**:
    Usa `backtest_runner.py` seguido del número de la estrategia que quieres probar.
    ```bash
    # Ejemplo para probar la estrategia 10
    py backtest_runner.py 10
    ```
    Puedes encontrar el número de cada estrategia en `utils/strategy_selector.py`.
