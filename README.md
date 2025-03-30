# VPN Tools Collection

A collection of Python-based tools for testing, optimizing, and managing VPN connections. This repository contains utilities designed to help users get the most out of their VPN services.

## Available Tools

### Mullvad Speed Test (`mullvad-speedtest.py`)

A comprehensive tool for testing and comparing Mullvad VPN server performance. This tool helps you find the best performing Mullvad servers based on various metrics including download speed, upload speed, latency, and reliability.

#### Features
- Interactive user interface with color-coded outputs
- Geographic-based server analysis and distance calculations
- Automatic connection calibration to optimize testing
- Tests multiple Mullvad VPN servers sequentially
- Measures:
  - Download and upload speeds
  - Latency and jitter
  - Packet loss
  - Connection time
- Performs MTR (My TraceRoute) tests
- Generates detailed reports with server performance metrics
- Provides comprehensive server rankings:
  - Top 5 servers by distance
  - Top 5 servers by connection time
  - Top 5 servers by download speed
  - Top 5 servers by upload speed
  - Top 5 servers by latency
  - Top 5 servers by reliability
  - Best overall servers (weighted scoring)
- Optimized server selection algorithm
- Enhanced visual feedback with multi-level color gradient progress bars
- Detailed breakdowns of selected servers by country
- Supports both WireGuard and OpenVPN protocols
- Detailed logging for troubleshooting
- Stores test results in SQLite database for historical analysis

## Prerequisites

- Python 3.6+ (3.12+ recommended)
- Mullvad VPN client with CLI access
- speedtest-cli
- mtr (My TraceRoute)
- geopy (for geographical calculations)

## Recommended Dependencies

- colorama (for color-coded terminal output)

## Installation

1. Install required system packages:
   ```bash
   # macOS
   brew install mtr

   # Debian/Ubuntu
   sudo apt-get install mtr

   # Fedora
   sudo dnf install mtr
   ```

2. Install Python dependencies:
   ```bash
   # Option 1: Install required packages directly
   pip install geopy speedtest-cli colorama

   # Option 2: Install from requirements.txt
   pip install -r requirements.txt
   ```

   Note: The script includes fallback handling if colorama is not installed, but the user experience will be enhanced with this package.

3. Install and configure Mullvad VPN client:
   - Download from [Mullvad's official website](https://mullvad.net/download)
   - Ensure the CLI tool is accessible in your system PATH

## Usage

Basic usage:
```bash
sudo python mullvad-speedtest.py
```

This will run in interactive mode, guiding you through the process.

Advanced usage with options:
```bash
sudo python mullvad-speedtest.py --location "Paris, France" --protocol WireGuard --max-servers 20
```

## Command-line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--location` | Reference location (format: "City, Country") | "Beijing, Beijing, China" |
| `--protocol` | VPN protocol to test ("WireGuard" or "OpenVPN") | "WireGuard" |
| `--max-servers` | Maximum number of servers to test | 15 |
| `--max-servers-hard-limit` | Hard limit on number of servers to test | 45 |
| `--max-distance` | Maximum distance (km) for server selection | No limit |
| `--default-lat` | Default latitude if geocoding fails | None |
| `--default-lon` | Default longitude if geocoding fails | None |
| `--min-download-speed` | Minimum download speed in Mbps for viable servers | 3.0 |
| `--connection-timeout` | Default connection timeout in seconds | 20.0 |
| `--min-viable-servers` | Minimum number of viable servers required | 8 |
| `--interactive` | Enable interactive mode | Auto-detected |
| `--non-interactive` | Disable interactive mode | - |
| `--verbose` | Enable verbose logging | Disabled |
| `--db` | SQLite database file path | "mullvad_results.db" |

## Example Use Cases

### Find Best Servers Near Your Location
```bash
sudo python mullvad-speedtest.py --interactive
```

### Test Servers Near a Specific Location
```bash
sudo python mullvad-speedtest.py --location "Tokyo, Japan" --max-servers 15
```

### Testing Within a Specific Distance Range
```bash
sudo python mullvad-speedtest.py --location "Berlin, Germany" --max-distance 2000
```

### Testing with OpenVPN Protocol
```bash
sudo python mullvad-speedtest.py --protocol OpenVPN --max-servers 10
```

### Testing with Custom Performance Criteria
```bash
sudo python mullvad-speedtest.py --min-download-speed 5.0 --min-viable-servers 10
```

## Supporting Modules

### Mullvad Coordinates (`mullvad_coordinates.py`)
A database module containing accurate geographical coordinates for Mullvad server locations worldwide. Used by the speed test tool for precise distance calculations.

## Understanding Results

After running the tests, the script generates a detailed report in a log file with the following sections:

1. **Test Parameters**: Your location, test date, protocol used, etc.
2. **Individual Server Results**: Detailed performance metrics for each tested server
3. **Summary Section**: 
   - Top 5 servers by distance
   - Top 5 servers by connection time
   - Top 5 servers by download speed
   - Top 5 servers by upload speed
   - Top 5 servers by latency
   - Top 5 servers by reliability
   - Best overall servers (weighted scoring)
   - Average performance statistics

The script also provides a real-time summary in the terminal and offers to open the full report when testing completes.

## Testing Process

1. **Connection Calibration**: The script first calibrates by testing connection times to servers on different continents
2. **Initial Testing**: Tests the closest servers to your location
3. **Adaptive Search**: If enough viable servers aren't found, searches for servers on other continents with detailed country breakdowns
4. **Results Analysis**: Calculates comprehensive metrics and generates rankings
5. **Report Generation**: Creates detailed logs and summaries

A server is considered "viable" if it establishes a connection successfully and provides a download speed above the minimum threshold (3 Mbps by default).

## Troubleshooting

### Dependency Issues
If you encounter errors related to missing Python modules:
```bash
# Install all required and recommended modules in one command
pip install geopy speedtest-cli colorama
```

The script is designed to work even if optional modules like colorama are not installed, but with a reduced user experience.

### Geolocation Issues
If your location cannot be determined automatically:
- Use the interactive mode which offers manual coordinate input
- Specify coordinates directly: `--default-lat 48.8566 --default-lon 2.3522`

### Connection Problems
- Permission Denied for MTR: Run the script with sudo privileges
- Mullvad CLI Not Found: Ensure Mullvad is installed and its CLI is in your system PATH
- If the script fails to connect to many servers:
  - Check your internet connection
  - Verify Mullvad VPN is properly configured
  - Increase the distance limit: `--max-distance 5000`

## Logging

The tools generate detailed logs that can be found in:
- `mullvad_speed_test.log` - Detailed operation logs
- `mullvad_test_results_*.log` - Test results and summaries
- SQLite database (`mullvad_results.db` by default) - Structured storage of all test results

## Future Tools (Planned)
- VPN connection monitor and auto-reconnect utility
- Multi-VPN provider speed comparison tool
- VPN traffic analysis tool
- Split tunneling configuration helper

## Security Notes

- The tool requires sudo privileges for MTR tests
- No sensitive data (like API keys or credentials) is stored
- All logs are stored locally and can be safely deleted

## Contributing

Contributions are welcome! If you have ideas for new VPN tools or improvements to existing ones, please feel free to:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
