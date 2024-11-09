# Display Manager
# Structure and some code from Weather Display Matrix project:
# https://learn.adafruit.com/weather-display-matrix/code-the-weather-display-matrix

import time
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font
import gc

cwd = ("/" + __file__).rsplit("/", 1)[0]

icon_spritesheet = cwd + "/bmp/weather-icons.bmp"

# custom font for temperature trend indicators
symbol_font = bitmap_font.load_font("/bdf/trend_icons.bdf")

# custom colors hex codes
metro_orange = 0xf06a37
metro_red = 0xda1b30
metro_green = 0x49742a

# custom scroll delay for scroll_text
scroll_delay = 0.03

# Pre-define common strings
TRAIN_NO_TRAINS = "No trains"
TRAIN_ARR = "ARR"
TRAIN_BRD = "BRD"

# Cache color values
COLORS = {
    'orange': metro_orange,
    'red': metro_red,
    'blue': 0x1e81b0,
    'white': 0xFFFFFF
}

# Use byte strings for icon mapping
ICON_MAP = b'\x00\x01\x02\x03\x04\x04\x05\x05\x06\x06\x07\x08\x09\x09\x0A\x0A\x0B\x0B'


class display_manager(displayio.Group):
    def __init__(
            self,
            display,
    ):
        super().__init__()
        self.display = display
        # set up label groups
        self.root_group = displayio.Group()
        self.root_group.append(self)

        # create night mode group
        self._night_mode_group = displayio.Group()
        # hide night mode group by default
        self._night_mode_group.hidden = True
        self.append(self._night_mode_group)

        # create scrolling notification group
        self._scrolling_group = displayio.Group()
        # hide scrolling group by default
        self._scrolling_group.hidden = True
        self.append(self._scrolling_group)

        # create parent weather group for weather display groups
        self._weather_group = displayio.Group()
        self._weather_group.hidden = False
        self.append(self._weather_group)

        # create current weather icon group
        self._icon_group = displayio.Group(x=4, y=2)
        self._weather_group.append(self._icon_group)

        # create current temperature group
        self._current_temp_group = displayio.Group()
        self._weather_group.append(self._current_temp_group)

        # create temperature trend symbol group
        self._temp_trend_group = displayio.Group()
        self._weather_group.append(self._temp_trend_group)

        # create min max temperature group
        self._min_max_temp_group = displayio.Group()
        self._weather_group.append(self._min_max_temp_group)

        # create parent train group for train Labels
        self._train_board_group = displayio.Group()
        self._train_board_group.hidden = False
        self.append(self._train_board_group)

        # set default column and row measurements
        self.col1 = 4
        self.col2 = 28
        self.col25 = 52
        self.col3 = 108
        self.row1 = 8
        self.row2 = 24

        # Load the icon sprite sheet
        icons = displayio.OnDiskBitmap(open(icon_spritesheet, "rb"))
        self._icon_sprite = displayio.TileGrid(
            icons,
            pixel_shader=getattr(icons, 'pixel_shader', displayio.ColorConverter()),
            tile_width=16,
            tile_height=16
        )

        # set current temperature text
        # left-middle column, top row
        self.temp_text = Label(terminalio.FONT)
        self.temp_text.x = self.col2 - 4
        self.temp_text.y = self.row1
        self.temp_text.color = 0xFFFFFF
        self._current_temp_group.append(self.temp_text)

        # set current temperature trend icon
        self.temp_trend_icon = Label(font=symbol_font)
        self.temp_trend_icon.x = self.col2 + 8
        self.temp_trend_icon.y = self.row1 - 7
        self._temp_trend_group.append(self.temp_trend_icon)

        # set daily minimum temperature text
        # left column, bottom row
        self.min_temp_text = Label(terminalio.FONT)
        self.min_temp_text.x = self.col1 + 2
        self.min_temp_text.y = self.row2
        self.min_temp_text.color = 0x1e81b0
        self._min_max_temp_group.append(self.min_temp_text)

        # set daily maximum temperature text
        # left-middle column, bottom row
        self.max_temp_text = Label(terminalio.FONT)
        self.max_temp_text.x = self.col2 - 4
        self.max_temp_text.y = self.row2
        self.max_temp_text.color = metro_red
        self._min_max_temp_group.append(self.max_temp_text)

        # set top row of train destination text
        # right-middle column, top row
        self.top_row_train_text = Label(terminalio.FONT)
        self.top_row_train_text.x = self.col25 - 5
        self.top_row_train_text.y = self.row1
        self.top_row_train_text.color = metro_orange
        self.top_row_train_text.text = "Shady Grv"
        self._train_board_group.append(self.top_row_train_text)

        # set top row of train time to arrival text
        # right column, top row
        self.top_row_train_min = Label(terminalio.FONT)
        self.top_row_train_min.x = self.col3
        self.top_row_train_min.y = self.row1
        self.top_row_train_min.color = metro_orange
        self.top_row_train_min.text = "0"
        self._train_board_group.append(self.top_row_train_min)

        # set bottom row of train destination text
        # right-middle column, bottom row
        self.bottom_row_train_text = Label(terminalio.FONT)
        self.bottom_row_train_text.x = self.col25 - 5
        self.bottom_row_train_text.y = self.row2
        self.bottom_row_train_text.color = metro_orange
        self.bottom_row_train_text.text = "Glenmont"
        self._train_board_group.append(self.bottom_row_train_text)

        # set bottom row of train time to arrival text
        # right column, bottom row
        self.bottom_row_train_min = Label(terminalio.FONT)
        self.bottom_row_train_min.x = self.col3
        self.bottom_row_train_min.y = self.row2
        self.bottom_row_train_min.color = metro_orange
        self.bottom_row_train_min.text = "0"
        self._train_board_group.append(self.bottom_row_train_min)

        # create row scrolling label
        self.scrolling_label = Label(terminalio.FONT)
        self.scrolling_label.x = 0
        self.scrolling_label.y = self.row1
        self.scrolling_label.color = 0xFFFFFF
        self._scrolling_group.append(self.scrolling_label)

        # default icon set to none
        self.set_icon(None)

    def set_icon(self, icon_name):
        """Use icon_name to get the position of the sprite and update
        the current icon.
        :param icon_name: The icon name returned by openweathermap
        Format is always 2 numbers followed by 'd' or 'n' as the 3rd character
        """
        icon_map = ("01", "02", "03", "04", "09", "10", "11", "13", "50")
        if self._icon_group:
            self._icon_group.pop()
        if icon_name is not None:
            row = None
            for index, icon in enumerate(icon_map):
                if icon == icon_name[0:2]:
                    row = index
                    break
            column = 0
            if icon_name[2] == "n":
                column = 1
            if row is not None:
                self._icon_sprite[0] = (row * 2) + column
                self._icon_group.append(self._icon_sprite)

    # helper function to assign color to minutes labels
    def get_minutes_color(self, minutes):
        try:
            if minutes == "ARR" or minutes == "BRD":
                return metro_red
            else:
                return metro_orange
        except ValueError as e:
            print("Value Error: {}".format(e))
            return metro_orange

    # update temperature text, trend, and max/min
    # input is a weather dict
    def update_weather(self, weather):
        """Updates weather display with current conditions"""
        if not weather:
            self.temp_text.text = "..."
            return
        
        # Update temperature values
        self.temp_text.text = str(int(weather["current_temp"]))
        self.min_temp_text.text = str(int(weather["daily_temp_min"]))
        self.max_temp_text.text = str(int(weather["daily_temp_max"]))
        
        # Map OpenWeather icon code to our sprite sheet index
        icon_map = {
            "01d": 0,  # clear sky day
            "01n": 1,  # clear sky night
            "02d": 2,  # few clouds day
            "02n": 3,  # few clouds night
            "03d": 4,  # scattered clouds
            "03n": 4,  # scattered clouds
            "04d": 5,  # broken clouds
            "04n": 5,  # broken clouds
            "09d": 6,  # shower rain
            "09n": 6,  # shower rain
            "10d": 7,  # rain day
            "10n": 8,  # rain night
            "11d": 9,  # thunderstorm
            "11n": 9,  # thunderstorm
            "13d": 10, # snow
            "13n": 10, # snow
            "50d": 11, # mist
            "50n": 11, # mist
        }
        
        # Update icon if we have one in the icon group
        if len(self._icon_group) > 0:
            icon_index = icon_map.get(weather["icon"], 0)
            self._icon_sprite[0] = icon_index
        else:
            # First time setup - add the sprite to the group
            icon_index = icon_map.get(weather["icon"], 0)
            self._icon_sprite[0] = icon_index
            self._icon_group.append(self._icon_sprite)
        
        # Update temperature trend
        temp_diff = weather["hourly_next_temp"] - weather["current_temp"]
        self._temp_trend_group.hidden = abs(temp_diff) <= 1
        
        if not self._temp_trend_group.hidden:
            self.temp_trend_icon.text = "," if temp_diff > 0 else "."
            self.temp_trend_icon.color = metro_red if temp_diff > 0 else 0x1e81b0
            self.temp_trend_icon.y = self.row1 - 6
        
        # Ensure icon group is visible
        self._icon_group.hidden = False
        
        gc.collect()  # Add collection after weather updates

    # update train destination text and time to arrival
    # input is a list of train objects
    # TODO abstract default and error handling to support any station
    def update_trains(self, trains, historical_trains):
        """
        Updates the train display with current train predictions
        Args:
            trains: List containing two Train objects [eastbound, westbound]
            historical_trains: List containing historical train data
        """
        if not trains:
            return
        
        # Update eastbound train
        if trains[0]:
            self.top_row_train_text.text = trains[0]['dest']
            self.top_row_train_min.text = trains[0]['min']
            # Set text color based on destination
            text_color = (metro_orange if trains[0]['dest'] in ["Shady Grv", "Glenmont"] else 0xFFFFFF)
            # Set minutes color based on arrival status
            min_color = metro_red if trains[0]['min'] in ["ARR", "BRD"] else metro_orange
            self.top_row_train_text.color = text_color
            self.top_row_train_min.color = min_color
        elif historical_trains[0]:
            self.top_row_train_text.text = historical_trains[0]['dest']
            self.top_row_train_min.text = historical_trains[0]['min']
            text_color = (metro_orange if historical_trains[0]['dest'] in ["Shady Grv", "Glenmont"] else 0xFFFFFF)
            min_color = metro_red if historical_trains[0]['min'] in ["ARR", "BRD"] else metro_orange
            self.top_row_train_text.color = text_color
            self.top_row_train_min.color = min_color
        else:
            self.top_row_train_text.text = "No trains"
            self.top_row_train_min.text = ""
            self.top_row_train_text.color = metro_orange
            self.top_row_train_min.color = metro_orange
        
        # Update westbound train
        if trains[1]:
            self.bottom_row_train_text.text = trains[1]['dest']
            self.bottom_row_train_min.text = trains[1]['min']
            text_color = (metro_orange if trains[1]['dest'] in ["Shady Grv", "Glenmont"] else 0xFFFFFF)
            min_color = metro_red if trains[1]['min'] in ["ARR", "BRD"] else metro_orange
            self.bottom_row_train_text.color = text_color
            self.bottom_row_train_min.color = min_color
        elif historical_trains[1]:
            self.bottom_row_train_text.text = historical_trains[1]['dest']
            self.bottom_row_train_min.text = historical_trains[1]['min']
            text_color = (metro_orange if historical_trains[1]['dest'] in ["Shady Grv", "Glenmont"] else 0xFFFFFF)
            min_color = metro_red if historical_trains[1]['min'] in ["ARR", "BRD"] else metro_orange
            self.bottom_row_train_text.color = text_color
            self.bottom_row_train_min.color = min_color
        else:
            self.bottom_row_train_text.text = "No trains"
            self.bottom_row_train_min.text = ""
            self.bottom_row_train_text.color = metro_orange
            self.bottom_row_train_min.color = metro_orange

    def update_event(self, station, departure_countdown):
        # station is Shady Grove
        if "shady" in station:
            self.top_row_train_text.text = "Shady Grv"
        # station is Glenmont
        else:
            self.top_row_train_text.text = "Glenmont"
        self.top_row_train_min.text = "in"

        # set proper grammar for singular remaining minute
        if departure_countdown > 1:
            self.bottom_row_train_text.text = "{} minutes".format(departure_countdown)
        else:
            self.bottom_row_train_text.text = "{} minute".format(departure_countdown)
        self.bottom_row_train_min.text = ""

        # set color based on minutes remaining
        if departure_countdown <= 10:
            self.bottom_row_train_text.color = metro_red
        else:
            self.bottom_row_train_text.color = metro_orange

        self.top_row_train_text.color = metro_orange
        self.top_row_train_min.color = metro_orange

    def night_mode_toggle(self, trigger):
        # night mode is activated, hide all groups
        if trigger:
            self._weather_group.hidden = False
            self._train_board_group.hidden = False
            self._night_mode_group.hidden = True
        # night mode is deactivated, show all groups
        else:
            self._weather_group.hidden = True
            self._train_board_group.hidden = True
            self._night_mode_group.hidden = False

    # use \n newline to access bottom row
    def scroll_text(self, label_text):
        try:
            self._scrolling_group.x = self.display.width
            self.scrolling_label.text = label_text
            self._weather_group.hidden = True
            self._train_board_group.hidden = True
            self._scrolling_group.hidden = False

            for _ in range(self.display.width + len(label_text) * 5):
                self._scrolling_group.x = self._scrolling_group.x - 1
                time.sleep(scroll_delay)
            self._scrolling_group.hidden = True
            self._weather_group.hidden = False
            self._train_board_group.hidden = False
            self.refresh_display()
            gc.collect()  # Add collection after scrolling completes
        except Exception as e:
            print(f"Scroll error: {e}")

    # refresh the root group on the display
    def refresh_display(self):
        """
        Refreshes the display with the current content.
        """
        self.display.root_group = self.root_group
