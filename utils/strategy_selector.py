import importlib

# ----------------- ESTRATEGIAS DISPONIBLES -----------------
# Centralizamos aquí todas las estrategias para que sean fáciles de gestionar.
# La clave es la opción del menú, y el valor contiene el nombre, módulo y función.
AVAILABLE_STRATEGIES = {
    "1": {
        "name": "OTC1 (Original)",
        "module": "strategies.bb_rsi_otc",
        "function": "bb_rsi_otc_trend",
    },
    "2": {
        "name": "OTC Balanced (Focus 9-11h)",
        "module": "strategies.bb_rsi_otc_balanced",
        "function": "strategy_bb_rsi_otc_balanced_v2_focus",
    },
    "3": {
        "name": "OTC2 (Más Entradas)",
        "module": "strategies.bb_rsi_otc_2",
        "function": "bb_rsi_otc_trend",
    },
    "4": {
        "name": "Real Trend v2 (Score-based)",
        "module": "strategies.bb_rsi_real_trend_v2",
        "function": "bb_rsi_real_trend_v2",
    },
    "5": {
        "name": "Normal Trend (Pullback)",
        "module": "strategies.bb_rsi_normal_trend",
        "function": "bb_rsi_normal_trend",
    },
}

def select_strategy():
    """
    Muestra un menú interactivo para seleccionar una estrategia de trading.
    Importa dinámicamente la función de la estrategia seleccionada.

    Returns:
        tuple: Una tupla conteniendo (función_estrategia, nombre_estrategia).
               Retorna (None, None) si la selección es inválida.
    """
    print("\n=== SELECCIONA LA ESTRATEGIA A USAR ===")
    for key, details in AVAILABLE_STRATEGIES.items():
        print(f"{key}) {details['name']}")

    choice = input("Opción: ").strip()
    strategy_info = AVAILABLE_STRATEGIES.get(choice)

    if not strategy_info:
        print(f"❌ Opción '{choice}' inválida.")
        return None, None

    module = importlib.import_module(strategy_info["module"])
    strategy_function = getattr(module, strategy_info["function"])
    
    # Devolvemos tanto la función como su nombre para usar en logs y gráficos
    return strategy_function, strategy_info["name"]