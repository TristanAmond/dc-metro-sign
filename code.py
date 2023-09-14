import board
import gc
import time
import busio
from digitalio import DigitalInOut
import neopixel
import supervisor

from adafruit_matrixportal.matrix import Matrix
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wifimanager

import display_manager

print("All imports loaded | Available memory: {} bytes".format(gc.mem_free()))

# --- CONSTANTS SETUP ---

try:
    from secrets import secrets
except ImportError:
    print("Wifi + constants are kept in secrets.py, please add them there!")
    raise

# Stores train data
station_code = secrets["station_code"]
historical_trains = [None, None]

# Stores nearest plane data
nearest_plane = None

# Stores next event data
next_event = None

# Stores most recent headline
current_headline = None

# Weather data dict
weather_data = {}
# Daily highest temperature
# max_temp, day of the year
highest_temp = [None, None]
# Daily lowest temperature
# min_temp, day of the year
lowest_temp = [None, None]
# Current temp (for historical)
current_temp = []

# Current time
current_time = None
current_time_epoch = None

# Default operating hour start and end times
start_time = 6
end_time = 21

# Notification queue
notification_queue = []

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
# Initialize Wi-Fi object
wifi = adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager(esp, secrets, status_light, attempts=5)
# wifi.connect()

gc.collect()
print("WiFi loaded | Available memory: {} bytes".format(gc.mem_free()))


# --- CLASSES ---

class Train:
    def __init__(self, destination, destination_name, destination_code, minutes):
        self.destination = destination
        self.destination_name = destination_name
        self.destination_code = destination_code
        self.minutes = minutes


class Plane:
    def __init__(self, flight, altitude, distance, emergency=None):
        self.flight = flight
        self.altitude = altitude
        self.distance = distance
        self.emergency = emergency


# --- TRANSIT API CALLS ---

# queries WMATA API to return an array of two Train objects
# input is StationCode from secrets.py, and a historical_trains array
def get_trains(station_code, historical_trains):
    json_data = None
    a_train = None
    b_train = None

    try:
        # query WMATA API with input StationCode
        URL = 'https://api.wmata.com/StationPrediction.svc/json/GetPrediction/'
        payload = {'api_key': secrets['wmata api key']}
        response = wifi.get(URL + station_code, headers=payload)
        json_data = response.json()
        del response
    except Exception as e:
        print("Failed to get WMATA data, retrying\n", e)
        wifi.reset()

    if json_data is not None:
        # Set up two train directions (A station code and B station code)
        try:
            for item in json_data['Trains']:
                if item['Line'] is not "RD":
                    pass
                # Handles A direction trains
                if item['DestinationCode'][0] == "A":
                    # If a train has not been assigned, create new Train object and assign
                    if a_train is None:
                        a_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'],
                                        item['Min'])
                    else:
                        pass
                # Handles B direction trains
                elif item['DestinationCode'][0] == "B":
                    # # If b train has not been assigned, create new Train object and assign
                    if b_train is None:
                        b_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'],
                                        item['Min'])
                    else:
                        pass
                # For neither A nor B direction trains, pass
                else:
                    pass

        except Exception as e:
            print("Error accessing the WMATA API: ", e)
            pass
    else:
        print("Failed to get response from WMATA API")
        pass

    # If new a train is found, replace historical a train
    if a_train is not None:
        historical_trains[0] = a_train
    elif a_train is None and historical_trains[0] is not None:
        a_train = historical_trains[0]
    # If new b train is found, replace historical b train
    if b_train is not None:
        historical_trains[1] = b_train
    elif b_train is None and historical_trains[1] is not None:
        b_train = historical_trains[1]

    # Print trains
    trains = [a_train, b_train]
    try:
        for item in trains:
            print("{}: {}".format(item.destination_name, item.minutes))
    except Exception as e:
        print(e)
        pass
    return trains


# --- PLANE API CALLS ---
def get_nearest_plane():
    global nearest_plane
    json_data = None
    # request plane.json from local ADS-B receiver (default location for readsb)
    # sample format: http://XXX.XXX.X.XXX/tar1090/data/aircraft.json
    try:
        response = wifi.get(secrets['plane_data_json_url'])
        json_data = response.json()
    except OSError as e:
        print("Failed to get PLANE data, retrying\n", e)
        wifi.reset()
    except RuntimeError as e:
        print("Failed to get PLANE data, retrying\n", e)
        wifi.reset()
    except Exception as e:
        print("Failed to get PLANE data", e)
        pass
    gc.collect()

    # If aircraft data exists
    if json_data is not None and json_data["aircraft"] is not None:
        try:
            # iterate through each aircraft entry
            for entry in json_data["aircraft"]:
                # Check if flight callsign and distance exists
                if "flight" and "alt_geom" and "r_dst" in entry:
                    entry_distance = round(int(entry["r_dst"]), 2)
                    if nearest_plane is None or (
                            nearest_plane is not None and int(nearest_plane.distance) > entry_distance):
                        try:
                            nearest_plane = Plane(
                                entry["flight"].strip(),
                                entry["alt_geom"],
                                str(entry_distance)
                            )
                            print("Nearest plane: {} | {} | {}".format(nearest_plane.flight, nearest_plane.altitude,
                                                                       nearest_plane.distance))
                            # separate emergency field as optional
                            if "emergency" in entry:
                                nearest_plane.emergency = entry["emergency"]
                        except Exception as e:
                            print(f"couldn't update nearest plane entry: {e}")
        except Exception as e:
            print(e)
    else:
        print("Failed to get PLANE data")


# --- WEATHER API CALLS ---

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
                            + 'lat=' + latitude
                            + '&lon=' + longitude
                            + '&exclude=' + exclude
                            + '&units=' + units
                            + '&appid=' + api_key
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
        print("Failed to get WEATHER data, retrying\n", e)
        wifi.reset()


# --- EVENT API CALLS ---

# retrieve an event from a local Raspberry Pi
# sample format: http://XXX.XXX.X.XXX/next_event.json
def get_next_event():
    global next_event
    try:
        response = wifi.get(secrets['event_data_json_url'])
        json_data = response.json()
        del response
    except Exception as e:
        print("Failed to get EVENT data: {}".format(e))
        return None
    if json_data is not None:
        next_event = {}
        try:
            next_event['departure_time'] = json_data['departure_time']
            next_event['departure_train'] = json_data['departure_train']
            return next_event
        except Exception as e:
            print("Probably no events scheduled: {}".format(e))
            return None
    else:
        return None


# switches mode to event if calculated departure is within 60 minutes
def event_mode_switch(departure_time, diff=60):
    departure_diff = minutes_until_departure(departure_time)

    # if departure time is within timeframe, switch mode to event
    if 0 < departure_diff < diff:
        return "Event"
    # if departure time is 0 or less than 0, reset mode
    else:
        return "Day"


# --- HEADLINE FUNCTIONS ---

def get_headline():
    global current_headline
    try:
        response = wifi.get(secrets['headline_json_url'])
        json_data = response.json()
        del response
    except Exception as e:
        print("Failed to get HEADLINE data: {}".format(e))
        return None
    if json_data is not None:
        new_headline = {}
        try:
            new_headline['source'] = json_data['source']
            new_headline['publishedTime'] = json_data['publishedTime']
            new_headline['title'] = json_data['title']
        except Exception as e:
            print("Failed to create HEADLINE object: {}".format(e))
            return None
        # Check to see if the headline has changed
        if current_headline is not None and current_headline['title'] == new_headline['title']:
            return None

        current_headline = new_headline
        return current_headline
    else:
        print("Failed to get HEADLINE data: json_data is None")
        return None


# --- TIME MGMT FUNCTIONS ---

def get_current_time():
    global current_time
    global current_time_epoch

    base_url = "http://io.adafruit.com/api/v2/time/"
    try:
        response = wifi.get(base_url + "seconds")
        current_time_epoch = int(response.text)
        del response
    except Exception as e:
        print(e)
        wifi.reset()

    try:
        response = wifi.get(base_url + "ISO-8601")
        current_iso_time = response.text
        current_time = parse_iso_time(current_iso_time)
        del response
    except Exception as e:
        print(e)
        wifi.reset()


def parse_iso_time(iso_time):
    year = int(iso_time[0:4])
    month = int(iso_time[5:7])
    day = int(iso_time[8:10])
    hours = int(iso_time[11:13])
    minutes = int(iso_time[14:16])
    seconds = int(iso_time[17:19])

    # Adjust month and year for January and February
    if month <= 2:
        month += 12
        year -= 1

    # Calculate weekday using Zeller's Congruence algorithm
    weekday = (day + 2 * month + 3 * (month + 1) // 5 + year + year // 4 - year // 100 + year // 400) % 7
    time_tuple = (year, month, day, hours, minutes, seconds, weekday, -1, -1)
    time_struct = time.struct_time(time_tuple)

    return time_struct


# Calculates difference between two epoch times
# Input is a departure time in epoch time
# Output is difference between departure and last current time in minutes
def minutes_until_departure(departure_time):
    global current_time_epoch
    if current_time_epoch is not None:
        difference = departure_time - current_time_epoch
        return round(difference / 60)
    else:
        return None


def check_open(start=start_time, end=end_time):
    weekday = current_time.tm_wday
    hour = current_time.tm_hour

    # Within operating hours, current day is Sat/Sun
    if hour < start + 1 and (weekday >= 5):
        print("Metro closed: Sat/Sun before 7| D{} H{}".format(weekday, hour))
        return False

    # Within operating hours, current day is M-F
    elif start <= hour < end:
        return True

    # Not in operating hours
    else:
        return False


# --- MISC. FUNCTIONS ---
def send_notification(text):
    display_manager.scroll_text(text)


def is_valid_integer(string):
    try:
        int(string)
        return True
    except ValueError:
        return False


# --- OPERATING LOOP ------------------------------------------
def main():
    global current_time
    global start_time
    global end_time
    global next_event
    global nearest_plane
    global historical_trains
    loop_counter = 1
    last_weather_check = None
    last_train_check = None
    last_plane_check = None
    last_event_check = None
    last_headline_check = None
    mode = "Day"

    # TODO switch counters to loop modulos to save memory

    while True:
        # update current time struct and epoch
        get_current_time()
        last_time_check = time.monotonic()
        if loop_counter == 1:
            print(
                f"Current Time: {current_time.tm_hour}:{current_time.tm_min} Wkd: {current_time.tm_wday}" +
                f"| Epoch Time: {current_time_epoch}"
            )

        # check if display should be in night mode
        try:
            if check_open() and mode != "Event":
                mode = "Day"
                display_manager.night_mode_toggle(True)
            elif check_open() and mode == "Event":
                pass
            else:
                mode = "Night"
                display_manager.night_mode_toggle(False)
        except Exception as e:
            print("Exception: {}".format(e))
            pass
        gc.collect()

        # --- DAY MODE
        if mode is "Day":
            # fetch weather data on start and recurring (default: 10 minutes)
            if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
                try:
                    get_weather(weather_data)
                    # update weather display component
                    display_manager.update_weather(weather_data)
                except Exception as e:
                    print(f"Weather error: {e}")
                last_weather_check = time.monotonic()

            # update train data (default: 15 seconds)
            if last_train_check is None or time.monotonic() > last_train_check + 15:
                try:
                    trains = get_trains(station_code, historical_trains)
                    # update train display component
                    display_manager.update_trains(trains, historical_trains)
                except Exception as e:
                    print(f"Train error: {e}")
                last_train_check = time.monotonic()

            # update plane data (default: 5 minutes)
            if last_plane_check is None or time.monotonic() > last_plane_check + 60 * 5:
                try:
                    get_nearest_plane()
                    last_plane_check = time.monotonic()
                except Exception as e:
                    print(f"Plane error: {e}")
                # Push nearest plane to notification queue (default: 12 minutes)
                if nearest_plane is not None and current_time.tm_min % 12 == 0:
                    nearest_plane_string = (
                            f"Flight: {nearest_plane.flight}\nAlt: {nearest_plane.altitude}" +
                            f" | Dist: {nearest_plane.distance}"
                    )
                    notification_queue.append(nearest_plane_string)

            # update event data (default: 5 minutes)
            if last_event_check is None or time.monotonic() > last_event_check + 60 * 5:
                try:
                    # check for event departure
                    next_event = get_next_event()
                    last_event_check = time.monotonic()
                    if next_event is not None:
                        # switch to event mode if time is within an hour
                        mode = event_mode_switch(next_event['departure_time'])
                        pass
                    else:
                        print("no event found.")
                except Exception as e:
                    print(f"Event error: {e}")

            # Update top headline (default: 1 minute)
            # Delay check on cold start by 2 loops
            if loop_counter >= 2 and (last_headline_check is None or time.monotonic() > last_headline_check + 60 * 1):
                global current_headline
                # Check for a new headline
                try:
                    headline = get_headline()
                except Exception as e:
                    print(f"Headline error: {e}")
                    headline = None

                # If a new headline exists, push it to the notification queue
                if headline is not None:
                    try:
                        headline_string = (
                                f"{current_headline['publishedTime']} | {current_headline['source']}\n" +
                                f"{current_headline['title']}"
                        )
                        notification_queue.append(headline_string)
                    except Exception as e:
                        print(f"Headline error: {e}")
                # No / No new headline
                else:
                    pass
                last_headline_check = time.monotonic()
            else:
                pass

            # Push current time to the top of the notification queue at the top of the hour
            if current_time.tm_min == 0 and current_time.tm_sec < 15:
                notification_queue.insert(0, "Time is {}:0{}".format(current_time.tm_hour, current_time.tm_min))

        # --- EVENT MODE ---
        if mode is "Event":
            # fetch weather data on start and recurring (default: 10 minutes)
            if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
                weather = get_weather(weather_data)
                if weather:
                    last_weather_check = time.monotonic()
                # update weather display component
                display_manager.update_weather(weather_data)

            # calculate time until departure
            if next_event is not None:
                departure_countdown = minutes_until_departure(next_event['departure_time'])
                if departure_countdown >= 1:
                    # test printing TODO remove
                    print("Current time: {}:{} | Departure countdown: {}".format(
                        current_time.tm_hour, current_time.tm_min, departure_countdown)
                    )
                    # update display with headsign/station and time to departure
                    display_manager.update_event(departure_countdown, next_event['departure_train'])
                # If departure time has passed, switch back to day mode
                else:
                    next_event = None
                    mode = "Day"
            # If next_event is None, switch back to day mode
            else:
                mode = "Day"

        # NOTIFICATION QUEUE HANDLER
        if len(notification_queue) > 0:
            print(f"Notification Queue:\n{notification_queue}")
            try:
                send_notification(notification_queue.pop(0))
            except Exception as e:
                print(f"Notification Error: {e}")

        # refresh display
        display_manager.refresh_display()
        # run garbage collection
        gc.collect()
        # print available memory
        print(f"Loop {loop_counter} | {mode} Mode | Available memory: {gc.mem_free()} bytes")

        # if any checks haven't run in a long time, restart the Matrix Portal
        # weather check: 60 minutes
        # train check: 10 minutes
        if mode == "Day" and ((last_train_check is None or time.monotonic() - last_train_check >= 600) and (
                last_time_check is None or time.monotonic() - last_time_check >= 3600)):
            print(
                "Supervisor reloading\nLast Weather Check: {} | Last Train Check: {}".format(
                    last_weather_check,
                    last_train_check
                )
            )
            time.sleep(5)
            supervisor.reload()

        # Increment loop and sleep
        # Day mode: 10 seconds
        # Event mode: 50 seconds
        loop_counter += 1
        if mode == "Day":
            time.sleep(10)
        elif mode == "Event":
            time.sleep(50)
        else:
            # Calculate the time until the next start_time
            if current_time.tm_hour < start_time:
                # If current_hour is before the start_time, sleep until start_time
                time_to_sleep = (start_time - current_time.tm_hour) * (60 * 60)
            else:
                # If current_hour is after the end_time, sleep until start_time of the next day
                time_to_sleep = (24 - current_time.tm_hour + start_time) * (60 * 60)

            time.sleep(time_to_sleep)


if __name__ == "__main__":
    main()
