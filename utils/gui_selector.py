# utils/gui_selector.py
import tkinter as tk
from tkinter import ttk
import importlib
from utils.strategy_selector import AVAILABLE_STRATEGIES

class StrategySelectorGUI:
    """
    Clase que encapsula la lógica de la GUI para seleccionar una estrategia.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("Selector de Estrategia del Bot")
        self.root.geometry("400x320")
        self.root.resizable(False, False)

        self.selected_strategy_key = tk.StringVar()
        self.result = (None, None)

        self.center_window()
        self.create_widgets()

    def center_window(self):
        """Centra la ventana en la pantalla."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def create_widgets(self):
        """Crea y posiciona los widgets en la ventana."""
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        label = ttk.Label(main_frame, text="Selecciona la estrategia a utilizar:", font=("Helvetica", 12, "bold"))
        label.pack(pady=(0, 15))

        # Crear un Radiobutton por cada estrategia disponible
        for key, details in AVAILABLE_STRATEGIES.items():
            rb = ttk.Radiobutton(main_frame, text=details['name'], variable=self.selected_strategy_key, value=key)
            rb.pack(anchor='w', pady=2)

        # Botón para confirmar la selección
        start_button = ttk.Button(main_frame, text="Iniciar Bot", command=self.on_start)
        start_button.pack(pady=(20, 0), ipadx=10, ipady=5)

    def on_start(self):
        """
        Se ejecuta al presionar el botón. Procesa la selección,
        carga la estrategia y cierra la ventana.
        """
        choice = self.selected_strategy_key.get()
        strategy_info = AVAILABLE_STRATEGIES.get(choice)

        if strategy_info:
            module = importlib.import_module(strategy_info["module"])
            strategy_function = getattr(module, strategy_info["function"])
            self.result = (strategy_function, strategy_info["name"])
        
        self.root.destroy() # Cierra la ventana de Tkinter

def select_strategy_gui():
    """
    Función principal que lanza la GUI y devuelve la estrategia seleccionada.
    """
    root = tk.Tk()
    app = StrategySelectorGUI(root)
    root.mainloop() # Bloquea la ejecución hasta que la ventana se cierre
    return app.result

if __name__ == '__main__':
    # Para probar la ventana de forma independiente
    strategy_func, strategy_name = select_strategy_gui()
    if strategy_func:
        print(f"Estrategia seleccionada: {strategy_name}")
        print(f"Función: {strategy_func}")