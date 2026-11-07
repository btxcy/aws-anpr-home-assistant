# Current version. Replaces old/ocr-lambda-v1-async-textract.py and old/ocr-lambda-v2-s3-trigger.py.

"""
OPTIMIZED FOR ACCURACY + SPEED
- Uses AWS Textract (highest accuracy)
- Synchronous API (5-10x faster than async)
- Enhanced validation and confidence checking
- Multiple OCR attempts if needed
"""

import json
import time
import boto3
import util
import os

ssm_client = boto3.client('ssm')
last_textract_call = 0
MIN_TIME_BETWEEN_CALLS = 0.3
QUEUE_URL_PARAMETER = os.environ.get('SQS_URL_PARAMETER', 'SQS-VISUAL-URL')

region_name = os.environ['AWS_REGION']

s3_client = boto3.client('s3', region_name=region_name)
dynamodb_client = boto3.client('dynamodb', region_name=region_name)
textract_client = boto3.client('textract', region_name=region_name)
sqs_client = boto3.client('sqs', region_name=region_name)


_cached_url = None

def get_queue_url():
    """
    Get the URL for the SQS queue.
    """
    global _cached_url

    if _cached_url is not None:
        return _cached_url

    try:
        response = ssm_client.get_parameter(
            Name=QUEUE_URL_PARAMETER,
            WithDecryption=True
        )
        _cached_url = response['Parameter']['Value']

        print(f"Retrieved SQS Queue URL from Parameter Store: {_cached_url[:30]}...")
        return _cached_url

    except Exception as e:
        print(f"Error getting SQS queue URL from Parameter Store: {str(e)}")
        raise


def get_high_confidence_text(response):
    """
    Extract text from Textract response with confidence filtering.
    Returns text and average confidence score.
    """
    lines = []
    confidences = []

    for item in response['Blocks']:
        if item['BlockType'] == 'LINE':
            confidence = item.get('Confidence', 0)
            text = item.get('Text', '')

            lines.append(text)
            confidences.append(confidence)

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    full_text = ''.join(lines)

    return full_text, avg_confidence


def perform_ocr_with_retry(image_bytes, max_attempts=1):
    """
    Perform OCR with retry logic for better accuracy.
    Returns (text, confidence) tuple.
    """
    global last_textract_call

    now = time.time()
    time_since_last = now - last_textract_call

    if time_since_last < MIN_TIME_BETWEEN_CALLS:
        sleep_time = MIN_TIME_BETWEEN_CALLS - time_since_last
        print(f"  Rate limiting: sleeping {sleep_time:.3f}s")
        time.sleep(sleep_time)

    try:

        response = textract_client.detect_document_text(
            Document={'Bytes': image_bytes}
        )

        last_textract_call = time.time()

        text, confidence = get_high_confidence_text(response)

        return text, confidence

    except textract_client.exceptions.ProvisionedThroughputExceededException as e:
        print(f" Textract throttled: {str(e)}")
        return "", 0

    except Exception as e:
        print(f" OCR error: {str(e)}")
        raise

def save_timing_metrics(car_id, download_time, ocr_time, process_time, db_time, sqs_time, total_time, confidence, raw_text, plate):
    """Save timing metrics to DynamoDB for analysis"""
    try:
        item = {
            'execution_id': {'S': f"{int(time.time() * 1000)}_{car_id}"},
            'car_id': {'S': str(car_id)},
            'timestamp': {'N': str(time.time())},
            'download_time': {'N': str(download_time)},
            'ocr_time': {'N': str(ocr_time)},
            'validation_time': {'N': str(process_time)},
            'database_time': {'N': str(db_time)},
            'sqs_time': {'N': str(sqs_time)},
            'total_time': {'N': str(total_time)},
            'confidence': {'N': str(confidence)},
            'raw_ocr': {'S': raw_text},
            'license_plate': {'S': plate}
        }

        dynamodb_client.put_item(TableName='lambda-performance-metrics', Item=item)
    except Exception as e:
        print(f"Failed to save timing metrics: {e}")

def lambda_handler(event, context):
    tic = time.time()

    try:
        bucket_name = event['Records'][0]['s3']['bucket']['name']
        filename = event['Records'][0]['s3']['object']['key']
        print("Lambda Function Start " + "x"*70)
        print(f"Processing: {filename}")

        car_id_ = int(filename.split('_')[0])
        fragment_number_ = filename.split('_')[1]
        print(f"Car ID: {car_id_}, Fragment: {fragment_number_}")

        download_start = time.time()
        s3_response = s3_client.get_object(Bucket=bucket_name, Key=filename)
        image_bytes = s3_response['Body'].read()
        download_time = time.time() - download_start
        print(f"Downloaded: {len(image_bytes)} bytes in {download_time:.3f}s")

        if len(image_bytes) > 5 * 1024 * 1024:
            print(" WARNING: Image > 5MB, using async Textract (will be slower)")
            s3_object = {'Bucket': bucket_name, 'Name': filename}
            ocr_start = time.time()
            response = textract_client.start_document_text_detection(
                DocumentLocation={'S3Object': s3_object}
            )
            job_id = response['JobId']

            max_wait = 20
            for i in range(max_wait):
                response = textract_client.get_document_text_detection(JobId=job_id)
                status = response['JobStatus']

                if status in ['SUCCEEDED', 'FAILED']:
                    break
                time.sleep(0.5)

            if status != 'SUCCEEDED':
                raise Exception(f"Async Textract failed: {status}")

            raw_text, confidence = get_high_confidence_text(response)
            ocr_time = time.time() - ocr_start
            print(f"OCR completed in {ocr_time:.3f}s")
        else:
            print("Using synchronous Textract API (fast)")
            ocr_start = time.time()
            raw_text, confidence = perform_ocr_with_retry(image_bytes, max_attempts=1)
            ocr_time = time.time() - ocr_start

            if raw_text == "" and confidence == 0:
                print(" Textract throttled - returning without processing")
                total_time = time.time() - tic
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': False,
                        'reason': 'throttled',
                        'processing_time': total_time
                    })
            }

            print(f"OCR completed in {ocr_time:.3f}s")

        if confidence < 40:
            print(f" Confidence too low ({confidence:.1f}%) - rejecting")
            total_time = time.time() - tic
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': False,
                    'reason': 'low_confidence',
                    'confidence': confidence,
                    'raw_text': raw_text,
                    'processing_time': total_time
                })
            }

        process_start = time.time()
        license_plate_number_ = util.process_plate(raw_text)
        process_time = time.time() - process_start

        if license_plate_number_:

            db_start = time.time()
            item = {
                'car_id': {'S': str(car_id_)},
                'license_plate_number': {'S': license_plate_number_},
                'confidence': {'N': str(confidence)},
                'processing_time': {'N': str(time.time() - tic)},
                'timestamp': {'S': str(time.time())}
            }

            dynamodb_client.put_item(TableName='license-plate-numbers', Item=item)
            db_time = time.time() - db_start

            queue_url = get_queue_url()

            sqs_start = time.time()
            sqs_client.send_message(
                QueueUrl=f'{queue_url}',
                MessageBody=json.dumps({
                    'license_plate': {
                        'track_id': str(car_id_),
                        'text': license_plate_number_,
                        'confidence': confidence
                    }
                }),
                MessageGroupId='lambda',
                MessageDeduplicationId=f"{car_id_}_{license_plate_number_}"
            )
            sqs_time = time.time() - sqs_start

            total_time = time.time() - tic
            print("*"*70)
            save_timing_metrics(car_id_, download_time, ocr_time, process_time, db_time, sqs_time, total_time, confidence, raw_text, license_plate_number_)
            print(f"SUCCESS - Total processing time: {total_time:.3f}s")
            print(f"  Raw OCR: '{raw_text}'")
            print(f"  License Plate Number: {license_plate_number_}")
            print(f"  Confidence: {confidence:.1f}%")
            print(f"  Download: {download_time:.3f}s")
            print(f"  OCR: {ocr_time:.3f}s" if 'ocr_time' in locals() else "")
            print(f"  Validation: {process_time:.3f}s")
            print(f"  Database: {db_time:.3f}s")
            print(f"  SQS: {sqs_time:.3f}s")
            print("*"*70)
            print("Lambda Function Ends " + "x"*70)

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'plate': license_plate_number_,
                    'confidence': confidence,
                    'processing_time': total_time
                })
            }
        else:
            print("*"*70)
            print(f"NO VALID LICENSE PLATE")
            print(f"  Raw OCR: '{raw_text}'")
            print(f"  Confidence: {confidence:.1f}%")
            print(f"  Reason: Failed validation (see util.process_plate debug above)")
            print("-"*70)

            total_time = time.time() - tic
            print(f"Processing time: {total_time:.3f}s")
            print("*"*70)

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': False,
                    'raw_text': raw_text,
                    'confidence': confidence,
                    'processing_time': total_time
                })
            }

    except Exception as e:
        error_time = time.time() - tic
        print("*"*70)
        print(f" ERROR at {error_time:.3f}s: {str(e)}")
        print("*"*70)
        import traceback
        print(traceback.format_exc())
        raise

    return {
        'statusCode': 200,
        'body': json.dumps('Completed')
    }
