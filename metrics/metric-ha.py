# Reads the Home Assistant notification Lambda timing records from DynamoDB and prints how many alerts were sent or skipped by the cooldown, plus the average time of each step.
# Created: 2025-12-17

import os
import boto3

from dotenv import load_dotenv

load_dotenv()

dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
table = dynamodb.Table('ha-lambda-performance-metrics')

response = table.scan()
items = response['Items']

sent_items = [i for i in items if i['was_sent_to_ha']]
skipped_items = [i for i in items if not i['was_sent_to_ha']]

print(f"Total invocations: {len(items)}")
print(f"Sent to HA: {len(sent_items)}")
print(f"Skipped (cooldown): {len(skipped_items)}")
print(f"Deduplication rate: {len(skipped_items)/len(items)*100:.1f}%\n")

if sent_items:
    n = len(sent_items)

    avg_cooldown_check = sum(float(i['cooldown_check_time']) for i in sent_items) / n
    avg_ssm = sum(float(i['ssm_retrieval_time']) for i in sent_items) / n
    avg_conversion = sum(float(i['timestamp_conversion_time']) for i in sent_items) / n
    avg_ha_call = sum(float(i['ha_api_call_time']) for i in sent_items) / n
    avg_cooldown_update = sum(float(i['cooldown_update_time']) for i in sent_items) / n
    avg_total = sum(float(i['total_time']) for i in sent_items) / n

    print(f"Averages for successful notifications (n={n}):")
    print(f"Cooldown Check: {avg_cooldown_check:.3f}s ({avg_cooldown_check/avg_total*100:.1f}%)")
    print(f"SSM Retrieval: {avg_ssm:.3f}s ({avg_ssm/avg_total*100:.1f}%)")
    print(f"Timestamp Conversion: {avg_conversion:.3f}s ({avg_conversion/avg_total*100:.1f}%)")
    print(f"HA API Call: {avg_ha_call:.3f}s ({avg_ha_call/avg_total*100:.1f}%)")
    print(f"Cooldown Update: {avg_cooldown_update:.3f}s ({avg_cooldown_update/avg_total*100:.1f}%)")
    print(f"Total: {avg_total:.3f}s\n")
