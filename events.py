# Standard library imports
import os
import sys
import json
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time

# Third-party library imports
import requests
from dateutil import parser
import pytz

# Google API-related imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# import secrets directory for origin location, Google API key and file locations
try:
    # Get the directory of the current script
    current_directory = os.path.dirname(os.path.abspath(__file__))
    # Add the parent directory to the Python path
    parent_directory = os.path.abspath(os.path.join(current_directory, '..'))
    sys.path.append(parent_directory)
    # Import secrets directory
    from creds import secrets
except ImportError as e:
    print(f"Import Error: {e}")

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class Event:
    def __init__(self, summary, start_time, destination):
        self.summary = summary
        self.start_time = start_time
        self.destination = destination
        self.departure_time = None
        self.departure_train = None

    def __repr__(self):
        return 'Event(summary=\'{self.summary}\', start_time=\'{self.start_time}\', destination=\'{self.destination}\', departure_time=\'{self.departure_time}\', departure_train=\'{self.departure_train}\')'.format(
            self=self)

    # JSON serialization only outputs display fields
    def __json__(self):
        return {
            'departure_time': self.departure_time,
            'departure_train': self.departure_train
        }


# --- GOOGLE API CALLS ---
# retrieves the next event from a specified Google Calendar within the next lookahead_days (default=3)
# inputs: lookahead_days (default=3), calendar_id from secrets, timezone
# outputs: Event object
def retrieve_next_event(lookahead_days=3, calendar_id=secrets['calendarId'],
                        timezone=pytz.timezone('America/New_York')):
    # change directory to credentials location
    os.chdir(secrets['google credentials location'])

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('calendar', 'v3', credentials=creds)

        # Call the Calendar API
        tz = timezone
        now = datetime.now(tz).date()
        start = datetime.combine(now, datetime_time.min).isoformat() + 'Z'  # start of today
        end = (datetime.combine(now, datetime_time.max) + timedelta(
            days=lookahead_days)).isoformat() + 'Z'  # end of lookahead
        events_result = service.events().list(calendarId=calendar_id, timeMin=start,
                                              timeMax=end, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        # If no events found, return None
        if not events:
            print('No events found.')
            return None
        # If events found, pop the first event off the list and turn it into an Event
        else:
            next_event_item = events.pop(0)
            summary = next_event_item['summary']
            start_time = next_event_item['start'].get('dateTime', next_event_item['start'].get('date'))
            start_time = int(convert_struct_to_epoch(start_time))

            # try to get location, otherwise set to None
            try:
                location = str.replace(next_event_item['location'], "\n", ", ")
            except Exception as e:
                location = None
                print("No location found: {}".format(e))

            # create Event object
            next_event = Event(summary=summary, start_time=start_time, destination=location)
            # return event
            return next_event

    except HttpError as error:
        print('An error occurred: %s' % error)


# Call the Google Directions API to retrieve a JSON object with directions
# see https://developers.google.com/maps/documentation/directions/get-directions
def get_directions(event):
    # Craft Google Directions API request
    directions_url = "https://maps.googleapis.com/maps/api/directions/json?"
    directions_url = directions_url + (f"origin={secrets['origin location']}"
                                       f"&destination={event.destination}"
                                       f"&arrival_time={event.start_time}"
                                       f"&mode=transit&transit_mode=subway"
                                       f"&key={secrets['google api key']}")

    try:
        directions_response = requests.get(directions_url)
    except Exception as e:
        print("Failed to get directions: {}".format(e))

    if directions_response:
        directions_json = directions_response.json()
        del directions_response
        return directions_json
    else:
        print("Error: {}".format(directions_response.status_code))
        return None


# --- UTILITY FUNCTIONS ---

# retrieve the train headsign from the first TRANSIT step
# inputs: directions_json
# outputs: train headsign (str)
def get_departure_train(directions_json):
    """
    Retrieves the departure train headsign from the given directions JSON.

    Args:
        directions_json (dict): A JSON object containing the directions information.

    Returns:
        str or None: The headsign of the departure train, or None if no transit steps are found.
    """
    try:
        if 'routes' in directions_json and directions_json['routes']:
            for route in directions_json['routes']:
                if 'legs' in route and route['legs']:
                    for leg in route['legs']:
                        if 'steps' in leg:
                            for step in leg['steps']:
                                if step.get('travel_mode') == 'TRANSIT':
                                    return step['transit_details']['headsign']
        print("Error: No transit steps found")
    except Exception as e:
        print(f"Error: {e}")
    return None


def get_departure_time(directions_json):
    # check if there is at least one route
    if 'routes' in directions_json:
        # check if the route contains legs
        if 'legs' in directions_json['routes'][0]:
            # return departure time from first leg
            return directions_json['routes'][0]['legs'][0]['departure_time']['value']
    else:
        return "Error: No routes found"


# -- HELPER FUNCTIONS ---
# Use custom Event JSON serialization to write JSON to file available on local network
def write_to_json(next_event):
    # set filepath for JSON file
    filepath = os.path.join(secrets['JSON file location'], 'next_event.json')

    # write JSON to file
    with open(filepath, 'w') as json_file:
        # use custom Event JSON serialization
        json.dump(next_event, json_file, default=Event.__json__)
    # confirm file was written
    if os.path.exists(filepath):
        print("JSON written successfully to {}".format(filepath))
    else:
        print("Error writing to {}".format(filepath))


def convert_struct_to_epoch(time_struct, timezone):
    # Create a timezone-aware datetime object using the specified timezone
    dt = datetime.datetime.fromtimestamp(time.mktime(time_struct))
    tz = pytz.timezone(timezone)
    dt = tz.localize(dt)

    # Convert the timezone-aware datetime object to epoch time
    epoch_time = dt.timestamp()

    return epoch_time


# --- MAIN ---
def main(start_time=6, end_time=21):
    while True:
        current_hour = time.localtime().tm_hour
        # If time of day is between start_time (default: 6 AM) and end_time (default: 9 PM) (inclusive)
        if start_time <= current_hour <= end_time:

            next_event = retrieve_next_event()
            # check if there is a next event and if it has a destination
            if next_event is not None and next_event.destination is not None:
                # retrieve directions JSON from Google Directions API
                directions = get_directions(next_event)
                # if the call is successful, populate departure time and train from directions response
                if directions is not None:
                    next_event.departure_time = get_departure_time(directions)
                    next_event.departure_train = get_departure_train(directions)

                    print(repr(next_event))
                    # write JSON to file
                    write_to_json(next_event)

                    # calculate time until departure
                    time_diff = next_event.departure_time - int(datetime.now().timestamp())
                    # if time is less than half an hour, decrease wait time
                    if time_diff < 1800:
                        time.sleep(15)
                    else:
                        time.sleep(360 * 5)

                # if the call is unsuccessful, print error
                else:
                    print("Could not retrieve directions")
                    time.sleep(30)
            # if there is no next event, sleep 5 minutes
            else:
                print("No events found")
                time.sleep(60 * 5)
        else:
            # Calculate the time until the next start_time
            if current_hour < start_time:
                # If current_hour is before the start_time, sleep until start_time
                time_to_sleep = (start_time - current_hour) * (60 * 60)
            else:
                # If current_hour is after the end_time, sleep until start_time of the next day
                time_to_sleep = (24 - current_hour + start_time) * (60 * 60)

            time.sleep(time_to_sleep)


if __name__ == '__main__':
    main()
