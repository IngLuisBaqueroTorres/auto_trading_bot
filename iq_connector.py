# iq_connector.py
from iqoptionapi.stable_api import IQ_Option
import time
from config import USERNAME, PASSWORD, BALANCE_TYPE

class IQConnector:
    def __init__(self):
        self.api = IQ_Option(USERNAME, PASSWORD)
        self.api.connect()
        self.api.change_balance(BALANCE_TYPE)

        if self.api.check_connect():
            print("✅ Conectado exitosamente")
        else:
            print("❌ Error de conexión")
            exit()

    def get_balance(self):
        return self.api.get_balance()

    def get_candles(self, pair, size=60, maxdict=10):
        return self.api.get_candles(pair, size, maxdict, time.time())

    def place_trade(self, amount, pair, direction, duration):
        status, id = self.api.buy(amount, pair, direction, duration)
        print("Estado:", status, "ID operación:", id)
        return status, id
