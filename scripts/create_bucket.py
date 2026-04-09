import os
from google.cloud import storage

def create_bucket(bucket_name, project_id, key_path):
    """Creates a new GCS bucket."""
    print(f"Connecting to GCP project: {project_id} using key: {key_path}")
    storage_client = storage.Client.from_service_account_json(key_path)
    
    # Check if bucket already exists
    bucket = storage_client.bucket(bucket_name)
    if bucket.exists():
        print(f"Bucket {bucket_name} already exists.")
        return
    
    # Create new bucket
    bucket = storage_client.create_bucket(bucket_name, location="asia-southeast1")
    print(f"Bucket {bucket.name} created successfully in {bucket.location}.")

if __name__ == "__main__":
    NEW_BUCKET = "crypto-stream-lake-xt89kz"
    PROJECT_ID = "crypto-stream-new"
    KEY_PATH = "gcp-key.json"
    
    try:
        create_bucket(NEW_BUCKET, PROJECT_ID, KEY_PATH)
    except Exception as e:
        print(f"Error creating bucket: {e}")
