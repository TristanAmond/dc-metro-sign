import board
import gc
import time
import busio
from digitalio import DigitalInOut, Pull
import neopixel

from adafruit_matrixportal.matrix import Matrix
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wifimanager

import json
import display_manager

print("All imports loaded | Available memory: {} bytes".format(gc.mem_free()))

# --- CONSTANTS SETUP ---

try:
    from secrets import secrets
except ImportError:
    print("Wifi + constants are kept in secrets.py, please add them there!")
    raise

# local Metro station
station_code = secrets["station_code"]
historical_trains = [None, None]

# weather data dict
weather_data = {}
# daily highest temperature
# max_temp, day of the year
highest_temp = [None,None]
# daily lowest temperature
# min_temp, day of the year
lowest_temp = [None, None]
# current temp (for historical)
current_temp = []

current_time = None

# --- DISPLAY SETUP ---

# MATRIX DISPLAY MANAGER
# NOTE this width is set for 2 64x32 RGB LED Matrix panels
# (https://www.adafruit.com/product/2278)
matrix = Matrix(width=128, height=32, bit_depth=2, tile_rows=1)
display_manager = display_manager.display_manager(matrix.display)
print("Display loaded | Available memory: {} bytes".format(gc.mem_free()))

# --- WIFI SETUP ---
# Initialize ESP32 Pins:
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)
# Initialize wifi components
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
# Initialize neopixel status light
status_light = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
# Initialize wifi object
wifi = adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager(esp, secrets, status_light, attempts=5)
#wifi.connect()

gc.collect()
print("WiFi loaded | Available memory: {} bytes".format(gc.mem_free()))

# --- CLASSES ---

class Train:
    def __init__(self, destination, destination_name, destination_code, minutes):
        self.destination = destination
        self.destination_name = destination_name
        self.destination_code = destination_code
        self.minutes = minutes

# --- API CALLS ---

# queries WMATA API to return an array of two Train objects
# input is StationCode from secrets.py, and a historical_trains array
def get_trains(StationCode, historical_trains):
    try:
        # query WMATA API with input StationCode
        URL = 'https://api.wmata.com/StationPrediction.svc/json/GetPrediction/'
        payload = {'api_key': secrets['wmata api key']}
        response = wifi.get(URL + StationCode, headers=payload)
        json_data = response.json()
        del response
    except Exception as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()

    # set up two train directions (A station code and B station code)
    A_train=None
    B_train=None
    # check trains in json response for correct destination code prefixes
    try:
        for item in json_data['Trains']:
            if item['Line'] is not "RD":
                pass
            # if no train and destination code prefix matches, add
            if item['DestinationCode'][0] is "A" and A_train is None:
                A_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            elif item['DestinationCode'][0] is "B" and B_train is None:
                B_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            # if both trains have a train object, pass
            else:
                pass

    except Exception as e:
        print ("Error accessing the WMATA API: ", e)
        pass

    # merge train objects into trains array
    # NOTE: None objects accepted, handled by update_trains function in display_manager.py
    trains=[A_train,B_train]
    # if train objects exist in trains array, add them to historical trains
    if A_train is not None:
        historical_trains[0] = A_train
    if B_train is not None:
        historical_trains[1] = B_train
    # print train data
    try:
        for item in trains:
            print("{} {}: {}".format(item.destination_code, item.destination_name, item.minutes))
    except:
        pass
    return trains

# queries Openweather API to return a dict with current and 3 hr forecast weather data
# input is latitude and longitude coordinates for weather location
def get_weather(weather_data):
    try:
        # query Openweather for weather at location defined by input lat, long
        base_URL = 'https://api.openweathermap.org/data/3.0/onecall?'
        latitude = secrets['dc coords x']
        longitude = secrets['dc coords y']
        units = 'imperial'
        api_key = secrets['openweather api key']
        exclude = 'minutely,alerts'
        response = wifi.get(base_URL
        +'lat='+latitude
        +'&lon='+longitude
        +'&exclude='+exclude
        +'&units='+units
        +'&appid='+api_key
        )
        weather_json = response.json()
        del response

        # insert/update icon and current weather data in dict
        weather_data["icon"] = weather_json["current"]["weather"][0]["icon"]
        weather_data["current_temp"] = weather_json["current"]["temp"]
        weather_data["current_feels_like"] = weather_json["current"]["feels_like"]
        # insert daily forecast min and max temperature into dict
        weather_data["daily_temp_min"] = weather_json["daily"][0]["temp"]["min"]
        weather_data["daily_temp_max"] = weather_json["daily"][0]["temp"]["max"]
        # insert next hour + 1 forecast temperature and feels like into dict
        weather_data["hourly_next_temp"] = weather_json["hourly"][2]["temp"]
        weather_data["hourly_feels_like"] = weather_json["hourly"][2]["feels_like"]

        # clean up response
        del weather_json

        global current_time

        # set daily highest temperature
        global highest_temp
        # if daily highest temperature hasn't been set or is from a previous day
        if highest_temp[0] is None or highest_temp[1] != current_time.tm_wday:
            highest_temp[0] = weather_data["daily_temp_max"]
            highest_temp[1] = current_time.tm_wday
        # if stored highest temp is less than new highest temp
        elif highest_temp[0] < weather_data["daily_temp_max"]:
            highest_temp[0] = weather_data["daily_temp_max"]
        # if stored highest temp is greater than new highest temp
        elif highest_temp[0] > weather_data["daily_temp_max"]:
            weather_data["daily_temp_max"] = highest_temp[0]

        # set daily lowest temperature
        global lowest_temp
        # if daily lowest temperature hasn't been set or is from a previous day
        if lowest_temp[0] is None or lowest_temp[1] != current_time.tm_wday:
            lowest_temp[0] = weather_data["daily_temp_min"]
            lowest_temp[1] = current_time.tm_wday
        # if daily lowest temp is greater than new lowest temp
        elif lowest_temp[0] > weather_data["daily_temp_min"]:
            lowest_temp[0] = weather_data["daily_temp_min"]
        # if daily lowest temp is less than new lowest temp
        elif lowest_temp[0] < weather_data["daily_temp_min"]:
            weather_data["daily_temp_min"] = lowest_temp[0]

        print("Daily Lowest Temp: {} | Daily Highest Temp: {}".format(lowest_temp[0], highest_temp[0]))

        # add current temp to historical array
        global current_temp
        current_temp.append(weather_data["current_temp"])

        # return True for updated dict
        return True

    except Exception as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()

# --- TIME MGMT FUNCTIONS ---

def check_time():
    base_url = "http://io.adafruit.com/api/v2/time/seconds"
    try:
        response = wifi.get(base_url)
        epoch_time = int(response.text)
        del response

        # DST offset
        # MUST UPDATE THIS FOR DAYLIGHT SAVING TIME CHANGE
        is_dst = False
        # Timezone offset
        timezone_offset = -4

        # Convert the timezone offset from hours to seconds
        timezone_offset_seconds = timezone_offset * 3600

        # Apply the timezone offset
        epoch_time += timezone_offset_seconds

        # Adjust for DST
        if is_dst:
            epoch_time -= 3600

        global current_time
        current_time = time.localtime(epoch_time)

    except Exception as e:
        print(e)
        wifi.reset()

def check_open(shut_off_hour):

    weekday = current_time.tm_wday
    hour = current_time.tm_hour
    # SET OPENING TIME
    # current day is Sat/Sun and time is before 7
    if hour < 7 and (weekday == 6 or weekday == 0):
        print("Metro closed: Sat/Sun before 7| D{} H{}".format(weekday, hour))
        return False

    # current day is M-F and time is before 5
    elif hour < 5:
        print("Metro closed: M-F before 5 | D{} H{}".format(weekday, hour))
        return False

    #SET CLOSING TIME
    # Check current hour against shut_off_hour (10PM default, passed in function)
    elif hour >= shut_off_hour:
        print("Metro closed: after 10PM, currently {}:{}".format(hour, current_time.tm_min))
        return False

    return True

# --- OPERATING LOOP ------------------------------------------
loop_counter=1
last_weather_check=None
last_train_check=None
mode="Day"

while True:
    check_time()

    try:
        if check_open(22):
            mode="Day"
            display_manager.night_mode_toggle(True)
        else:
            mode="Night"
            display_manager.night_mode_toggle(False)
    except Exception as e:
        print("Exception: {}".format(e))
        pass
    gc.collect()

    if mode is "Day":

        # fetch weather data on start and recurring (default: 10 minutes)
        if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
            weather = get_weather(weather_data)
            if weather:
                last_weather_check = time.monotonic()
            # update weather display component
            display_manager.update_weather(weather_data)

        # update train data (default: 15 seconds)
        if last_train_check is None or time.monotonic() > last_train_check + 15:
            trains = get_trains(station_code, historical_trains)
            if trains:
                last_train_check = time.monotonic()
            # update train display component
            display_manager.assign_trains(trains, historical_trains)

    display_manager.refresh_display()

    # run garbage collection
    gc.collect()
    # print available memory
    print("Loop {} available memory: {} bytes".format(loop_counter, gc.mem_free()))

    # increment loop and sleep
    # Day mode: 10 seconds
    # Night mode: 5 minutes
    loop_counter+=1
    if mode == "Day":
        time.sleep(10)
    elif mode == "Night":
        time.sleep(300)
