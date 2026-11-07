import os
import boto3
import random

from dotenv import load_dotenv

load_dotenv()

dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
s3_client = boto3.client('s3', region_name=os.environ['AWS_REGION'])

ocr_table = dynamodb.Table('lambda-performance-metrics')
response = ocr_table.scan()
items = response['Items']

sample_size = 25
sample = random.sample(items, min(sample_size, len(items)))

print(f"Sample {len(sample)} detections for manual validation:\n")
print(f"{'#':<4} {'Car ID':<10} {'License Plate':<15} {'Confidence':<12} {'S3 Key'}")
print("="*80)

for i, item in enumerate(sample, 1):
    car_id = item['car_id']
    plate = item['license_plate']
    confidence = float(item['confidence'])

    print(f"{i:<4} {car_id:<10} {plate:<15} {confidence:>5.1f}%")
