import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

from intelligence.ml.signal_model import train_model, TRAIN_SYMBOLS

try:
    print("Running train_model...")
    result = train_model(symbols=TRAIN_SYMBOLS, limit=1000)
    print("Result:", result)
except Exception as e:
    import traceback
    traceback.print_exc()
