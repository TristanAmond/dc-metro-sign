# DC Metro Sign

Code for an LED sign displaying incoming and outgoing DC Metro train arrival times so you'll never miss a train again! The v1.0.0 release also includes current weather conditions sourced from OpenWeather, along with daily minimum and maximum temperatures.
Find the full [build log here](https://tristanamond.substack.com/)!
## Table of Contents
- [Features](#features)
- [Primary Hardware Requirements](#primary-hardware-requirements)
- [Required APIs](#required-apis)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Contributing](#contributing)

## Features
- Displays real-time Metro train data from WMATA API
- Displays weather information
- Day/Night cycling
- Scrolling notifications


## Primary Hardware Requirements
- Matrix Portal ([Adafruit](https://www.adafruit.com/product/4745))
- 64x32 RGB LED Matrix - 4mm pitch (x2) ([Adafruit](https://www.adafruit.com/product/2278))
- Additional components listed in the [project outline Substack post](https://tristanamond.substack.com/p/metro-sign-build-log-1-project-outline-parts-list)

## Required APIs
- WMATA API ([source](https://developer.wmata.com/))
- Openweather Onecall 3.0 ([source](https://openweathermap.org/api/one-call-3))
- Adafruit IO Time ([source](https://io.adafruit.com/api/docs/#time))

## Getting Started
Clone the repo and transfer all files to a MatrixPortal running CircuitPython.

## Usage

To run the project, execute the `code.py` file.

```python code.py```


## Contributing

Contributions are welcome! To contribute, fork the repository and create a pull request with your changes.

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](https://github.com/TristanAmond/dc-metro-sign/blob/main/LICENSE.txt) file for details.
