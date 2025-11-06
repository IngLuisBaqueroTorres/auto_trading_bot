# gui_app.py
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel
import subprocess
import os
import importlib
from dotenv import load_dotenv

from utils.strategy_selector import AVAILABLE_STRATEGIES
from utils.config_manager import get_settings, save_settings

class TradingBotGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Auto Trading Bot")
        self.geometry("800x600")

        self.container = ttk.Frame(self)
        self.container.pack(side="top", fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.create_menu()

        self.frames = {}
        for F in (WelcomePage, StrategyPage, SettingsPage):
            page_name = F.__name__
            frame = F(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("WelcomePage")

    def create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # Menú de opciones
        options_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="☰ Menú", menu=options_menu)
        
        options_menu.add_command(label="🏠 Inicio", command=lambda: self.show_frame("WelcomePage"))
        options_menu.add_command(label="📈 Estrategias", command=lambda: self.show_frame("StrategyPage"))
        options_menu.add_separator()
        options_menu.add_command(label="📊 Analizar Resultados", command=self.run_analysis)
        options_menu.add_command(label="⏪ Ejecutar Backtest", command=self.run_backtest_selector)
        options_menu.add_separator()
        options_menu.add_command(label="⚙️ Configuración", command=lambda: self.show_frame("SettingsPage"))
        options_menu.add_separator()
        options_menu.add_command(label="🚪 Salir", command=self.quit)

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if hasattr(frame, 'on_show'): # Llama a on_show si existe para refrescar datos
            frame.on_show()
        frame.tkraise()

    def run_script_in_terminal(self, command):
        try:
            # Abre una nueva terminal y ejecuta el comando
            subprocess.Popen(f'start cmd /k {" ".join(command)}', shell=True)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo ejecutar el script:\n{e}")

    def run_analysis(self):
        messagebox.showinfo("Análisis", "Se abrirá una terminal para ejecutar el análisis de resultados.")
        self.run_script_in_terminal(["python", "analyze_results.py"])

    def run_backtest_selector(self):
        # Crea una ventana emergente para seleccionar la estrategia de backtest
        selector = Toplevel(self)
        selector.title("Seleccionar Estrategia para Backtest")
        
        ttk.Label(selector, text="Elige la estrategia para el backtest:").pack(padx=20, pady=10)
        
        strategy_var = tk.StringVar()
        strategy_menu = ttk.Combobox(selector, textvariable=strategy_var, state="readonly")
        strategy_menu['values'] = [f"{key}: {details['name']}" for key, details in AVAILABLE_STRATEGIES.items()]
        strategy_menu.pack(padx=20, pady=5)
        strategy_menu.set("Selecciona una...")

        def on_confirm():
            selection = strategy_var.get()
            if not selection or selection == "Selecciona una...":
                messagebox.showwarning("Advertencia", "Debes seleccionar una estrategia.")
                return
            
            strategy_key = selection.split(':')[0]
            selector.destroy()
            messagebox.showinfo("Backtest", f"Iniciando backtest para '{selection}'.\nSe abrirá una terminal.")
            # Pasamos la clave de la estrategia como argumento al script
            self.run_script_in_terminal(["python", "backtest.py", strategy_key])

        ttk.Button(selector, text="Iniciar Backtest", command=on_confirm).pack(pady=20)


class WelcomePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        label = ttk.Label(self, text="Bienvenido al Bot de Trading", font=("Helvetica", 24, "bold"))
        label.place(relx=0.5, rely=0.4, anchor="center")
        
        sub_label = ttk.Label(self, text="Usa el menú ☰ para navegar por las opciones.", font=("Helvetica", 12))
        sub_label.place(relx=0.5, rely=0.5, anchor="center")


class StrategyPage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        label = ttk.Label(self, text="Selecciona una Estrategia para Iniciar", font=("Helvetica", 18, "bold"))
        label.pack(pady=20)

        self.strategy_var = tk.StringVar()
        
        for key, details in AVAILABLE_STRATEGIES.items():
            rb = ttk.Radiobutton(self, text=details['name'], variable=self.strategy_var, value=key)
            rb.pack(anchor='w', padx=50, pady=5)
            
        start_button = ttk.Button(self, text="▶ Iniciar Bot en Vivo", command=self.start_bot)
        start_button.pack(pady=30, ipadx=20, ipady=10)

    def start_bot(self):
        strategy_key = self.strategy_var.get()
        if not strategy_key:
            messagebox.showwarning("Sin Selección", "Por favor, selecciona una estrategia antes de iniciar.")
            return
        
        strategy_name = AVAILABLE_STRATEGIES[strategy_key]['name']
        if messagebox.askyesno("Confirmar Inicio", f"¿Estás seguro de que quieres iniciar el bot con la estrategia '{strategy_name}'?"):
            self.controller.run_script_in_terminal(["python", "main.py", strategy_key])


class SettingsPage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.vars = {
            "EMAIL": tk.StringVar(),
            "PASSWORD": tk.StringVar(),
            "BALANCE_MODE": tk.StringVar(),
            "PAIR": tk.StringVar(),
            "AMOUNT": tk.DoubleVar(),
            "DURATION": tk.IntVar(),
            "STOP_WIN": tk.DoubleVar(),
            "STOP_LOSS": tk.DoubleVar(),
            # Nuevas variables para el Trailing Stop
            "TRAILING_STOP_ENABLED": tk.BooleanVar(),
            "TRAILING_STOP_WIN_PERCENT": tk.DoubleVar(),
            "TRAILING_STOP_LOSS_PERCENT": tk.DoubleVar(),
        }

        frame = ttk.Frame(self, padding="20")
        frame.pack(expand=True)

        ttk.Label(frame, text="Configuración General", font=("Helvetica", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=20)

        # Campos del formulario
        self.create_entry(frame, "Email:", self.vars["EMAIL"], 1)
        self.create_entry(frame, "Contraseña:", self.vars["PASSWORD"], 2, show="*")
        
        # Selector de modo de cuenta
        ttk.Label(frame, text="Modo de Cuenta:").grid(row=3, column=0, sticky="w", pady=5, padx=5)
        balance_mode_menu = ttk.Combobox(frame, textvariable=self.vars["BALANCE_MODE"], state="readonly", width=28)
        balance_mode_menu['values'] = ["PRACTICE", "REAL"]
        balance_mode_menu.grid(row=3, column=1, pady=5, padx=5)
        
        # Selector de moneda
        ttk.Label(frame, text="Par de Divisas:").grid(row=4, column=0, sticky="w", pady=5, padx=5)
        self.pair_menu = ttk.Combobox(frame, textvariable=self.vars["PAIR"], state="readonly", width=28)
        self.pair_menu.grid(row=4, column=1, pady=5, padx=5)

        self.create_entry(frame, "Monto por Operación ($):", self.vars["AMOUNT"], 5) # Sin guardar referencia
        self.create_entry(frame, "Duración (minutos):", self.vars["DURATION"], 6) # Sin guardar referencia
        self.stop_win_widgets = self.create_entry(frame, "Stop Win ($):", self.vars["STOP_WIN"], 7)
        self.stop_loss_widgets = self.create_entry(frame, "Stop Loss ($):", self.vars["STOP_LOSS"], 8)
        
        # --- Trailing Stop ---
        ttk.Separator(frame, orient='horizontal').grid(row=9, column=0, columnspan=2, sticky='ew', pady=15)
        
        self.trailing_switch = ttk.Checkbutton(frame, text="Activar Trailing Stop Porcentual", variable=self.vars["TRAILING_STOP_ENABLED"], command=self.toggle_trailing_fields)
        self.trailing_switch.grid(row=10, column=0, columnspan=2, sticky="w", padx=5)

        self.trailing_win_label = self.create_entry(frame, "Reajuste de Ganancia (%):", self.vars["TRAILING_STOP_WIN_PERCENT"], 11)
        self.trailing_loss_label = self.create_entry(frame, "Nuevo Stop Loss (% sobre ganancia):", self.vars["TRAILING_STOP_LOSS_PERCENT"], 12)

        save_button = ttk.Button(frame, text="Guardar Configuración", command=self.save)
        save_button.grid(row=13, column=0, columnspan=2, pady=30, ipadx=10, ipady=5)

        self.load_currency_pairs()
        self.on_show()

    def create_entry(self, parent, text, var, row, show=None):
        label = ttk.Label(parent, text=text)
        label.grid(row=row, column=0, sticky="w", pady=5, padx=5)
        entry = ttk.Entry(parent, textvariable=var, show=show, width=30)
        entry.grid(row=row, column=1, pady=5, padx=5)
        return label, entry # Devolvemos los widgets para poder ocultarlos

    def toggle_trailing_fields(self):
        """Muestra u oculta los campos de configuración del trailing stop."""
        is_trailing_enabled = self.vars["TRAILING_STOP_ENABLED"].get()
        
        trailing_state = "normal" if is_trailing_enabled else "disabled"
        normal_stop_state = "disabled" if is_trailing_enabled else "normal"

        # Activa/desactiva los campos del Trailing Stop
        for label, entry in [self.trailing_win_label, self.trailing_loss_label]:
            label.config(state=trailing_state)
            entry.config(state=trailing_state)
            
        # Activa/desactiva los campos de Stop Win/Loss normales
        for label, entry in [self.stop_win_widgets, self.stop_loss_widgets]:
            label.config(state=normal_stop_state)
            entry.config(state=normal_stop_state)

    def load_currency_pairs(self):
        try:
            with open("currencies.txt", "r") as f:
                pairs = [line.strip() for line in f if line.strip()]
                self.pair_menu['values'] = pairs
        except FileNotFoundError:
            self.pair_menu['values'] = ["EURUSD-OTC"]
            messagebox.showwarning("Archivo no encontrado", "No se encontró 'currencies.txt'. Se usará un valor por defecto.")

    def on_show(self):
        """Carga la configuración actual cuando se muestra la página."""
        settings = get_settings()
        load_dotenv() # Carga las variables de .env para os.getenv()
        
        self.vars["EMAIL"].set(os.getenv("EMAIL", ""))
        self.vars["PASSWORD"].set(os.getenv("PASSWORD", ""))
        self.vars["BALANCE_MODE"].set(settings.get("BALANCE_MODE"))
        self.vars["PAIR"].set(settings.get("PAIR"))
        self.vars["AMOUNT"].set(settings.get("AMOUNT"))
        self.vars["DURATION"].set(settings.get("DURATION"))
        self.vars["STOP_WIN"].set(settings.get("STOP_WIN"))
        self.vars["STOP_LOSS"].set(settings.get("STOP_LOSS"))
        # Cargar nuevos valores
        self.vars["TRAILING_STOP_ENABLED"].set(settings.get("TRAILING_STOP_ENABLED", False))
        self.vars["TRAILING_STOP_WIN_PERCENT"].set(settings.get("TRAILING_STOP_WIN_PERCENT", 2.0))
        self.vars["TRAILING_STOP_LOSS_PERCENT"].set(settings.get("TRAILING_STOP_LOSS_PERCENT", 1.0))

        self.toggle_trailing_fields() # Actualizar visibilidad de campos

    def save(self):
        """Guarda la configuración actual en los archivos."""
        try:
            new_settings = {key: var.get() for key, var in self.vars.items()}
            
            # Validaciones simples
            if not new_settings["EMAIL"] or "@" not in new_settings["EMAIL"]:
                raise ValueError("El email no es válido.")
            if new_settings["AMOUNT"] <= 0 or new_settings["DURATION"] <= 0:
                raise ValueError("El monto y la duración deben ser mayores a cero.")

            save_settings(new_settings)
            messagebox.showinfo("Éxito", "La configuración se ha guardado correctamente.")
        except Exception as e:
            messagebox.showerror("Error al Guardar", f"No se pudo guardar la configuración:\n{e}")


if __name__ == "__main__":
    app = TradingBotGUI()
    app.mainloop()