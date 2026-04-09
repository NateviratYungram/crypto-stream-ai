import os
import subprocess
import time
import urllib.request
import sys

def create_directories():
    directories = [
        "airflow",
        "datalake",
        "infrastructure",
        "mcp_server",
        "streaming",
        "visualization"
    ]
    base_dir = os.getcwd()
    print(f"Creating directories in {base_dir}...")
    for dir_name in directories:
        path = os.path.join(base_dir, dir_name)
        try:
            os.makedirs(path, exist_ok=True)
            print(f"Created: {dir_name}")
        except Exception as e:
            print(f"Failed to create {dir_name}: {e}")

def run_docker_compose():
    print("\nStarting Docker Compose...")
    try:
        # Check if docker-compose.yml exists
        if not os.path.exists("docker-compose.yml"):
            print("Error: docker-compose.yml not found!")
            return

        subprocess.run(["docker", "compose", "up", "-d"], check=True)
        print("Docker Compose started successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error running docker compose: {e}")
    except FileNotFoundError:
        print("Error: docker command not found. Please ensure Docker is installed and in PATH.")

def verify_services():
    print("\nVerifying services...")
    time.sleep(5) # Wait for services to spin up
    try:
        result = subprocess.run(["docker", "compose", "ps"], capture_output=True, text=True)
        print(result.stdout)
    except Exception as e:
        print(f"Error checking docker status: {e}")

    # Check Kafka UI
    print("Checking Kafka UI on port 8080...")
    try:
        with urllib.request.urlopen("http://localhost:8080", timeout=5) as response:
             print(f"Kafka UI Status: {response.getcode()}")
    except Exception as e:
        print(f"Could not connect to Kafka UI: {e}")

if __name__ == "__main__":
    create_directories()
    run_docker_compose()
    verify_services()
