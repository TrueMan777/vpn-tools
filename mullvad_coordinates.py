#!/usr/bin/env python3

"""
Database of correct coordinates for Mullvad server locations.
This is used instead of relying on potentially incorrect coordinates from Mullvad's output.
"""

from typing import Dict, Tuple

# Format: 'City, Country': (latitude, longitude)
COORDINATES: Dict[str, Tuple[float, float]] = {
    # Australia and New Zealand
    'Perth, Australia': (-31.9535, 115.8571),
    'Sydney, Australia': (-33.8688, 151.2093),
    'Melbourne, Australia': (-37.8136, 144.9631),
    'Brisbane, Australia': (-27.4698, 153.0251),
    'Adelaide, Australia': (-34.9285, 138.6007),
    'Auckland, New Zealand': (-36.8509, 174.7645),

    # North America
    # Canada
    'Calgary, Canada': (51.0447, -114.0719),
    'Montreal, Canada': (45.5017, -73.5673),
    'Toronto, Canada': (43.6532, -79.3832),
    'Vancouver, Canada': (49.2827, -123.1207),

    # United States
    'New York, NY, USA': (40.7128, -74.0060),
    'Los Angeles, CA, USA': (34.0522, -118.2437),
    'Chicago, IL, USA': (41.8781, -87.6298),
    'Dallas, TX, USA': (32.7767, -96.7970),
    'Seattle, WA, USA': (47.6062, -122.3321),
    'Miami, FL, USA': (25.7617, -80.1918),
    'Atlanta, GA, USA': (33.7490, -84.3880),
    'Phoenix, AZ, USA': (33.4484, -112.0740),
    'Denver, CO, USA': (39.7392, -104.9903),
    'Salt Lake City, UT, USA': (40.7608, -111.8910),
    'Raleigh, NC, USA': (35.7796, -78.6382),
    'San Jose, CA, USA': (37.3382, -121.8863),
    'McAllen, TX, USA': (26.2034, -98.2300),
    'Boston, MA, USA': (42.3601, -71.0589),
    'Houston, TX, USA': (29.7604, -95.3698),
    'Detroit, MI, USA': (42.3314, -83.0458),
    'Ashburn, VA, USA': (39.0438, -77.4874),
    'Washington DC, USA': (38.9072, -77.0369),
    'Secaucus, NJ, USA': (40.7895, -74.0565),

    # Europe
    'London, UK': (51.5074, -0.1278),
    'Manchester, UK': (53.4808, -2.2426),
    'Glasgow, UK': (55.8642, -4.2518),
    'Amsterdam, Netherlands': (52.3676, 4.9041),
    'Paris, France': (48.8566, 2.3522),
    'Bordeaux, France': (44.8378, -0.5792),
    'Marseille, France': (43.2965, 5.3698),
    'Frankfurt, Germany': (50.1109, 8.6821),
    'Berlin, Germany': (52.5200, 13.4050),
    'Brussels, Belgium': (50.8503, 4.3517),
    'Copenhagen, Denmark': (55.6761, 12.5683),
    'Dusseldorf, Germany': (51.2277, 6.7735),
    'Stockholm, Sweden': (59.3293, 18.0686),
    'Gothenburg, Sweden': (57.7089, 11.9746),
    'Oslo, Norway': (59.9139, 10.7522),
    'Helsinki, Finland': (60.1699, 24.9384),
    'Zurich, Switzerland': (47.3769, 8.5417),
    'Vienna, Austria': (48.2082, 16.3738),
    'Madrid, Spain': (40.4168, -3.7038),
    'Barcelona, Spain': (41.3851, 2.1734),
    'Valencia, Spain': (39.4699, -0.3763),
    'Rome, Italy': (41.9028, 12.4964),
    'Milan, Italy': (45.4642, 9.1900),
    'Palermo, Italy': (38.1157, 13.3615),
    'Warsaw, Poland': (52.2297, 21.0122),
    'Prague, Czech Republic': (50.0755, 14.4378),
    'Budapest, Hungary': (47.4979, 19.0402),
    'Bucharest, Romania': (44.4268, 26.1025),
    'Sofia, Bulgaria': (42.6977, 23.3219),
    'Athens, Greece': (37.9838, 23.7275),
    'Tirana, Albania': (41.3275, 19.8187),
    'Stavanger, Norway': (58.9690, 5.7331),
    'Dublin, Ireland': (53.3498, -6.2603),
    'Lisbon, Portugal': (38.7223, -9.1393),
    'Zagreb, Croatia': (45.8150, 15.9819),
    'Belgrade, Serbia': (44.7866, 20.4489),
    'Ljubljana, Slovenia': (46.0569, 14.5058),
    'Bratislava, Slovakia': (48.1486, 17.1077),
    'Tallinn, Estonia': (59.4370, 24.7536),
    'Nicosia, Cyprus': (35.1856, 33.3823),
    'Istanbul, Turkey': (41.0082, 28.9784),
    'Kyiv, Ukraine': (50.4501, 30.5234),

    # Asia
    'Tokyo, Japan': (35.6762, 139.6503),
    'Osaka, Japan': (34.6937, 135.5023),
    'Singapore, Singapore': (1.3521, 103.8198),
    'Hong Kong, Hong Kong': (22.3193, 114.1694),
    'Seoul, South Korea': (37.5665, 126.9780),
    'Taipei, Taiwan': (25.0330, 121.5654),
    'Bangkok, Thailand': (13.7563, 100.5018),
    'Jakarta, Indonesia': (-6.2088, 106.8456),
    'Kuala Lumpur, Malaysia': (3.1390, 101.6869),
    'Manila, Philippines': (14.5995, 120.9842),
    'Tel Aviv, Israel': (32.0853, 34.7818),

    # South America
    'Sao Paulo, Brazil': (-23.5505, -46.6333),
    'Santiago, Chile': (-33.4489, -70.6693),
    'Bogota, Colombia': (4.7110, -74.0721),
    'Lima, Peru': (-12.0464, -77.0428),
    'Queretaro, Mexico': (20.5881, -100.3889),

    # Africa
    'Lagos, Nigeria': (6.5244, 3.3792),
    'Johannesburg, South Africa': (-26.2041, 28.0473),

    # Default location
    'Lijiang, China': (26.8721, 100.2299),
}

def get_coordinates(city: str, country: str) -> Tuple[float, float]:
    """
    Get the correct coordinates for a given city and country.

    Args:
        city: The city name
        country: The country name

    Returns:
        A tuple of (latitude, longitude)
    """
    location_key = f"{city}, {country}"
    return COORDINATES.get(location_key, (0.0, 0.0))