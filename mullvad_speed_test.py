#!/usr/bin/env python3

import subprocess
import json
import re
import time
import os
import pickle
import sqlite3
from typing import List, Dict, Tuple, Optional
import statistics
from dataclasses import dataclass
from datetime import datetime
import logging
import sys
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import argparse
from mullvad_coordinates import get_coordinates
import shutil  # For terminal size
import random  # For random server selection

# Try to import colorama for colored terminal output
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLOR_SUPPORT = True
except ImportError:
    # Create dummy color classes if colorama is not available
    class DummyFore:
        RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = RESET = ''
    class DummyStyle:
        BRIGHT = DIM = NORMAL = RESET_ALL = ''
    class DummyBack:
        RED = GREEN = YELLOW = BLUE = RESET = ''
    Fore = DummyFore()
    Style = DummyStyle()
    Back = DummyBack()
    COLOR_SUPPORT = False

DEFAULT_MAX_SERVERS = 20
MAX_SERVERS_HARD_LIMIT = 100  # Maximum number of servers to test
DEFAULT_LOCATION = "Beijing, Beijing, China"
BEIJING_COORDS = (39.9057136, 116.3912972)  # Default coordinates for Beijing
COORDS_CACHE_FILE = "geocoords_cache.pkl"
DEFAULT_DB_FILE = "mullvad_results.db"
MIN_DOWNLOAD_SPEED = 5.0  # Minimum viable download speed in Mbps
DEFAULT_CONNECTION_TIME = 15.0  # Default connection timeout if no adaptive value
MAX_CONNECTION_TIME = 10.0  # Initial connection timeout (will be adjusted)
MAX_SPEEDTEST_TIME = 45.0  # Maximum time for speed test (seconds)
MIN_VIABLE_SERVERS = 10   # Minimum number of viable servers before stopping tests

# Continent mapping for server countries
CONTINENT_MAPPING = {
    'North America': ['us', 'ca', 'mx'],
    'South America': ['br', 'ar', 'cl', 'co', 'pe'],
    'Europe': ['gb', 'uk', 'de', 'fr', 'it', 'es', 'nl', 'se', 'no', 'dk', 'fi', 'ch', 'at', 'be', 'ie', 'pt', 'pl', 'cz', 'gr', 'ro', 'hu'],
    'Asia': ['jp', 'kr', 'sg', 'hk', 'in', 'my', 'th', 'vn', 'id', 'ph', 'tw', 'cn'],
    'Oceania': ['au', 'nz'],
    'Africa': ['za', 'eg', 'ng', 'ke', 'ma']
}

# Configure logging - only to file, not to terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mullvad_speed_test.log')
    ]
)
logger = logging.getLogger(__name__)

# Unicode symbols for status indicators
SYMBOLS = {
    'success': '✓',
    'error': '✗',
    'warning': '⚠',
    'info': 'ℹ',
    'connecting': '→',
    'testing': '⋯',
    'bullet': '•',
    'right_arrow': '→',
    'speedometer': '🔄',
    'clock': '⏱',
    'globe': '🌐',
    'server': '🖥',
    'signal': '📶',
    'download': '⬇',
    'upload': '⬆',
    'ping': '📡',
    'checkmark': '✓',
    'cross': '✗',
}

# Fallback ASCII symbols if terminal doesn't support Unicode
ASCII_SYMBOLS = {
    'success': '+',
    'error': 'x',
    'warning': '!',
    'info': 'i',
    'connecting': '>',
    'testing': '...',
    'bullet': '*',
    'right_arrow': '->',
    'speedometer': 'O',
    'clock': 'T',
    'globe': 'G',
    'server': 'S',
    'signal': '^',
    'download': 'D',
    'upload': 'U',
    'ping': 'P',
    'checkmark': 'V',
    'cross': 'X',
}

# Check if terminal supports Unicode
try:
    "\u2713".encode(sys.stdout.encoding)
    USE_UNICODE = True
except UnicodeEncodeError:
    USE_UNICODE = False

def get_symbol(name):
    """Get the appropriate symbol based on terminal support"""
    if USE_UNICODE:
        return SYMBOLS.get(name, '')
    return ASCII_SYMBOLS.get(name, '')

def get_terminal_width():
    """Get the width of the terminal window"""
    try:
        return shutil.get_terminal_size().columns
    except:
        return 80  # Default if can't determine

def print_header(title, width=None):
    """Print a formatted header"""
    if width is None:
        width = get_terminal_width()
    
    if COLOR_SUPPORT:
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{title}")
        print(f"{Fore.CYAN}{Style.BRIGHT}{'-' * min(len(title), width)}{Style.RESET_ALL}")
    else:
        print(f"\n{title}")
        print(f"{'-' * min(len(title), width)}")

def print_success(message):
    """Print a success message"""
    if COLOR_SUPPORT:
        print(f"{Fore.GREEN}{get_symbol('success')} {message}{Style.RESET_ALL}")
    else:
        print(f"{get_symbol('success')} {message}")

def print_error(message):
    """Print an error message"""
    if COLOR_SUPPORT:
        print(f"{Fore.RED}{get_symbol('error')} {message}{Style.RESET_ALL}")
    else:
        print(f"{get_symbol('error')} {message}")

def print_warning(message):
    """Print a warning message"""
    if COLOR_SUPPORT:
        print(f"{Fore.YELLOW}{get_symbol('warning')} {message}{Style.RESET_ALL}")
    else:
        print(f"{get_symbol('warning')} {message}")

def print_info(message):
    """Print an info message"""
    if COLOR_SUPPORT:
        print(f"{Fore.BLUE}{get_symbol('info')} {message}{Style.RESET_ALL}")
    else:
        print(f"{get_symbol('info')} {message}")

def print_status(message, status=None):
    """Print a status message with appropriate color"""
    if status == "success":
        print_success(message)
    elif status == "error":
        print_error(message)
    elif status == "warning":
        print_warning(message)
    elif status == "info":
        print_info(message)
    else:
        print(message)

def format_server_info(server):
    """Format server information nicely"""
    if COLOR_SUPPORT:
        return (f"{Fore.CYAN}{get_symbol('server')} {server.hostname} "
               f"{Fore.WHITE}({server.city}, {server.country}) "
               f"{Fore.YELLOW}{server.distance_km:.0f} km")
    else:
        return (f"{get_symbol('server')} {server.hostname} "
               f"({server.city}, {server.country}) "
               f"{server.distance_km:.0f} km")

    def format_mtr_results(result):
        """Format MTR results nicely"""
        if COLOR_SUPPORT:
            return (f"{Fore.YELLOW}{get_symbol('ping')} Latency: {result.avg_latency:.2f} ms | "
                f"Loss: {result.packet_loss:.2f}% | Hops: {result.hops}")
        else:
            return (f"{get_symbol('ping')} Latency: {result.avg_latency:.2f} ms | "
                f"Loss: {result.packet_loss:.2f}% | Hops: {result.hops}")

    def format_speedtest_results(result):
        """Format speedtest results nicely"""
        if COLOR_SUPPORT:
            return (f"{Fore.GREEN}{get_symbol('download')} {result.download_speed:.2f} Mbps | "
                f"{Fore.BLUE}{get_symbol('upload')} {result.upload_speed:.2f} Mbps | "
                f"{Fore.YELLOW}{get_symbol('ping')} {result.ping:.2f} ms | "
                f"Jitter: {result.jitter:.2f} ms | Loss: {result.packet_loss:.2f}%")
        else:
            return (f"{get_symbol('download')} {result.download_speed:.2f} Mbps | "
                f"{get_symbol('upload')} {result.upload_speed:.2f} Mbps | "
                f"{get_symbol('ping')} {result.ping:.2f} ms | "
                f"Jitter: {result.jitter:.2f} ms | Loss: {result.packet_loss:.2f}%")

def print_connection_status(hostname, status, time_taken=None):
    """Print connection status with color coding"""
    if status == "connecting":
        if COLOR_SUPPORT:
            print(f"{Fore.YELLOW}{get_symbol('connecting')} Connecting to {hostname}...{Style.RESET_ALL}", end="\r")
        else:
            print(f"{get_symbol('connecting')} Connecting to {hostname}...", end="\r")
    elif status == "success":
        if time_taken is not None:
            if COLOR_SUPPORT:
                print(f"{Fore.GREEN}{get_symbol('success')} Connected to {hostname} in {time_taken:.2f}s{Style.RESET_ALL}")
            else:
                print(f"{get_symbol('success')} Connected to {hostname} in {time_taken:.2f}s")
        else:
            if COLOR_SUPPORT:
                print(f"{Fore.GREEN}{get_symbol('success')} Connected to {hostname}{Style.RESET_ALL}")
            else:
                print(f"{get_symbol('success')} Connected to {hostname}")
    elif status == "error":
        if COLOR_SUPPORT:
            print(f"{Fore.RED}{get_symbol('error')} Connection to {hostname} failed{Style.RESET_ALL}")
        else:
            print(f"{get_symbol('error')} Connection to {hostname} failed")
    elif status == "timeout":
        if COLOR_SUPPORT:
            print(f"{Fore.RED}{get_symbol('clock')} Connection to {hostname} timed out{Style.RESET_ALL}")
        else:
            print(f"{get_symbol('clock')} Connection to {hostname} timed out")
    
def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """Print a progress bar"""
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + ' ' * (length - filled_length)
    
    if COLOR_SUPPORT:
        # Color the progress bar based on completion
        if percent < 33:
            color = Fore.RED
        elif percent < 66:
            color = Fore.YELLOW
        else:
            color = Fore.GREEN
            
        print(f'\r{prefix} {color}{bar}{Style.RESET_ALL} {percent:.1f}% {suffix}', end='\r')
    else:
        print(f'\r{prefix} {bar} {percent:.1f}% {suffix}', end='\r')
        
    # Print a newline when complete
    if iteration == total:
        print()

@dataclass
class ServerInfo:
    country: str
    city: str
    hostname: str
    protocol: str
    provider: str
    ownership: str
    ip: str
    ipv6: str
    connection_time: float = 0  # Time in seconds to establish connection
    latitude: float = 0.0
    longitude: float = 0.0
    distance_km: float = 0.0  # Distance from reference location

@dataclass
class SpeedTestResult:
    download_speed: float  # Mbps
    upload_speed: float    # Mbps
    ping: float           # ms
    jitter: float         # ms
    packet_loss: float    # percentage

@dataclass
class MtrResult:
    avg_latency: float    # ms
    packet_loss: float    # percentage
    hops: int

def input_location() -> str:
    """Interactive function to input location."""
    print_header("LOCATION FOR MULLVAD VPN TESTS")
    print_info("Please enter your location in the format 'City, Country'")
    print("Example: 'Paris, France' or 'Beijing, China'")
    
    while True:
        location = input("\nYour location: ").strip()
        if location:
            # Basic format validation
            if ',' in location and len(location.split(',')) >= 2:
                return location
            else:
                print_warning("Incorrect format. Please use the format 'City, Country'")
        else:
            print_info(f"Using default location: {DEFAULT_LOCATION}")
            return DEFAULT_LOCATION

def input_coordinates() -> Tuple[float, float]:
    """Interactive function to input coordinates manually."""
    print_header("MANUAL COORDINATES INPUT")
    print_warning("Unable to determine coordinates automatically.")
    print_info("Please enter the coordinates manually.\n")
    
    while True:
        try:
            lat = float(input("Latitude (e.g. 48.8566 for Paris): ").strip())
            lon = float(input("Longitude (e.g. 2.3522 for Paris): ").strip())
            
            # Simple validation
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                print_success(f"Coordinates accepted: ({lat}, {lon})")
                return (lat, lon)
            else:
                print_warning("Coordinates out of range. Latitude: -90 to 90, Longitude: -180 to 180")
        except ValueError:
            print_error("Please enter valid numbers.")

def verify_location_coordinates(location: str, geolocator) -> Tuple[bool, Optional[Tuple[float, float]]]:
    """Verify if coordinates can be determined for a location."""
    try:
        print_info(f"Searching for coordinates for {location}...")
        location_data = geolocator.geocode(location, exactly_one=True)
        if location_data:
            coords = (location_data.latitude, location_data.longitude)
            print_success(f"Location found: {location_data.address}")
            print_success(f"Coordinates: {coords}")
            return True, coords
        else:
            print_error(f"Unable to find coordinates for: {location}")
            return False, None
    except (GeocoderTimedOut, Exception) as e:
        print_error(f"Error searching for coordinates: {e}")
        return False, None

class MullvadTester:
    def __init__(self, target_host: str = "1.1.1.1", reference_location: str = DEFAULT_LOCATION,
                 default_lat: float = None, default_lon: float = None, verbose: bool = False,
                 db_file: str = DEFAULT_DB_FILE, interactive: bool = False):
        # Configure logging level based on verbosity
        log_level = logging.INFO if verbose else logging.WARNING
        logger.setLevel(log_level)
        
        self.target_host = target_host
        self.interactive = interactive
        
        # Handle location interactively if needed
        if interactive and reference_location == DEFAULT_LOCATION:
            reference_location = input_location()
        
        self.reference_location = reference_location
        self.default_coords = (default_lat, default_lon) if default_lat is not None and default_lon is not None else None
        self.db_file = db_file
        
        # Load coordinates cache
        self.coords_cache = self._load_coords_cache()
        
        # Initialize database
        self._init_database()
        
        # Get reference coordinates, possibly interactively
        self.reference_coords = self._get_location_coordinates(reference_location, interactive)
        
        # Get server list
        print_header("RETRIEVING MULLVAD SERVERS")
        self.servers = self._get_servers()
        self.results: Dict[str, Tuple[SpeedTestResult, MtrResult]] = {}
        self.connection_timeout = MAX_CONNECTION_TIME  # Connection timeout in seconds (will be adjusted)
        self.successful_servers = 0  # Counter for servers that respond correctly

        if not self.servers:
            print_error("No Mullvad servers found. Please check that Mullvad is installed and accessible.")
            logger.error("No Mullvad servers found. Please check if Mullvad is installed and accessible.")
            sys.exit(1)

        logger.info(f"Found {len(self.servers)} Mullvad servers")
        logger.info(f"Reference location: {reference_location} ({self.reference_coords})")
        
        if interactive:
            print_success(f"Mullvad servers found: {len(self.servers)}")
            print_info(f"Reference location: {reference_location}")
            print_info(f"Coordinates: ({self.reference_coords[0]:.4f}, {self.reference_coords[1]:.4f})")

    def _load_coords_cache(self) -> Dict[str, Tuple[float, float]]:
        """Load coordinates cache from disk if it exists."""
        if os.path.exists(COORDS_CACHE_FILE):
            try:
                with open(COORDS_CACHE_FILE, 'rb') as f:
                    cache = pickle.load(f)
                    logger.info(f"Loaded {len(cache)} location coordinates from cache")
                    if self.interactive:
                        print_info(f"Loaded {len(cache)} coordinates from cache")
                    return cache
            except Exception as e:
                logger.warning(f"Could not load coordinates cache: {e}")
                if self.interactive:
                    print_warning(f"Could not load coordinates cache: {e}")
        return {}

    def _save_coords_cache(self):
        """Save coordinates cache to disk."""
        try:
            with open(COORDS_CACHE_FILE, 'wb') as f:
                pickle.dump(self.coords_cache, f)
                logger.info(f"Saved {len(self.coords_cache)} location coordinates to cache")
        except Exception as e:
            logger.warning(f"Could not save coordinates cache: {e}")

    def _init_database(self):
        """Initialize SQLite database for storing test results."""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            
            # Create tables if they don't exist
            c.execute('''
                CREATE TABLE IF NOT EXISTS test_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    reference_location TEXT,
                    reference_lat REAL,
                    reference_lon REAL,
                    protocol TEXT
                )
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS server_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    hostname TEXT,
                    country TEXT,
                    city TEXT,
                    distance_km REAL,
                    connection_time REAL,
                    download_speed REAL,
                    upload_speed REAL,
                    ping REAL,
                    jitter REAL,
                    speedtest_packet_loss REAL,
                    mtr_latency REAL,
                    mtr_packet_loss REAL,
                    mtr_hops INTEGER,
                    FOREIGN KEY (session_id) REFERENCES test_sessions (id)
                )
            ''')
            
            # Check if viable column exists, if not add it
            try:
                c.execute("PRAGMA table_info(server_results)")
                columns = [column[1] for column in c.fetchall()]
                if 'viable' not in columns:
                    logger.info("Adding 'viable' column to server_results table")
                    c.execute("ALTER TABLE server_results ADD COLUMN viable INTEGER DEFAULT 0")
                    if self.interactive:
                        print_info("Adding 'viable' column to existing database")
            except Exception as column_error:
                logger.warning(f"Error checking or adding viable column: {column_error}")
                if self.interactive:
                    print_warning(f"Error checking or adding 'viable' column: {column_error}")
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            if self.interactive:
                print_error(f"Error initializing database: {e}")

    def _get_location_coordinates(self, location: str, interactive: bool = False) -> Tuple[float, float]:
        """Get coordinates for a location using geocoding with caching and interactive mode."""
        # Check cache first
        if location in self.coords_cache:
            coords = self.coords_cache[location]
            logger.info(f"Using cached coordinates for {location}: {coords}")
            if interactive:
                print_info(f"Using cached coordinates for {location}: {coords}")
            return coords

        try:
            geolocator = Nominatim(user_agent="mullvad_speed_test")
            
            if interactive:
                # Interactive verification
                success, coords = verify_location_coordinates(location, geolocator)
                
                if not success:
                    # Propose to try a different location or enter coordinates manually
                    print_header("LOCATION OPTIONS")
                    print("1. Try another location")
                    print("2. Enter coordinates manually")
                    
                    choice = input("\nYour choice (1/2): ").strip()
                    if choice == "1":
                        new_location = input_location()
                        return self._get_location_coordinates(new_location, interactive)
                    else:
                        coords = input_coordinates()
                        # Save manually entered coordinates to cache
                        self.coords_cache[location] = coords
                        self._save_coords_cache()
                        return coords
                else:
                    # Save to cache
                    self.coords_cache[location] = coords
                    self._save_coords_cache()
                    return coords
            else:
                # Non-interactive mode
                location_data = geolocator.geocode(location, exactly_one=True)
                
                if location_data:
                    coords = (location_data.latitude, location_data.longitude)
                    logger.info(f"Found coordinates for {location}: {coords}")
                    logger.info(f"Full location data: {location_data.address}")
                    
                    # Save to cache
                    self.coords_cache[location] = coords
                    self._save_coords_cache()
                    
                    return coords
                else:
                    logger.warning(f"Could not find coordinates for {location}")
                    if self.default_coords:
                        logger.info(f"Using provided default coordinates: {self.default_coords}")
                        return self.default_coords
                    elif location.lower().startswith("beijing"):
                        logger.info(f"Using built-in Beijing coordinates: {BEIJING_COORDS}")
                        return BEIJING_COORDS
                    else:
                        logger.warning("No default coordinates provided. Using (0.0, 0.0) as fallback.")
                        return (0.0, 0.0)  # Return zeros instead of exiting
                    
        except (GeocoderTimedOut, Exception) as e:
            logger.warning(f"Error getting coordinates for {location}: {e}")
            
            if interactive:
                print_error(f"Error searching for coordinates: {e}")
                coords = input_coordinates()
                self.coords_cache[location] = coords
                self._save_coords_cache()
                return coords
            else:
                if self.default_coords:
                    logger.info(f"Using provided default coordinates: {self.default_coords}")
                    return self.default_coords
                elif location.lower().startswith("beijing"):
                    logger.info(f"Using built-in Beijing coordinates: {BEIJING_COORDS}")
                    return BEIJING_COORDS
                else:
                    logger.warning("No default coordinates provided. Using (0.0, 0.0) as fallback.")
                    return (0.0, 0.0)  # Return zeros instead of exiting

    def _calculate_distance(self, server_coords: Tuple[float, float]) -> float:
        """Calculate distance between server and reference location."""
        if server_coords == (0.0, 0.0) or self.reference_coords == (0.0, 0.0):
            return float('inf')

        distance = geodesic(self.reference_coords, server_coords).kilometers
        logger.debug(f"Distance calculation:")
        logger.debug(f"  Reference: {self.reference_coords}")
        logger.debug(f"  Server: {server_coords}")
        logger.debug(f"  Distance: {distance:.2f} km")
        return distance

    def _get_servers(self) -> List[ServerInfo]:
        """Parse mullvad relay list output to get server information."""
        servers = []
        try:
            logger.info("Fetching Mullvad server list...")
            if self.interactive:
                print_info("Retrieving Mullvad server list...")
                
            # Run this once and capture all output to reduce subprocess calls
            output = subprocess.check_output(["mullvad", "relay", "list"], text=True)

            logger.debug("Got server list output")
            
            # Show a spinner while processing
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                print("Processing server data ", end='')
                sys.stdout.flush()

            current_country = ""
            current_city = ""
            spinner_idx = 0
            
            lines = output.strip().split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # Update spinner every few lines in interactive mode
                if self.interactive and i % 10 == 0:
                    print(f"\rProcessing server data {spinner_chars[spinner_idx]} ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()

                logger.debug(f"Processing line: {line}")

                # Parse country
                country_match = re.match(r'^([A-Za-z\s]+)\s+\(([a-z]{2})\)$', line)
                if country_match:
                    current_country = country_match.group(1)
                    logger.debug(f"Found country: {current_country}")
                    continue

                # Parse city
                city_match = re.match(r'^\s*([A-Za-z\s,]+)\s+\([a-z]+\)\s+@\s+[-\d.]+°[NS],\s+[-\d.]+°[EW]$', line)
                if city_match:
                    current_city = city_match.group(1)
                    logger.debug(f"Found city: {current_city}")
                    # Get coordinates from our database instead of parsing from Mullvad output
                    current_coords = get_coordinates(current_city, current_country)
                    logger.debug(f"Using coordinates from database: {current_coords}")
                    continue

                # Parse server
                server_match = re.match(r'^\s*([a-z]{2}-[a-z]+-(?:wg|ovpn)-\d+)\s+\(([^,]+)(?:,\s*([^)]+))?\)\s+-\s+([^,]+)(?:,\s+hosted by ([^()]+))?\s+\(([^)]+)\)$', line)
                if server_match:
                    hostname = server_match.group(1)
                    ip = server_match.group(2)
                    ipv6 = server_match.group(3) if server_match.group(3) else ""
                    protocol = server_match.group(4)
                    provider = server_match.group(5) if server_match.group(5) else ""
                    ownership = server_match.group(6)

                    # Calculate distance from reference location
                    distance = self._calculate_distance(current_coords)

                    logger.debug(f"Found server: {hostname} ({ip}) at {current_city}, {current_country}")
                    logger.debug(f"  Coordinates: {current_coords}")
                    logger.debug(f"  Distance: {distance:.2f} km")

                    servers.append(ServerInfo(
                        country=current_country,
                        city=current_city,
                        hostname=hostname,
                        protocol=protocol,
                        provider=provider,
                        ownership=ownership,
                        ip=ip,
                        ipv6=ipv6,
                        latitude=current_coords[0],
                        longitude=current_coords[1],
                        distance_km=distance
                    ))
                else:
                    logger.debug(f"Line did not match server pattern: {line}")
            
            # Clear spinner and show success message
            if self.interactive:
                print(f"\rProcessing server data {' ' * 20}")
            
            # Sort servers by distance
            servers.sort(key=lambda x: x.distance_km)

            logger.info(f"Successfully parsed and sorted {len(servers)} servers by distance")
            return servers
        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting server list: {e}")
            if self.interactive:
                print_error(f"Error retrieving server list: {e}")
                print_warning("Please verify that Mullvad VPN is correctly installed and configured.")
                sys.exit(1)
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting server list: {e}")
            logger.exception(e)
            if self.interactive:
                print_error(f"Unexpected error retrieving server list: {e}")
                print_warning("Please verify that Mullvad VPN is correctly installed and configured.")
                sys.exit(1)
            return []

    def _get_location_continent(self, location):
        """Determine which continent a location is in."""
        # Common locations and their continents
        location_continents = {
            # Asia
            'china': 'Asia', 'beijing': 'Asia', 'tokyo': 'Asia', 'japan': 'Asia',
            'india': 'Asia', 'singapore': 'Asia', 'hongkong': 'Asia',
            'seoul': 'Asia', 'korea': 'Asia', 'thailand': 'Asia',
            'malaysia': 'Asia', 'vietnam': 'Asia', 'indonesia': 'Asia',
            'philippines': 'Asia', 'taiwan': 'Asia',
            
            # Europe
            'france': 'Europe', 'paris': 'Europe', 'germany': 'Europe',
            'berlin': 'Europe', 'uk': 'Europe', 'london': 'Europe',
            'italy': 'Europe', 'rome': 'Europe', 'spain': 'Europe',
            'madrid': 'Europe', 'netherlands': 'Europe', 'amsterdam': 'Europe',
            'sweden': 'Europe', 'stockholm': 'Europe', 'switzerland': 'Europe',
            'zurich': 'Europe',
            
            # North America
            'usa': 'North America', 'united states': 'North America',
            'new york': 'North America', 'los angeles': 'North America',
            'canada': 'North America', 'toronto': 'North America',
            'vancouver': 'North America', 'mexico': 'North America',
            
            # South America
            'brazil': 'South America', 'argentina': 'South America',
            'chile': 'South America', 'colombia': 'South America',
            'peru': 'South America',
            
            # Oceania
            'australia': 'Oceania', 'sydney': 'Oceania',
            'melbourne': 'Oceania', 'new zealand': 'Oceania',
            
            # Africa
            'south africa': 'Africa', 'egypt': 'Africa',
            'nigeria': 'Africa', 'kenya': 'Africa', 'morocco': 'Africa'
        }
        
        # Clean up and lowercase the location
        location_lower = location.lower().replace(',', ' ').replace('.', ' ')
        
        # Check for direct continent names
        for continent in CONTINENT_MAPPING.keys():
            if continent.lower() in location_lower:
                return continent
        
        # Check for known locations
        for loc, continent in location_continents.items():
            if loc in location_lower:
                return continent
        
        # Check country codes
        for continent, countries in CONTINENT_MAPPING.items():
            for country in countries:
                if country in location_lower:
                    return continent
        
        # Default to Europe if unknown
        logger.warning(f"Could not determine continent for {location}, defaulting to Europe")
        return "Europe"
        
    def run_connection_calibration(self):
        """Run preliminary tests on random servers from different continents to calibrate connection timeout."""
        if self.interactive:
            print_header("CONNECTION CALIBRATION")
            print_info("Selecting servers from each continent to determine average connection time...")
        
        # Get country code for each server
        server_countries = {}
        for server in self.servers:
            # Extract country code from hostname (first 2 characters)
            country_code = server.hostname.split('-')[0]
            if country_code not in server_countries:
                server_countries[country_code] = []
            server_countries[country_code].append(server)
        
        # Find which continents we have servers for
        available_continents = {}
        for continent, countries in CONTINENT_MAPPING.items():
            for country in countries:
                if country in server_countries:
                    if continent not in available_continents:
                        available_continents[continent] = []
                    available_continents[continent].extend(server_countries[country])
        
        # Determine user's continent
        self.user_continent = self._get_location_continent(self.reference_location)
        if self.interactive:
            print_info(f"Your location appears to be in: {self.user_continent}")
        
        # Select one random server from each available continent
        test_servers = []
        for continent, continent_servers in available_continents.items():
            if continent_servers:
                test_servers.append(random.choice(continent_servers))
        
        if self.interactive:
            print_success(f"Servers selected for calibration: {len(test_servers)}")
            for server in test_servers:
                print_info(f"  • {server.hostname} ({server.city}, {server.country})")
            print("")
        else:
            print(f"Testing {len(test_servers)} servers for connection calibration")
        
        # Test connection times using a more generous initial timeout
        self.connection_timeout = DEFAULT_CONNECTION_TIME
        conn_times = []
        
        for server in test_servers:
            if self.interactive:
                print_info(f"Testing {server.hostname}...")
            
            # Try to connect to the server
            if self.connect_to_server(server):
                conn_times.append(server.connection_time)
                # Disconnect after successful connection
                try:
                    subprocess.run(["mullvad", "disconnect"], check=True, capture_output=True)
                except Exception:
                    pass
        
        # Calculate the average connection time or use default
        if conn_times:
            avg_conn_time = sum(conn_times) / len(conn_times)
            # Add a 50% buffer for reliability
            self.connection_timeout = min(avg_conn_time * 1.5, DEFAULT_CONNECTION_TIME)
            
            if self.interactive:
                print_success(f"Average connection time: {avg_conn_time:.2f}s")
                print_success(f"Connection timeout adjusted to: {self.connection_timeout:.2f}s")
            
            logger.info(f"Calibrated connection timeout to {self.connection_timeout:.2f}s based on average {avg_conn_time:.2f}s")
            return avg_conn_time
        else:
            # If no server responded, use default
            self.connection_timeout = DEFAULT_CONNECTION_TIME
            
            if self.interactive:
                print_warning("No servers responded, using default timeout")
                print_info(f"Connection timeout: {self.connection_timeout:.2f}s")
            
            logger.warning("No servers responded during calibration, using default timeout")
            return None

    def _run_speedtest(self) -> SpeedTestResult:
        """Run speedtest-cli and return results."""
        try:
            logger.info("Running speedtest...")
            if self.interactive:
                print("")  # Add a blank line for readability
                print_info("Running speed test...")
                
            cmd = ["speedtest-cli", "--json"]
            
            # Display a spinner during the test
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                spinner_idx = 0
                start_time = time.time()
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Show spinner while the process is running
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    # Stop after MAX_SPEEDTEST_TIME
                    if elapsed > MAX_SPEEDTEST_TIME:
                        process.terminate()
                        print("")  # Newline after spinner
                        print_info(f"Speed test canceled after {MAX_SPEEDTEST_TIME}s (maximum time reached)")
                        return SpeedTestResult(0, 0, 0, 0, 100)
                        
                    print(f"\r{get_symbol('speedometer')} Speed test in progress {spinner_chars[spinner_idx]} ({elapsed:.1f}s) ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()
                    time.sleep(0.1)
                
                # Get the output
                stdout, stderr = process.communicate()
                
                # Check for errors
                if process.returncode != 0:
                    print("")  # Newline after spinner
                    
                    # Check for specific 403 Forbidden error
                    if "403: Forbidden" in stderr:
                        print_info("Speedtest service unavailable from this VPN server (IP likely blocked)")
                        logger.warning("Speedtest service blocked this VPN server's IP address (403 Forbidden)")
                    else:
                        print_info(f"Speed test unavailable for this server")
                        logger.error(f"Speedtest failed: {stderr}")
                        
                    return SpeedTestResult(0, 0, 0, 0, 100)
                
                # Clear spinner line
                print(f"\r{' ' * get_terminal_width()}", end='\r')
                
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError:
                    print_info(f"Speed test results not usable (unrecognized format)")
                    return SpeedTestResult(0, 0, 0, 0, 100)
            else:
                # Non-interactive mode: just run the command with timeout
                try:
                    output = subprocess.check_output(
                        cmd,
                        text=True,
                        stderr=subprocess.PIPE,
                        timeout=MAX_SPEEDTEST_TIME
                    )
                    data = json.loads(output)
                except subprocess.TimeoutExpired:
                    logger.error(f"Speedtest timed out after {MAX_SPEEDTEST_TIME} seconds")
                    return SpeedTestResult(0, 0, 0, 0, 100)
                except subprocess.CalledProcessError as e:
                    # Check for specific 403 Forbidden error
                    if e.stderr and "403: Forbidden" in e.stderr:
                        logger.warning("Speedtest service blocked this VPN server's IP address (403 Forbidden)")
                    else:
                        logger.error(f"Speedtest failed: {e.stderr if e.stderr else str(e)}")
                    return SpeedTestResult(0, 0, 0, 0, 100)
                except json.JSONDecodeError:
                    logger.error("Failed to decode JSON from speedtest result")
                    return SpeedTestResult(0, 0, 0, 0, 100)

            result = SpeedTestResult(
                download_speed=data['download'] / 1_000_000,  # Convert to Mbps
                upload_speed=data['upload'] / 1_000_000,      # Convert to Mbps
                ping=data['ping'],
                jitter=data.get('jitter', 0),
                packet_loss=data.get('packetLoss', 0)
            )

            logger.info(f"Speedtest results - Download: {result.download_speed:.2f} Mbps, "
                       f"Upload: {result.upload_speed:.2f} Mbps, Ping: {result.ping:.2f} ms")
            
            if self.interactive:
                print_success("Speed test results:")
                print(format_speedtest_results(result))
                
            return result

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Error running speedtest: {e}")
            if self.interactive:
                print_info(f"Speed test unavailable for this server")
            return SpeedTestResult(0, 0, 0, 0, 100)
        except Exception as e:
            logger.error(f"Unexpected error during speedtest: {e}")
            if self.interactive:
                print_info(f"Speed test unavailable (technical error)")
            return SpeedTestResult(0, 0, 0, 0, 100)

    def _run_mtr(self) -> MtrResult:
        """Run mtr and return results."""
        try:
            logger.info(f"Running MTR to {self.target_host}...")
            if self.interactive:
                print_info(f"Running MTR test to {self.target_host}...")
                
            # Set a reasonable count of packets
            count = 10
            timeout = 60
            
            # Display a spinner during the test
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                spinner_idx = 0
                start_time = time.time()
                
                process = subprocess.Popen(
                    ["sudo", "mtr", "-n", "-c", str(count), "-r", self.target_host],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Show spinner while the process is running
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    print(f"\r{get_symbol('ping')} MTR test in progress {spinner_chars[spinner_idx]} ({elapsed:.1f}s) ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()
                    time.sleep(0.1)
                
                # Get the output
                stdout, stderr = process.communicate()
                
                # Check for errors
                if process.returncode != 0:
                    print("")  # Newline after spinner
                    print_info(f"MTR test failed")
                    return MtrResult(0, 100, 0)
                
                # Clear spinner line
                print(f"\r{' ' * get_terminal_width()}", end='\r')
                
                output = stdout
            else:
                # Non-interactive mode: just run the command
                output = subprocess.check_output(
                    ["sudo", "mtr", "-n", "-c", str(count), "-r", self.target_host],
                    text=True,
                    timeout=timeout
                )

            lines = output.strip().split('\n')[1:]  # Skip header
            if not lines:
                logger.warning("No MTR results received")
                if self.interactive:
                    print_warning("No MTR results received")
                return MtrResult(0, 100, 0)

            last_hop = lines[-1].split()
            avg_latency = float(last_hop[7])  # Average latency
            packet_loss = float(last_hop[2].rstrip('%'))  # Loss%
            hops = len(lines)

            logger.info(f"MTR results - Latency: {avg_latency:.2f} ms, "
                       f"Packet Loss: {packet_loss:.2f}%, Hops: {hops}")
            
            if self.interactive:
                print_success("MTR test results:")
                print(format_mtr_results(result=MtrResult(avg_latency, packet_loss, hops)))
                
            return MtrResult(avg_latency, packet_loss, hops)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Error running mtr: {e}")
            if self.interactive:
                print_info(f"MTR test failed")
            return MtrResult(0, 100, 0)
        except Exception as e:
            logger.error(f"Unexpected error during MTR test: {e}")
            logger.exception(e)
            if self.interactive:
                print_info(f"MTR test unavailable (technical error)")
            return MtrResult(0, 100, 0)

    def connect_to_server(self, server: ServerInfo) -> bool:
        """Connect to a specific Mullvad server with unified timeout."""
        try:
            logger.info(f"Connecting to server {server.hostname} ({server.city}, {server.country})...")
            if self.interactive:
                print_header(f"SERVER TEST: {server.hostname}")
                print(format_server_info(server))
                print_connection_status(server.hostname, "connecting")

            # Record start time for the entire connection process
            connection_start_time = time.time()
            total_timeout = self.connection_timeout
            
            # First phase: set up connection
            try:
                # Set relay command
                if self.interactive:
                    print_info(f"Configuring relay...")
                
                subprocess.run(
                    ["mullvad", "relay", "set", "location", server.hostname],
                    check=True, capture_output=True,
                    timeout=min(5, total_timeout/4)  # Max 5 sec or 1/4 of timeout
                )
                
                # Connect command
                if self.interactive:
                    print_info(f"Initiating connection...")
                    
                subprocess.run(
                    ["mullvad", "connect"], 
                    check=True, capture_output=True,
                    timeout=min(5, total_timeout/4)  # Max 5 sec or 1/4 of timeout
                )
            except subprocess.TimeoutExpired:
                if self.interactive:
                    print_info("Configuration commands took too long, connection aborted")
                return False
            except subprocess.CalledProcessError as e:
                if self.interactive:
                    print_connection_status(server.hostname, "error")
                    print_error(f"Mullvad command failed. Please check that Mullvad VPN is running.")
                return False
                
            # Second phase: wait for connection to establish
            # Calculate how much time we have left
            elapsed_setup_time = time.time() - connection_start_time
            remaining_time = max(1, total_timeout - elapsed_setup_time)
            
            if self.interactive:
                print_info(f"Waiting for connection confirmation (total timeout: {total_timeout:.1f}s)...")
                
                # Use a progress bar that shows total elapsed time
                poll_interval = 0.1  # Check every 0.1 seconds for smoother progress bar
                max_steps = int(remaining_time / poll_interval)
                
                for i in range(max_steps):
                    current_time = time.time()
                    total_elapsed = current_time - connection_start_time
                    
                    # Check if we've exceeded the total timeout
                    if total_elapsed >= total_timeout:
                        break
                        
                    try:
                        output = subprocess.check_output(["mullvad", "status"], text=True, timeout=2)
                        if "Connected" in output:
                            server.connection_time = total_elapsed
                            logger.info(f"Successfully connected to server in {total_elapsed:.2f} seconds")
                            # Clear progress bar line
                            print(f"\r{' ' * get_terminal_width()}", end='\r')
                            print_connection_status(server.hostname, "success", total_elapsed)
                            return True
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                        # If status check fails, continue polling
                        pass
                    
                    # Update progress bar with total elapsed time
                    print_progress_bar(
                        total_elapsed, 
                        total_timeout,
                        prefix=f"{get_symbol('connecting')} Connection: ", 
                        suffix=f"{total_elapsed:.1f}s / {total_timeout:.1f}s"
                    )
                    time.sleep(poll_interval)
                    
                # Connection timed out
                print(f"\r{' ' * get_terminal_width()}", end='\r')  # Clear progress bar
                print_connection_status(server.hostname, "timeout")
                print_info(f"Server {server.hostname} did not respond within the timeout of {total_timeout:.1f}s")
            else:
                # Non-interactive mode: simpler polling
                poll_interval = 0.2
                end_time = connection_start_time + total_timeout
                
                while time.time() < end_time:
                    try:
                        output = subprocess.check_output(["mullvad", "status"], text=True, timeout=2)
                        if "Connected" in output:
                            server.connection_time = time.time() - connection_start_time
                            logger.info(f"Successfully connected to server in {server.connection_time:.2f} seconds")
                            return True
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                        # Continue polling
                        pass
                        
                    time.sleep(poll_interval)
            
            logger.warning(f"Failed to connect to server within {total_timeout:.1f} seconds")
            server.connection_time = 0
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error while connecting to server: {e}")
            if self.interactive:
                print_connection_status(server.hostname, "error")
                print_error(f"Connection error: {str(e).split(':')[0]}")
            return False

    def test_server(self, server: ServerInfo) -> Tuple[SpeedTestResult, MtrResult, bool]:
        """Test a single server's performance with new limitations."""
        viable = True  # Assume server is viable initially
        
        # 1. If connection takes more than connection_timeout, mark the server as unreachable
        if not self.connect_to_server(server):
            logger.warning(f"Skipping tests for {server.hostname} due to connection failure")
            return SpeedTestResult(0, 0, 0, 0, 100), MtrResult(0, 100, 0), False

        # 2. Run speed test
        speedtest_result = self._run_speedtest()
        
        # 3. If download speed is below 5 Mbps, mark the server as non-viable
        if speedtest_result.download_speed < MIN_DOWNLOAD_SPEED and speedtest_result.download_speed > 0:
            if self.interactive:
                print_info(f"Insufficient speed: {speedtest_result.download_speed:.2f} Mbps < {MIN_DOWNLOAD_SPEED} Mbps")
                print_info(f"Server {server.hostname} is classified as non-viable")
            viable = False
        
        # 4. If speed test fails, skip MTR test
        if speedtest_result.download_speed == 0:
            if self.interactive:
                print_info(f"Speed test unsuccessful, MTR test skipped")
            mtr_result = MtrResult(0, 100, 0)
        else:
            # Speed test was successful, proceed with MTR test
            mtr_result = self._run_mtr()
        
        # Check if this server responded correctly
        if speedtest_result.download_speed > 0 and mtr_result.avg_latency > 0:
            self.successful_servers += 1
            if self.interactive:
                if viable:
                    print_success(f"Test successful for {server.hostname} ✓")
                else:
                    print_info(f"Test successful but insufficient speed for {server.hostname}")
        else:
            if self.interactive:
                print_info(f"Server {server.hostname} did not respond correctly")
            viable = False
            
        return speedtest_result, mtr_result, viable

    def _save_results_to_db(self, session_id: int, server: ServerInfo, speedtest: SpeedTestResult, mtr: MtrResult, viable: bool):
        """Save server test results to SQLite database."""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            
            # Check if viable column exists before trying to insert
            try:
                # First, try to add the viable column if it doesn't exist
                try:
                    c.execute("ALTER TABLE server_results ADD COLUMN viable INTEGER DEFAULT 0")
                    conn.commit()
                    logger.info("Added missing 'viable' column to database")
                except sqlite3.OperationalError:
                    # Column might already exist or table might not exist yet
                    pass
                
                # Now insert with viable column included
                c.execute('''
                    INSERT INTO server_results (
                        session_id, hostname, country, city, distance_km, connection_time,
                        download_speed, upload_speed, ping, jitter, speedtest_packet_loss,
                        mtr_latency, mtr_packet_loss, mtr_hops, viable
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_id, server.hostname, server.country, server.city, server.distance_km,
                    server.connection_time, speedtest.download_speed, speedtest.upload_speed,
                    speedtest.ping, speedtest.jitter, speedtest.packet_loss,
                    mtr.avg_latency, mtr.packet_loss, mtr.hops, 1 if viable else 0
                ))
            
            except sqlite3.OperationalError as e:
                # If we still can't insert with viable, fall back to basic insert
                logger.warning(f"Database error: {e}. Falling back to basic insert.")
                
                try:
                    c.execute('''
                        INSERT INTO server_results (
                            session_id, hostname, country, city, distance_km, connection_time,
                            download_speed, upload_speed, ping, jitter, speedtest_packet_loss,
                            mtr_latency, mtr_packet_loss, mtr_hops
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        session_id, server.hostname, server.country, server.city, server.distance_km,
                        server.connection_time, speedtest.download_speed, speedtest.upload_speed,
                        speedtest.ping, speedtest.jitter, speedtest.packet_loss,
                        mtr.avg_latency, mtr.packet_loss, mtr.hops
                    ))
                    logger.info("Saved without viable field")
                except sqlite3.OperationalError as second_error:
                    logger.error(f"Could not insert data: {second_error}")
                    # Don't show this error to user - silently continue
            
            conn.commit()
            conn.close()
            logger.debug(f"Saved results for server {server.hostname} to database")
            return True
        
        except Exception as e:
            logger.error(f"Error saving results to database: {e}")
            # Don't display database errors to the user
            return False

    def run_tests(self, protocol: str = "WireGuard", max_servers: int = None, max_distance: float = None):
        """Run tests on servers."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results_file = f"mullvad_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{protocol.lower()}.log"

        # Set default max_servers if not provided
        if max_servers is None:
            max_servers = DEFAULT_MAX_SERVERS

        # Reset successful servers counter
        self.successful_servers = 0
        viable_servers = 0
        
        # Filter servers by protocol first
        protocol_servers = [s for s in self.servers if protocol.lower() in s.protocol.lower()]
        
        if not protocol_servers:
            logger.error(f"No servers found for protocol: {protocol}")
            if self.interactive:
                print_error(f"No servers found for protocol {protocol}")
            return
        
        # Run connection calibration to determine optimal timeout
        avg_time = self.run_connection_calibration()
        
        # Show test parameters
        if self.interactive:
            print_header("MULLVAD VPN TEST PARAMETERS")
            print_info(f"Date                : {timestamp}")
            print_info(f"Location            : {self.reference_location}")
            print_info(f"Protocol            : {protocol}")
            print_info(f"Minimum servers     : {MIN_VIABLE_SERVERS} viable")
            print_info(f"Initial servers     : {max_servers}")
            print_info(f"Connection timeout  : {self.connection_timeout:.1f}s")
            if max_distance:
                print_info(f"Maximum distance    : {max_distance} km")
            print_info(f"Results file        : {results_file}")
            print("")  # Add a blank line for readability
            
        # Create a new session in the database
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute('''
                INSERT INTO test_sessions (timestamp, reference_location, reference_lat, reference_lon, protocol)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                timestamp, self.reference_location, 
                self.reference_coords[0], self.reference_coords[1], 
                protocol
            ))
            session_id = c.lastrowid
            conn.commit()
            conn.close()
            logger.info(f"Created new test session with ID {session_id}")
        except Exception as e:
            logger.error(f"Error creating test session in database: {e}")
            session_id = None

        with open(results_file, 'w') as f:
            f.write("Mullvad VPN Server Performance Test Results\n")
            f.write(f"Test Date: {timestamp}\n")
            f.write(f"Reference Location: {self.reference_location}\n")
            f.write(f"Target Host for MTR: {self.target_host}\n")
            f.write(f"Protocol: {protocol}\n")
            f.write(f"Connection Timeout: {self.connection_timeout:.1f}s")
            if avg_time:
                f.write(f" (calibrated from average {avg_time:.2f}s)")
            f.write("\n")
            f.write(f"Minimum Viable Servers Required: {MIN_VIABLE_SERVERS}\n")
            f.write(f"Initial Servers to Test: {max_servers}\n")
            if max_distance:
                f.write(f"Maximum Distance: {max_distance} km\n")
            f.write("=" * 80 + "\n\n")
            
            # Filter all servers by distance if max_distance is specified
            if max_distance is not None:
                all_servers_filtered = [s for s in protocol_servers if s.distance_km <= max_distance]
            else:
                all_servers_filtered = protocol_servers
                
            # Take initial batch of servers
            initial_servers = all_servers_filtered[:max_servers]
            # Keep remaining servers available
            remaining_servers = all_servers_filtered[max_servers:]
                
            logger.info(f"Starting initial tests on {len(initial_servers)} servers" + 
                       (f" within {max_distance} km" if max_distance else ""))
            
            if self.interactive:
                print_header("STARTING TESTS")
                print_info(f"Starting tests on {len(initial_servers)} servers " + 
                         (f"(max distance: {max_distance} km)" if max_distance else ""))
            
            # Track servers we've already tested
            tested_servers = []
            total_servers_to_test = initial_servers.copy()
            
            # Test servers until we have at least MIN_VIABLE_SERVERS viable servers
            # AND we've tested at least max_servers servers
            while total_servers_to_test:
                server = total_servers_to_test.pop(0)
                tested_servers.append(server)
                idx = len(tested_servers)
                
                logger.info(f"\nTesting server {idx}/{len(initial_servers)}: {server.hostname}")
                
                if self.interactive:
                    print_header(f"TEST {idx}/{len(initial_servers) if idx <= len(initial_servers) else '+'}")
                    print_info(f"Server: {server.hostname}")
                    print_info(f"Location: {server.city}, {server.country}")
                    print_info(f"Distance: {server.distance_km:.0f} km")
                else:
                    print(f"\nTest server {idx}/{len(initial_servers) if idx <= len(initial_servers) else '+'}: {server.hostname}")
                    print(f"Location: {server.city}, {server.country} (Distance: {server.distance_km:.0f} km)")

                speedtest_result, mtr_result, viable = self.test_server(server)
                self.results[server.hostname] = (speedtest_result, mtr_result, viable)
                
                if viable:
                    viable_servers += 1

                # Save results to database if session was created
                if session_id:
                    try:
                        self._save_results_to_db(session_id, server, speedtest_result, mtr_result, viable)
                    except sqlite3.OperationalError as db_error:
                        if "no column named viable" in str(db_error):
                            logger.warning("Column 'viable' not found. Attempting to add it.")
                            try:
                                conn = sqlite3.connect(self.db_file)
                                c = conn.cursor()
                                c.execute("ALTER TABLE server_results ADD COLUMN viable INTEGER DEFAULT 0")
                                conn.commit()
                                conn.close()
                                logger.info("Added missing 'viable' column. Retrying save.")
                                # Try again
                                self._save_results_to_db(session_id, server, speedtest_result, mtr_result, viable)
                            except Exception as alter_error:
                                logger.error(f"Failed to add column: {alter_error}")
                        else:
                            # Some other database error
                            logger.error(f"Database error: {db_error}")

                # Write results to file
                self._write_server_results_to_file(f, server, speedtest_result, mtr_result, viable)
                
                # Show progress so far
                if self.interactive:
                    print_info(f"Progress: {idx} servers tested ({self.successful_servers} successful, {viable_servers} viable)")
                
                # Stop if we have enough viable servers
                if viable_servers >= MIN_VIABLE_SERVERS and idx >= max_servers:
                    logger.info(f"Found {viable_servers} viable servers after testing {idx} servers. Stopping tests.")
                    if self.interactive:
                        print_success(f"Goal achieved: {viable_servers}/{MIN_VIABLE_SERVERS} viable servers found.")
                    break
                    
                # Continue first phase: test all initial servers even if we have enough viable servers
                if idx < max_servers:
                    continue
                
                # Handle second phase: we've tested all initial servers but don't have enough viable servers
                if viable_servers < MIN_VIABLE_SERVERS:
                    if idx == max_servers:  # First time we hit this condition
                        # Prepare for spiral search from other continents
                        logger.info(f"Extending testing beyond initial {max_servers} servers to find {MIN_VIABLE_SERVERS} viable servers")
                        if self.interactive:
                            print_warning(f"Only {viable_servers}/{MIN_VIABLE_SERVERS} viable servers found")
                            print_info(f"Searching for servers on continents other than {self.user_continent}")
                        
                        # Write to log file
                        f.write(f"\nNote: Extending testing beyond initial {max_servers} servers to find at least {MIN_VIABLE_SERVERS} viable servers.\n")
                        f.write(f"Excluding servers from {self.user_continent} and selecting from other continents.\n\n")
                        
                        # Modify remaining servers to exclude user's continent and organize by distance
                        server_countries = {}
                        outside_continent_servers = []
                        
                        # Group servers by country
                        for server in remaining_servers:
                            country_code = server.hostname.split('-')[0]
                            if country_code not in server_countries:
                                server_countries[country_code] = []
                            server_countries[country_code].append(server)
                        
                        # Find servers outside user's continent
                        for continent, countries in CONTINENT_MAPPING.items():
                            if continent != self.user_continent:
                                for country in countries:
                                    if country in server_countries:
                                        outside_continent_servers.extend(server_countries[country])
                        
                        # Sort remaining servers by distance and replace remaining_servers list
                        outside_continent_servers.sort(key=lambda x: x.distance_km)
                        remaining_servers = outside_continent_servers
                        
                        if self.interactive:
                            print_info(f"Found {len(remaining_servers)} servers on other continents")
                    
                    # Check if we've reached the hard limit
                    if len(tested_servers) >= MAX_SERVERS_HARD_LIMIT:
                        logger.warning(f"Reached hard limit of {MAX_SERVERS_HARD_LIMIT} servers tested without finding {MIN_VIABLE_SERVERS} viable servers")
                        if self.interactive:
                            print_warning(f"Maximum limit reached: {MAX_SERVERS_HARD_LIMIT} servers tested")
                            print_warning(f"Unable to find {MIN_VIABLE_SERVERS} viable servers")
                        break
                    
                    # Add next server from remaining list if available
                    if remaining_servers:
                        next_server = remaining_servers.pop(0)
                        total_servers_to_test.append(next_server)
                    else:
                        # No more servers to test
                        logger.warning("No more servers available to test")
                        if self.interactive:
                            print_warning("No more servers available to test")
                        break
                else:
                    # We have enough viable servers
                    break

            if self.results:
                self._print_summary(results_file, viable_servers)
                
                if self.interactive:
                    print_header("TESTS COMPLETED")
                    print_success(f"Tests successfully completed: {self.successful_servers} functional servers out of {len(tested_servers)} tested")
                    if viable_servers >= MIN_VIABLE_SERVERS:
                        print_success(f"Goal achieved: {viable_servers}/{MIN_VIABLE_SERVERS} viable servers (speed > {MIN_DOWNLOAD_SPEED} Mbps)")
                    else:
                        print_warning(f"Goal not achieved: {viable_servers}/{MIN_VIABLE_SERVERS} viable servers (speed > {MIN_DOWNLOAD_SPEED} Mbps)")
                    print_info(f"Detailed results saved in: {results_file}")
                    
                    print("\nWould you like to open the results file?")
                    choice = input("Open file? (y/n): ").strip().lower()
                    if choice.startswith('y'):
                        try:
                            if sys.platform == 'darwin':  # macOS
                                subprocess.call(('open', results_file))
                            elif sys.platform == 'win32':  # Windows
                                os.startfile(results_file)
                            else:  # linux
                                subprocess.call(('xdg-open', results_file))
                        except Exception as e:
                            print_error(f"Unable to open file: {e}")
                else:
                    print(f"\nTests completed with {self.successful_servers} functional servers out of {len(tested_servers)} tested.")
                    print(f"Viable servers (speed > {MIN_DOWNLOAD_SPEED} Mbps): {viable_servers}/{MIN_VIABLE_SERVERS} required")
                    print(f"Results saved in {results_file}")
            else:
                logger.error("No test results available to generate summary")
                if self.interactive:
                    print_error("No test results available to generate a summary.")

    def _write_server_results_to_file(self, file, server: ServerInfo, 
                                      speedtest_result: SpeedTestResult, 
                                      mtr_result: MtrResult,
                                      viable: bool):
        """Write server test results to the log file."""
        file.write(f"Server: {server.hostname}\n")
        file.write(f"Location: {server.city}, {server.country}\n")
        file.write(f"Distance: {server.distance_km:.0f} km\n")
        file.write(f"Provider: {server.provider} ({server.ownership})\n")
        file.write(f"Protocol: {server.protocol}\n")
        file.write(f"Connection Time: {server.connection_time:.2f} seconds\n")
        file.write(f"Viable: {'Yes' if viable else 'No'}\n")
        file.write("\nSpeedtest Results:\n")
        file.write(f"Download: {speedtest_result.download_speed:.2f} Mbps\n")
        file.write(f"Upload: {speedtest_result.upload_speed:.2f} Mbps\n")
        file.write(f"Ping: {speedtest_result.ping:.2f} ms\n")
        file.write(f"Jitter: {speedtest_result.jitter:.2f} ms\n")
        file.write(f"Packet Loss: {speedtest_result.packet_loss:.2f}%\n")
        file.write("\nMTR Results:\n")
        file.write(f"Average Latency: {mtr_result.avg_latency:.2f} ms\n")
        file.write(f"Packet Loss: {mtr_result.packet_loss:.2f}%\n")
        file.write(f"Number of Hops: {mtr_result.hops}\n")
        file.write("=" * 80 + "\n\n")
        file.flush()  # Ensure data is written immediately

    def _print_summary_table(self, servers_list, title, file_handle=None, field_fn=None, reverse=False, header_list=None):
        """Generate a formatted summary table for terminal and log file."""
        if not servers_list:
            return
            
        if not header_list:
            header_list = ["Server", "Country", "Distance", "Value"]
            
        # Determine max widths for each column for nice formatting
        col_widths = [max(len(header_list[0]), max([len(s[0]) for s in servers_list]))]
        col_widths.append(max(len(header_list[1]), max([len(next(sv for sv in self.servers if sv.hostname == s[0]).country) for s in servers_list])))
        col_widths.append(max(len(header_list[2]), 10))  # Distance column
        col_widths.append(max(len(header_list[3]), 10))  # Value column
        
        # Format header and separator
        header = "| " + " | ".join([header_list[i].ljust(col_widths[i]) for i in range(len(header_list))]) + " |"
        separator = "+-" + "-+-".join(["-" * col_widths[i] for i in range(len(header_list))]) + "-+"
        
        # Create formatted rows
        rows = []
        for hostname, value in servers_list:
            server = next(s for s in self.servers if s.hostname == hostname)
            
            # Format value based on the field function
            if field_fn:
                formatted_value = field_fn(value)
            else:
                formatted_value = str(value)
                
            row = "| " + hostname.ljust(col_widths[0]) + " | " + \
                  server.country.ljust(col_widths[1]) + " | " + \
                  f"{server.distance_km:.0f} km".ljust(col_widths[2]) + " | " + \
                  formatted_value.ljust(col_widths[3]) + " |"
            rows.append(row)
        
        # Output to file if provided
        if file_handle:
            file_handle.write(f"\n{title}\n")
            file_handle.write(separator + "\n")
            file_handle.write(header + "\n")
            file_handle.write(separator + "\n")
            for row in rows:
                file_handle.write(row + "\n")
            file_handle.write(separator + "\n")
            
        # Output to terminal if interactive
        if self.interactive:
            print_header(title)
            print(separator)
            if COLOR_SUPPORT:
                print(f"{Fore.CYAN}{header}{Style.RESET_ALL}")
            else:
                print(header)
            print(separator)
            for row in rows:
                print(row)
            print(separator)
            print("")  # Add a blank line
        
        return separator, header, rows

    def _print_summary(self, results_file: str, viable_servers: int):
        """Print a summary of the best performing servers."""
        if not self.results:
            logger.error("No results available for summary")
            return

        try:
            # Sort servers by different metrics - only include viable servers
            viable_hostname_set = {hostname for hostname, (_, _, viable) in self.results.items() if viable}
            
            servers_by_distance = sorted(
                [(s.hostname, s.distance_km) for s in self.servers if s.hostname in viable_hostname_set],
                key=lambda x: x[1]
            )

            servers_by_download = sorted(
                [(hostname, data[0].download_speed) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                key=lambda x: x[1],
                reverse=True
            )

            servers_by_upload = sorted(
                [(hostname, data[0].upload_speed) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                key=lambda x: x[1],
                reverse=True
            )

            servers_by_latency = sorted(
                [(hostname, data[1].avg_latency) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                key=lambda x: x[1] if x[1] > 0 else float('inf')
            )

            servers_by_packet_loss = sorted(
                [(hostname, data[0].packet_loss + data[1].packet_loss) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                key=lambda x: x[1]
            )

            servers_by_connection_time = sorted(
                [(hostname, next(s.connection_time for s in self.servers if s.hostname == hostname)) 
                 for hostname in viable_hostname_set if next(s.connection_time for s in self.servers if s.hostname == hostname) > 0],
                key=lambda x: x[1]
            )

            with open(results_file, 'a') as f:
                f.write("\nSUMMARY\n")
                f.write("=" * 80 + "\n\n")

                f.write(f"Reference Location: {self.reference_location}\n")
                f.write(f"Total Servers Tested: {len(self.results)}\n")
                f.write(f"Successful Servers: {self.successful_servers}\n")
                f.write(f"Viable Servers (>{MIN_DOWNLOAD_SPEED} Mbps): {viable_servers}\n\n")

                if viable_servers > 0:
                    # Generate tables for each category
                    self._print_summary_table(
                        servers_by_distance[:5],
                        "Top 5 Viable Servers by Distance",
                        f,
                        field_fn=lambda x: f"{x:.0f} km"
                    )
                    
                    self._print_summary_table(
                        servers_by_connection_time[:5],
                        "Top 5 Viable Servers by Connection Time",
                        f,
                        field_fn=lambda x: f"{x:.2f} sec"
                    )
                    
                    self._print_summary_table(
                        servers_by_download[:5],
                        "Top 5 Viable Servers by Download Speed",
                        f,
                        field_fn=lambda x: f"{x:.2f} Mbps",
                        header_list=["Server", "Country", "Distance", "Download"]
                    )
                    
                    self._print_summary_table(
                        servers_by_upload[:5],
                        "Top 5 Viable Servers by Upload Speed",
                        f,
                        field_fn=lambda x: f"{x:.2f} Mbps",
                        header_list=["Server", "Country", "Distance", "Upload"]
                    )
                    
                    self._print_summary_table(
                        servers_by_latency[:5],
                        "Top 5 Viable Servers by Latency",
                        f,
                        field_fn=lambda x: f"{x:.2f} ms",
                        header_list=["Server", "Country", "Distance", "Latency"]
                    )
                    
                    self._print_summary_table(
                        servers_by_packet_loss[:5],
                        "Top 5 Viable Servers by Reliability (Lowest Packet Loss)",
                        f,
                        field_fn=lambda x: f"{x:.2f}%",
                        header_list=["Server", "Country", "Distance", "Loss"]
                    )

                    # Calculate averages only for viable servers with valid results
                    valid_results = [(hostname, s, m) for hostname, (s, m, v) in self.results.items()
                                   if v and s.download_speed > 0 and m.avg_latency > 0]

                    if valid_results:
                        avg_download = statistics.mean(r[1].download_speed for r in valid_results)
                        avg_upload = statistics.mean(r[1].upload_speed for r in valid_results)
                        avg_latency = statistics.mean(r[2].avg_latency for r in valid_results)

                        # Calculate average connection time for successful connections
                        successful_connections = [s.connection_time for s in self.servers 
                                               if s.hostname in viable_hostname_set and s.connection_time > 0]
                        avg_connection_time = statistics.mean(successful_connections) if successful_connections else 0

                        f.write("\nGLOBAL STATISTICS (viable servers only):\n")
                        f.write(f"Average Connection Time: {avg_connection_time:.2f} seconds\n")
                        f.write(f"Average Download Speed: {avg_download:.2f} Mbps\n")
                        f.write(f"Average Upload Speed: {avg_upload:.2f} Mbps\n")
                        f.write(f"Average Latency: {avg_latency:.2f} ms\n")
                        
                        # Print to terminal if interactive
                        if self.interactive:
                            print_header("GLOBAL STATISTICS")
                            print_info(f"Average connection time: {avg_connection_time:.2f} seconds")
                            print_info(f"Average download speed: {avg_download:.2f} Mbps")
                            print_info(f"Average upload speed: {avg_upload:.2f} Mbps")
                            print_info(f"Average latency: {avg_latency:.2f} ms")
                            print("")
                    else:
                        f.write("\nNo valid test results available for statistics\n")

                    # Get the best overall server based on a combined metric
                    if valid_results:
                        best_servers = self._calculate_best_overall_servers(viable_hostname_set)
                        if best_servers:
                            self._print_summary_table(
                                best_servers[:5],
                                "Best Overall Viable Servers (Score combines Speed, Latency, and Reliability)",
                                f,
                                field_fn=lambda x: f"{x:.2f}",
                                header_list=["Server", "Country", "Distance", "Score"]
                            )
                            
                            # Print detailed info for top 3 servers
                            if self.interactive:
                                print_header("BEST SERVERS DETAILS")
                                for hostname, score in best_servers[:3]:
                                    server = next(s for s in self.servers if s.hostname == hostname)
                                    speed_result, mtr_result, _ = self.results[hostname]
                                    if COLOR_SUPPORT:
                                        print(f"{Fore.CYAN}{hostname} {Fore.RESET}({server.city}, {server.country}): Score {Fore.GREEN}{score:.2f}")
                                        print(f"  → {Fore.GREEN}↓{speed_result.download_speed:.1f} Mbps {Fore.BLUE}↑{speed_result.upload_speed:.1f} Mbps {Fore.YELLOW}⏱{mtr_result.avg_latency:.1f} ms, Loss: {mtr_result.packet_loss:.1f}%")
                                    else:
                                        print(f"{hostname} ({server.city}, {server.country}): Score {score:.2f}")
                                        print(f"  → ↓{speed_result.download_speed:.1f} Mbps ↑{speed_result.upload_speed:.1f} Mbps ⏱{mtr_result.avg_latency:.1f} ms, Loss: {mtr_result.packet_loss:.1f}%")
                                print("")
                else:
                    f.write("\nNo viable servers found.\n")
                    f.write(f"Consider increasing the distance range or checking your connection.\n")
                    
                    if self.interactive:
                        print_warning("No viable servers found.")
                        print_info("Consider increasing the distance range or checking your connection.")

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            logger.exception(e)
            if self.interactive:
                print_error(f"Error generating summary: {e}")

    def _calculate_best_overall_servers(self, viable_hostname_set):
        """Calculate best overall servers using a weighted scoring system."""
        try:
            # Get max values for normalization
            max_download = max((res[0].download_speed for hostname, res in self.results.items() 
                               if hostname in viable_hostname_set and res[0].download_speed > 0), default=1)
            max_upload = max((res[0].upload_speed for hostname, res in self.results.items() 
                             if hostname in viable_hostname_set and res[0].upload_speed > 0), default=1)
            
            # Create scoring for each server (higher is better)
            scores = {}
            for hostname, (speed, mtr, viable) in self.results.items():
                # Skip servers that are not viable
                if not viable:
                    continue
                
                # Skip servers with failed tests
                if speed.download_speed <= 0 or mtr.avg_latency <= 0:
                    continue
                
                # Normalize values (0-1 scale)
                download_norm = speed.download_speed / max_download  # Higher is better
                upload_norm = speed.upload_speed / max_upload  # Higher is better
                
                # For ping, lower is better, so invert the normalization
                ping_factor = 1 / (1 + mtr.avg_latency / 100)  # Transform so higher is better
                
                # For packet loss, lower is better
                packet_loss = speed.packet_loss + mtr.packet_loss
                reliability_factor = 1 - (packet_loss / 100)  # Higher is better
                
                # Calculate weighted score
                score = (
                    download_norm * 0.4 +  # 40% weight on download speed
                    upload_norm * 0.2 +    # 20% weight on upload speed
                    ping_factor * 0.3 +    # 30% weight on ping
                    reliability_factor * 0.1  # 10% weight on reliability
                )
                
                scores[hostname] = score
                
            # Sort by score (higher is better)
            return sorted(scores.items(), key=lambda x: x[1], reverse=True)
        except Exception as e:
            logger.error(f"Error calculating best servers: {e}")
            return []

def check_dependencies():
    """Check if required dependencies are installed."""
    missing_deps = []
    
    # Check if speedtest-cli is installed
    try:
        subprocess.run(["speedtest-cli", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing_deps.append("speedtest-cli")

    # Check if mtr is installed
    try:
        subprocess.run(["mtr", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing_deps.append("mtr")

    # Check if mullvad is installed
    try:
        subprocess.run(["mullvad", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing_deps.append("Mullvad VPN CLI")
        
    return missing_deps

def check_optional_dependencies():
    """Check for optional dependencies and suggest installation"""
    suggestions = []
    
    # Check for colorama
    try:
        import colorama
    except ImportError:
        suggestions.append("colorama (for colored output): pip install colorama")
        
    return suggestions

def print_welcome():
    """Print a welcome message with ASCII art"""
    title = """
 __  __       _ _               _   _   _______ _____ 
|  \\/  |     | | |             | | | | |__   __|  __ \\
| \\  / |_   _| | |_   ____ _  _| |_| |    | |  | |__) |
| |\\/| | | | | | \\ \\ / / _` |/ _` | '_ \\   | |  |  ___/ 
| |  | | |_| | | |\\ V / (_| | (_| | |_) |  | |  | |     
|_|  |_|\\__,_|_|_| \\_/ \\__,_|\\__,_|_.__/   |_|  |_|     
"""
    if COLOR_SUPPORT:
        print(f"{Fore.CYAN}{Style.BRIGHT}{title}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}Mullvad VPN Server Performance Tester{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Simplified version with automatic calibration{Style.RESET_ALL}")
    else:
        print(title)
        print("Mullvad VPN Server Performance Tester")
        print("Simplified version with automatic calibration")
    print("")

def main():
    # Check dependencies first
    missing_deps = check_dependencies()
    if missing_deps:
        print_error("Missing dependencies detected:")
        for dep in missing_deps:
            print_error(f"- {dep}")
        print("\nPlease install these dependencies before running the script.")
        if "speedtest-cli" in missing_deps:
            print("Install speedtest-cli: pip install speedtest-cli")
        if "mtr" in missing_deps:
            print("Install mtr: use your package manager")
        if "Mullvad VPN CLI" in missing_deps:
            print("Install Mullvad VPN from https://mullvad.net")
        sys.exit(1)
        
    # Print welcome message
    print_welcome()
    
    # Check for optional dependencies
    suggested_deps = check_optional_dependencies()
    if suggested_deps:
        print_info("Recommended optional dependencies:")
        for dep in suggested_deps:
            print(f"- {dep}")
        print("")

    parser = argparse.ArgumentParser(description='Test Mullvad VPN servers performance')
    parser.add_argument('--location', type=str, default=DEFAULT_LOCATION,
                      help=f'Reference location for distance calculation (default: {DEFAULT_LOCATION})')
    parser.add_argument('--protocol', type=str, default="WireGuard",
                      choices=['WireGuard', 'OpenVPN'],
                      help='VPN protocol to test (default: WireGuard)')
    parser.add_argument('--max-servers', type=int, default=DEFAULT_MAX_SERVERS,
                      help=f'Maximum number of servers to test (default: {DEFAULT_MAX_SERVERS})')
    parser.add_argument('--default-lat', type=float, default=None,
                      help='Default latitude to use if geocoding fails')
    parser.add_argument('--default-lon', type=float, default=None,
                      help='Default longitude to use if geocoding fails')
    parser.add_argument('--max-distance', type=float, default=None,
                      help='Maximum distance in km for server testing (default: no limit)')
    parser.add_argument('--verbose', action='store_true',
                      help='Enable verbose logging')
    parser.add_argument('--db', type=str, default=DEFAULT_DB_FILE,
                      help=f'SQLite database file path (default: {DEFAULT_DB_FILE})')
    parser.add_argument('--interactive', action='store_true',
                      help='Enable interactive mode with prompts for location input')
    parser.add_argument('--non-interactive', action='store_false', dest='interactive',
                      help='Disable interactive mode (useful for scripts)')

    # Set default for interactive mode based on whether arguments are provided
    parser.set_defaults(interactive=len(sys.argv) <= 1)
    
    args = parser.parse_args()

    # Create tester instance with reference location and default coordinates
    tester = MullvadTester(
        reference_location=args.location,
        default_lat=args.default_lat,
        default_lon=args.default_lon,
        verbose=args.verbose,
        db_file=args.db,
        interactive=args.interactive
    )

    # Run tests with the specified parameters
    tester.run_tests(
        protocol=args.protocol, 
        max_servers=args.max_servers,
        max_distance=args.max_distance
    )

if __name__ == "__main__":
    main()
