from iqoptionapi.stable_api import IQ_Option
import logging
import time
logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(message)s')
EMAIL='iingeduardobt123@gmail.com'
PASSWORD='1IAgenesis1'
I_want_money=IQ_Option(EMAIL,PASSWORD)
goal="EURUSD"
print("get candles")
print(I_want_money.get_candles(goal,60,111,time.time()))
Money=1
ACTIVES="EURUSD"
ACTION="call"#or "put"
expirations_mode=1

check,id=I_want_money.buy(Money,ACTIVES,ACTION,expirations_mode)
if check:
    print("!buy!")
else:
    print("buy fail")