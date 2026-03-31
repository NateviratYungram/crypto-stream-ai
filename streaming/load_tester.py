import json
import logging
import time
import random
import uuid
import sys
from kafka import KafkaProducer

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("load_tester")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BROKER = 'localhost:9092'
KAFKA_TOPIC = 'trade_stream'
TARGET_TPS = 1000
DURATION_SECONDS = 10

def get_kafka_producer():
    try:
        producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda x: json.dumps(x).encode('utf-8'),
            api_version=(0, 10, 1),
            batch_size=16384,     # Optimize for high throughput
            linger_ms=5           # Wait up to 5ms to batch messages
        )
        logger.info(f"Successfully connected to Kafka at {KAFKA_BROKER}")
        return producer
    except Exception as e:
        logger.error(f"Failed to connect to Kafka: {e}")
        return None

def generate_mock_trade(scenario="normal"):
    """
    Generate a mock Binance trade event based on the requested scenario.
    Valid schema: symbol, price, quantity, timestamp, trade_id, is_buyer_maker
    """
    timestamp = int(time.time() * 1000)
    trade_id = random.randint(1000000000, 9999999999)
    is_buyer_maker = random.choice([True, False])

    if scenario == "normal":
        return {
            "symbol": "BTCUSDT",
            "price": round(random.uniform(60000, 70000), 2),
            "quantity": round(random.uniform(0.001, 0.499), 5), # Below whale threshold
            "timestamp": timestamp,
            "trade_id": trade_id,
            "is_buyer_maker": is_buyer_maker
        }
    elif scenario == "whale":
        return {
            "symbol": "BTCUSDT",
            "price": round(random.uniform(60000, 70000), 2),
            "quantity": round(random.uniform(0.501, 5.0), 5),   # Whale! (>0.5)
            "timestamp": timestamp,
            "trade_id": trade_id,
            "is_buyer_maker": is_buyer_maker
        }
    elif scenario == "invalid_null_qty":
        return {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": None, # DQ Failure -> Should land in DLQ
            "timestamp": timestamp,
            "trade_id": trade_id,
            "is_buyer_maker": is_buyer_maker
        }
    elif scenario == "invalid_negative_price":
        return {
            "symbol": "BTCUSDT",
            "price": -100.0,  # DQ Failure -> DLQ
            "quantity": 0.1,
            "timestamp": timestamp,
            "trade_id": trade_id,
            "is_buyer_maker": is_buyer_maker
        }

def run_load_test():
    producer = get_kafka_producer()
    if not producer:
        logger.error("Exiting due to Kafka connection failure.")
        sys.exit(1)

    logger.info(f"🚀 Starting Load Test: {TARGET_TPS} TPS for {DURATION_SECONDS} seconds...")
    
    total_messages = TARGET_TPS * DURATION_SECONDS
    messages_sent = 0
    start_time = time.time()
    
    # Track statistics
    stats = {
        "normal": 0,
        "whale": 0,
        "invalid": 0
    }

    try:
        for i in range(total_messages):
            # Distribution: 90% Normal, 5% Whale, 5% Invalid
            rand_val = random.random()
            scenario_stat = None
            if rand_val < 0.90:
                scenario = "normal"
            elif rand_val < 0.95:
                scenario = "whale"
            elif rand_val < 0.975:
                scenario = "invalid_null_qty"
                scenario_stat = "invalid"
            else:
                scenario = "invalid_negative_price"
                scenario_stat = "invalid"
                
            stats_key = scenario_stat if scenario_stat else scenario
            stats[stats_key] += 1

            trade_data = generate_mock_trade(scenario)
            producer.send(KAFKA_TOPIC, value=trade_data)
            messages_sent += 1
            
            # Simple TPS pacing control (flush every sec or sleep)
            if i > 0 and i % TARGET_TPS == 0:
                producer.flush()
                elapsed = time.time() - start_time
                expected_elapsed = messages_sent / TARGET_TPS
                if elapsed < expected_elapsed:
                    time.sleep(expected_elapsed - elapsed)
                logger.info(f"Progress: {messages_sent}/{total_messages} messages sent...")

        # Final flush
        producer.flush()
        end_time = time.time()
        actual_duration = end_time - start_time
        actual_tps = messages_sent / actual_duration

        logger.info("\n" + "="*50)
        logger.info("✅ Load Test Completed Successfully!")
        logger.info("="*50)
        logger.info(f"Total Time:      {actual_duration:.2f} seconds")
        logger.info(f"Total Messages:  {messages_sent}")
        logger.info(f"Actual TPS:      {actual_tps:.2f} trades/sec")
        logger.info("--- Message Distribution ---")
        logger.info(f"Normal Trades:   {stats['normal']}")
        logger.info(f"Whale Trades:    {stats['whale']} (>0.5 BTC - should trigger Flink Alerts)")
        logger.info(f"Invalid Trades:  {stats['invalid']} (Should be routed to DLQ & data_quality_log)")
        logger.info("==================================================")

    except KeyboardInterrupt:
        logger.info("Load test interrupted by user.")
    finally:
        producer.close()

if __name__ == "__main__":
    run_load_test()
