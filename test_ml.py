import logging
logging.basicConfig(level=logging.DEBUG)

from intelligence.crypto_intelligence import CryptoIntelligence
intel = CryptoIntelligence(client=None)

signals = intel.get_quick_signals(['BTC'])
for s in signals:
    print(s)
