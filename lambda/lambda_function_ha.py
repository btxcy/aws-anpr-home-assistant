import json
import requests
import os

HA_WEBHOOK_URL = os.environ["HA_WEBHOOK_URL"]

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            plate_info = message.get('license_plate', {})

            plate_number = plate_info.get('text')
            car_id = plate_info.get('track_id')

            if not plate_number:
                print("No valid plate number found in:", message)
                continue

            payload = {
                "plate_number": plate_number,
                "car_id": car_id
            }

            response = requests.post(HA_WEBHOOK_URL, json=payload, timeout=5)
            print(f"Sent to HA ({response.status_code}): {payload}")

        except Exception as e:
            print("Error processing record:", e)

    return {"statusCode": 200, "body": json.dumps("Lambda Function HA Execution Complete")}
