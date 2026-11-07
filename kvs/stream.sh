#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "$SCRIPT_DIR/../.env"
set +a

VIDEO_FILE="$SCRIPT_DIR/sample_30fps_1440.mp4"
STREAM_NAME="$KVS_STREAM_NAME"
REGION="$AWS_REGION"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <number_of_loops>"
    echo "Example: $0 1    # Stream once (60 seconds)"
    echo "Example: $0 5    # Stream 5 times (300 seconds)"
    echo "Example: $0 inf  # Stream infinitely"
    exit 1
fi

LOOP_COUNT=$1

if [ "$LOOP_COUNT" = "inf" ] || [ "$LOOP_COUNT" = "infinite" ]; then
    echo "Starting infinite KVS streaming..."
    echo "Press Ctrl+C to stop"
    INFINITE=true
    LOOP_COUNT=999999
else
    echo "Starting KVS streaming for $LOOP_COUNT loop(s)..."
    echo "Estimated duration: $((LOOP_COUNT * 60)) seconds"
    INFINITE=false
fi

CURRENT_LOOP=0

while [ $CURRENT_LOOP -lt $LOOP_COUNT ]; do
    CURRENT_LOOP=$((CURRENT_LOOP + 1))
    
    echo "========================================="
    if [ "$INFINITE" = true ]; then
        echo "Loop $CURRENT_LOOP - Started at $(date)"
    else
        echo "Loop $CURRENT_LOOP of $LOOP_COUNT - Started at $(date)"
    fi
    echo "========================================="
    
    gst-launch-1.0 -v \
       filesrc location="$VIDEO_FILE" ! \
       qtdemux name=demux ! \
       queue ! \
       h264parse ! \
       video/x-h264,stream-format=avc,alignment=au ! \
       kvssink name=sink \
            stream-name="$STREAM_NAME" \
            access-key="$KVS_PRODUCER_ACCESS_KEY_ID" \
            secret-key="$KVS_PRODUCER_SECRET_ACCESS_KEY" \
            aws-region="$REGION" \
            streaming-type=offline \
    	    fragment-duration=2 \
       demux. ! queue ! aacparse ! sink.

    EXIT_CODE=$?
    
    if [ $EXIT_CODE -ne 0 ]; then
        echo "GStreamer exited with error code $EXIT_CODE"
        echo "Waiting 2 seconds before retry..."
        sleep 2
    else
        echo "Loop $CURRENT_LOOP completed successfully"
        
        if [ $CURRENT_LOOP -lt $LOOP_COUNT ]; then
            echo "Restarting in 1 second..."
            sleep 1
        fi
    fi
done

echo "========================================="
echo "Streaming complete!"
echo "Total loops completed: $CURRENT_LOOP"
echo "========================================="
