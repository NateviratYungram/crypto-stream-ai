import json
import logging
from kafka import KafkaConsumer
import sys
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_TOPIC = 'trade_stream'
KAFKA_BROKER = 'localhost:9092'

def verify_data():
    logger.info("Starting verification consumer...")
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            group_id='verifier_group',
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            consumer_timeout_ms=10000  # Stop after 10 seconds if no message
        )
    except Exception as e:
        logger.error(f"Failed to connect to Kafka: {e}")
        return

    logger.info(f"Listening to topic '{KAFKA_TOPIC}' for up to 10 seconds...")
    
    count = 0
    start_time = time.time()
    
    for message in consumer:
        data = message.value
        logger.info(f"SUCCESS: Received trade: {data['symbol']} Price: {data['price']}")
        count += 1
        if count >= 3:
            logger.info("Verification Successful: Received 3 messages.")
            sys.exit(0)

    if count == 0:
        logger.error("FAILED: No messages received after 10 seconds. Is the producer running?")
        sys.exit(1)

if __name__ == "__main__":
    verify_data()
