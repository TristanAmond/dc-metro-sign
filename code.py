import board
import gc
import time
import busio
from digitalio import DigitalInOut, Pull
import neopixel
import supervisor

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

# Local Metro station
station_code = secrets["station_code"]
historical_trains = [None, None]

# Stores recent Plane data to avoid repetition
historical_planes = {}

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
    def __init__(self, flight, alt_geom, lat, lon):
        self.flight = flight
        self.alt_geom = alt_geom
        self.lat = lat
        self.lon = lon
        self.location = (lat, lon)
        self.emergency = None

    def get_location(self):
        return self.location


# --- TRANSIT API CALLS ---

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
        print("Failed to get WMATA data, retrying\n", e)
        wifi.reset()

    # set up two train directions (A station code and B station code)
    A_train = None
    B_train = None
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
        print("Error accessing the WMATA API: ", e)
        pass

    # merge train objects into trains array
    # NOTE: None objects accepted, handled by update_trains function in display_manager.py
    trains = [A_train, B_train]
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


# queries local ADS-B reciever with readsb installed for flight data
# adds unseen flights to the plane array
# input is plane array
def get_planes(historical_planes):
    # set local variables
    plane_counter = 0
    planes = {}
    # request plane.json from local ADS-B receiver (default location for readsb)
    # sample format: http://XXX.XXX.X.XXX/tar1090/data/aircraft.json
    try:
        response = wifi.get(secrets['plane_data_json_url'])
        json_dump = response.json()
    except OSError as e:
        print("Failed to get PLANE data, retrying\n", e)
        wifi.reset()
    except RuntimeError as e:
        print("Failed to get PLANE data, retrying\n", e)
        wifi.reset()
    except:
        return historical_planes
    gc.collect()

    try:
        # iterate through each aircraft entry
        for entry in json_dump["aircraft"]:
            # if flight callsign exists
            if "flight" in entry:
                try:
                    new_plane = Plane(entry["flight"].strip(), entry["alt_geom"], entry["lat"], entry["lon"])
                    # seperate emergency field as optional
                    if "emergency" in entry:
                        new_plane.emergency = entry["emergency"]
                    # add to planes dict and increment counter
                    planes[new_plane.flight] = new_plane
                    # add to historical plane dict if not already there
                    if entry["flight"].strip() not in historical_planes:
                        historical_planes[new_plane.flight] = new_plane
                        plane_counter += 1
                except:
                    print("couldn't add plane?")
        print("found {} new planes | {} total planes".format(plane_counter, len(historical_planes)))
        if plane_counter >= 1 and len(historical_planes) >= 5:
            historical_planes = planes
        return planes
    except Exception as e:
        print(e)
        return historical_planes


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
    global mode
    departure_diff = minutes_until_departure(departure_time)

    # if departure time is beyond, do nothing
    if departure_diff > diff:
        print(f"{departure_diff} minutes until departure")
        pass
    # if departure time is within timeframe, switch mode to event
    elif 0 < departure_diff < diff:
        mode = "Event"
    # if departure time is 0 or less than 0, reset mode
    else:
        mode = "Day"


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

def check_time():
    base_url = "http://io.adafruit.com/api/v2/time/seconds"
    try:
        response = wifi.get(base_url)
        epoch_time = int(response.text)
        del response

        global current_time
        global current_time_epoch
        current_time = convert_epoch_to_struct(epoch_time)
        current_time_epoch = epoch_time

    except Exception as e:
        print(e)
        wifi.reset()


def convert_epoch_to_struct(epoch_time):
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

    return time.localtime(epoch_time)


def convert_struct_to_epoch(struct_time):
    date, t = struct_time.split("T")

    year, month, day = map(int, date.split("-"))

    hour, minute, second = map(int, t.split("-")[0].split(":"))

    t = time.struct_time((year, month, day, hour, minute, second, -1, -1, -1))

    epoch_time = time.mktime(t)

    return epoch_time


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


# --- OPERATING LOOP ------------------------------------------
def main():
    loop_counter = 1
    last_weather_check = None
    last_train_check = None
    last_plane_check = None
    last_event_check = None
    last_headline_check = None
    global mode
    mode = "Day"

    # TODO switch counters to loop modulos to save memory

    while True:
        # update current time struct and epoch
        check_time()
        last_time_check = time.monotonic()

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

        # run day mode actions
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
                    planes = get_planes(historical_planes)
                except Exception as e:
                    print(f"Plane error: {e}")
                last_plane_check = time.monotonic()

            # update event data (default: 5 minutes)
            if last_event_check is None or time.monotonic() > last_event_check + 60 * 5:
                try:
                    # check for event departure
                    global next_event
                    next_event = get_next_event()
                    if next_event is not None:
                        # switch to event mode if time is within an hour
                        event_mode_switch(next_event['departure_time'])
                        pass
                    else:
                        print("no event found.")
                except Exception as e:
                    print(f"Event error: {e}")
                last_event_check = time.monotonic()

            # update top headline (default: 1 minute)
            if loop_counter >= 2 and (last_headline_check is None or time.monotonic() > last_headline_check + 60 * 1):
                global current_headline
                try:
                    headline = get_headline()
                except Exception as e:
                    print(f"Headline error: {e}")
                    headline = None

                if headline is not None:
                    try:
                        headline_string = f"{current_headline['publishedTime']} | {current_headline['source']}\n{current_headline['title']}"
                        print("pushing headline: {}".format(current_headline['title']))
                        send_notification(headline_string)
                    except Exception as e:
                        print(f"Headline error: {e}")
                # No / No new headline
                else:
                    pass
                last_headline_check = time.monotonic()
            else:
                pass

            # send a scrolling notification on the hour (DEMO)
            if current_time.tm_min == 0 and current_time.tm_sec < 15:
                send_notification("Time is {}:0{}".format(current_time.tm_hour, current_time.tm_min))

        # run event mode actions
        if mode is "Event":
            # fetch weather data on start and recurring (default: 10 minutes)
            if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
                weather = get_weather(weather_data)
                if weather:
                    last_weather_check = time.monotonic()
                # update weather display component
                display_manager.update_weather(weather_data)

            # calculate time until departure
            departure_countdown = minutes_until_departure(next_event['departure_time'])
            if departure_countdown >= 1:
                # test printing TODO remove
                departure_time = convert_epoch_to_struct(next_event['departure_time'])
                print("Current time: {}:{} | Departure time: {}:{} | Departure countdown: {}".format(
                    current_time.tm_hour, current_time.tm_min, departure_time.tm_hour, departure_time.tm_min,
                    departure_countdown)
                )
                # update display with headsign/station and time to departure
                display_manager.update_event(departure_countdown, next_event['departure_train'])
            else:
                next_event = {}
                mode = "Day"

        # display top plane data every 40 loops
        # TODO find closest plane and display when within a certain distance
        if loop_counter % 40 == 0 and len(planes) > 0:
            try:
                plane = planes.popitem()[1]
                display_manager.scroll_text("Flight {}\n  Alt: {}".format(plane.flight, plane.alt_geom))
            except Exception as e:
                print(f"Plane Notification Error: {e}")

        # refresh display
        display_manager.refresh_display()
        # run garbage collection
        gc.collect()
        # print available memory
        print("Loop {} | {} Mode | Available memory: {} bytes".format(loop_counter, mode, gc.mem_free()))

        # if any checks haven't run in a long time, restart the Matrix Portal
        # weather check: 60 minutes
        # train check: 10 minutes
        if mode == "Day" and ((last_train_check is None or time.monotonic() - last_train_check >= 600) and (
                last_time_check is None or time.monotonic() - last_time_check >= 3600)):
            print("Supervisor reloading\nLast Weather Check: {} | Last Train Check: {}".format(last_weather_check,
                                                                                               last_train_check))
            time.sleep(5)
            supervisor.reload()

        # Increment loop and sleep
        # Day mode: 10 seconds
        # Event mode: 50 seconds
        # Night mode: 5 minutes
        # TODO make Night mode smarter to reduce API calls during off-hours
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
