import json
import os
import urllib3
import boto3
from datetime import datetime
import time
from datetime import datetime
from zoneinfo import ZoneInfo

http = urllib3.PoolManager()
ssm_client = boto3.client('ssm')
dynamodb_client = boto3.client('dynamodb')

HA_URL_PARAMETER = os.environ.get('HA_URL_PARAMETER_NAME', 'Home-Assistant-URL')
HA_TOKEN_PARAMETER = os.environ.get('HA_TOKEN_PARAMETER_NAME', 'Home-Assistant-Token')
TIMEZONE_PARAMETER = os.environ.get('TIMEZONE_PARAMETER_NAME', 'Time-Zone')

COOLDOWN_SECONDS = 30

_cached_url = None
_cached_token = None
_cached_timezone = None

def get_ssm_parameters():
    """
    Retrieve Home Assistant URL, token, and timezone from SSM Parameter Store.
    Returns: (url, token, timezone)
    """
    global _cached_url, _cached_token, _cached_timezone

    if _cached_url is not None and _cached_token is not None and _cached_timezone is not None:
        return _cached_url, _cached_token, _cached_timezone

    try:
        print(f"Retrieving credentials from Parameter Store...")

        response = ssm_client.get_parameters(
            Names=[HA_URL_PARAMETER, HA_TOKEN_PARAMETER, TIMEZONE_PARAMETER],
            WithDecryption=True
        )

        parameters = {p['Name']: p['Value'] for p in response['Parameters']}

        _cached_url = parameters.get(HA_URL_PARAMETER)
        _cached_token = parameters.get(HA_TOKEN_PARAMETER)
        _cached_timezone = parameters.get(TIMEZONE_PARAMETER, 'UTC')

        if not _cached_url:
            raise Exception(f"Parameter not found: {HA_URL_PARAMETER}")
        if not _cached_token:
            raise Exception(f"Parameter not found: {HA_TOKEN_PARAMETER}")
        if not _cached_timezone:
            print(f" Warning: Timezone parameter not found, using default: UTC")
            _cached_timezone = 'UTC'

        print(f" Retrieved URL: {_cached_url[:30]}...")
        print(f" Retrieved token: {_cached_token[:20]}...")
        print(f" Retrieved timezone: {_cached_timezone}")

        return _cached_url, _cached_token, _cached_timezone

    except Exception as e:
        print(f" Error retrieving credentials: {str(e)}")
        raise


def check_and_update_notification_cooldown(license_plate):
    """
    Check if license plate is in cooldown period.
    Returns (should_notify: bool, check_time: float, update_time: float)
    """
    current_time = time.time()

    try:
        check_start = time.time()
        response = dynamodb_client.get_item(
            TableName='ha-license-plate-notification',
            Key={'license_plate_number': {'S': license_plate}}
        )
        check_time = time.time() - check_start

        if 'Item' in response:
            last_notified = float(response['Item']['last_notified_timestamp']['N'])
            time_since_notification = current_time - last_notified

            if time_since_notification < COOLDOWN_SECONDS:
                print(f" Cooldown active: plate '{license_plate}' notified {time_since_notification:.1f}s ago")
                return False, check_time, 0
            else:
                print(f" Cooldown expired: plate '{license_plate}' last notified {time_since_notification:.1f}s ago")
        else:
            print(f" First notification for plate '{license_plate}'")

        update_start = time.time()
        ttl = int(current_time + 86400)
        dynamodb_client.put_item(
            TableName='ha-license-plate-notification',
            Item={
                'license_plate_number': {'S': license_plate},
                'last_notified_timestamp': {'N': str(current_time)},
                'ttl': {'N': str(ttl)}
            }
        )
        update_time = time.time() - update_start

        return True, check_time, update_time

    except Exception as e:
        print(f" Warning: Error checking cooldown for '{license_plate}': {str(e)}")
        return True, 0, 0


def save_timing_metrics(license_plate, car_id, cooldown_check_time, ssm_time, conversion_time, ha_call_time, cooldown_update_time, total_time, was_sent, confidence):
    """Save timing metrics to DynamoDB for analysis"""
    try:
        item = {
            'execution_id': {'S': f"{int(time.time() * 1000)}_{car_id}"},
            'license_plate': {'S': license_plate},
            'car_id': {'S': str(car_id)},
            'timestamp': {'N': str(time.time())},
            'cooldown_check_time': {'N': str(cooldown_check_time)},
            'ssm_retrieval_time': {'N': str(ssm_time)},
            'timestamp_conversion_time': {'N': str(conversion_time)},
            'ha_api_call_time': {'N': str(ha_call_time)},
            'cooldown_update_time': {'N': str(cooldown_update_time)},
            'total_time': {'N': str(total_time)},
            'was_sent_to_ha': {'BOOL': was_sent},
            'confidence': {'N': str(confidence)}
        }

        dynamodb_client.put_item(TableName='ha-lambda-performance-metrics', Item=item)
    except Exception as e:
        print(f"Failed to save timing metrics: {e}")


def lambda_handler(event, context):
    """
    Triggered by DynamoDB Stream when license plate record is added/modified.
    Sends notification to Home Assistant with deduplication based on license plate.
    """
    tic = time.time()

    record = event['Records'][0]

    if record['eventName'] not in ['INSERT', 'MODIFY']:
        print(f"Skipping {record['eventName']} event")
        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Skipped {record["eventName"]} event'})
        }

    try:
        new_image = record['dynamodb']['NewImage']

        license_plate = new_image['license_plate_number']['S']
        confidence = float(new_image.get('confidence', {}).get('N', 0))
        timestamp_unix = float(new_image.get('timestamp', {}).get('S', '0'))
        car_id = new_image.get('car_id', {}).get('S', 'unknown')

        print(f"Processing: plate={license_plate}, car_id={car_id}, event={record['eventName']}")

        should_notify, cooldown_check_time, cooldown_update_time_initial = check_and_update_notification_cooldown(license_plate)

        if not should_notify:
            total_time = time.time() - tic
            print(f"SKIPPED - Cooldown active")
            print(f"  Cooldown check: {cooldown_check_time:.3f}s")
            print(f"  Total time: {total_time:.3f}s")

            save_timing_metrics(
                license_plate, car_id,
                cooldown_check_time, 0, 0, 0, 0,
                total_time, False, confidence
            )

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Skipped - cooldown period',
                    'license_plate': license_plate,
                    'car_id': car_id
                })
            }

        ssm_start = time.time()
        ha_url, ha_token, timezone = get_ssm_parameters()
        ssm_time = time.time() - ssm_start

        conversion_start = time.time()
        user_tz = ZoneInfo(timezone)
        timestamp_readable = datetime.fromtimestamp(timestamp_unix, tz=user_tz).strftime('%Y-%m-%d %I:%M:%S %p %Z')
        conversion_time = time.time() - conversion_start

        print(f" Sending notification for '{license_plate}' (car_id: {car_id})")

        ha_call_start = time.time()
        send_to_home_assistant(
            license_plate=license_plate,
            confidence=confidence,
            timestamp=timestamp_readable,
            ha_token=ha_token,
            ha_url=ha_url
        )
        ha_call_time = time.time() - ha_call_start

        print(f" Successfully sent notification for '{license_plate}'")

        total_time = time.time() - tic

        print("*"*70)
        print(f"SUCCESS - Total processing time: {total_time:.3f}s")
        print(f"  License Plate: {license_plate}")
        print(f"  Confidence: {confidence:.1f}%")
        print(f"  Cooldown check: {cooldown_check_time:.3f}s")
        print(f"  SSM retrieval: {ssm_time:.3f}s")
        print(f"  Timestamp conversion: {conversion_time:.3f}s")
        print(f"  HA API call: {ha_call_time:.3f}s")
        print(f"  Cooldown update: {cooldown_update_time_initial:.3f}s")
        print("*"*70)

        save_timing_metrics(
            license_plate, car_id,
            cooldown_check_time, ssm_time, conversion_time, ha_call_time, cooldown_update_time_initial,
            total_time, True, confidence
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Success',
                'license_plate': license_plate,
                'confidence': confidence,
                'car_id': car_id
            })
        }

    except urllib3.exceptions.HTTPError as e:
        error_str = str(e)
        print(f" HTTP Error: {error_str}")

        if any(code in error_str for code in ['401', '403', '404']):
            print(f"Permanent error - NOT retrying")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Permanent error - skipped retry',
                    'error': error_str
                })
            }

        print(f"Temporary error - will retry")
        raise

    except urllib3.exceptions.MaxRetryError as e:
        print(f" Connection error: {str(e)}")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Home Assistant unreachable - skipped retry',
                'error': str(e)
            })
        }

    except urllib3.exceptions.TimeoutError as e:
        print(f" Timeout error: {str(e)}")
        raise

    except Exception as e:
        total_time = time.time() - tic
        print(f" Unexpected error at {total_time:.3f}s: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise


def send_to_home_assistant(license_plate, confidence, timestamp, ha_token, ha_url):
    """
    Send license plate data to Home Assistant via REST API.
    """

    headers = {
        'Authorization': f'Bearer {ha_token}',
        'Content-Type': 'application/json'
    }

    event_url = f"{ha_url}/api/events/license_plate_detected"

    payload = json.dumps({
        'license_plate': license_plate,
        'confidence': round(confidence, 2),
        'timestamp': timestamp
    })

    print(f"Sending to: {event_url[:30]}")
    print(f"Payload: {payload}")

    try:
        response = http.request(
            'POST',
            event_url,
            body=payload,
            headers=headers,
            timeout=5.0,
            retries=False
        )

        if response.status == 200:
            print(f" Home Assistant response: {response.status}")
            return response.status
        elif response.status == 401:
            error_msg = f"Authentication failed (401)"
            print(f" {error_msg}")
            raise urllib3.exceptions.HTTPError(error_msg)
        elif response.status == 403:
            error_msg = f"Forbidden (403)"
            print(f" {error_msg}")
            raise urllib3.exceptions.HTTPError(error_msg)
        elif response.status == 404:
            error_msg = f"Not found (404)"
            print(f" {error_msg}")
            raise urllib3.exceptions.HTTPError(error_msg)
        else:
            error_body = response.data.decode('utf-8') if response.data else 'No response body'
            error_msg = f"Status {response.status}: {error_body}"
            print(f" {error_msg}")
            raise urllib3.exceptions.HTTPError(error_msg)

    except urllib3.exceptions.MaxRetryError as e:
        print(f" Cannot connect to Home Assistant")
        raise

    except urllib3.exceptions.TimeoutError as e:
        print(f" Request timed out")
        raise
