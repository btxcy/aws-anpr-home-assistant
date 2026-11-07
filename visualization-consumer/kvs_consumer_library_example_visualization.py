# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0.

'''
Example to demonstrate usage the AWS Kinesis Video Streams (KVS) Consumer Library for Python.
 '''

__version__ = "0.0.1"
__status__ = "Development"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
__author__ = "Dean Colcott <https://www.linkedin.com/in/deancolcott/>"

import os
import time
import sys
import boto3
import cv2
import logging
import datetime
from amazon_kinesis_video_consumer_library.kinesis_video_streams_parser import KvsConsumerLibrary
from amazon_kinesis_video_consumer_library.kinesis_video_fragment_processor import KvsFragementProcessor

from dotenv import load_dotenv

load_dotenv()


log = logging.getLogger(__name__)
logging.basicConfig(format="[%(name)s.%(funcName)s():%(lineno)d] - [%(levelname)s] - %(message)s",
                    stream=sys.stdout,
                    level=logging.INFO)

REGION = os.environ['AWS_REGION']
KVS_STREAM01_NAME = os.environ['KVS_STREAM_NAME']

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
            log.info("Visualization consumer active and processing fragments...")
            time.sleep(10)

    def on_fragment_arrived(self, stream_name, fragment_bytes, fragment_dom, fragment_receive_duration):
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
            log.info(f'\n\n##########################\nFragment Received on Stream: {stream_name}\n##########################')

            log.info('')
            log.info(f'####### Fragment Receive and Processing Duration: {fragment_receive_duration} Secs')

            self.last_good_fragment_tags = self.kvs_fragment_processor.get_fragment_tags(fragment_dom)

            time_now = time.time()
            kvs_ms_behind_live = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_MILLIS_BEHIND_NOW'])
            producer_timestamp = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_PRODUCER_TIMESTAMP'])
            server_timestamp = float(self.last_good_fragment_tags['AWS_KINESISVIDEO_SERVER_TIMESTAMP'])

            log.info('')
            log.info('####### Timestamps and Delta: ')
            log.info(f'KVS Reported Time Behind Live {kvs_ms_behind_live} mS')
            log.info(f'Local Time Diff to Fragment Producer Timestamp: {round(((time_now - producer_timestamp)*1000), 3)} mS')
            log.info(f'Local Time Diff to Fragment Server Timestamp: {round(((time_now - server_timestamp)*1000), 3)} mS')

            log.info('')
            log.info('####### Fragment MKV Tags:')
            for key, value in self.last_good_fragment_tags.items():
                log.info(f'{key} : {value}')

            log.info('')
            log.info('####### Pretty Print Fragment DOM: #######')
            pretty_frag_dom = self.kvs_fragment_processor.get_fragement_dom_pretty_string(fragment_dom)
            log.info(pretty_frag_dom)

            save_dir = './tmp'
            frag_file_name = self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER'] + '.mkv'
            frag_file_path = os.path.join(save_dir, frag_file_name)

            one_in_frames_ratio = 1
            log.info('')
            log.info(f'#######  Reading 1 in {one_in_frames_ratio} Frames from fragment as ndarray:')
            ndarray_frames = self.kvs_fragment_processor.get_frames_as_ndarray(fragment_bytes, one_in_frames_ratio)
            for i in range(len(ndarray_frames)):
                ndarray_frame = ndarray_frames[i]

            '''
            one_in_frames_ratio = 1
            save_dir = 'frames'
            jpg_file_base_name = self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']
            jpg_file_base_path = os.path.join(save_dir, jpg_file_base_name)
            
            # Uncomment below to enable this function - will take a significant amount of disk space if left running unchecked:
            log.info('')
            log.info(f'####### Saving 1 in {one_in_frames_ratio} Frames from fragment as JPEG to base path: {jpg_file_base_path}')
            jpeg_paths = self.kvs_fragment_processor.save_frames_as_jpeg(fragment_bytes, one_in_frames_ratio, jpg_file_base_path)
            for i in range(len(jpeg_paths)):
                jpeg_path = jpeg_paths[i]
                print(f'Saved JPEG-{i} Path: {jpeg_path}')
            '''
            one_in_frames_ratio = 1
            save_dir = './amazon-kinesis-video-streams-consumer-library-for-python/frames'
            os.makedirs(save_dir, exist_ok=True)
            fragment_number = self.last_good_fragment_tags['AWS_KINESISVIDEO_FRAGMENT_NUMBER']

            log.info(f'####### Saving frames for fragment: {fragment_number}')

            ndarray_frames = self.kvs_fragment_processor.get_frames_as_ndarray(fragment_bytes, one_in_frames_ratio)

            for i, frame in enumerate(ndarray_frames):
                frame_number = i * one_in_frames_ratio
                frame_filename = f'{fragment_number}-{frame_number}.jpg'
                frame_path = os.path.join(save_dir, frame_filename)
                cv2.imwrite(frame_path, frame)

            log.info(f'Saved {len(ndarray_frames)} frames to {save_dir}')

            processed_fragments_dir = './amazon-kinesis-video-streams-consumer-library-for-python/processed_fragments'
            os.makedirs(processed_fragments_dir, exist_ok=True)

            processed_marker_path = os.path.join(processed_fragments_dir, fragment_number)
            with open(processed_marker_path, 'w') as f:
                pass
            log.info(f'Created processed fragment marker')
            log.info(f'####### Fragment {fragment_number} ready for visualization!')

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

        print(f'Read Media on stream: {stream_name} Completed successfully - Last Fragment Tags: {self.last_good_fragment_tags}')

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

    import time
    time.sleep(1)

    kvsConsumerExample = KvsPythonConsumerExample()
    kvsConsumerExample.service_loop()
