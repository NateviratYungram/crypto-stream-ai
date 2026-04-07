import json
import logging
import os
import websocket
from kafka import KafkaProducer
from kafka.errors import KafkaError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Kafka Configuration
# KAFKA_BROKER is overridden by the 'ingestion-producer' Docker Compose service
# to use the internal address kafka:29092. Defaults to localhost for local dev.
KAFKA_BROKER = os.environ.get('KAFKA_BROKER', 'localhost:9092')
KAFKA_TOPIC = 'trade_stream'

# Binance WebSocket URL
# Symbol: btcusdt, Stream: trade
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"

# Global Producer (initialised in main())
producer = None
message_count = 0

def get_kafka_producer():
    """Initializes and returns a Kafka producer."""
    try:
        _producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda x: json.dumps(x).encode('utf-8'),
            api_version=(0, 10, 1) # Force API version if auto-detect fails
        )
        logger.info("Successfully connected to Kafka")
        return _producer
    except Exception as e:
        logger.error(f"Failed to connect to Kafka: {e}")
        return None

def on_message(ws, message):
    """Callback for WebSocket messages."""
    global message_count
    try:
        data = json.loads(message)
        
        # Extract relevant fields
        # https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#trade
        processed_data = {
            "symbol": data.get("s"),
            "price": float(data.get("p")),
            "quantity": float(data.get("q")),
            "timestamp": data.get("T"),
            "trade_id": data.get("t"),
            "is_buyer_maker": data.get("m")
        }

        # Send to Kafka
        if producer:
            future = producer.send(KAFKA_TOPIC, value=processed_data)
            # future.get(timeout=10) # Synchronous send for debugging if needed
            
            message_count += 1
            if message_count % 10 == 0:
                logger.info(f"Sent {message_count} messages to Kafka topic '{KAFKA_TOPIC}'. Last price: {processed_data['price']}")

    except Exception as e:
        logger.error(f"Error processing message: {e}")

def on_error(ws, error):
    """Callback for WebSocket errors."""
    logger.error(f"WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    """Callback for WebSocket close."""
    logger.info("WebSocket connection closed")
    if producer:
        producer.close()

def on_open(ws):
    """Callback for WebSocket open."""
    logger.info("WebSocket connection opened. Subscribing to trade stream...")

def main():
    global producer
    producer = get_kafka_producer()
    
    if not producer:
        logger.error("Exiting due to Kafka connection failure. Please confirm Kafka is running.")
        return

    # websocket.enableTrace(True) # Uncomment for debug trace
    ws = websocket.WebSocketApp(
        BINANCE_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        logger.info("Stopping producer...")
        if producer:
            producer.close()

if __name__ == "__main__":
    main()
