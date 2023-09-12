import os
import time
from datetime import datetime
import json
import requests
import pytz

try:
    from creds import secrets
except ImportError as e:
    print(f"Import Error: {e}")
    secrets = {}


class Article:
    def __init__(self, source, title, description, publishedat):
        self.source = source
        self.title = title
        self.description = description
        self.publishedAt = publishedat

    def __repr__(self):
        return ('Article(source=\'{self.source}\', title=\'{self.title}\', description=\'{self.description}\', '
                'publishedAt=\'{self.publishedAt}\')').format(
            self=self)

    def __json__(self):
        """
        Returns a dictionary representation of the object in JSON format.

        :return: A dictionary containing the 'source', 'title', and 'formatted_time' attributes.
        :rtype: dict
        """
        # Parse the publishedAt date string into a datetime object
        date_obj = datetime.strptime(self.publishedAt, "%Y-%m-%dT%H:%M:%SZ")
        utc_timezone = pytz.timezone("UTC")
        date_obj = utc_timezone.localize(date_obj)
        desired_timezone = pytz.timezone("America/New_York")  # Replace with your desired timezone
        date_obj = date_obj.astimezone(desired_timezone)

        # Format the datetime object as "hh:mmAM/PM"
        formatted_time = date_obj.strftime("%I:%M%p")

        return {
            'source': self.source,
            'publishedTime': formatted_time,
            'publishedAt': self.publishedAt,
            'title': self.title
        }


# --- NEWS API CALL AND FUNCTIONS---

def retrieve_headlines(news_source='gnews', count=3):
    """
    Retrieves the top headlines from the News API.

    Args:
        count (int, optional): The number of headlines to retrieve. Defaults to 5.
        news_source (str, optional): The news source to use. Defaults to 'gnews'.

    Returns:
        dict: A dictionary containing the JSON response from the News API.
    """
    request_url = None
    if news_source == 'newsapi':
        # query News API with input count
        request_url = f'https://newsapi.org/v2/top-headlines?country=us&pageSize={count}'
        headers = {'X-Api-Key': secrets['news api key']}
    elif news_source == 'gnews':
        # query GNews API with input count
        request_url = f'https://gnews.io/api/v4/top-headlines?category=general&lang=en&country=us&max={count}'
        request_url += f'&apikey={secrets["gnews api key"]}'
        headers = {}

    if request_url is not None:
        response = requests.get(request_url, headers=headers)
        json_data = response.json()
        del response
        return json_data
    else:
        print('Error: invalid news source: please input "newsapi" or "gnews"')
        return None


def create_article_list(json_data):
    """
        Creates a list of Article objects from a JSON data.
        Parameters:
            json_data (dict): A dictionary containing the JSON data.
        Returns:
            list: A list of Article objects.
    """
    article_list = []
    for item in json_data['articles']:
        article_title = item['title'].split(' - ')[0].strip()
        article_list.append(Article(item['source']['name'], article_title, item['description'], item['publishedAt']))

    # Used for TESTING, remove from production
    for item in article_list:
        print(repr(item), '\n')
    return article_list


# --- UTILITY FUNCTIONS ---
def write_to_json(article):
    """
        Write the given article to a JSON file.
        Parameters:
            article (object): The article to be written to the JSON file.
        Returns:
            None
    """
    # set filepath for JSON file
    filepath = os.path.join(secrets['JSON file location'], 'headline.json')

    # write JSON to file
    with open(filepath, 'w') as json_file:
        # use custom Article JSON serialization
        json.dump(article, json_file, default=Article.__json__)
    # confirm file was written
    if os.path.exists(filepath):
        print("Headline written successfully to {}".format(filepath))
    else:
        print("Error writing to {}".format(filepath))


# --- MAIN ---
def main(start_time=6, end_time=21, news_source="gnews"):
    """
    Continuously retrieve headlines, create article list, and write the most recent article to JSON.
    Sleep for 15 minutes between each iteration during operating hours.
    """
    while True:
        current_hour = time.localtime().tm_hour

        # If time of day is between start_time (default: 6 AM) and end_time (default: 10 PM) (inclusive)
        if start_time <= current_hour <= end_time:
            json_data = None
            try:
                # Retrieve headlines
                json_data = retrieve_headlines(news_source)
            except Exception as e:
                print(e)

            if json_data is not None:
                # Create article list
                article_list = create_article_list(json_data)
                # Write the most recent article to JSON
                write_to_json(article_list.pop(0))
            else:
                print("No headlines found")

            # Sleep for 15 minutes
            time.sleep(60 * 15)
        else:
            # Calculate the time until the next start_time
            if current_hour < start_time:
                # If current_hour is before the start_time, sleep until start_time
                time_to_sleep = (start_time - current_hour) * (60 * 60)
            else:
                # If current_hour is after the end_time, sleep until start_time of the next day
                time_to_sleep = (24 - current_hour + start_time) * (60 * 60)

            time.sleep(time_to_sleep)


if __name__ == "__main__":
    main()
