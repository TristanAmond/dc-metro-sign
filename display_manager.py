# Display Manager

import time
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font

# custom colors hex codes
metro_orange=0xf06a37
metro_red=0xda1b30
metro_green=0x49742a

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

        # create parent train group for train Labels
        self._train_board_group = displayio.Group()
        self._train_board_group.hidden = False
        self.append(self._train_board_group)

        # set default column and row measurements
        self.col1=16
        self.col2=96
        self.row1=8
        self.row2=24

        # set top row of train destination text
        # right-middle column, top row
        self.top_row_train_text = Label(terminalio.FONT)
        self.top_row_train_text.x = self.col1
        self.top_row_train_text.y = self.row1
        self.top_row_train_text.color = metro_orange
        self.top_row_train_text.text = "Shady Grove"
        self._train_board_group.append(self.top_row_train_text)

        # set top row of train time to arrival text
        # right column, top row
        self.top_row_train_min = Label(terminalio.FONT)
        self.top_row_train_min.x = self.col2
        self.top_row_train_min.y = self.row1
        self.top_row_train_min.color = metro_orange
        self.top_row_train_min.text = "0"
        self._train_board_group.append(self.top_row_train_min)

        # set bottom row of train destination text
        # right-middle column, bottom row
        self.bottom_row_train_text = Label(terminalio.FONT)
        self.bottom_row_train_text.x = self.col1
        self.bottom_row_train_text.y = self.row2
        self.bottom_row_train_text.color = metro_orange
        self.bottom_row_train_text.text = "Glenmont"
        self._train_board_group.append(self.bottom_row_train_text)

        # set bottom row of train time to arrival text
        # right column, bottom row
        self.bottom_row_train_min = Label(terminalio.FONT)
        self.bottom_row_train_min.x = self.col2
        self.bottom_row_train_min.y = self.row2
        self.bottom_row_train_min.color = metro_orange
        self.bottom_row_train_min.text = "0"
        self._train_board_group.append(self.bottom_row_train_min)

    # helper function to assign color to minutes labels
    def get_minutes_color(self, minutes):
        try:
            if minutes=="ARR" or minutes=="BRD":
                return metro_red
            else:
                return metro_orange
        except ValueError as e:
            print("Value Error: {}".format(e))
            return metro_orange

    # update train destination text and time to arrival
    # input is a list of train objects and display config integer
    def assign_trains(self, trains, historical_trains):
        try:
            if trains[0] is not None:
                self.top_row_train_text.text = trains[0].destination_name

                # if train isn't Shady Grove, set train text color to white
                if trains[0].destination_code is not "A15":
                    self.top_row_train_text.color = 0xFFFFFF
                else:
                    self.top_row_train_text.color = self.get_minutes_color(trains[0].minutes)

                # set min and min text colors
                self.top_row_train_min.text = trains[0].minutes
                self.top_row_train_min.color = self.get_minutes_color(trains[0].minutes)

            # no A train data
            elif historical_trains[0] is not None:
                self.top_row_train_text.text = historical_trains[0].destination_name
                self.top_row_train_min.text = historical_trains[0].minutes
                self.top_row_train_min.color = 0xFFFFFF
            else:
                self.top_row_train_min.text = "NULL"

            if trains[1] is not None:
                self.bottom_row_train_text.text = trains[1].destination_name

                # if train isn't Glenmont, set train text color to white
                if trains[1].destination_code is not "B11":
                    self.bottom_row_train_text.color = 0xFFFFFF
                else:
                    self.bottom_row_train_text.color = self.get_minutes_color(trains[1].minutes)

                # set min and min text colors
                self.bottom_row_train_min.text = trains[1].minutes
                self.bottom_row_train_min.color = self.get_minutes_color(trains[1].minutes)

            # no B train data
            elif historical_trains[1] is not None:
                self.bottom_row_train_text.text = historical_trains[1].destination_name
                self.bottom_row_train_min.text = historical_trains[1].minutes
                self.bottom_row_train_min.color = 0xFFFFFF
            else:
                self.bottom_row_train_min.text = "NULL"

        except TypeError as e:
            print(e)

    # refresh the root group on the display
    def refresh_display(self):
        self.display.show(self.root_group)
