# Reads the OCR Lambda timing records from DynamoDB and prints the average time of each step (download, OCR, validation, database, queue) and the average OCR confidence.
# Created: 2025-12-17

import os
import boto3

from dotenv import load_dotenv

load_dotenv()

dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
table = dynamodb.Table('lambda-performance-metrics')

response = table.scan()
items = response['Items']

data = []
for item in items:
    data.append({
        'total': float(item['total_time']),
        'download': float(item['download_time']),
        'ocr': float(item['ocr_time']),
        'validation': float(item['validation_time']),
        'database': float(item['database_time']),
        'sqs': float(item['sqs_time']),
        'confidence': float(item['confidence']),
        'raw_ocr': item['raw_ocr'],
        'plate': item['license_plate']
    })

n = len(data)
print(f"Sample size: {n}\n")

avg_total = sum(d['total'] for d in data) / n
avg_download = sum(d['download'] for d in data) / n
avg_ocr = sum(d['ocr'] for d in data) / n
avg_validation = sum(d['validation'] for d in data) / n
avg_database = sum(d['database'] for d in data) / n
avg_sqs = sum(d['sqs'] for d in data) / n
avg_confidence = sum(d['confidence'] for d in data) / n

print("Averages:")
print(f"Total: {avg_total:.3f}s")
print(f"Download: {avg_download:.3f}s ({avg_download/avg_total*100:.1f}%)")
print(f"OCR: {avg_ocr:.3f}s ({avg_ocr/avg_total*100:.1f}%)")
print(f"Validation: {avg_validation:.3f}s ({avg_validation/avg_total*100:.1f}%)")
print(f"Database: {avg_database:.3f}s ({avg_database/avg_total*100:.1f}%)")
print(f"SQS: {avg_sqs:.3f}s ({avg_sqs/avg_total*100:.1f}%)")
print(f"Avg Confidence: {avg_confidence:.1f}%\n")
