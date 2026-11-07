# Current version. Replaces old/process-queue-v1.py.

import time
import ast
import os
import shutil

import pandas as pd
import boto3

from dotenv import load_dotenv

load_dotenv()


queue_url = os.environ['SQS_QUEUE_URL']
table_name = 'object-detection-tracking'
region_name = os.environ['AWS_REGION']

detections_dir = './amazon-kinesis-video-streams-consumer-library-for-python/detections/'
processed_fragments_dir = './amazon-kinesis-video-streams-consumer-library-for-python/processed_fragments/'
license_plates_dir = './amazon-kinesis-video-streams-consumer-library-for-python/license_plates/'
frames_dir = './amazon-kinesis-video-streams-consumer-library-for-python/frames/'

for dir_ in [detections_dir, processed_fragments_dir, license_plates_dir, frames_dir]:
    if os.path.exists(dir_):
        shutil.rmtree(dir_)
    os.makedirs(dir_)

sqs = boto3.client(
    'sqs',
    region_name=region_name
)

dynamodb = boto3.client(
    'dynamodb',
    region_name=region_name
)

count = 0
messages_processed = 0
last_message_time = time.time()

print("Queue processor started...")
print(f"Polling queue: {queue_url}")

while True:
    try:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=5
        )

        if 'Messages' not in response.keys():
            count += 1
            current_time = time.time()
            idle_time = current_time - last_message_time

            if count % 10 == 0:
                print(f'Waiting for messages... (idle for {idle_time:.1f}s, processed: {messages_processed})')

            time.sleep(1)

        else:
            messages = response['Messages']
            print(f'Processing {len(messages)} message(s)...')

            for message in messages:
                try:
                    receipt_handle = message['ReceiptHandle']
                    message_body = ast.literal_eval(message['Body'])

                    if 'fragment_number' in message_body.keys():
                        primary_key_value = str(message_body['fragment_number'])

                        dynamodb_response = dynamodb.query(
                            TableName=table_name,
                            KeyConditionExpression='fragment_number = :key_value',
                            ExpressionAttributeValues={
                                ':key_value': {'S': primary_key_value}
                            }
                        )

                        items = dynamodb_response.get('Items', [])

                        if items:
                            data = [{key: value['S'] for key, value in item.items()} for item in items]
                            df = pd.DataFrame(data)

                            csv_path = os.path.join(detections_dir, f'{primary_key_value}.csv')
                            df.to_csv(csv_path, index=False)

                            marker_path = os.path.join(processed_fragments_dir, str(primary_key_value))
                            with open(marker_path, 'w') as f:
                                pass

                            print(f'  Processed fragment {primary_key_value} ({len(items)} detections)')
                        else:
                            print(f'  No data found for fragment {primary_key_value}')

                    elif 'license_plate' in message_body.keys():
                        license_track_id = message_body['license_plate']['track_id']
                        text = message_body['license_plate']['text']

                        license_file = os.path.join(license_plates_dir, f'{license_track_id}_{text}')
                        with open(license_file, 'w') as f:
                            pass

                        print(f'  Detected license plate: {text} (track_id: {license_track_id})')

                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=receipt_handle
                    )

                    messages_processed += 1
                    last_message_time = time.time()

                except Exception as e:
                    print(f'  Error processing message: {e}')
                    try:
                        sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=receipt_handle
                        )
                    except:
                        pass

    except KeyboardInterrupt:
        print("\nStopping queue processor...")
        break
    except Exception as e:
        print(f'Error in main loop: {e}')
        time.sleep(5)

print(f"\nQueue processor stopped. Total messages processed: {messages_processed}")
