import os
import boto3
import time
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
table = dynamodb.Table('license-plate-numbers')

def insert_test_plate(car_id, license_plate, confidence=75.5):
    """Insert a test license plate matching your structure"""

    current_timestamp = time.time()

    item = {
        'car_id': str(car_id),
        'license_plate_number': license_plate,
        'confidence': Decimal(str(confidence)),
        'timestamp': Decimal(str(current_timestamp)),
        'processing_time': Decimal('0.65')
    }

    response = table.put_item(Item=item)

    print(f"Inserted plate: {license_plate} (car_id: {car_id}, confidence: {confidence}%)")
    print(f"  Timestamp: {current_timestamp}")
    print(f"  Response: {response['ResponseMetadata']['HTTPStatusCode']}")

    return response

if __name__ == "__main__":
    print("Testing DynamoDB insert with YOUR structure...\n")

    insert_test_plate(car_id=100, license_plate="LP14LJA", confidence=99.5)

    print("\nWaiting 3 seconds...")
    time.sleep(3)

    insert_test_plate(car_id=100, license_plate="LP14LJA", confidence=85.0)

    print("\nAll test plates inserted!")
    print("Check CloudWatch Logs and Home Assistant for results")
