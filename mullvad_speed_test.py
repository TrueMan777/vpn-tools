#!/usr/bin/env python3
"""Mullvad VPN Server Performance Tester - Optimized Version"""
import subprocess, json, re, time, os, pickle, sqlite3, statistics, logging, sys, shutil, random
from typing import List, Dict, Tuple, Optional, Set, Union, Any
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import argparse

# Constants
DEFAULT_MAX_SERVERS, MAX_SERVERS_HARD_LIMIT = 15, 45
DEFAULT_LOCATION, COORDS_CACHE_FILE, DEFAULT_DB_FILE = "Beijing, Beijing, China", "geocoords_cache.pkl", "mullvad_results.db"
BEIJING_COORDS = (39.9057136, 116.3912972)
MIN_DOWNLOAD_SPEED, DEFAULT_CONNECTION_TIME = 3.0, 20.0
MAX_SPEEDTEST_TIME, MIN_SPEEDTEST_TIME, MIN_VIABLE_SERVERS = 70.0, 15.0, 8

# Continent mapping for server selection
CONTINENT_MAPPING = {
    'North America': ['us', 'ca', 'mx'],
    'South America': ['br', 'ar', 'cl', 'co', 'pe'],
    'Europe': ['gb', 'uk', 'de', 'fr', 'it', 'es', 'nl', 'se', 'no', 'dk', 'fi', 'ch', 'at', 'be', 'ie', 'pt', 'pl', 'cz', 'gr', 'ro', 'hu'],
    'Asia': ['jp', 'kr', 'sg', 'hk', 'in', 'my', 'th', 'vn', 'id', 'ph', 'tw', 'cn'],
    'Oceania': ['au', 'nz'],
    'Africa': ['za', 'eg', 'ng', 'ke', 'ma']
}

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler('mullvad_speed_test.log')])
logger = logging.getLogger(__name__)

# Try to import colorama for color support
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLOR_SUPPORT = True
except ImportError:
    # Create dummy color classes if colorama is not available
    class DummyFore: RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = RESET = LIGHTGREEN_EX = LIGHTYELLOW_EX = LIGHTRED_EX = ''
    class DummyStyle: BRIGHT = DIM = NORMAL = RESET_ALL = ''
    class DummyBack: RED = GREEN = YELLOW = BLUE = RESET = ''
    Fore, Style, Back = DummyFore(), DummyStyle(), DummyBack()
    COLOR_SUPPORT = False

# UI symbols (Unicode and ASCII)
SYMBOLS = {
    'success': '✓', 'error': '✗', 'warning': '⚠', 'info': 'ℹ', 'connecting': '→', 'testing': '⋯', 
    'bullet': '•', 'right_arrow': '→', 'speedometer': '🔄', 'clock': '⏱', 'globe': '🌐', 
    'server': '🖥 ', 'signal': '📶', 'download': '⬇', 'upload': '⬆', 'ping': '📡', 
    'checkmark': '✓', 'cross': '✗',
}
ASCII_SYMBOLS = {k: v for k, v in zip(SYMBOLS.keys(), ['+', 'x', '!', 'i', '>', '...', '*', '->', 'O', 'T', 'G', 'S ', '^', 'D', 'U', 'P', 'V', 'X'])}

# Check if terminal supports Unicode
try: "\u2713".encode(sys.stdout.encoding); USE_UNICODE = True
except UnicodeEncodeError: USE_UNICODE = False

# Dataclasses for structured data
@dataclass
class ServerInfo:
    country: str; city: str; hostname: str; protocol: str
    provider: str; ownership: str; ip: str; ipv6: str
    connection_time: float = 0; latitude: float = 0.0; longitude: float = 0.0; distance_km: float = 0.0

@dataclass
class SpeedTestResult:
    download_speed: float; upload_speed: float; ping: float; jitter: float; packet_loss: float

@dataclass
class MtrResult:
    avg_latency: float; packet_loss: float; hops: int

# UI Utilities
def get_symbol(name): return SYMBOLS.get(name, '') if USE_UNICODE else ASCII_SYMBOLS.get(name, '')
def get_terminal_width(): return shutil.get_terminal_size().columns if hasattr(shutil, 'get_terminal_size') else 80

def print_status(message, status=None):
    """Unified function for printing status messages with appropriate styling"""
    if status == "success": prefix, color = get_symbol('success'), Fore.GREEN
    elif status == "error": prefix, color = get_symbol('error'), Fore.RED
    elif status == "warning": prefix, color = get_symbol('warning'), Fore.YELLOW
    elif status == "info": prefix, color = get_symbol('info'), Fore.BLUE
    else: print(message); return
    print(f"{color}{prefix} {message}{Style.RESET_ALL}" if COLOR_SUPPORT else f"{prefix} {message}")

def print_header(title, width=None):
    width = width or get_terminal_width()
    if COLOR_SUPPORT:
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{title}\n{'-' * min(len(title), width)}{Style.RESET_ALL}")
    else:
        print(f"\n{title}\n{'-' * min(len(title), width)}")

# Shorthand status printing functions 
def print_success(message): print_status(message, "success")
def print_error(message): print_status(message, "error")
def print_warning(message): print_status(message, "warning")
def print_info(message): print_status(message, "info")

def format_server_info(server):
    """Format server information nicely"""
    if COLOR_SUPPORT:
        return f"{Fore.CYAN}{get_symbol('server')}{server.hostname} {Fore.WHITE}({server.city}, {server.country}) {Fore.YELLOW}{server.distance_km:.0f} km"
    return f"{get_symbol('server')}{server.hostname} ({server.city}, {server.country}) {server.distance_km:.0f} km"

def format_mtr_results(result):
    """Format MTR results nicely"""
    if COLOR_SUPPORT:
        return f"{Fore.YELLOW}{get_symbol('ping')} Latency: {result.avg_latency:.2f} ms | Loss: {result.packet_loss:.2f}% | Hops: {result.hops}"
    return f"{get_symbol('ping')} Latency: {result.avg_latency:.2f} ms | Loss: {result.packet_loss:.2f}% | Hops: {result.hops}"

def format_speedtest_results(result):
    """Format speedtest results nicely"""
    if COLOR_SUPPORT:
        return (f"{Fore.GREEN}{get_symbol('download')} {result.download_speed:.2f} Mbps | "
            f"{Fore.BLUE}{get_symbol('upload')} {result.upload_speed:.2f} Mbps | "
            f"{Fore.YELLOW}{get_symbol('ping')} {result.ping:.2f} ms | "
            f"Jitter: {result.jitter:.2f} ms | Loss: {result.packet_loss:.2f}%")
    return (f"{get_symbol('download')} {result.download_speed:.2f} Mbps | "
        f"{get_symbol('upload')} {result.upload_speed:.2f} Mbps | "
        f"{get_symbol('ping')} {result.ping:.2f} ms | "
        f"Jitter: {result.jitter:.2f} ms | Loss: {result.packet_loss:.2f}%")

def print_connection_status(hostname, status, time_taken=None):
    """Print connection status with color coding"""
    if status == "connecting":
        msg = f"{get_symbol('connecting')} Connecting to {hostname}..."
        if COLOR_SUPPORT: print(f"{Fore.YELLOW}{msg}{Style.RESET_ALL}", end="\r")
        else: print(msg, end="\r")
    elif status == "success":
        msg = f"{get_symbol('success')} Connected to {hostname}" + (f" in {time_taken:.2f}s" if time_taken else "")
        if COLOR_SUPPORT: print(f"{Fore.GREEN}{msg}{Style.RESET_ALL}")
        else: print(msg)
    elif status == "error":
        msg = f"{get_symbol('error')} Connection to {hostname} failed"
        if COLOR_SUPPORT: print(f"{Fore.RED}{msg}{Style.RESET_ALL}")
        else: print(msg)
    elif status == "timeout":
        msg = f"{get_symbol('clock')} Connection to {hostname} timed out"
        if COLOR_SUPPORT: print(f"{Fore.RED}{msg}{Style.RESET_ALL}")
        else: print(msg)

def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """Print a progress bar with gradient colors from green to red"""
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + ' ' * (length - filled_length)
    
    if COLOR_SUPPORT:
        # Create a gradient from green to red (reversed from original)
        try:
            if percent <= 16: color = Fore.GREEN  # 0-16%: Green
            elif percent <= 33: color = Fore.LIGHTGREEN_EX  # 16-33%: Light Green
            elif percent <= 50: color = Fore.YELLOW  # 33-50%: Yellow
            elif percent <= 66: color = Fore.LIGHTYELLOW_EX  # 50-66%: Light Yellow
            elif percent <= 83: color = Fore.LIGHTRED_EX  # 66-83%: Light Red
            else: color = Fore.RED  # 83-100%: Red
        except AttributeError:
            # Fallback if extended colors aren't available
            if percent <= 33: color = Fore.GREEN
            elif percent <= 66: color = Fore.YELLOW
            else: color = Fore.RED
            
        print(f'\r{prefix} {color}{bar}{Style.RESET_ALL} {percent:.1f}% {suffix}', end='\r')
    else:
        print(f'\r{prefix} {bar} {percent:.1f}% {suffix}', end='\r')
    if iteration == total: print()

def display_parameters_summary(args, countdown_seconds=5):
    """Display a summary of all parameters with a countdown"""
    print_header("SUMMARY OF MULLVAD VPN TEST PARAMETERS")
    params = [
        f"Location: {args.location}",
        f"Protocol: {args.protocol}",
        f"Max number of servers: {args.max_servers}",
        f"Min. download speed: {args.min_download_speed} Mbps",
        f"Connection timeout: {args.connection_timeout} seconds",
        f"Minimum viable servers: {args.min_viable_servers}",
        f"Maximum distance: {args.max_distance if args.max_distance else 'No limit'} km",
        f"Database file: {args.db}",
        f"Interactive mode: {'Yes' if args.interactive else 'No'}"
    ]
    for param in params: print_info(param)

    print(f"\nTests will start in {countdown_seconds} seconds. Press Ctrl+C to cancel...")
    try:
        for i in range(countdown_seconds, 0, -1):
            sys_msg = f"Starting in {i} seconds..."
            if COLOR_SUPPORT: print(f"\r{Fore.YELLOW}{sys_msg}{Style.RESET_ALL}", end="")
            else: print(f"\r{sys_msg}", end="")
            sys.stdout.flush()
            time.sleep(1)
        print("\rStarting tests... ")
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(0)

def run_command(cmd, timeout=None, check=False, capture_output=False):
    """Run a command with unified error handling"""
    try:
        return subprocess.run(cmd, text=True, timeout=timeout, check=check, capture_output=capture_output or check)
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with code {e.returncode}: {' '.join(cmd)}")
        logger.error(f"STDERR: {e.stderr}")
        return e
    except Exception as e:
        logger.error(f"Error running command {' '.join(cmd)}: {e}")
        return None

def load_geo_modules():
    """Lazily load geopy modules only when needed"""
    try:
        from geopy.distance import geodesic
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut
        return geodesic, Nominatim, GeocoderTimedOut
    except ImportError:
        logger.error("geopy modules not found. Please install with: pip install geopy")
        print_error("Required geopy modules not found. Please install with: pip install geopy")
        sys.exit(1)

def input_location():
    """Interactive function to input location"""
    print_header("LOCATION FOR MULLVAD VPN TESTS")
    print_info("Please enter your location in the format 'City, Country'")
    print("Example: 'Paris, France' or 'Beijing, China'")
    
    while True:
        location = input("\nYour location: ").strip()
        if location:
            if ',' in location and len(location.split(',')) >= 2: return location
            else: print_warning("Incorrect format. Please use the format 'City, Country'")
        else:
            print_info(f"Using default location: {DEFAULT_LOCATION}")
            return DEFAULT_LOCATION

def input_coordinates():
    """Interactive function to input coordinates manually"""
    print_header("MANUAL COORDINATES INPUT")
    print_warning("Unable to determine coordinates automatically.")
    print_info("Please enter the coordinates manually.\n")
    
    while True:
        try:
            lat = float(input("Latitude (e.g. 48.8566 for Paris): ").strip())
            lon = float(input("Longitude (e.g. 2.3522 for Paris): ").strip())
            
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                print_success(f"Coordinates accepted: ({lat}, {lon})")
                return (lat, lon)
            else:
                print_warning("Coordinates out of range. Latitude: -90 to 90, Longitude: -180 to 180")
        except ValueError:
            print_error("Please enter valid numbers.")

def print_welcome():
    """Print a welcome message with ASCII art"""
    title = """
 __  __         _ _               _  __     _______  _   _   _____         _            
|  \/  |       | | |             | | \ \   /  /  _ \| \ | | |_   _|       | |           
| \  / |_   _ _| | |_   ____ _  _| |  \ \_/  /| |_) |  \| |   | | ___  ___| |_ ___ _ __ 
| |\/| | | | | | | \ \ / / _` |/ _` |  \    / |  __/| . ` |   | |/ _ \/ __| __/ _ \ '__|
| |  | | |_| | | | |\ V / (_| | (_| |   \  /  | |   | |\  |   | |  __/\__ \ ||  __/ |   
|_|  |_|\__,_|_|_|_| \_/ \__,_|\__,_|    \/   |_|   |_| \_|   |_|\___||___/\__\___|_|   
    """
    if COLOR_SUPPORT:
        print(f"{Fore.CYAN}{Style.BRIGHT}{title}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}Mullvad VPN Server Performance Tester{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Optimized Version with Enhanced Features{Style.RESET_ALL}")
    else:
        print(title)
        print("Mullvad VPN Server Performance Tester")
        print("Optimized Version with Enhanced Features")
    print("")

# Main Mullvad Tester Class
class MullvadTester:
    def __init__(self, target_host="1.1.1.1", reference_location=DEFAULT_LOCATION,
                 default_lat=None, default_lon=None, verbose=False,
                 db_file=DEFAULT_DB_FILE, interactive=False,
                 max_servers_hard_limit=MAX_SERVERS_HARD_LIMIT,
                 min_download_speed=MIN_DOWNLOAD_SPEED,
                 connection_timeout=DEFAULT_CONNECTION_TIME,
                 min_viable_servers=MIN_VIABLE_SERVERS):
        
        # Set up logging and instance variables
        logger.setLevel(logging.INFO if verbose else logging.WARNING)
        self.target_host, self.interactive = target_host, interactive
        self.max_servers_hard_limit = max_servers_hard_limit
        self.min_download_speed = min_download_speed
        self.default_connection_timeout = connection_timeout
        self.min_viable_servers = min_viable_servers
        self.db_file = db_file
        
        # Get reference location
        if interactive and reference_location == DEFAULT_LOCATION:
            reference_location = input_location()
        
        self.reference_location = reference_location
        self.default_coords = (default_lat, default_lon) if default_lat is not None and default_lon is not None else None
        
        # Initialize tester
        self.coords_cache = self._load_coords_cache()
        self._init_database()
        self.reference_coords = self._get_location_coordinates()
        
        # Get Mullvad servers
        print_header("RETRIEVING MULLVAD SERVERS")
        self.servers = self._get_servers()
        
        # Initialize results and counters
        self.results = {}
        self.connection_timeout = self.default_connection_timeout
        self.successful_servers = 0
        
        if not self.servers:
            print_error("No Mullvad servers found. Please check that Mullvad is installed and accessible.")
            logger.error("No Mullvad servers found")
            sys.exit(1)
            
        logger.info(f"Found {len(self.servers)} Mullvad servers")
        logger.info(f"Reference location: {reference_location} ({self.reference_coords})")
        
        if interactive:
            print_success(f"Mullvad servers found: {len(self.servers)}")
            print_info(f"Reference location: {reference_location}")
            print_info(f"Coordinates: ({self.reference_coords[0]:.4f}, {self.reference_coords[1]:.4f})")

    def _load_coords_cache(self):
        """Load coordinates cache from disk if it exists"""
        if os.path.exists(COORDS_CACHE_FILE):
            try:
                with open(COORDS_CACHE_FILE, 'rb') as f:
                    cache = pickle.load(f)
                    logger.info(f"Loaded {len(cache)} location coordinates from cache")
                    if self.interactive: print_info(f"Loaded {len(cache)} coordinates from cache")
                    return cache
            except Exception as e:
                logger.warning(f"Could not load coordinates cache: {e}")
                if self.interactive: print_warning(f"Could not load coordinates cache: {e}")
        return {}

    def _save_coords_cache(self):
        """Save coordinates cache to disk"""
        try:
            with open(COORDS_CACHE_FILE, 'wb') as f:
                pickle.dump(self.coords_cache, f)
                logger.info(f"Saved {len(self.coords_cache)} location coordinates to cache")
        except Exception as e:
            logger.warning(f"Could not save coordinates cache: {e}")

    def _init_database(self):
        """Initialize SQLite database for storing test results"""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            
            # Create tables with a single SQL operation for efficiency
            c.executescript('''
                CREATE TABLE IF NOT EXISTS test_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                    reference_location TEXT, reference_lat REAL, reference_lon REAL, protocol TEXT);
                
                CREATE TABLE IF NOT EXISTS server_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER,
                    hostname TEXT, country TEXT, city TEXT, distance_km REAL,
                    connection_time REAL, download_speed REAL, upload_speed REAL,
                    ping REAL, jitter REAL, speedtest_packet_loss REAL,
                    mtr_latency REAL, mtr_packet_loss REAL, mtr_hops INTEGER,
                    viable INTEGER DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES test_sessions (id));
            ''')
            
            # Check for viable column
            c.execute("PRAGMA table_info(server_results)")
            columns = [column[1] for column in c.fetchall()]
            if 'viable' not in columns:
                logger.info("Adding 'viable' column to server_results table")
                c.execute("ALTER TABLE server_results ADD COLUMN viable INTEGER DEFAULT 0")
                if self.interactive: print_info("Adding 'viable' column to existing database")
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            if self.interactive: print_error(f"Error initializing database: {e}")

    def _get_location_coordinates(self):
        """Get coordinates for reference location"""
        location = self.reference_location
        
        # Check cache first
        if location in self.coords_cache:
            coords = self.coords_cache[location]
            logger.info(f"Using cached coordinates for {location}: {coords}")
            if self.interactive: print_info(f"Using cached coordinates for {location}: {coords}")
            return coords
        
        # Load geopy modules
        geodesic, Nominatim, GeocoderTimedOut = load_geo_modules()
        
        try:
            geolocator = Nominatim(user_agent="mullvad_speed_test")
            
            if self.interactive:
                print_info(f"Searching for coordinates for {location}...")
                location_data = geolocator.geocode(location, exactly_one=True)
                
                if location_data:
                    coords = (location_data.latitude, location_data.longitude)
                    print_success(f"Location found: {location_data.address}")
                    print_success(f"Coordinates: {coords}")
                    
                    self.coords_cache[location] = coords
                    self._save_coords_cache()
                    return coords
                else:
                    print_error(f"Unable to find coordinates for: {location}")
                    print_header("LOCATION OPTIONS")
                    print("1. Try another location")
                    print("2. Enter coordinates manually")
                    
                    choice = input("\nYour choice (1/2): ").strip()
                    if choice == "1":
                        new_location = input_location()
                        self.reference_location = new_location
                        return self._get_location_coordinates()
                    else:
                        coords = input_coordinates()
                        self.coords_cache[location] = coords
                        self._save_coords_cache()
                        return coords
            else:
                location_data = geolocator.geocode(location, exactly_one=True)
                
                if location_data:
                    coords = (location_data.latitude, location_data.longitude)
                    logger.info(f"Found coordinates for {location}: {coords}")
                    
                    self.coords_cache[location] = coords
                    self._save_coords_cache()
                    return coords
                else:
                    logger.warning(f"Could not find coordinates for {location}")
                    if self.default_coords: return self.default_coords
                    elif location.lower().startswith("beijing"): return BEIJING_COORDS
                    else: return (0.0, 0.0)
                    
        except Exception as e:
            logger.warning(f"Error getting coordinates for {location}: {e}")
            
            if self.interactive:
                print_error(f"Error searching for coordinates: {e}")
                coords = input_coordinates()
                self.coords_cache[location] = coords
                self._save_coords_cache()
                return coords
            else:
                if self.default_coords: return self.default_coords
                elif location.lower().startswith("beijing"): return BEIJING_COORDS
                else: return (0.0, 0.0)

    def _calculate_distance(self, server_coords):
        """Calculate distance between server and reference location"""
        if server_coords == (0.0, 0.0) or self.reference_coords == (0.0, 0.0): return float('inf')
        geodesic, _, _ = load_geo_modules()
        return geodesic(self.reference_coords, server_coords).kilometers

    def _get_servers(self):
        """Parse mullvad relay list output to get server information"""
        servers = []
        try:
            logger.info("Fetching Mullvad server list...")
            if self.interactive: print_info("Retrieving Mullvad server list...")
                
            output = subprocess.check_output(["mullvad", "relay", "list"], text=True)
            
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                print("Processing server data ", end='')
                sys.stdout.flush()

            current_country, current_city = "", ""
            spinner_idx = 0
            current_coords = (0.0, 0.0)
            
            # Regular expressions (compiled for efficiency)
            country_pattern = re.compile(r'^([A-Za-z\s]+)\s+\(([a-z]{2})\)$')
            city_pattern = re.compile(r'^\s*([A-Za-z\s,]+)\s+\([a-z]+\)\s+@\s+[-\d.]+°[NS],\s+[-\d.]+°[EW]$')
            server_pattern = re.compile(r'^\s*([a-z]{2}-[a-z]+-(?:wg|ovpn)-\d+)\s+\(([^,]+)(?:,\s*([^)]+))?\)\s+-\s+([^,]+)(?:,\s+hosted by ([^()]+))?\s+\(([^)]+)\)$')
            
            lines = output.strip().split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line: continue

                if self.interactive and i % 10 == 0:
                    print(f"\rProcessing server data {spinner_chars[spinner_idx]} ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()

                # Parse country, city, and server in a single pass with if/elif chain
                if country_match := country_pattern.match(line):
                    current_country = country_match.group(1)
                elif city_match := city_pattern.match(line):
                    current_city = city_match.group(1)
                    try:
                        from mullvad_coordinates import get_coordinates
                        current_coords = get_coordinates(current_city, current_country)
                    except ImportError:
                        current_coords = (0.0, 0.0)
                elif server_match := server_pattern.match(line):
                    hostname, ip = server_match.group(1), server_match.group(2)
                    ipv6 = server_match.group(3) or ""
                    protocol, provider = server_match.group(4), server_match.group(5) or ""
                    ownership = server_match.group(6)
                    distance = self._calculate_distance(current_coords)
                    servers.append(ServerInfo(
                        country=current_country, city=current_city, hostname=hostname,
                        protocol=protocol, provider=provider, ownership=ownership,
                        ip=ip, ipv6=ipv6, latitude=current_coords[0],
                        longitude=current_coords[1], distance_km=distance
                    ))
            
            if self.interactive: print(f"\rProcessing server data {' ' * 20}")
            
            # Sort servers by distance - more efficient than sorting during processing
            return sorted(servers, key=lambda x: x.distance_km)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting server list: {e}")
            if self.interactive:
                print_error(f"Error retrieving server list: {e}")
                print_warning("Please verify that Mullvad VPN is correctly installed and configured.")
                sys.exit(1)
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting server list: {e}")
            if self.interactive:
                print_error(f"Unexpected error retrieving server list: {e}")
                sys.exit(1)
            return []

    def _get_location_continent(self, location):
        """Determine which continent a location is in"""
        location_continents = {
            'china': 'Asia', 'beijing': 'Asia', 'japan': 'Asia', 'singapore': 'Asia',
            'france': 'Europe', 'germany': 'Europe', 'uk': 'Europe', 'london': 'Europe',
            'usa': 'North America', 'united states': 'North America', 'canada': 'North America',
            'brazil': 'South America', 'argentina': 'South America',
            'australia': 'Oceania', 'new zealand': 'Oceania',
            'south africa': 'Africa', 'egypt': 'Africa'
        }
        
        location_lower = location.lower().replace(',', ' ').replace('.', ' ')
        
        # Try all possible matches for efficiency
        for continent in CONTINENT_MAPPING:
            if continent.lower() in location_lower: return continent
            
        for loc, continent in location_continents.items():
            if loc in location_lower: return continent
            
        for continent, countries in CONTINENT_MAPPING.items():
            if any(country in location_lower for country in countries): return continent
        
        logger.warning(f"Could not determine continent for {location}, defaulting to Europe")
        return "Europe"
        
    def run_connection_calibration(self):
        """Run connection tests on servers from different continents to calibrate timeout"""
        if self.interactive:
            print_header("CONNECTION CALIBRATION")
            print_info("Selecting servers from each continent to determine average connection time...")
        
        # Group servers by country and continent more efficiently
        server_countries = {}
        for server in self.servers:
            country_code = server.hostname.split('-')[0]
            server_countries.setdefault(country_code, []).append(server)
        
        # Map countries to continents
        available_continents = {}
        for continent, countries in CONTINENT_MAPPING.items():
            continent_servers = []
            for country in countries:
                if country in server_countries:
                    continent_servers.extend(server_countries[country])
            if continent_servers:
                available_continents[continent] = continent_servers
        
        # Determine user's continent
        self.user_continent = self._get_location_continent(self.reference_location)
        if self.interactive: print_info(f"Your location appears to be in: {self.user_continent}")
        
        # Select test servers - one from each continent
        test_servers = [random.choice(servers) for continent, servers in available_continents.items() if servers]
        
        if self.interactive:
            print_success(f"Servers selected for calibration: {len(test_servers)}")
            for server in test_servers: print_info(f"  • {server.hostname} ({server.city}, {server.country})")
            print("")
        else:
            print(f"Testing {len(test_servers)} servers for connection calibration")
        
        # Test connection times
        self.connection_timeout = self.default_connection_timeout
        conn_times = []
        
        for server in test_servers:
            if self.interactive: print_info(f"Testing {server.hostname}...")
            
            if self.connect_to_server(server):
                conn_times.append(server.connection_time)
                try: subprocess.run(["mullvad", "disconnect"], check=True, capture_output=True)
                except Exception: pass
        
        # Calculate and set timeout based on results
        if conn_times:
            avg_conn_time = sum(conn_times) / len(conn_times)
            self.connection_timeout = max(min(avg_conn_time * 1.5, self.default_connection_timeout), 10.0)
            
            if self.interactive:
                print_success(f"Average connection time: {avg_conn_time:.2f}s")
                print_success(f"Connection timeout adjusted to: {self.connection_timeout:.2f}s")
            
            logger.info(f"Calibrated connection timeout to {self.connection_timeout:.2f}s based on average {avg_conn_time:.2f}s")
            return avg_conn_time
        else:
            self.connection_timeout = self.default_connection_timeout
            
            if self.interactive:
                print_warning("No servers responded, using default timeout")
                print_info(f"Connection timeout: {self.connection_timeout:.2f}s")
            
            logger.warning("No servers responded during calibration, using default timeout")
            return None

    def _select_servers(self, servers_list, max_per_country=5, max_total_servers=None, 
                      exclude_continent=None, tested_servers=None):
        """
        Unified server selection function that can be used for both initial and additional selection
        with parameters controlling behavior for each case.
        """
        if max_total_servers is None: max_total_servers = len(servers_list)
        if tested_servers is None: tested_servers = []
        
        # Filter by continent if needed
        if exclude_continent:
            filtered_servers = []
            for server in servers_list:
                country_code = server.hostname.split('-')[0]
                for continent, countries in CONTINENT_MAPPING.items():
                    if continent != exclude_continent and country_code in countries:
                        filtered_servers.append(server)
                        break
            servers_list = filtered_servers
        
        # If no servers after filtering, return empty list
        if not servers_list: return []
        
        # Group by country and city (more efficient grouping)
        country_city_servers = {}
        for server in servers_list:
            country_code = server.hostname.split('-')[0]
            city = server.city
            if country_code not in country_city_servers:
                country_city_servers[country_code] = {}
            country_city_servers[country_code].setdefault(city, []).append(server)

        if self.interactive:
            print_info(f"Selecting up to {max_total_servers} servers (max {max_per_country} per country)")
        
        # Sort countries by distance
        countries_by_distance = []
        for country_code, cities in country_city_servers.items():
            min_distance = min(min(server.distance_km for server in servers) 
                             for city, servers in cities.items())
            countries_by_distance.append((country_code, min_distance))
        countries_by_distance.sort(key=lambda x: x[1])
        
        selected_servers = []
        countries_processed = 0
        selected_countries = {}  # Track selected servers by country
        
        # Select servers from each country
        for country_code, _ in countries_by_distance:
            if len(selected_servers) >= max_total_servers: break
                
            cities = country_city_servers[country_code]
            country_servers = []
            
            # Randomize city order
            city_names = list(cities.keys())
            random.shuffle(city_names)
            
            # Select one server from each city
            for city in city_names:
                if len(country_servers) < max_per_country:
                    server = random.choice(cities[city])
                    country_servers.append(server)
                    if len(selected_servers) + len(country_servers) >= max_total_servers: break
            
            # Fill any remaining slots for this country
            if len(country_servers) < max_per_country:
                remaining = max_per_country - len(country_servers)
                remaining_servers = [s for city in cities for s in cities[city] if s not in country_servers]
                random.shuffle(remaining_servers)
                country_servers.extend(remaining_servers[:remaining])
                
            # Track selected servers by country
            if country_servers:
                selected_countries[country_code] = len(country_servers)
                
            selected_servers.extend(country_servers)
            countries_processed += 1
            
            if self.interactive:
                cities_count = len(set(s.city for s in country_servers))
                print_info(f"Selected {len(country_servers)} servers from {cities_count} cities in {country_code}")
        
        # Ensure we have exactly the right number of servers
        if len(selected_servers) > max_total_servers:
            random.shuffle(selected_servers)
            selected_servers = selected_servers[:max_total_servers]
            
            # Update selected_countries counts
            selected_countries = {}
            for server in selected_servers:
                country_code = server.hostname.split('-')[0]
                selected_countries[country_code] = selected_countries.get(country_code, 0) + 1
        
        # Sort by distance
        selected_servers.sort(key=lambda x: x.distance_km)
        
        # Display success message
        if self.interactive:
            msg = f"Selected {len(selected_servers)} servers from {countries_processed} countries"
            if exclude_continent:
                msg += f" outside of {exclude_continent}"
            print_success(msg)
            
            # Display selected countries and server counts
            if exclude_continent:
                print_info("Selected countries and server counts:")
                for country_code, count in sorted(selected_countries.items(), key=lambda x: x[1], reverse=True):
                    # Find country name from country code
                    country_name = None
                    for server in self.servers:
                        if server.hostname.startswith(country_code):
                            country_name = server.country
                            break
                    
                    if country_name:
                        print_info(f"  • {country_name} ({country_code}): {count} servers")
                    else:
                        print_info(f"  • {country_code}: {count} servers")
        
        return selected_servers

    def _run_speedtest(self):
        """Run speedtest-cli and return results"""
        try:
            logger.info("Running speedtest...")
            if self.interactive:
                print("")  # Add a blank line for readability
                print_info("Running speed test...")
                
            cmd = ["speedtest-cli", "--json", "--secure", "--timeout", "20"]
            
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                spinner_idx = 0
                start_time = time.time()
                
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    if elapsed > MAX_SPEEDTEST_TIME:
                        process.terminate()
                        print("")  # Newline after spinner
                        print_info(f"Speed test canceled after {MAX_SPEEDTEST_TIME}s (maximum time reached)")
                        return SpeedTestResult(0, 0, 0, 0, 100)
                        
                    print(f"\r{get_symbol('speedometer')} Speed test in progress {spinner_chars[spinner_idx]} ({elapsed:.1f}s) ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()
                    time.sleep(0.1)
                
                stdout, stderr = process.communicate()
                
                end_time = time.time()
                elapsed_time = end_time - start_time
                
                if elapsed_time < MIN_SPEEDTEST_TIME:
                    print(f"\r{get_symbol('speedometer')} Speed test completed too quickly ({elapsed_time:.1f}s), may be unreliable ", end='')
                    logger.warning(f"Speed test completed too quickly: {elapsed_time:.2f}s < {MIN_SPEEDTEST_TIME}s minimum")
                    time.sleep(1)  # Give user time to see the message
                
                if process.returncode != 0:
                    print("")  # Newline after spinner
                    
                    if stderr and "403: Forbidden" in stderr:
                        print_info("Speedtest service unavailable from this VPN server (IP likely blocked)")
                        logger.warning("Speedtest service blocked this VPN server's IP address (403 Forbidden)")
                    else:
                        print_info(f"Speed test failed: {stderr if stderr else 'Unknown error'}")
                        logger.error(f"Speedtest failed: {stderr}")
                        
                    return SpeedTestResult(0, 0, 0, 0, 100)
                
                print(f"\r{' ' * get_terminal_width()}", end='\r')
                
                try: data = json.loads(stdout)
                except json.JSONDecodeError as e:
                    print_info(f"Speed test results not usable (JSON parsing error)")
                    logger.error(f"JSON parse error on output: {e}")
                    return SpeedTestResult(0, 0, 0, 0, 100)
            else:
                result = run_command(cmd, timeout=MAX_SPEEDTEST_TIME)
                
                if result is None or isinstance(result, Exception) or result.returncode != 0:
                    logger.error("Speedtest failed")
                    return SpeedTestResult(0, 0, 0, 0, 100)
                
                stdout = result.stdout
                try: data = json.loads(stdout)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode JSON from speedtest result: {e}")
                    return SpeedTestResult(0, 0, 0, 0, 100)

            # Check required fields
            required_fields = ['download', 'upload', 'ping']
            if not all(field in data for field in required_fields):
                field = next((f for f in required_fields if f not in data), "unknown field")
                logger.error(f"Missing required field in speedtest result: {field}")
                if self.interactive: print_info(f"Speed test results missing required data (no {field})")
                return SpeedTestResult(0, 0, 0, 0, 100)

            # Create SpeedTestResult from data
            result = SpeedTestResult(
                download_speed=data['download'] / 1_000_000,  # Convert to Mbps
                upload_speed=data['upload'] / 1_000_000,      # Convert to Mbps
                ping=data['ping'],
                jitter=data.get('jitter', 0),                 # Safe access with default
                packet_loss=data.get('packetLoss', 0)         # Safe access with default
            )

            logger.info(f"Speedtest results - Download: {result.download_speed:.2f} Mbps, "
                       f"Upload: {result.upload_speed:.2f} Mbps, Ping: {result.ping:.2f} ms")
            
            if self.interactive:
                print_success("Speed test results:")
                print(format_speedtest_results(result))
                
            return result
        except Exception as e:
            logger.error(f"Unexpected error during speedtest: {e}")
            if self.interactive: print_info(f"Speed test unavailable (technical error: {str(e)[:50]})")
            return SpeedTestResult(0, 0, 0, 0, 100)

    def _run_mtr(self):
        """Run mtr and return results"""
        try:
            logger.info(f"Running MTR to {self.target_host}...")
            if self.interactive: print_info(f"Running MTR test to {self.target_host}...")
                
            count, timeout = 10, 60
            
            if self.interactive:
                spinner_chars = ['|', '/', '-', '\\']
                spinner_idx = 0
                start_time = time.time()
                
                process = subprocess.Popen(
                    ["sudo", "mtr", "-n", "-c", str(count), "-r", self.target_host],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    print(f"\r{get_symbol('ping')} MTR test in progress {spinner_chars[spinner_idx]} ({elapsed:.1f}s) ", end='')
                    spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                    sys.stdout.flush()
                    time.sleep(0.1)
                
                stdout, stderr = process.communicate()
                
                if process.returncode != 0:
                    print("")  # Newline after spinner
                    print_info(f"MTR test failed")
                    return MtrResult(0, 100, 0)
                
                print(f"\r{' ' * get_terminal_width()}", end='\r')
                output = stdout
            else:
                result = run_command(["sudo", "mtr", "-n", "-c", str(count), "-r", self.target_host], timeout=timeout)
                if result is None or isinstance(result, Exception) or result.returncode != 0:
                    logger.error("MTR test failed")
                    return MtrResult(0, 100, 0)
                output = result.stdout

            # Parse MTR output efficiently
            lines = output.strip().split('\n')[1:]  # Skip header
            if not lines:
                logger.warning("No MTR results received")
                if self.interactive: print_warning("No MTR results received")
                return MtrResult(0, 100, 0)

            # Extract data from last line (direct access instead of multiple splits)
            last_hop = lines[-1].split()
            avg_latency = float(last_hop[7])
            packet_loss = float(last_hop[2].rstrip('%'))
            hops = len(lines)

            logger.info(f"MTR results - Latency: {avg_latency:.2f} ms, "
                       f"Packet Loss: {packet_loss:.2f}%, Hops: {hops}")
            
            if self.interactive:
                print_success("MTR test results:")
                print(format_mtr_results(result=MtrResult(avg_latency, packet_loss, hops)))
                
            return MtrResult(avg_latency, packet_loss, hops)
        except Exception as e:
            logger.error(f"Unexpected error during MTR test: {e}")
            if self.interactive: print_info(f"MTR test unavailable (technical error)")
            return MtrResult(0, 100, 0)

    def connect_to_server(self, server):
        """Connect to a specific Mullvad server with timeout"""
        try:
            logger.info(f"Connecting to server {server.hostname} ({server.city}, {server.country})...")
            if self.interactive:
                print_header(f"SERVER TEST: {server.hostname}")
                if COLOR_SUPPORT:
                    print(f"{Fore.CYAN}{get_symbol('server').rstrip()}  {server.hostname} "
                        f"{Fore.WHITE}({server.city}, {server.country}) "
                        f"{Fore.YELLOW}{server.distance_km:.0f} km{Style.RESET_ALL}")
                else:
                    print(f"{get_symbol('server').rstrip()}  {server.hostname} "
                        f"({server.city}, {server.country}) "
                        f"{server.distance_km:.0f} km")
                print_connection_status(server.hostname, "connecting")

            connection_start_time = time.time()
            total_timeout = self.connection_timeout
            
            try:
                if self.interactive: print_info(f"Configuring relay...")
                
                # Configure relay
                result = run_command(
                    ["mullvad", "relay", "set", "location", server.hostname],
                    timeout=min(5, total_timeout/4), check=True, capture_output=True
                )
                
                if result is None or isinstance(result, Exception):
                    if self.interactive: print_connection_status(server.hostname, "error")
                    return False
                
                if self.interactive: print_info(f"Initiating connection...")
                    
                # Connect to VPN
                result = run_command(
                    ["mullvad", "connect"],
                    timeout=min(5, total_timeout/4), check=True, capture_output=True
                )
                
                if result is None or isinstance(result, Exception):
                    if self.interactive: print_connection_status(server.hostname, "error")
                    return False
                
            except Exception:
                if self.interactive: print_connection_status(server.hostname, "error")
                return False
                
            elapsed_setup_time = time.time() - connection_start_time
            remaining_time = max(1, total_timeout - elapsed_setup_time)
            
            if self.interactive:
                print_info(f"Waiting for connection confirmation (total timeout: {total_timeout:.1f}s)...")
                
                poll_interval = 0.1  # Check every 0.1 seconds for smoother progress bar
                max_steps = int(remaining_time / poll_interval)
                
                for i in range(max_steps):
                    current_time = time.time()
                    total_elapsed = current_time - connection_start_time
                    
                    if total_elapsed >= total_timeout: break
                        
                    try:
                        output = subprocess.check_output(["mullvad", "status"], text=True, timeout=2)
                        if "Connected" in output:
                            server.connection_time = total_elapsed
                            logger.info(f"Successfully connected to server in {total_elapsed:.2f} seconds")
                            print(f"\r{' ' * get_terminal_width()}", end='\r')
                            print_connection_status(server.hostname, "success", total_elapsed)
                            return True
                    except: pass
                    
                    print_progress_bar(
                        total_elapsed, total_timeout,
                        prefix=f"{get_symbol('connecting')} Connection: ", 
                        suffix=f"{total_elapsed:.1f}s / {total_timeout:.1f}s"
                    )
                    time.sleep(poll_interval)
                    
                print(f"\r{' ' * get_terminal_width()}", end='\r')  # Clear progress bar
                print_connection_status(server.hostname, "timeout")
                print_info(f"Server {server.hostname} did not respond within the timeout of {total_timeout:.1f}s")
            else:
                # Non-interactive mode - more efficient polling
                poll_interval = 0.2
                end_time = connection_start_time + total_timeout
                
                while time.time() < end_time:
                    try:
                        result = run_command(["mullvad", "status"], timeout=2)
                        if result and not isinstance(result, Exception) and "Connected" in result.stdout:
                            server.connection_time = time.time() - connection_start_time
                            logger.info(f"Successfully connected to server in {server.connection_time:.2f} seconds")
                            return True
                    except: pass
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

    def test_server(self, server):
        """Test a single server's performance with connection stabilization period"""
        viable = True  # Assume server is viable initially
        
        if not self.connect_to_server(server):
            logger.warning(f"Skipping tests for {server.hostname} due to connection failure")
            return SpeedTestResult(0, 0, 0, 0, 100), MtrResult(0, 100, 0), False

        if self.interactive: print_info(f"Allowing connection to stabilize before testing...")
        
        stabilization_time = 8  # seconds to allow for connection optimization
        
        if self.interactive:
            spinner_chars = ['|', '/', '-', '\\']
            for i in range(stabilization_time * 10):  # Update spinner 10 times per second
                spinner_idx = i % len(spinner_chars)
                seconds_left = stabilization_time - (i // 10)
                print(f"\r{get_symbol('connecting')} Stabilizing connection {spinner_chars[spinner_idx]} ({seconds_left}s remaining) ", end='')
                sys.stdout.flush()
                time.sleep(0.1)
            
            print(f"\r{' ' * get_terminal_width()}", end='\r')
            print_success(f"Connection stabilized and ready for testing")
        else: time.sleep(stabilization_time)

        # Run speed test
        speedtest_result = self._run_speedtest()
        
        if speedtest_result.download_speed < self.min_download_speed and speedtest_result.download_speed > 0:
            if self.interactive:
                print_info(f"Insufficient speed: {speedtest_result.download_speed:.2f} Mbps < {self.min_download_speed} Mbps")
                print_info(f"Server {server.hostname} is classified as non-viable")
            viable = False
        
        # Run MTR test if speed test was successful
        if speedtest_result.download_speed == 0:
            if self.interactive: print_info(f"Speed test unsuccessful, MTR test skipped")
            mtr_result = MtrResult(0, 100, 0)
        else: mtr_result = self._run_mtr()
        
        if speedtest_result.download_speed > 0 and mtr_result.avg_latency > 0:
            self.successful_servers += 1
            if self.interactive:
                if viable: print_success(f"Test successful for {server.hostname} ✓")
                else: print_info(f"Test successful but insufficient speed for {server.hostname}")
        else:
            if self.interactive: print_info(f"Server {server.hostname} did not respond correctly")
            viable = False
            
        return speedtest_result, mtr_result, viable

    def _save_results_to_db(self, session_id, server, speedtest, mtr, viable):
        """Save server test results to SQLite database"""
        if session_id is None: return False
            
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            
            c.execute('''INSERT INTO server_results (
                session_id, hostname, country, city, distance_km, connection_time,
                download_speed, upload_speed, ping, jitter, speedtest_packet_loss,
                mtr_latency, mtr_packet_loss, mtr_hops, viable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                session_id, server.hostname, server.country, server.city, server.distance_km,
                server.connection_time, speedtest.download_speed, speedtest.upload_speed,
                speedtest.ping, speedtest.jitter, speedtest.packet_loss,
                mtr.avg_latency, mtr.packet_loss, mtr.hops, 1 if viable else 0
            ))
            
            conn.commit()
            conn.close()
            logger.debug(f"Saved results for server {server.hostname} to database")
            return True
        
        except Exception as e:
            logger.error(f"Error saving results to database: {e}")
            return False

    def run_tests(self, protocol="WireGuard", max_servers=None, max_distance=None):
        """Run tests on servers"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results_file = f"mullvad_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{protocol.lower()}.log"
        if max_servers is None: max_servers = DEFAULT_MAX_SERVERS

        self.successful_servers = 0
        viable_servers = 0
        
        # Filter servers by protocol
        protocol_servers = [s for s in self.servers if protocol.lower() in s.protocol.lower()]
        
        if not protocol_servers:
            logger.error(f"No servers found for protocol: {protocol}")
            if self.interactive: print_error(f"No servers found for protocol {protocol}")
            return
        
        # Calibrate connection timeout
        avg_time = self.run_connection_calibration()
        
        if self.interactive:
            print_header("MULLVAD VPN TEST PARAMETERS")
            params = [
                f"Date                : {timestamp}",
                f"Location            : {self.reference_location}",
                f"Protocol            : {protocol}",
                f"Minimum servers     : {self.min_viable_servers} viable",
                f"Initial servers     : {max_servers}",
                f"Connection timeout  : {self.connection_timeout:.1f}s",
                f"Maximum distance    : {max_distance if max_distance else 'No limit'} km",
                f"Results file        : {results_file}"
            ]
            for param in params: print_info(param)
            print("")  # Add a blank line for readability
            
        # Create a test session in the database
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute('''INSERT INTO test_sessions (
                timestamp, reference_location, reference_lat, reference_lon, protocol
            ) VALUES (?, ?, ?, ?, ?)''', (
                timestamp, self.reference_location, 
                self.reference_coords[0], self.reference_coords[1], protocol
            ))
            session_id = c.lastrowid
            conn.commit()
            conn.close()
            logger.info(f"Created new test session with ID {session_id}")
        except Exception as e:
            logger.error(f"Error creating test session in database: {e}")
            session_id = None

        # Open results file
        with open(results_file, 'w') as f:
            # Write header information
            f.write("Mullvad VPN Server Performance Test Results\n")
            f.write(f"Test Date: {timestamp}\n")
            f.write(f"Reference Location: {self.reference_location}\n")
            f.write(f"Target Host for MTR: {self.target_host}\n")
            f.write(f"Protocol: {protocol}\n")
            f.write(f"Connection Timeout: {self.connection_timeout:.1f}s")
            if avg_time: f.write(f" (calibrated from average {avg_time:.2f}s)")
            f.write("\n")
            f.write(f"Minimum Viable Servers Required: {self.min_viable_servers}\n")
            f.write(f"Initial Servers to Test: {max_servers}\n")
            if max_distance: f.write(f"Maximum Distance: {max_distance} km\n")
            f.write("=" * 80 + "\n\n")
            
            # Filter servers by distance if applicable
            if max_distance is not None:
                all_servers_filtered = [s for s in protocol_servers if s.distance_km <= max_distance]
            else: all_servers_filtered = protocol_servers
            
            # Select initial diverse servers (up to max_servers)
            initial_servers = self._select_servers(
                all_servers_filtered, 
                max_per_country=5, 
                max_total_servers=max_servers
            )
            
            # Create a list of remaining servers (not in the initial selection)
            remaining_servers = [s for s in all_servers_filtered if s not in initial_servers]
                
            logger.info(f"Starting initial tests on {len(initial_servers)} servers" + 
                       (f" within {max_distance} km" if max_distance else ""))
            
            if self.interactive:
                print_header("STARTING TESTS")
                print_info(f"Starting tests on {len(initial_servers)} servers " + 
                         (f"(max distance: {max_distance} km)" if max_distance else ""))
            
            tested_servers = []
            total_servers_to_test = initial_servers.copy()
            
            # Test servers one by one
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

                # Test the server
                speedtest_result, mtr_result, viable = self.test_server(server)
                self.results[server.hostname] = (speedtest_result, mtr_result, viable)
                
                if viable: viable_servers += 1

                # Save results to database and file
                if session_id: self._save_results_to_db(session_id, server, speedtest_result, mtr_result, viable)
                self._write_server_results_to_file(f, server, speedtest_result, mtr_result, viable)
                
                if self.interactive:
                    print_info(f"Progress: {idx} servers tested ({self.successful_servers} successful, {viable_servers} viable)")
                
                # Check if we've found enough viable servers
                if viable_servers >= self.min_viable_servers and idx >= max_servers:
                    logger.info(f"Found {viable_servers} viable servers after testing {idx} servers. Stopping tests.")
                    if self.interactive:
                        print_success(f"Goal achieved: {viable_servers}/{self.min_viable_servers} viable servers found.")
                    break
                    
                if idx < max_servers: continue
                
                # If we need more viable servers, continue testing
                if viable_servers < self.min_viable_servers:
                    if idx == max_servers:  # First time we hit this condition
                        logger.info(f"Extending testing beyond initial {max_servers} servers to find {self.min_viable_servers} viable servers")
                        
                        if self.interactive:
                            print_warning(f"Only {viable_servers}/{self.min_viable_servers} viable servers found")
                            print_info(f"Searching for servers on continents other than {self.user_continent}")
                        
                        f.write(f"\nNote: Extending testing beyond initial {max_servers} servers to find at least {self.min_viable_servers} viable servers.\n")
                        f.write(f"Excluding servers from {self.user_continent} and selecting from other continents.\n\n")
                        
                        # Calculate how many additional servers we need (at maximum)
                        remaining_to_test = min(self.max_servers_hard_limit - len(tested_servers), 
                                              (self.min_viable_servers - viable_servers) * 3)  # Estimate: need 3x tests for each viable server
                        
                        if remaining_to_test > 0:
                            # Use optimized selection for additional servers
                            additional_servers = self._select_servers(
                                [s for s in remaining_servers if s not in tested_servers],
                                max_per_country=3,
                                max_total_servers=remaining_to_test,
                                exclude_continent=self.user_continent,
                                tested_servers=tested_servers
                            )
                            
                            if additional_servers:
                                if self.interactive:
                                    countries_count = len(set([s.hostname.split('-')[0] for s in additional_servers]))
                                    print_info(f"Found {len(additional_servers)} servers from {countries_count} countries")
                                
                                remaining_servers = additional_servers
                            else:
                                logger.warning("No more servers available for additional testing")
                                if self.interactive:
                                    print_warning("No more servers available for additional testing")
                    
                    # Check if we've hit the hard limit
                    if len(tested_servers) >= self.max_servers_hard_limit:
                        logger.warning(f"Reached hard limit of {self.max_servers_hard_limit} servers tested without finding {self.min_viable_servers} viable servers")
                        if self.interactive:
                            print_warning(f"Maximum limit reached: {self.max_servers_hard_limit} servers tested")
                            print_warning(f"Unable to find {self.min_viable_servers} viable servers")
                        break
                    
                    # Get next server to test
                    if remaining_servers:
                        next_server = remaining_servers.pop(0)
                        total_servers_to_test.append(next_server)
                    else:
                        logger.warning("No more servers available to test")
                        if self.interactive: print_warning("No more servers available to test")
                        break
                else: break

            # Generate summary
            if self.results:
                self._print_summary(results_file, viable_servers)
                
                if self.interactive:
                    print_header("TESTS COMPLETED")
                    print_success(f"Tests successfully completed: {self.successful_servers} functional servers out of {len(tested_servers)} tested")
                    if viable_servers >= self.min_viable_servers:
                        print_success(f"Goal achieved: {viable_servers}/{self.min_viable_servers} viable servers (speed > {self.min_download_speed} Mbps)")
                    else:
                        print_warning(f"Goal not achieved: {viable_servers}/{self.min_viable_servers} viable servers (speed > {self.min_download_speed} Mbps)")
                    print_info(f"Detailed results saved in: {results_file}")
                    
                    print("\nWould you like to open the results file?")
                    choice = input("Open file? (y/n): ").strip().lower()
                    if choice.startswith('y'):
                        try:
                            if sys.platform == 'darwin': subprocess.call(('open', results_file))
                            elif sys.platform == 'win32': os.startfile(results_file)
                            else: subprocess.call(('xdg-open', results_file))
                        except Exception as e:
                            print_error(f"Unable to open file: {e}")
                else:
                    print(f"\nTests completed with {self.successful_servers} functional servers out of {len(tested_servers)} tested.")
                    print(f"Viable servers (speed > {self.min_download_speed} Mbps): {viable_servers}/{self.min_viable_servers} required")
                    print(f"Results saved in {results_file}")
            else:
                logger.error("No test results available to generate summary")
                if self.interactive: print_error("No test results available to generate a summary.")

    def _write_server_results_to_file(self, file, server, speedtest_result, mtr_result, viable):
        """Write server test results to the log file"""
        results = [
            f"Server: {server.hostname}",
            f"Location: {server.city}, {server.country}",
            f"Distance: {server.distance_km:.0f} km",
            f"Provider: {server.provider} ({server.ownership})",
            f"Protocol: {server.protocol}",
            f"Connection Time: {server.connection_time:.2f} seconds",
            f"Viable: {'Yes' if viable else 'No'}",
            "\nSpeedtest Results:",
            f"Download: {speedtest_result.download_speed:.2f} Mbps",
            f"Upload: {speedtest_result.upload_speed:.2f} Mbps",
            f"Ping: {speedtest_result.ping:.2f} ms",
            f"Jitter: {speedtest_result.jitter:.2f} ms",
            f"Packet Loss: {speedtest_result.packet_loss:.2f}%",
            "\nMTR Results:",
            f"Average Latency: {mtr_result.avg_latency:.2f} ms",
            f"Packet Loss: {mtr_result.packet_loss:.2f}%",
            f"Number of Hops: {mtr_result.hops}",
            "=" * 80 + "\n"
        ]
        file.write("\n".join(results) + "\n")
        file.flush()  # Ensure data is written immediately

    def _print_summary_table(self, servers_list, title, file_handle=None, field_fn=None, header_list=None):
        """Generate a formatted summary table for terminal and log file"""
        if not servers_list: return
        
        # Default headers if not provided
        if not header_list: header_list = ["Server", "Country", "Distance", "Value"]
            
        # Calculate column widths
        col_widths = [
            max(len(header_list[0]), max([len(s[0]) for s in servers_list])),
            max(len(header_list[1]), max([len(next(sv for sv in self.servers if sv.hostname == s[0]).country) for s in servers_list])),
            max(len(header_list[2]), 10),  # Distance column
            max(len(header_list[3]), 10)   # Value column
        ]
        
        # Format header and separator
        header = "| " + " | ".join([header_list[i].ljust(col_widths[i]) for i in range(len(header_list))]) + " |"
        separator = "+-" + "-+-".join(["-" * col_widths[i] for i in range(len(header_list))]) + "-+"
        
        # Generate table rows
        rows = []
        for hostname, value in servers_list:
            server = next(s for s in self.servers if s.hostname == hostname)
            formatted_value = field_fn(value) if field_fn else str(value)
            rows.append("| " + hostname.ljust(col_widths[0]) + " | " + \
                  server.country.ljust(col_widths[1]) + " | " + \
                  f"{server.distance_km:.0f} km".ljust(col_widths[2]) + " | " + \
                  formatted_value.ljust(col_widths[3]) + " |")
        
        # Write to file if specified
        if file_handle:
            file_handle.write(f"\n{title}\n")
            file_handle.write(separator + "\n")
            file_handle.write(header + "\n")
            file_handle.write(separator + "\n")
            for row in rows: file_handle.write(row + "\n")
            file_handle.write(separator + "\n")
            
        # Display in terminal if interactive
        if self.interactive:
            print_header(title)
            print(separator)
            if COLOR_SUPPORT: print(f"{Fore.CYAN}{header}{Style.RESET_ALL}")
            else: print(header)
            print(separator)
            for row in rows: print(row)
            print(separator)
            print("")  # Add a blank line
        
        return separator, header, rows

    def _print_summary(self, results_file, viable_servers):
        """Print a summary of the best performing servers"""
        if not self.results:
            logger.error("No results available for summary")
            return

        try:
            # Get viable hostnames
            viable_hostname_set = {hostname for hostname, (_, _, viable) in self.results.items() if viable}
            
            # Sort servers by different metrics
            sorted_servers = {
                'distance': sorted(
                    [(s.hostname, s.distance_km) for s in self.servers if s.hostname in viable_hostname_set],
                    key=lambda x: x[1]
                ),
                'download': sorted(
                    [(hostname, data[0].download_speed) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                    key=lambda x: x[1], reverse=True
                ),
                'upload': sorted(
                    [(hostname, data[0].upload_speed) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                    key=lambda x: x[1], reverse=True
                ),
                'latency': sorted(
                    [(hostname, data[1].avg_latency) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                    key=lambda x: x[1] if x[1] > 0 else float('inf')
                ),
                'packet_loss': sorted(
                    [(hostname, data[0].packet_loss + data[1].packet_loss) for hostname, data in self.results.items() if hostname in viable_hostname_set],
                    key=lambda x: x[1]
                ),
                'connection_time': sorted(
                    [(hostname, next(s.connection_time for s in self.servers if s.hostname == hostname)) 
                    for hostname in viable_hostname_set if next(s.connection_time for s in self.servers if s.hostname == hostname) > 0],
                    key=lambda x: x[1]
                )
            }

            with open(results_file, 'a') as f:
                # Write summary header
                f.write("\nSUMMARY\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Reference Location: {self.reference_location}\n")
                f.write(f"Total Servers Tested: {len(self.results)}\n")
                f.write(f"Successful Servers: {self.successful_servers}\n")
                f.write(f"Viable Servers (>{self.min_download_speed} Mbps): {viable_servers}\n\n")

                if viable_servers > 0:
                    # Print summary tables for each metric
                    metrics = [
                        ('distance', "Top 5 Viable Servers by Distance", lambda x: f"{x:.0f} km"),
                        ('connection_time', "Top 5 Viable Servers by Connection Time", lambda x: f"{x:.2f} sec"),
                        ('download', "Top 5 Viable Servers by Download Speed", lambda x: f"{x:.2f} Mbps", ["Server", "Country", "Distance", "Download"]),
                        ('upload', "Top 5 Viable Servers by Upload Speed", lambda x: f"{x:.2f} Mbps", ["Server", "Country", "Distance", "Upload"]),
                        ('latency', "Top 5 Viable Servers by Latency", lambda x: f"{x:.2f} ms", ["Server", "Country", "Distance", "Latency"]),
                        ('packet_loss', "Top 5 Viable Servers by Reliability (Lowest Packet Loss)", lambda x: f"{x:.2f}%", ["Server", "Country", "Distance", "Loss"])
                    ]
                    
                    for metric, title, fmt_fn, *headers in metrics:
                        self._print_summary_table(
                            sorted_servers[metric][:5], title, f, field_fn=fmt_fn,
                            header_list=headers[0] if headers else None
                        )

                    # Calculate global statistics
                    valid_results = [(hostname, s, m) for hostname, (s, m, v) in self.results.items()
                                   if v and s.download_speed > 0 and m.avg_latency > 0]

                    if valid_results:
                        # Calculate averages
                        avg_download = statistics.mean(r[1].download_speed for r in valid_results)
                        avg_upload = statistics.mean(r[1].upload_speed for r in valid_results)
                        avg_latency = statistics.mean(r[2].avg_latency for r in valid_results)

                        successful_connections = [s.connection_time for s in self.servers 
                                               if s.hostname in viable_hostname_set and s.connection_time > 0]
                        avg_connection_time = statistics.mean(successful_connections) if successful_connections else 0

                        # Write statistics 
                        f.write("\nGLOBAL STATISTICS (viable servers only):\n")
                        f.write(f"Average Connection Time: {avg_connection_time:.2f} seconds\n")
                        f.write(f"Average Download Speed: {avg_download:.2f} Mbps\n")
                        f.write(f"Average Upload Speed: {avg_upload:.2f} Mbps\n")
                        f.write(f"Average Latency: {avg_latency:.2f} ms\n")
                        
                        if self.interactive:
                            print_header("GLOBAL STATISTICS")
                            print_info(f"Average connection time: {avg_connection_time:.2f} seconds")
                            print_info(f"Average download speed: {avg_download:.2f} Mbps")
                            print_info(f"Average upload speed: {avg_upload:.2f} Mbps")
                            print_info(f"Average latency: {avg_latency:.2f} ms")
                            print("")
                    else: f.write("\nNo valid test results available for statistics\n")

                    # Calculate best servers
                    best_servers = self._calculate_best_overall_servers(viable_hostname_set)
                    if best_servers:
                        self._print_summary_table(
                            best_servers[:5],
                            "Best Overall Viable Servers (Score combines Speed, Latency, and Reliability)",
                            f, field_fn=lambda x: f"{x:.2f}",
                            header_list=["Server", "Country", "Distance", "Score"]
                        )
                        
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
            if self.interactive: print_error(f"Error generating summary: {e}")

    def _calculate_best_overall_servers(self, viable_hostname_set):
        """Calculate best overall servers using a weighted scoring system"""
        try:
            # Get maximum values for normalization
            max_download = max((res[0].download_speed for hostname, res in self.results.items() 
                               if hostname in viable_hostname_set and res[0].download_speed > 0), default=1)
            max_upload = max((res[0].upload_speed for hostname, res in self.results.items() 
                             if hostname in viable_hostname_set and res[0].upload_speed > 0), default=1)
            
            # Calculate scores with list comprehension for efficiency
            scores = {hostname: (
                (speed.download_speed / max_download) * 0.4 +  # 40% weight on download speed
                (speed.upload_speed / max_upload) * 0.2 +      # 20% weight on upload speed
                (1 / (1 + mtr.avg_latency / 100)) * 0.3 +      # 30% weight on ping
                (1 - ((speed.packet_loss + mtr.packet_loss) / 100)) * 0.1  # 10% weight on reliability
            ) for hostname, (speed, mtr, viable) in self.results.items() 
              if viable and speed.download_speed > 0 and mtr.avg_latency > 0}
                
            return sorted(scores.items(), key=lambda x: x[1], reverse=True)
        except Exception as e:
            logger.error(f"Error calculating best servers: {e}")
            return []

def input_custom_parameters(args):
    """Interactive function to customize test parameters before the summary"""
    if not args.interactive: return args  # In non-interactive mode, use command-line parameters
    
    print_header("CUSTOMIZATION OF TEST PARAMETERS")
    print_info("You can customize the test parameters before starting.")
    print_info("Press Enter to keep the default values.")
    print("")
    
    # Get location if not provided
    if args.location == DEFAULT_LOCATION: args.location = input_location()
    
    print_header("CUSTOMIZATION OF TEST CRITERIA")
    try:
        # Get parameters with validation in a compact format
        params = [
            ("Maximum number of servers", "max_servers", int),
            ("Hard limit on number of servers", "max_servers_hard_limit", int),
            ("Min. download speed (Mbps)", "min_download_speed", float),
            ("Connection timeout (seconds)", "connection_timeout", float),
            ("Minimum number of viable servers", "min_viable_servers", int)
        ]
        
        for prompt, param, converter in params:
            value = input(f"{prompt} [{getattr(args, param)}]: ").strip()
            if value: setattr(args, param, converter(value))
        
        # Handle max distance separately due to special None case
        if args.max_distance is None:
            max_distance_input = input("Maximum distance (km) [no limit]: ").strip()
            if max_distance_input: args.max_distance = float(max_distance_input)
        else:
            max_distance_input = input(f"Maximum distance (km) [{args.max_distance}]: ").strip()
            if max_distance_input: 
                args.max_distance = None if max_distance_input.lower() in ['none', 'no', '0'] else float(max_distance_input)
        
        print_success("Custom parameters saved.")
    except ValueError as e:
        print_error(f"Input error: {e}")
        print_warning("Using default values for invalid parameters.")
    
    return args

def check_dependencies():
    """Check if required dependencies are installed"""
    missing_deps = []
    for cmd, dep_name in [
        (["speedtest-cli", "--version"], "speedtest-cli"),
        (["mtr", "--version"], "mtr"),
        (["mullvad", "--version"], "Mullvad VPN CLI")
    ]:
        try: subprocess.run(cmd, check=True, capture_output=True)
        except: missing_deps.append(dep_name)
    return missing_deps

def check_optional_dependencies():
    """Check for optional dependencies and suggest installation"""
    try: import colorama; return []
    except ImportError: return ["colorama (for colored output): pip install colorama"]

def main():
    """Main function"""
    # Check dependencies
    missing_deps = check_dependencies()
    if missing_deps:
        print_error("Missing dependencies detected:")
        for dep in missing_deps: print_error(f"- {dep}")
        print("\nPlease install these dependencies before running the script.")
        if "speedtest-cli" in missing_deps: print("Install speedtest-cli: pip install speedtest-cli")
        if "mtr" in missing_deps: print("Install mtr: use your package manager")
        if "Mullvad VPN CLI" in missing_deps: print("Install Mullvad VPN from https://mullvad.net")
        sys.exit(1)
    
    # Print welcome message
    print_welcome()
    
    # Check optional dependencies
    suggested_deps = check_optional_dependencies()
    if suggested_deps:
        print_info("Recommended optional dependencies:")
        for dep in suggested_deps: print(f"- {dep}")
        print("")

    # Set up command-line arguments
    parser = argparse.ArgumentParser(description='Test Mullvad VPN servers performance')
    
    # Basic options
    parser.add_argument('--location', type=str, default=DEFAULT_LOCATION,
                      help=f'Reference location for distance calculation (default: {DEFAULT_LOCATION})')
    parser.add_argument('--protocol', type=str, default="WireGuard",
                      choices=['WireGuard', 'OpenVPN'],
                      help='VPN protocol to test (default: WireGuard)')
    parser.add_argument('--max-servers', type=int, default=DEFAULT_MAX_SERVERS,
                      help=f'Maximum number of servers to test (default: {DEFAULT_MAX_SERVERS})')
    
    # Advanced options  
    parser.add_argument('--default-lat', type=float, default=None,
                      help='Default latitude to use if geocoding fails')
    parser.add_argument('--default-lon', type=float, default=None,
                      help='Default longitude to use if geocoding fails')
    parser.add_argument('--max-distance', type=float, default=None,
                      help='Maximum distance in km for server testing (default: no limit)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--db', type=str, default=DEFAULT_DB_FILE,
                      help=f'SQLite database file path (default: {DEFAULT_DB_FILE})')
    
    # Mode options
    parser.add_argument('--interactive', action='store_true',
                      help='Enable interactive mode with prompts for location input')
    parser.add_argument('--non-interactive', action='store_false', dest='interactive',
                      help='Disable interactive mode (useful for scripts)')
    
    # Testing criteria
    parser.add_argument('--max-servers-hard-limit', type=int, default=MAX_SERVERS_HARD_LIMIT,
                      help=f'Hard limit on the number of servers to test (default: {MAX_SERVERS_HARD_LIMIT})')
    parser.add_argument('--min-download-speed', type=float, default=MIN_DOWNLOAD_SPEED,
                      help=f'Minimum download speed in Mbps for viable servers (default: {MIN_DOWNLOAD_SPEED})')
    parser.add_argument('--connection-timeout', type=float, default=DEFAULT_CONNECTION_TIME,
                      help=f'Default connection timeout in seconds (default: {DEFAULT_CONNECTION_TIME})')
    parser.add_argument('--min-viable-servers', type=int, default=MIN_VIABLE_SERVERS,
                      help=f'Minimum number of viable servers required (default: {MIN_VIABLE_SERVERS})')

    # Default to interactive mode if no args are provided
    parser.set_defaults(interactive=len(sys.argv) <= 1)
    args = parser.parse_args()
    
    # Customize parameters in interactive mode
    args = input_custom_parameters(args)
    
    # Display parameter summary
    display_parameters_summary(args, countdown_seconds=5)

    # Create tester and run tests
    tester = MullvadTester(
        reference_location=args.location, default_lat=args.default_lat, default_lon=args.default_lon,
        verbose=args.verbose, db_file=args.db, interactive=args.interactive,
        max_servers_hard_limit=args.max_servers_hard_limit, min_download_speed=args.min_download_speed,
        connection_timeout=args.connection_timeout, min_viable_servers=args.min_viable_servers
    )
    tester.run_tests(protocol=args.protocol, max_servers=args.max_servers, max_distance=args.max_distance)

if __name__ == "__main__":
    main()
