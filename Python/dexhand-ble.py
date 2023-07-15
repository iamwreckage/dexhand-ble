# DexHand-BLE - Demo of BLE Interface to DexHand on Arduino RP2040 Connect Board

# Released under the MIT License (MIT). See LICENSE file for details.
# Trent Shumay - trent@iotdesignshop.com

import asyncio
import sys
import cv2
import time
import struct

from bleak import BleakScanner

import mediapipe as mp
from mediapipe import solutions
from mediapipe.framework.formats import landmark_pb2

from itertools import count, takewhile
from typing import Iterator

import numpy as np

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData



MARGIN = 10  # pixels
FONT_SIZE = 1
FONT_THICKNESS = 1
HANDEDNESS_TEXT_COLOR = (88, 205, 54) # vibrant green

def draw_landmarks_on_image(rgb_image, detection_result):
  hand_landmarks_list = detection_result.hand_landmarks
  handedness_list = detection_result.handedness
  annotated_image = np.copy(rgb_image)

  # Loop through the detected hands to visualize.
  for idx in range(len(hand_landmarks_list)):
    hand_landmarks = hand_landmarks_list[idx]
    handedness = handedness_list[idx]

    # Draw the hand landmarks.
    hand_landmarks_proto = landmark_pb2.NormalizedLandmarkList()
    hand_landmarks_proto.landmark.extend([
      landmark_pb2.NormalizedLandmark(x=landmark.x, y=landmark.y, z=landmark.z) for landmark in hand_landmarks
    ])
    solutions.drawing_utils.draw_landmarks(
      annotated_image,
      hand_landmarks_proto,
      solutions.hands.HAND_CONNECTIONS,
      solutions.drawing_styles.get_default_hand_landmarks_style(),
      solutions.drawing_styles.get_default_hand_connections_style())

    # Get the top left corner of the detected hand's bounding box.
    height, width, _ = annotated_image.shape
    x_coordinates = [landmark.x for landmark in hand_landmarks]
    y_coordinates = [landmark.y for landmark in hand_landmarks]
    text_x = int(min(x_coordinates) * width)
    text_y = int(min(y_coordinates) * height) - MARGIN

    # Draw handedness (left or right hand) on the image.
    cv2.putText(annotated_image, f"{handedness[0].category_name}",
                (text_x, text_y), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE, HANDEDNESS_TEXT_COLOR, FONT_THICKNESS, cv2.LINE_AA)
    
    # Draw marker numbers on the image
    for i in range(21):
        cv2.putText(annotated_image, f"{i}",
                (int(hand_landmarks[i].x * width), int(hand_landmarks[i].y * height)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)

  return annotated_image

def millis() -> int:
    """Get the current time in milliseconds."""
    return int(round(time.time() * 1000))

def angle_between(p1,midpt,p2,plane=np.array([1,1,1])):
    """Computes the angle between two 3d points and a midpoint"""
    ba = (p1 - midpt)*plane
    bc = (p2 - midpt)*plane

    cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc))
    angle = np.arccos(cosine_angle)

    return np.degrees(angle)

def analyze_hand_landmarks(hand_landmarks):
    """Analyze the hand landmarks and return the joint angles."""
    
    # We have the hand tracker configured to return only one hand, so we can make some assumptions
    # and just grab the first hand_landmarks object, which contains the normalized coordinates
    # of the detected hand.
    hand_landmarks = hand_landmarks.hand_landmarks[0]

    # Convert the hand landmark data into a numpy array of joint positions
    joint_xyz = np.zeros((21,3))
    for i in range(21):
        joint_xyz[i] = np.array([hand_landmarks[i].x, hand_landmarks[i].y, hand_landmarks[i].z])
    

    # Create storage for the angles
    joint_angles = np.zeros(15)

    # First finger, fore or index
    # Angles calculated correspond to knuckle flex, knuckle yaw and long tendon length for all fingers,
    joint_angles[0] = 180-angle_between(joint_xyz[0], joint_xyz[5], joint_xyz[6])
    joint_angles[1] = 90-angle_between(joint_xyz[9], joint_xyz[5], joint_xyz[6])
    joint_angles[2] = 180-angle_between(joint_xyz[5], joint_xyz[6], joint_xyz[7])
    #print(int(joint_angles[0]), int(joint_angles[1]), int(joint_angles[2]))

    # Second finger, middle
    joint_angles[3] = 180-angle_between(joint_xyz[0], joint_xyz[9], joint_xyz[10])
    joint_angles[4] = 90-angle_between(joint_xyz[13], joint_xyz[9], joint_xyz[10])
    joint_angles[5] = 180-angle_between(joint_xyz[9], joint_xyz[10], joint_xyz[11])
    #print(joint_angles[3], joint_angles[4], joint_angles[5])

    # Third finger, ring
    joint_angles[6] = 180-angle_between(joint_xyz[0], joint_xyz[13], joint_xyz[14])
    joint_angles[7] = angle_between(joint_xyz[9], joint_xyz[13], joint_xyz[14])-90
    joint_angles[8] = 180-angle_between(joint_xyz[13], joint_xyz[14], joint_xyz[15])
    #print(joint_angles[6], joint_angles[7], joint_angles[8])

    # Fourth finger, pinky
    joint_angles[9] = 180-angle_between(joint_xyz[0], joint_xyz[17], joint_xyz[18])
    joint_angles[10] = angle_between(joint_xyz[13], joint_xyz[17], joint_xyz[18])-90
    joint_angles[11] = 180-angle_between(joint_xyz[17], joint_xyz[18], joint_xyz[19])
    #print(int(joint_angles[9]), int(joint_angles[10]), int(joint_angles[11]))

    # Thumb, bit of a guess for basal rotation might be better automatic
    joint_angles[12] = 180-angle_between(joint_xyz[1], joint_xyz[2], joint_xyz[3])
    joint_angles[13] = 60-angle_between(joint_xyz[2], joint_xyz[1], joint_xyz[5])
    joint_angles[14] = 180-angle_between(joint_xyz[2], joint_xyz[3], joint_xyz[4])
    #joint_angles[15] = angle_between(joint_xyz[9], joint_xyz[5], joint_xyz[2])
    #print(joint_angles[12], joint_angles[13], joint_angles[14], joint_angles[15])

    return joint_angles

# Angle debug display
def draw_angles_on_image(image, joint_angles):
    """Draw the joint angles on the image."""
    height, width, _ = image.shape

    # Draw the finger angles
    for i in range(15):
        cv2.putText(image, f"{i}: {int(joint_angles[i])}",
                (int(width*0.05+int(i/3)*width*0.1), int(height*0.1 + (i%3)*height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
        
    # Draw titles for the columns
    cv2.putText(image, "idx", (int(width*0.05), int(height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
    cv2.putText(image, "mid", (int(width*0.15), int(height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
    cv2.putText(image, "rng", (int(width*0.25), int(height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
    cv2.putText(image, "pnk", (int(width*0.35), int(height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
    cv2.putText(image, "thb", (int(width*0.45), int(height*0.05)), cv2.FONT_HERSHEY_DUPLEX,
                FONT_SIZE/2, (0,0,0), FONT_THICKNESS, cv2.LINE_AA)
        
    return image
    
# Main hand tracking function
async def hand_tracking(tx_queue):
    BaseOptions = mp.tasks.BaseOptions
    HandLandmarker = mp.tasks.vision.HandLandmarker
    HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
    VisionRunningMode = mp.tasks.vision.RunningMode


    # Create a hand landmarker instance with the video mode:
    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path='models/hand_landmarker.task'),
        running_mode=VisionRunningMode.VIDEO)
    with HandLandmarker.create_from_options(options) as landmarker:

        cap = cv2.VideoCapture(0)

        # Get elapsed millis
        ts = millis()
        
        try: 
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Mirror the image because we're facing the webcam
                frame = cv2.flip(frame, 1)

                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)

                # Run hand detection
                detection_result = landmarker.detect_for_video(mp_image,millis()-ts)

                # Draw the hand annotations on the image.
                annotated_image = draw_landmarks_on_image(frame, detection_result)

                # Analyze the hand landmarks
                if detection_result.hand_landmarks:
                    joint_angles = analyze_hand_landmarks(detection_result)
                    if (joint_angles is not None):

                        # Push the joint angles into the transmit queue
                        await tx_queue.put(joint_angles) 

                        # Draw debug info on image
                        annotated_image = draw_angles_on_image(annotated_image, joint_angles)
                        pass

                cv2.imshow('DexHand BLE', annotated_image)

                
                # Yield
                await asyncio.sleep(0.01)

                # Check for escape key
                if cv2.waitKey(5) & 0xFF == 27:
                    raise Exception('User pressed ESC')
        
        except asyncio.CancelledError:
            print('Hand tracking task has been cancelled.')
            # Clean Up
            cap.release()
            cv2.destroyAllWindows()



UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# TIP: you can get this function and more from the ``more-itertools`` package.
def sliced(data: bytes, n: int) -> Iterator[bytes]:
    """
    Slices *data* into chunks of size *n*. The last slice may be smaller than
    *n*.
    """
    return takewhile(len, (data[i : i + n] for i in count(0, n)))

       
async def ble_communication(tx_queue):
    """This is a simple transmission scheme that uses the Nordic Semiconductor
    (nRF) UART service to stream commands and data to the DexHand. 
    """

    def dexhand_devices(device: BLEDevice, adv: AdvertisementData):
        if (adv.local_name is not None) and ("DexHand" in adv.local_name):
            return True
        return False

    device = await BleakScanner.find_device_by_filter(dexhand_devices)

    if device is None:
        print("No DexHand device was found to establish a connection.")
        sys.exit(1)

    def handle_disconnect(_: BleakClient):
        print("Device was disconnected, goodbye.")
        # cancelling all tasks effectively ends the program
        #for task in asyncio.all_tasks():
        #    task.cancel()

    def handle_rx(_: BleakGATTCharacteristic, data: bytearray):
        # Convert received byte array to string
        data = data.decode("utf-8")

        # Responses are pretty basic - this can be extended later if more
        # data comes back from the hand
        if (data.startswith("HB:")):
            print("Heartbeat received from hand: ", data[3:])
        else:
            print("Unknown message received:", data)

    
    async with BleakClient(device, disconnected_callback=handle_disconnect) as client:
        await client.start_notify(UART_TX_CHAR_UUID, handle_rx)

        print("Connected, start typing and press ENTER...")

        loop = asyncio.get_running_loop()
        nus = client.services.get_service(UART_SERVICE_UUID)
        rx_char = nus.get_characteristic(UART_RX_CHAR_UUID)

        # Schedule a timer to send a heartbeat message to the hand every 5 seconds
        async def send_heartbeat():
            hb = 0
            
            while True:
                await asyncio.sleep(5)
                hb_msg = "HB:"+str(hb)+"\n"
                hb += 1
                await client.write_gatt_char(rx_char, hb_msg.encode(), True)

        asyncio.create_task(send_heartbeat())

        while True:

            # Throw away any surplus queued joint angles - we only want to transmit the latest
            while (tx_queue.qsize() > 1):
                tx_queue.get_nowait()

            # Grab the latest set of angles
            joint_angles = await tx_queue.get()

            # Encode the joint angles into 16-bit integers
            data = bytearray()
            data += b"POS:"
            for angle in joint_angles:
                data += struct.pack('<h', int(angle))
            data += b"\n"
            
            # Send the joint angles to the hand
            for s in sliced(data, rx_char.max_write_without_response_size):
                await client.write_gatt_char(rx_char, s)

            #await client.write_gatt_char(rx_char, data, True)
            #print("Sent:", data, "Bytes:", len(data))

            # This waits until you type a line and press ENTER.
            # A real terminal program might put stdin in raw mode so that things
            # like CTRL+C get passed to the remote device.
            #data = await loop.run_in_executor(None, sys.stdin.buffer.readline)

            # data will be empty on EOF (e.g. CTRL+D on *nix)
            #if not data:
            #    break

            # Send the data via BLE
            #await client.write_gatt_char(rx_char, data, True)
            #print("Sent:", data)


async def main():

    # Create the transmit queue
    ble_tx_queue = asyncio.Queue()
    
    # Create the tasks
    hand_tracking_task = asyncio.create_task(hand_tracking(ble_tx_queue))
    ble_communication_task = asyncio.create_task(ble_communication(ble_tx_queue))

    # Run the tasks concurrently
    
    await asyncio.gather(hand_tracking_task, ble_communication_task, return_exceptions=True)

asyncio.run(main())