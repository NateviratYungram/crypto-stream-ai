import socket
import sys

SERVICES = {
    'Zookeeper': 2181,
    'Kafka': 9092,
    'PostgreSQL': 5432,
    'Kafka UI': 8080,
    'Flink JobManager': 8081
}

def check_port(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((host, port))
        s.close()
        return True
    except:
        return False

def main():
    print("Checking services...")
    all_up = True
    for service, port in SERVICES.items():
        if check_port('localhost', port):
            print(f"[OK] {service} is reachable on port {port}")
        else:
            print(f"[FAIL] {service} is NOT reachable on port {port}")
            all_up = False
    
    if all_up:
        print("\nAll critical services are UP.")
    else:
        print("\nSome services are DOWN. Please check 'docker compose ps'.")

if __name__ == "__main__":
    main()
