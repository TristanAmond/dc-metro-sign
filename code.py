import board
import gc
import time
import busio
from digitalio import DigitalInOut
import neopixel
import microcontroller

from adafruit_matrixportal.matrix import Matrix
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wifimanager

import display_manager

print(f"All imports loaded | Available memory: {gc.mem_free()} bytes")

# --- CONSTANTS SETUP ---

try:
    from secrets import secrets
except ImportError:
    print("Wifi + constants are kept in secrets.py, please add them there!")
    raise

# Stores train data
station_code = secrets["station code"]
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
timezone_offset = None

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
print(f"Display loaded | Available memory: {gc.mem_free()} bytes")

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
wifi.timeout = 20

gc.collect()
print(f"WiFi loaded | Available memory: {gc.mem_free()} bytes")


# --- CLASSES ---

class Train:
    def __init__(self, destination, destination_name, destination_code, minutes):
        self.destination = destination
        self.destination_name = destination_name
        self.destination_code = destination_code
        self.minutes = minutes

    def __getitem__(self, key):
        if key == 'destination':
            return self.destination
        elif key == 'destination_name':
            return self.destination_name
        elif key == 'destination_code':
            return self.destination_code
        elif key == 'minutes':
            return self.minutes
        else:
            raise KeyError(f"Invalid key: {key}")


class Plane:
    def __init__(self, flight, altitude, distance, emergency=None):
        self.flight = flight
        self.altitude = altitude
        self.distance = distance
        self.emergency = emergency

    def __getitem__(self, key):
        if key == 'flight':
            return self.flight
        elif key == 'altitude':
            return self.altitude
        elif key == 'distance':
            return self.distance
        elif key == 'emergency':
            return self.emergency
        else:
            raise KeyError(f"Invalid key: {key}")

    def get_plane_string(self):
        return (f"Flight: {self.flight}\nAlt: {add_commas_to_number(str(self.altitude))}ft" +
                f" | Dist: {self.distance}nmi")


class Article:
    def __init__(self, source, publishedTime, publishedAt, title):
        self.source = source
        self.publishedTime = publishedTime
        self.publishedAt = publishedAt
        self.title = title

    def __repr__(self):
        return ('Article(source=\'{self.source}\', title=\'{self.title}\', publishedTime=\'{self.publishedTime}\', '
                'publishedAt=\'{self.publishedAt}\')').format(
            self=self)

    def __getitem__(self, key):
        if key == 'source':
            return self.source
        elif key == 'publishedTime':
            return self.publishedTime
        elif key == 'publishedAt':
            return self.publishedAt
        elif key == 'title':
            return self.title
        else:
            raise KeyError(f"Invalid key: {key}")

    def get_headline_string(self):
        headline_string = format_time_struct(self.publishedTime)
        return f"{headline_string} | {self.source}\n{self.title}"


# --- WEATHER API CALLS ---

# queries Openweather API to return a dict with current and 3 hr forecast weather data
# input is latitude and longitude coordinates for weather location
def get_weather():
    """
    Retrieves weather data from the OpenWeather API based on the provided latitude and longitude.

    Args:
        weather_data (dict): A dictionary to store the weather data.

    Returns:
        bool: True if the weather data is successfully retrieved and updated in the dictionary.
    """
    global weather_data
    global current_time

    # Query Openweather for weather at location defined by input lat, long
    try:
        base_url = 'https://api.openweathermap.org/data/3.0/onecall?'
        latitude = secrets['dc coords x']
        longitude = secrets['dc coords y']
        units = 'imperial'
        api_key = secrets['openweather api key']
        exclude = 'minutely,alerts'
        response = wifi.get(base_url
                            + 'lat=' + latitude
                            + '&lon=' + longitude
                            + '&exclude=' + exclude
                            + '&units=' + units
                            + '&appid=' + api_key
                            )
        weather_json = response.json()
        del response

        # Insert/update icon and current weather data in dict
        weather_data["icon"] = weather_json["current"]["weather"][0]["icon"]
        weather_data["current_temp"] = weather_json["current"]["temp"]
        weather_data["current_feels_like"] = weather_json["current"]["feels_like"]
        # Insert daily forecast min and max temperature into dict
        weather_data["daily_temp_min"] = weather_json["daily"][0]["temp"]["min"]
        weather_data["daily_temp_max"] = weather_json["daily"][0]["temp"]["max"]
        # Insert next hour + 1 forecast temperature and feels like into dict
        weather_data["hourly_next_temp"] = weather_json["hourly"][2]["temp"]
        weather_data["hourly_feels_like"] = weather_json["hourly"][2]["feels_like"]

        # Clean up response
        del weather_json

        # Set daily highest temperature
        global highest_temp
        # If daily highest temperature hasn't been set or is from a previous day
        if highest_temp[0] is None or highest_temp[1] != current_time.tm_wday:
            highest_temp[0] = weather_data["daily_temp_max"]
            highest_temp[1] = current_time.tm_wday
        # If stored highest temp is less than new highest temp
        elif highest_temp[0] < weather_data["daily_temp_max"]:
            highest_temp[0] = weather_data["daily_temp_max"]
        # If stored highest temp is greater than new highest temp
        elif highest_temp[0] > weather_data["daily_temp_max"]:
            weather_data["daily_temp_max"] = highest_temp[0]

        # Set daily lowest temperature
        global lowest_temp
        # If daily lowest temperature hasn't been set or is from a previous day
        if lowest_temp[0] is None or lowest_temp[1] != current_time.tm_wday:
            lowest_temp[0] = weather_data["daily_temp_min"]
            lowest_temp[1] = current_time.tm_wday
        # If daily lowest temp is greater than new lowest temp
        elif lowest_temp[0] > weather_data["daily_temp_min"]:
            lowest_temp[0] = weather_data["daily_temp_min"]
        # If daily lowest temp is less than new lowest temp
        elif lowest_temp[0] < weather_data["daily_temp_min"]:
            weather_data["daily_temp_min"] = lowest_temp[0]

        #print("Daily Lowest Temp: {} | Daily Highest Temp: {}".format(lowest_temp[0], highest_temp[0]))

        # add current temp to historical array
        global current_temp
        current_temp.append(weather_data["current_temp"])

        # return True for updated dict
        return True

    except Exception as e:
        print("Failed to get WEATHER data, retrying\n", e)
        wifi.reset()


# --- METRO API CALLS ---

# queries WMATA API to return an array of two Train objects
# input is station code from secrets.py, and a historical_trains array
def get_trains():
    """
    Retrieves train data from the WMATA API based on the input station code.

    This function queries the WMATA API using the provided station code and retrieves train prediction data for the specified station. It sets up two train directions: A and B, and assigns train objects to these directions based on the prediction data. It then updates the historical trains with the new train objects if they are found. Finally, it prints the destination name and minutes for each train, and returns a list of the train objects.

    Returns:
        List[Train]: A list of train objects representing the predicted train data.
    """
    global station_code
    global historical_trains
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

    trains = [a_train, b_train]
    '''try:
        for item in trains:
            print("{}: {}".format(item.destination_name, item.minutes))
    except Exception as e:
        print(e)
        pass'''
    return trains


# --- PLANE API CALLS ---
def get_nearest_plane(range=2.0):
    """
    Retrieves the nearest plane within a given range by requesting plane.json from local ADS-B receiver (default
    location for readsb)
    Sample format: http://XXX.XXX.X.XXX/tar1090/data/aircraft.json

    Args:
        range (float, optional): The range within which to search for planes. Defaults to 2.0.

    Returns:
        None
    """
    global nearest_plane
    json_data = None

    try:
        response = wifi.get(secrets['plane data json url'])
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
            for entry in json_data["aircraft"]:
                # Check if flight callsign and distance exists, check distance against range
                if "flight" and "alt_geom" and "r_dst" in entry and float(entry["r_dst"]) <= range:
                    entry_distance = round(float(entry["r_dst"]), 2)
                    if nearest_plane is None or (
                            nearest_plane is not None and nearest_plane.distance > entry_distance):
                        try:
                            nearest_plane = Plane(
                                entry["flight"].strip(),
                                entry["alt_geom"],
                                float(entry_distance)
                            )
                            # print(nearest_plane.get_plane_string())
                            # Separate emergency field as optional
                            if "emergency" in entry:
                                nearest_plane.emergency = entry["emergency"]
                        except Exception as e:
                            print(f"couldn't update nearest plane entry: {e}")
                else:
                    # print("Plane data didn't meet object criteria")
                    pass
        except Exception as e:
            print("Failed to create PLANE object:", e)
    else:
        print("Failed to get PLANE data")


# --- EVENT API CALLS ---
def get_next_event():
    """
    Retrieves the next scheduled event from the API.

    This function makes a request to the specified event data JSON URL
    and retrieves the response. It then parses the JSON data to extract
    the departure time and the departure train information of the next event.
    Sample format: http://XXX.XXX.X.XXX/next_event.json

    Returns:
        dict or None: A dictionary containing the departure time and
        departure train information of the next event if successful,
        None otherwise.
    """
    global next_event
    try:
        response = wifi.get(secrets['event data json url'])
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


def event_mode_switch(departure_time, diff=60):
    """
    Returns the mode to switch based on the departure time.

    Parameters:
    - departure_time (datetime): The departure time.
    - diff (int, optional): The time difference in minutes. Default is 60.

    Returns:
    - str: The mode to switch based on the departure time. It can be either "Event" or "Day".
    """
    departure_diff = epoch_diff(departure_time)

    # if departure time is within timeframe, switch mode to event
    if 0 < departure_diff < diff:
        return "Event"
    # if departure time is 0 or less than 0, reset mode
    else:
        return "Day"


# --- HEADLINE FUNCTIONS ---
def get_headline(recent_only=True, recent_within=90, news_source="gnews", article_count=1):
    """
    Generates a headline from a specified news source.

    Args:
        recent_only (bool, optional): Flag indicating if only recent headlines should be returned. Defaults to True.
        recent_within (int, optional): The time window (in minutes) within which a headline is considered recent. Defaults to 90.
        news_source (str, optional): The source of the news. Can be 'gnews', 'newsapi', or 'sample_data'. Defaults to "gnews".
        article_count (int, optional): The number of articles to retrieve. Defaults to 1.

    Returns:
        Article or None: The generated headline as an Article object, or None if no headline is available.
    """
    global current_headline
    global current_time
    global timezone_offset
    article_list = []

    # Make API call to specified news source
    request_url = None
    if news_source == 'newsapi':
        # Query News API with input count
        request_url = f'https://newsapi.org/v2/top-headlines?country=us&pageSize={article_count}'
        headers = {'X-Api-Key': secrets['news api key']}
    elif news_source == 'gnews':
        # Query GNews API with input count
        request_url = f'https://gnews.io/api/v4/top-headlines?category=general&lang=en&country=us&max={article_count}'
        request_url += f'&apikey={secrets["gnews api key"]}'
        headers = {}
    elif news_source == 'sample_data':
        # Add sample API output here for testing
        pass

    if request_url and news_source != 'sample_data':
        try:
            response = wifi.get(request_url, headers=headers)
            if response.status_code == 200:
                json_data = response.json()
                del response
            else:
                print("Failed to retrieve NEWS data from endpoint: {}".format(response.status_code))
                return None
        except Exception as e:
            print("Failed to retrieve NEWS data from endpoint: {}".format(e))
            return None

    # Iterate through json data to create list of Article objects
    if json_data:
        for item in json_data['articles']:
            title = item['title'].split(' - ')[0].strip()
            published_time = item['publishedAt'].split("T")[1].split(":")
            published_time_hour = int(published_time[0])
            published_time_minutes = int(published_time[1])

            # Adjust the parsed_time using timezone_offset
            # Convert timezone offset string to minutes
            offset_hours = int(timezone_offset[:-2])
            offset_minutes = int(timezone_offset[-2:])
            offset_minutes_total = offset_hours * 60 + offset_minutes
            local_time_hour = (published_time_hour + (offset_minutes_total // 60)) % 24

            # Create local time struct
            local_time_struct = time.struct_time(
                current_time[:3] + (local_time_hour,) + (published_time_minutes,) + current_time[5:]
            )

            article_list.append(Article(
                item['source']['name'],
                local_time_struct,
                item['publishedAt'],
                title
            )
            )
    if len(article_list) != 0:
        new_headline = article_list.pop(0)

        # Any headline and no current headline
        if not recent_only and current_headline is None:
            current_headline = new_headline
            return current_headline
        # Any headline and current headline is the same as new headline
        elif not recent_only and current_headline is not None and current_headline.title == new_headline.title:
            return None
        # Recent headline only
        elif recent_only is True:
            # if new headline is more than recent_within minutes old, don't replace
            local_time_epoch = time.mktime(local_time_struct)
            if epoch_diff(local_time_epoch) > recent_within:
                '''print(
                    "DO NOT REPLACE: New headline is {} minutes old | Adjusted time: {}:{}".format(
                        epoch_diff(local_time_epoch), local_time_struct.tm_hour, local_time_struct.tm_min,
                    ))'''
                return None
            # If new headline is less than 60 minutes old and title is different, replace
            elif current_headline is None or (current_headline is not None and current_headline.title != new_headline.title):
                '''print(
                    "REPLACE: New headline is {} minutes old | Adjusted time: {}:{}".format(
                        epoch_diff(local_time_epoch), local_time_struct.tm_hour, local_time_struct.tm_min,
                    ))'''
                current_headline = new_headline
                return current_headline
            else:
                return None

    else:
        print("No headlines found, Article list length is 0")
        return None


# --- TIME MGMT FUNCTIONS ---
def get_current_time():
    """
    Retrieves the current time from Adafruit IO API and stores it in the global variables.
    This function makes up to three API requests to Adafruit IO:
    1. Get current time in epoch seconds.
    2. Get current time as a struct.
    3. Get timezone offset if it hasn't already been retrieved.

    Parameters:
        None

    Returns:
        None
    """
    global current_time
    global current_time_epoch
    global timezone_offset

    base_url = "https://io.adafruit.com/api/v2/"

    # Get current time as a struct
    try:
        request_url = (base_url + secrets["aio username"] +
                       "/integrations/time/struct?x-aio-key=" + secrets["aio key"])
        response = wifi.get(request_url)
        json_response = response.text
        del response
    except Exception as e:
        print("Failed to get Adafruit IO time struct: {}".format(e))
        wifi.reset()
    if json_response:
        # Extract values from the JSON
        data = eval(json_response)
        time_values = [int(data[key]) for key in ['year', 'mon', 'mday', 'hour', 'min', 'sec', 'wday', 'yday', 'isdst']]

        # Create a current time struct
        current_time = time.struct_time(time_values)

    # Get current time in epoch seconds
    current_time_epoch = time.mktime(current_time)

    # Get timezone offset

    if timezone_offset is None:
        # Get timezone offset for timezone in secrets.py
        try:
            request_url = (base_url + secrets["aio username"] +
                           "/integrations/time/strftime?x-aio-key=" + secrets["aio key"] +
                           "&tz=" + secrets["timezone"] +
                           "&strftime=%25z")
            response = wifi.get(request_url)
            timezone_offset = response.text
            del response
        except Exception as e:
            print("Failed to get Adafruit IO timezone: {}".format(e))
            wifi.reset()


def epoch_diff(epoch_time):
    """
    Calculate the difference in minutes between the given epoch time and the current time epoch.

    Parameters:
        epoch_time (int): The epoch time to calculate the difference with.

    Returns:
        int or None: The difference in minutes if the current time epoch is available, else None.
    """
    global current_time_epoch
    if current_time_epoch is not None:
        difference = abs(epoch_time - current_time_epoch)
        return round(difference / 60)
    else:
        return None


def check_open(start=start_time, end=end_time):
    """
    Check if the current time falls within the operating hours.

    Parameters:
        start (int, optional): The start time of the operating hours. Defaults to start_time.
        end (int, optional): The end time of the operating hours. Defaults to end_time.

    Returns:
        bool: True if the current time falls within the operating hours, False otherwise.
    """
    weekday = current_time.tm_wday
    hour = current_time.tm_hour

    # Within operating hours, current day is Sat/Sun
    if hour < start + 1 and (weekday == 0 or weekday == 6):
        print("Metro closed: Sat/Sun before 7| D{} H{}".format(weekday, hour))
        return False

    # Within operating hours, current day is M-F
    elif start <= hour < end:
        return True

    # Not in operating hours
    else:
        return False


# --- ADAFRUIT IO FUNCTIONS ---

def send_feed_data(feed_key, data):
    request_url = f"https://io.adafruit.com/api/v2/{secrets['aio username']}/feeds/{feed_key}/data"
    headers = {'X-AIO-Key': secrets['aio key']}
    payload = {'value': data}
    try:
        response = wifi.post(request_url, headers=headers, json=payload)
        return response.status_code, response.json()
    except Exception as e:
        print("Failed to send Adafruit IO data: {}".format(e))
        return None


def get_feed_data(feed_key, limit=1):
    request_url = f"https://io.adafruit.com/api/v2/{secrets['aio username']}/feeds/{feed_key}/data?limit={limit}"
    headers = {'X-AIO-Key': secrets['aio key']}
    try:
        response = wifi.get(request_url, headers=headers)
        return response.status_code, response.json()
    except Exception as e:
        print("Failed to get Adafruit IO data: {}".format(e))
        return 400, "{}"


# --- MISC. FUNCTIONS ---
def send_notification(text):
    display_manager.scroll_text(text)


def is_valid_integer(string):
    try:
        int(string)
        return True
    except ValueError:
        return False


def add_commas_to_number(number_str):
    reversed_number = "".join(reversed(number_str))
    groups = [reversed_number[i:i + 3] for i in range(0, len(reversed_number), 3)]
    formatted_number = ",".join("".join(reversed(group)) for group in reversed(groups))

    return formatted_number


def format_time_struct(time_struct):
    """
    Format the given time struct to a 12-hour format.

    Args:
        time_struct (time.struct_time): The time struct to be formatted.

    Returns:
        str: The formatted time string in the format "HH:MMAM/PM".
    """
    if time_struct.tm_hour == 0:
        hour = 12
    elif time_struct.tm_hour > 12:
        hour = time_struct.tm_hour % 12
    else:
        hour = time_struct.tm_hour
    minute = "{:02d}".format(time_struct.tm_min)
    # Calculate AM/PM suffix
    suffix = "AM" if time_struct.tm_hour < 12 else "PM"
    return f"{hour}:{minute} {suffix}"


# --- OPERATING LOOP ------------------------------------------
def main():
    """
    The main function that controls the execution of the program.

    This function initializes all the global variables and enters into an infinite loop.
    Within the loop, it checks for a RESET command from the Adafruit IO feed and resets the microcontroller if necessary.
    It updates the current time and checks if the display should be in night mode based on the opening hours.

    If the display is in day mode, it fetches the weather data, updates the weather display, updates the train data,
    updates the plane data, updates the event data, and updates the top headline.

    If the display is in event mode, it fetches the weather data, calculates the time until departure, and updates
    the event display.

    It also handles the notification queue, refreshes the display, and performs garbage collection.

    Every 5th loop iteration, or on the first iteration, it outputs local diagnostics and Adafruit IO diagnostics.
    It checks for an updated start time from the Adafruit IO feed.

    It increments the loop counter and sleeps for a certain amount of time based on the mode.
    """
    global current_time
    global start_time
    global end_time
    global weather_data
    global historical_trains
    global nearest_plane
    global next_event
    global current_headline

    loop_counter = 1
    last_weather_check = None
    last_train_check = None
    last_plane_check = None
    last_event_check = None
    last_headline_check = None
    mode = "Day"

    while True:

        # Check Adafruit IO for RESET command
        updated_reset_status, updated_reset = get_feed_data(secrets['aio reset'])
        if updated_reset_status == 200 and updated_reset[0]['value'] == 1:
            print("Resetting Now: {}".format(updated_reset))
            send_feed_data(secrets['aio reset'], 0)
            time.sleep(3)
            microcontroller.reset()
        else:
            pass

        # Update current time struct and epoch
        get_current_time()
        last_time_check = time.monotonic()
        if loop_counter == 1:
            time_info = format_time_struct(current_time)
            print(f"Current time: {time_info} | Weekday: {current_time.tm_wday}")

        # Check if display should be in night mode
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

        # --- DAY MODE ---
        if mode is "Day":
            # Fetch weather data on start and recurring (default: 10 minutes)
            if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
                try:
                    get_weather()
                    # Update weather display component
                    display_manager.update_weather(weather_data)
                except Exception as e:
                    print(f"Weather error: {e}")
                last_weather_check = time.monotonic()

            # Update train data (default: 15 seconds)
            if last_train_check is None or time.monotonic() > last_train_check + 15:
                try:
                    trains = get_trains()
                    # Update train display component
                    display_manager.update_trains(trains, historical_trains)
                except Exception as e:
                    print(f"Train error: {e}")
                last_train_check = time.monotonic()

            # Update plane data (default: 5 minutes)
            if last_plane_check is None or time.monotonic() > last_plane_check + 60 * 5:
                try:
                    get_nearest_plane()
                    last_plane_check = time.monotonic()
                except Exception as e:
                    print(f"Plane error: {e}")
                # Push plane to notification queue if within 2 miles
                if nearest_plane is not None:
                    notification_queue.append(nearest_plane.get_plane_string())
                    nearest_plane = None

            # Update event data (default: 5 minutes)
            if last_event_check is None or time.monotonic() > last_event_check + 60 * 5:
                try:
                    # Check for event departure
                    next_event = get_next_event()
                    last_event_check = time.monotonic()
                    if next_event is not None:
                        # Switch to event mode if time is within an hour
                        mode = event_mode_switch(next_event['departure_time'])
                        pass
                    else:
                        print("no event found.")
                except Exception as e:
                    print(f"Event error: {e}")

            # Update top headline (default: 12 minutes)
            if last_headline_check is None or time.monotonic() > last_headline_check + 60 * 12:
                global current_headline
                # Check for a new headline
                try:
                    headline = get_headline()
                except Exception as e:
                    print(f"Headline retrieval error: {e}")
                    headline = None

                # If a new headline exists, push it to the notification queue
                if headline is not None:
                    try:
                        notification_queue.append(headline.get_headline_string())
                    except Exception as e:
                        print(f"Headline notification error: {e}")
                # No / No new headline
                else:
                    pass
                last_headline_check = time.monotonic()

            # Push current time to the top of the notification queue at the top of the hour
            if current_time.tm_min == 0 and current_time.tm_sec <= 15:
                notification_queue.insert(0, f"Time is {current_time.tm_hour:02}:{current_time.tm_min:02}")

        # --- EVENT MODE ---
        if mode is "Event":
            # Fetch weather data on start and recurring (default: 10 minutes)
            if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
                weather = get_weather(weather_data)
                if weather:
                    last_weather_check = time.monotonic()
                # Update weather display component
                display_manager.update_weather(weather_data)

            # Calculate time until departure
            if next_event is not None:
                departure_countdown = epoch_diff(next_event['departure_time'])
                if departure_countdown >= 1:
                    # Test printing TODO remove
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
        if loop_counter > 1 and len(notification_queue) > 0:
            print(f"Notification Queue:\n{notification_queue}")
            try:
                send_notification(notification_queue.pop(0))
            except Exception as e:
                print(f"Notification Error: {e}")

        # Refresh display
        display_manager.refresh_display()
        # Run garbage collection
        gc.collect()

        # Output diagnostics loop
        if loop_counter % 5 == 0 or loop_counter == 1:
            # Output local diagnostics
            print(f"Loop {loop_counter} | {mode} Mode | Available memory: {gc.mem_free()} bytes")
            # Output Adafruit IO diagnostics
            if last_train_check is not None:
                check_diff_seconds = time.monotonic() - last_train_check
                response = send_feed_data(secrets['aio train'], check_diff_seconds)
                if response is not None and response[0] != 200:
                    print(f"Last Train Check: {response[1]}")
            if last_plane_check is not None:
                check_diff_seconds = time.monotonic() - last_plane_check
                response = send_feed_data(secrets['aio plane'], check_diff_seconds / 60)
                if response is not None and response[0] != 200:
                    print(f"Nearest Plane: {response[1]}")
            if last_event_check is not None:
                check_diff_seconds = time.monotonic() - last_event_check
                response = send_feed_data(secrets['aio event'], check_diff_seconds / 60)
                if response is not None and response[0] != 200:
                    print(f"Last Event Check: {response[1]}")
            if last_headline_check is not None:
                check_diff_seconds = time.monotonic() - last_headline_check
                response = send_feed_data(secrets['aio headline'], check_diff_seconds / 60)
                if response is not None and response[0] != 200:
                    print(f"Headline: {response[1]}")
            response = send_feed_data(secrets['aio loop counter'], loop_counter)
            if response is not None and response[0] != 200:
                print(f"Loop Counter: {response[1]}")

            # Check Adafruit IO for updated start time
            try:
                updated_start_time_status, updated_start_time = get_feed_data(secrets['aio start time'])
            except Exception as e:
                print(f"Failed to get start time: {e}")
                updated_start_time_status, updated_start_time = None, None
            if (updated_start_time_status is not None and updated_start_time_status == 200
                    and updated_start_time is not None and int(updated_start_time[0]['value']) != start_time):
                start_time = updated_start_time[0]['value']

                print(f"Updated start time: {updated_start_time[0]['value']}")
            else:
                pass

        # Increment loop and sleep
        # Day mode: 10 seconds
        # Event mode: 50 seconds
        loop_counter += 1
        if mode == "Day":
            time.sleep(10)
        elif mode == "Event":
            time.sleep(50)
        # Night mode
        else:
            # Calculate the time until the next start_time
            current_minutes = current_time.tm_hour * 60 + current_time.tm_min
            start_minutes = start_time * 60

            if current_minutes < start_minutes:
                # If current time is before the start_time, sleep until start_time
                time_to_sleep = start_minutes - current_minutes
                print(
                    f"Current time: {current_time.tm_hour:02}:{current_time.tm_min:02} | Start Time: {start_time}:00 | Sleeping for {time_to_sleep // 60:02}:{time_to_sleep % 60:02}")
            else:
                # If current time is after the end_time, sleep until start_time of the next day
                time_to_sleep = (24 * 60) - current_minutes + start_minutes
                print(
                    f"Current time: {current_time.tm_hour:02}:{current_time.tm_min:02} | Start Time: {start_time}:00 | Sleeping for {time_to_sleep // 60:02}:{time_to_sleep % 60:02}")

            time.sleep(time_to_sleep * 60)


if __name__ == "__main__":
    main()
