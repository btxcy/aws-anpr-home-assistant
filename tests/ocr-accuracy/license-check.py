import boto3
import os

from dotenv import load_dotenv

load_dotenv()

s3_client = boto3.client('s3', region_name=os.environ['AWS_REGION'])
BUCKET_NAME = os.environ['S3_BUCKET_NAME']

car_ids = ['179', '88', '69', '92', '78', '171', '7', '32', '82', '139',
           '149', '1', '144', '112', '136', '22']

os.makedirs('validation_images', exist_ok=True)

response = s3_client.list_objects_v2(Bucket=BUCKET_NAME)

downloaded = []
for obj in response.get('Contents', []):
    key = obj['Key']
    car_id = key.split('_')[0]

    if car_id in car_ids:
        local_path = f"validation_images/{key}"
        s3_client.download_file(BUCKET_NAME, key, local_path)
        downloaded.append((car_id, key))
        print(f"Downloaded: {key}")

print(f"\nTotal images downloaded: {len(downloaded)}")
print(f"Images saved to: validation_images/")
