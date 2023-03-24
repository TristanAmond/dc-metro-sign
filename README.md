# DC Metro Sign

Code for an LED sign displaying incoming and outgoing DC Metro train arrival times so you'll never miss a train again! The v1.0.0 release also includes current weather conditions sourced from OpenWeather, along with daily minimum and maximum temperatures.

## Hardware Requirements
- Adafruit Matrix Portal (https://www.adafruit.com/product/4745)
- 64x32 RGB LED Matrix - 4mm pitch (x2) (https://www.adafruit.com/product/2278)
- Additional components listed in the project outline Substack post (https://tristanamond.substack.com/p/metro-sign-build-log-1-project-outline-parts-list)


## Features
- Displays real-time Metro train data from WMATA API
- Displays weather information
- Day/Night cycling

## Getting Started

You can use the lib directory as it has all the required libraries and has pared down unused libraries from the default Circuitpython bundle. Alternatively, you can clone the repository and install the required libraries. 

```git clone https://github.com/TristanAmond/dc-metro-sign.git cd dc-metro-sign pip install -r requirements.txt```


## Usage

To run the project, execute the `code.py` file.

```python code.py```


## Contributing

Contributions are welcome! To contribute, fork the repository and create a pull request with your changes.
