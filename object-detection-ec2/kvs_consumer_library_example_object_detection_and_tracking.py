# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0.
# Current version. Replaces old/consumer-v1-no-filtering.py and old/consumer-v2-filtering.py.

'''
Example to demonstrate usage the AWS Kinesis Video Streams (KVS) Consumer Library for Python.
 '''

__version__ = "0.0.1"
__status__ = "Development"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
__author__ = "Dean Colcott <https://www.linkedin.com/in/deancolcott/>"


import os
from io import BytesIO
import sys
import time
import random
import math
import json
import string
import datetime
import easyocr

import boto3
import cv2
import pandas as pd
from ultralytics import YOLO
import logging
from amazon_kinesis_video_consumer_library.kinesis_video_streams_parser import KvsConsumerLibrary
from amazon_kinesis_video_consumer_library.kinesis_video_fragment_processor import KvsFragementProcessor
from sort.sort import *

from dotenv import load_dotenv

load_dotenv()


track_upload_counts = {}
track_frame_counts = {}
MAX_UPLOADS_PER_TRACK = 3
MIN_FRAMES_BEFORE_UPLOAD = 8
DESIRED_WIDTH = 75
DESIRED_HEIGHT = 32
USE_VISUALIZATION = 1

def calculate_quality_score(crop):
    """Calculate quality score based on sharpness and size"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

    h, w = crop.shape[:2]
    size_score = w * h

    return sharpness * (size_score / 10000)

def has_readable_text(crop):
    """
    Check if crop contains actual text using EasyOCR.
    Returns True if text is detected, False otherwise.
    This filters out false positives like road lines, shadows, etc.
    """
    try:
        results = reader.readtext(crop)

        if len(results) == 0:
            return False

        detected_text = ''.join([res[1] for res in results]).upper()

        alphanumeric_only = ''.join(c for c in detected_text if c.isalnum())

        has_letter = any(c.isalpha() for c in alphanumeric_only)
        has_number = any(c.isdigit() for c in alphanumeric_only)

        return has_letter and has_number

    except Exception as e:
        log.warning(f'EasyOCR error: {e}')
        return True

def random_string(N=20):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(N))


def convert_to_dynamodb_item(row):
    item = {}
    for column, value in row.items():
        item[column] = str(value)
    return item


def get_car(license_plate, vehicles):

    x1, y1, x2, y2  = license_plate

    foundIt = False
    for j in range(len(vehicles)):
        xcar1, ycar1, xcar2, ycar2, score, class_id = vehicles[j]

        if x1 > xcar1 and y1 > ycar1 and x2 < xcar2 and y2 < ycar2:
            car_indx = j
            foundIt = True
            break

    if foundIt:
        return xcar1, ycar1, xcar2, ycar2

    return -1, -1, -1, -1


log = logging.getLogger(__name__)

detailed_formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] - %(message)s"
)

file_handler = logging.FileHandler('kvs_consumer.log', mode='a')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(detailed_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('[%(levelname)s] - %(message)s'))

log.addHandler(file_handler)
log.addHandler(console_handler)
log.setLevel(logging.INFO)

REGION = os.environ['AWS_REGION']
KVS_STREAM01_NAME = os.environ['KVS_STREAM_NAME']

license_plate_detector = YOLO('../license_plate_detector.pt')

s3_client = boto3.client('s3', region_name=REGION)
dynamodb_client = boto3.resource('dynamodb', region_name=REGION)
sqs_client = boto3.client('sqs', region_name=REGION)

bucket_name = os.environ['S3_BUCKET_NAME']

table_name = 'object-detection-tracking'

queue_url = os.environ['SQS_QUEUE_URL']

processed_track_ids = []

data = pd.DataFrame(columns=['fragment_number', 'abs_frame_number', 'frame_number', 'x1', 'y1', 'x2', 'y2', 'x1car', 'y1car', 'x2car', 'y2car', 'class_id', 'track_id'])

counter = 0

fragment_nmrs = []

mot_tracker = Sort()

reader = easyocr.Reader(['en'], gpu=False)
log.info("EasyOCR initialized")

class KvsPythonConsumerExample:
    '''
    Example class to demonstrate usage the AWS Kinesis Video Streams KVS) Consumer Library for Python.
    '''

    def __init__(self):
        '''
        Initialize the KVS clients as needed. The KVS Comsumer Library intentionally does not abstract 
        the KVS clients or the various media API calls. These have individual authentication configuration and 
        a variety of other user defined settings so we keep them here in the users application logic for configurability.

        The KvsConsumerLibrary sits above these and parses responses from GetMedia and GetMediaForFragmentList 
        into MKV fragments and provides convenience functions to further process, save and extract individual frames.  
        '''

        self.kvs_fragment_processor = KvsFragementProcessor()

        self.last_good_fragment_tags = None

        log.info('Initializing Amazon Kinesis Video client....')
        self.session = boto3.Session(region_name=REGION)
        self.kvs_client = self.session.client("kinesisvideo")

    def service_loop(self):
        try:
            response = self.kvs_client.describe_stream(StreamName=KVS_STREAM01_NAME)
            log.info(f"Stream Status: {response['StreamInfo']['Status']}")
            log.info(f"Stream ARN: {response['StreamInfo']['StreamARN']}")
            log.info(f"Stream Creation Time: {response['StreamInfo']['CreationTime']}")

            streams = self.kvs_client.list_streams()
            log.info(f"Available streams in region: {[s['StreamName'] for s in streams['StreamInfoList']]}")
        except Exception as e:
            log.error(f"Error checking stream: {e}")

        log.info(f'Getting KVS GetMedia Endpoint for stream: {KVS_STREAM01_NAME} ........')
        get_media_endpoint = self._get_data_endpoint(KVS_STREAM01_NAME, 'GET_MEDIA')

        log.info(f'Initializing KVS Media client for stream: {KVS_STREAM01_NAME}........')
        kvs_media_client = self.session.client('kinesis-video-media', endpoint_url=get_media_endpoint)

        start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)

        log.info(f'Requesting KVS GetMedia Response for stream: {KVS_STREAM01_NAME} from {start_time}........')

        try:
            get_media_response = kvs_media_client.get_media(
                StreamName=KVS_STREAM01_NAME,
                StartSelector={
                    'StartSelectorType': 'SERVER_TIMESTAMP',
                    'StartTimestamp': start_time
                }
            )
            log.info('Successfully connected with SERVER_TIMESTAMP selector')
        except Exception as e:
            log.warning(f'SERVER_TIMESTAMP failed: {e}, trying EARLIEST...')
            get_media_response = kvs_media_client.get_media(
                StreamName=KVS_STREAM01_NAME,
                StartSelector={
                    'StartSelectorType': 'EARLIEST'
                }
            )
            log.info('Successfully connected with EARLIEST selector')

        log.info(f'Starting KvsConsumerLibrary for stream: {KVS_STREAM01_NAME}........')
        my_stream01_consumer = KvsConsumerLibrary(KVS_STREAM01_NAME,
                                            get_media_response,
                                            self.on_fragment_arrived,
                                            self.on_stream_read_complete,
                                            self.on_stream_read_exception
                                            )

        my_stream01_consumer.start()

        while True:
            log.info("Consumer active and processing fragments...")
            time.sleep(10)

    def on_fragment_arrived(self, stream_name, fragment_bytes, fragment_dom, fragment_receive_duration):
        global processed_track_ids
        global counter
        global data
        global fragment_nmrs
        '''
        This is the callback for the KvsConsumerLibrary to send MKV fragments as they are received from a stream being processed.
        The KvsConsumerLibrary returns the received fragment as raw bytes and a DOM like structure containing the fragments meta data.

        With these parameters you can do a variety of post-processing including saving the fragment as a standalone MKV file
        to local disk, request individual frames as a numpy.ndarray for data science applications or as JPEG/PNG files to save to disk 
        or pass to computer vison solutions. Finally, you can also use the Fragment DOM to access Meta-Data such as the MKV tags as well
        as track ID and codec information. 

        In the below example we provide a demonstration of all of these described functions.

        ### Parameters:

            **stream_name**: str
                Name of the stream as set when the KvsConsumerLibrary thread triggering this callback was initiated.
                Use this to identify a fragment when multiple streams are read from different instances of KvsConsumerLibrary to this callback.

            **fragment_bytes**: bytearray
                A ByteArray with raw bytes from exactly one fragment. Can be save or processed to access individual frames

            **fragment_dom**: mkv_fragment_doc: ebmlite.core.Document <ebmlite.core.MatroskaDocument>
                A DOM like structure of the parsed fragment providing searchable list of EBML elements and MetaData in the Fragment

            **fragment_receive_duration**: float
                The time in seconds that the fragment took for the streaming data to be received and processed. 
        
        '''

        try:

            self.last_good_fragment_tags = self.kvs_fragment_processor.get_fragment_tags(fragment_dom)

            time_now = time.time()
            kvs_ms_behind_live = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_MILLIS_BEHIND_NOW'])
            producer_timestamp = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_PRODUCER_TIMESTAMP'])
            server_timestamp = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_SERVER_TIMESTAMP'])

            save_dir = 'ENTER_DIRECTORY_PATH_TO_SAVE_FRAGEMENTS'
            frag_file_name = self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER'] + '.mkv'
            frag_file_path = os.path.join(save_dir, frag_file_name)

            one_in_frames_ratio = 1
            fragment_nmrs.append(str(self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']))
            ndarray_frames = self.kvs_fragment_processor.get_frames_as_ndarray(fragment_bytes, one_in_frames_ratio)

            actual_frames_in_fragment = len(ndarray_frames) * one_in_frames_ratio

            for i in range(len(ndarray_frames)):

                ndarray_frame = ndarray_frames[i]
                H, W, _ = ndarray_frame.shape

                results = license_plate_detector(ndarray_frame, conf=0.2, verbose=False)[0]

                lc_detections = results.boxes.data.tolist()

                lc_detections_ = mot_tracker.update(np.asarray([(x1, y1, x2, y2, score) for x1, y1, x2, y2, score, _ in lc_detections])) if len(lc_detections) > 0 else []

                for detections in lc_detections_:
                    if len(detections) == 5 and not math.isnan(detections[0]) and not math.isnan(detections[1]) and not math.isnan(detections[2]) and not math.isnan(detections[3]):

                        x1, y1, x2, y2, track_id = detections
                        track_id = int(track_id)
                        class_id = 0

                        x1car, y1car, x2car, y2car = x1, y1, x2, y2

                        if track_id not in track_frame_counts:
                            track_frame_counts[track_id] = 0
                            track_upload_counts[track_id] = 0

                        track_frame_counts[track_id] += 1

                        license_plate_crop = ndarray_frame[int(y1):int(y2), int(x1):int(x2), :]

                        crop_height = int(y2) - int(y1)
                        crop_width = int(x2) - int(x1)

                        with open('plate_dimensions.log', 'a') as f:
                            f.write(f"Track {track_id}, Frame {i}: {crop_width}x{crop_height}px\n")

                        should_skip = False
                        skip_reason = ""

                        if track_frame_counts[track_id] < MIN_FRAMES_BEFORE_UPLOAD:
                            should_skip = True
                            skip_reason = f"waiting (frame {track_frame_counts[track_id]}/{MIN_FRAMES_BEFORE_UPLOAD})"

                        elif track_upload_counts[track_id] >= MAX_UPLOADS_PER_TRACK:
                            should_skip = True
                            skip_reason = f"limit reached ({MAX_UPLOADS_PER_TRACK})"

                        elif crop_width < DESIRED_WIDTH or crop_height < DESIRED_HEIGHT:
                            should_skip = True
                            skip_reason = f"too small ({crop_width}x{crop_height})"

                        elif not should_skip:
                            quality = calculate_quality_score(license_plate_crop)
                            if quality < 35:
                                should_skip = True
                                skip_reason = f"too blurry (quality={quality:.1f})"

                        elif not has_readable_text(license_plate_crop):
                            should_skip = True
                            skip_reason = "no readable text"

                        if should_skip:

                            new_row = {
                                'fragment_number': str(self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']),
                                'abs_frame_number': counter + int(one_in_frames_ratio * i),
                                'frame_number': int(one_in_frames_ratio * i),
                                'x1': float(x1),
                                'y1': float(y1),
                                'x2': float(x2),
                                'y2': float(y2),
                                'x1car': float(x1car),
                                'y1car': float(y1car),
                                'x2car': float(x2car),
                                'y2car': float(y2car),
                                'class_id': int(class_id) if int(class_id) in [0, 1] else 1,
                                'track_id': track_id
                            }
                            data.loc[len(data.index)] = list(new_row.values())
                            continue

                        quality = calculate_quality_score(license_plate_crop)
                        log.info(f'Track {track_id}:  UPLOADING frame {i} ({crop_width}x{crop_height}px, quality={quality:.1f}, upload {track_upload_counts[track_id]+1}/{MAX_UPLOADS_PER_TRACK})')

                        if crop_width < 200 or crop_height < 60:
                            scale_factor = max(200 / crop_width, 60 / crop_height)
                            new_width = int(crop_width * scale_factor)
                            new_height = int(crop_height * scale_factor)
                            license_plate_crop = cv2.resize(license_plate_crop, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

                        ret, buffer = cv2.imencode('.jpg', license_plate_crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
                        bytes_io = BytesIO(buffer)

                        first_seen_track = 1 if track_id not in processed_track_ids else 0
                        if track_id not in processed_track_ids:
                            processed_track_ids.append(track_id)

                        key = '{}_{}_{}_{}.jpg'.format(str(int(track_id)), self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER'], str(int(one_in_frames_ratio * i)), first_seen_track)

                        s3_client.upload_fileobj(bytes_io, bucket_name, key)
                        track_upload_counts[track_id] += 1

                        new_row = {'fragment_number': str(self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']),
                                    'abs_frame_number': counter + int(one_in_frames_ratio * i),
                                    'frame_number': int(one_in_frames_ratio * i),
                                    'x1': float(x1),
                                    'y1': float(y1),
                                    'x2': float(x2),
                                    'y2': float(y2),
                                    'x1car': float(x1car),
                                    'y1car': float(y1car),
                                    'x2car': float(x2car),
                                    'y2car': float(y2car),
                                    'class_id': int(class_id) if int(class_id) in [0, 1] else 1,
                                    'track_id': int(track_id)
                                    }

                        data.loc[len(data.index)] = list(new_row.values())

            unique_values = data[(data['class_id'] == 0) & (data['fragment_number'] == str(self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']))]['track_id'].unique()
            for value in unique_values:
                new_df = data[data['track_id'] == value].copy()
                all_values_abs_frames = list(range(min(new_df['abs_frame_number']), 1 + max(new_df['abs_frame_number'])))
                missing_values = list(set(all_values_abs_frames) - set(list(new_df['abs_frame_number'])))
                new_rows = [{'abs_frame_number': value_, 'class_id': new_df['class_id'].iloc[0], 'track_id': new_df['track_id'].iloc[0]} for value_ in missing_values]
                new_df_ = pd.DataFrame(new_rows)
                new_df = pd.concat([new_df, new_df_], ignore_index=True)
                new_df = new_df.sort_values(by='abs_frame_number')
                new_df['x1'] = new_df['x1'].interpolate(method='linear')
                new_df['x2'] = new_df['x2'].interpolate(method='linear')
                new_df['y1'] = new_df['y1'].interpolate(method='linear')
                new_df['y2'] = new_df['y2'].interpolate(method='linear')
                new_df['x1car'] = new_df['x1car'].interpolate(method='linear')
                new_df['x2car'] = new_df['x2car'].interpolate(method='linear')
                new_df['y1car'] = new_df['y1car'].interpolate(method='linear')
                new_df['y2car'] = new_df['y2car'].interpolate(method='linear')
                fragment_start = counter
                new_df['frame_number'] = new_df['abs_frame_number'] - fragment_start
                new_df['fragment_number'] = new_df['fragment_number'].ffill()
                data = pd.concat([data, new_df])
                data = data.sort_values(by='abs_frame_number')

            data = data.drop_duplicates(keep='first')

            if len(fragment_nmrs) > 0:
                df = data[data['fragment_number']==fragment_nmrs[-1]]

                table = dynamodb_client.Table(table_name)

                with table.batch_writer() as batch:
                    for index, row in df.iterrows():
                        item = convert_to_dynamodb_item(row)
                        batch.put_item(Item=item)

                print(f"DEBUG: Successfully wrote to DynamoDB")

                if USE_VISUALIZATION:
                    response = sqs_client.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({'fragment_number': fragment_nmrs[-1]}),
                    MessageGroupId=fragment_nmrs[-1],
                    MessageDeduplicationId=random_string()
                    )

            one_in_frames_ratio = 1
            save_dir = 'ENTER_DIRECTORY_PATH_TO_SAVE_JPEG_FRAMES'
            jpg_file_base_name = self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']
            jpg_file_base_path = os.path.join(save_dir, jpg_file_base_name)

            counter += actual_frames_in_fragment

        except Exception as err:
            log.error(f'on_fragment_arrived Error: {err}')

    def on_stream_read_complete(self, stream_name):
        '''
        This callback is triggered by the KvsConsumerLibrary when a stream has no more fragments available.
        This represents a graceful exit of the KvsConsumerLibrary thread.

        A stream will reach the end of the available fragments if the StreamSelector applied some 
        time or fragment bounding on the media request or if requesting a live steam and the producer 
        stopped sending more fragments. 

        Here you can choose to either restart reading the stream at a new time or just clean up any
        resources that were expecting to process any further fragments. 
        
        ### Parameters:

            **stream_name**: str
                Name of the stream as set when the KvsConsumerLibrary thread triggering this callback was initiated.
                Use this to identify a fragment when multiple streams are read from different instances of KvsConsumerLibrary to this callback.
        '''

    def on_stream_read_exception(self, stream_name, error):
        '''
        This callback is triggered by an exception in the KvsConsumerLibrary reading a stream. 
        
        For example, to process use the last good fragment number from self.last_good_fragment_tags to
        restart the stream from that point in time with the example stream selector provided below. 
        
        Alternatively, just handle the failed stream as per your application logic requirements.

        ### Parameters:

            **stream_name**: str
                Name of the stream as set when the KvsConsumerLibrary thread triggering this callback was initiated.
                Use this to identify a fragment when multiple streams are read from different instances of KvsConsumerLibrary to this callback.

            **error**: err / exception
                The Exception obje tvthat was thrown to trigger this callback.

        '''

        print(f'####### ERROR: Exception on read stream: {stream_name}\n####### Fragment Tags:\n{self.last_good_fragment_tags}\nError Message:{error}')

    def _get_data_endpoint(self, stream_name, api_name):
        '''
        Convenience method to get the KVS client endpoint for specific API calls. 
        '''
        response = self.kvs_client.get_data_endpoint(
            StreamName=stream_name,
            APIName=api_name
        )
        return response['DataEndpoint']

if __name__ == "__main__":
    '''
    Main method for example KvsConsumerLibrary
    '''

    kvsConsumerExample = KvsPythonConsumerExample()
    kvsConsumerExample.service_loop()
