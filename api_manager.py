import time
import gc
from adafruit_esp32spi import adafruit_esp32spi_wifimanager

class APICache:
    def __init__(self, ttl=300):  # 5 minutes TTL
        self.cache = {}
        self.ttl = ttl
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.monotonic() - timestamp < self.ttl:
                return data
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, time.monotonic())
        if len(self.cache) > 5:  # Limit cache size
            oldest = min(self.cache.items(), key=lambda x: x[1][1])
            del self.cache[oldest[0]]

class APIManager:
    def __init__(self, wifi: adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager, secrets: dict):
        self.wifi = wifi
        self.secrets = secrets
        self.timezone_offset = None
        self.current_time = None
        self.current_time_epoch = None
        # Initialize time on startup
        self._initialize_time()

    def _initialize_time(self, max_retries=3):
        """
        Ensures we have valid time data on startup
        """
        for attempt in range(max_retries):
            try:
                if self.get_current_time():  # Only proceed if get_current_time returns True
                    if self.current_time is not None:
                        print(f"Time initialized successfully on attempt {attempt + 1}")
                        return True
                print(f"Time initialization attempt {attempt + 1} failed, retrying...")
                time.sleep(2)  # Increased sleep time between retries
            except Exception as e:
                print(f"Time initialization error: {e}")
                time.sleep(2)
        
        # If we still don't have time after max retries, set a fallback
        print("Using fallback time values")
        self.current_time = time.struct_time((2024, 1, 1, 0, 0, 0, 0, 1, -1))
        self.current_time_epoch = time.mktime(self.current_time)
        return False

    # --- TIME MANAGEMENT ---
    def get_current_time(self):
        """Retrieves current time from Adafruit IO API"""
        try:
            request_url = f"https://io.adafruit.com/api/v2/{self.secrets['aio username']}/integrations/time/struct?x-aio-key={self.secrets['aio key']}"
            response = self.wifi.get(request_url)
            
            if response.status_code != 200:
                print(f"Time API status: {response.status_code}")
                return False
                
            data = response.json()
            del response
            gc.collect()  # Force garbage collection after deleting response

            # Create time struct directly from values to avoid intermediate lists
            self.current_time = time.struct_time((
                data['year'], data['mon'], data['mday'],
                data['hour'], data['min'], data['sec'],
                data['wday'], data['yday'], data['isdst']
            ))
            self.current_time_epoch = time.mktime(self.current_time)
            return True
                
        except Exception as e:
            print(f"Time error: {e}")
            return False

    # --- WEATHER API ---
    def get_weather(self):
        """Retrieves weather data from the OpenWeather API"""
        try:
            base_url = 'https://api.openweathermap.org/data/3.0/onecall?'
            latitude = self.secrets['dc coords x']
            longitude = self.secrets['dc coords y']
            units = 'imperial'
            api_key = self.secrets['openweather api key']
            exclude = 'minutely,alerts'
            response = self.wifi.get(base_url
                                   + 'lat=' + latitude
                                   + '&lon=' + longitude
                                   + '&exclude=' + exclude
                                   + '&units=' + units
                                   + '&appid=' + api_key
                                   )
            if response.status_code == 200:
                data = response.json()
                needed_data = {
                    "current": {
                        "weather": [{"icon": data["current"]["weather"][0]["icon"]}],
                        "temp": data["current"]["temp"],
                        "feels_like": data["current"]["feels_like"]
                    },
                    "daily": [{
                        "temp": {
                            "min": data["daily"][0]["temp"]["min"],
                            "max": data["daily"][0]["temp"]["max"]
                        }
                    }],
                    "hourly": [{}, {}, {
                        "temp": data["hourly"][2]["temp"],
                        "feels_like": data["hourly"][2]["feels_like"]
                    }]
                }
                del data
                return needed_data
            else:
                print(f"Weather API returned status code: {response.status_code}")
                return None
        except Exception as e:
            print(f"Failed to get weather data: {e}")
            self.wifi.reset()
            return None

    # --- METRO API ---
    def get_trains(self, station_code):
        """Retrieves train predictions from WMATA API"""
        try:
            response = self.wifi.get(
                'https://api.wmata.com/StationPrediction.svc/json/GetPrediction/' + station_code, 
                headers={'api_key': self.secrets['wmata api key']}
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Train API returned status code: {response.status_code}")
                return None
        except Exception as e:
            print(f"Failed to get train data: {e}")
            self.wifi.reset()
            return None

    # --- PLANE API ---
    def get_plane_data(self):
        """Retrieves plane data from local ADS-B receiver"""
        try:
            response = self.wifi.get(self.secrets['plane data json url'])
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Plane API returned status code: {response.status_code}")
                return None
        except Exception as e:
            print(f"Failed to get plane data: {e}")
            self.wifi.reset()
            return None

    # --- EVENT API ---
    def get_event_data(self):
        """Retrieves next event data"""
        try:
            response = self.wifi.get(self.secrets['event data json url'])
            return response.json()
        except Exception as e:
            print("Failed to get EVENT data: {}".format(e))
            return None

    # --- NEWS API ---
    def get_news(self, news_source="gnews", article_count=1):
        """Retrieves news headlines from specified source"""
        request_url = None
        headers = {}

        if news_source == 'newsapi':
            request_url = f'https://newsapi.org/v2/top-headlines?country=us&pageSize={article_count}'
            headers = {'X-Api-Key': self.secrets['news api key']}
        elif news_source == 'gnews':
            request_url = f'https://gnews.io/api/v4/top-headlines?category=general&lang=en&country=us&max={article_count}'
            request_url += f'&apikey={self.secrets["gnews api key"]}'

        try:
            response = self.wifi.get(request_url, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to retrieve NEWS data: {response.status_code}")
                return None
        except Exception as e:
            print(f"Failed to retrieve NEWS data: {e}")
            return None

    # --- ADAFRUIT IO ---
    def send_feed_data(self, feed_key, data):
        """Sends data to Adafruit IO feed"""
        request_url = f"https://io.adafruit.com/api/v2/{self.secrets['aio username']}/feeds/{feed_key}/data"
        headers = {'X-AIO-Key': self.secrets['aio key']}
        payload = {'value': data}
        try:
            response = self.wifi.post(request_url, headers=headers, json=payload)
            return response.status_code, response.json()
        except Exception as e:
            print("Failed to send Adafruit IO data: {}".format(e))
            return None

    def get_feed_data(self, feed_key, limit=1):
        """Gets data from Adafruit IO feed"""
        request_url = f"https://io.adafruit.com/api/v2/{self.secrets['aio username']}/feeds/{feed_key}/data?limit={limit}"
        headers = {'X-AIO-Key': self.secrets['aio key']}
        try:
            response = self.wifi.get(request_url, headers=headers)
            return response.status_code, response.json()
        except Exception as e:
            print("Failed to get Adafruit IO data: {}".format(e))
            return 400, "{}" 