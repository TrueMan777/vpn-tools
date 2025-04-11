# VPN Tools Collection

A collection of Python-based tools for testing, optimizing, and managing VPN connections. This repository contains utilities designed to help users get the most out of their VPN services.

## Available Tools

### 1. Mullvad Speed Test (`mullvad_speed_test.py`)

A comprehensive tool for testing and comparing Mullvad VPN server performance. This tool helps you find the best performing Mullvad servers based on various metrics including download speed, upload speed, latency, and reliability.

#### Features
- Tests multiple Mullvad VPN servers automatically
- Measures:
  - Download and upload speeds
  - Latency and jitter
  - Packet loss
  - Connection time
- Performs MTR (My TraceRoute) tests
- Generates detailed reports with server performance metrics
- Provides summaries of:
  - Top 5 servers by distance
  - Top 5 servers by connection speed
  - Top 5 servers by download speed
  - Top 5 servers by upload speed
  - Top 5 servers by latency
  - Top 5 servers by reliability
- Supports both WireGuard and OpenVPN protocols
- Includes detailed logging for troubleshooting

#### Prerequisites
- Python 3.12+
- Mullvad VPN client with CLI access
- mtr (My TraceRoute)

#### Installation

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
   pip install -r requirements.txt
   ```

3. Install and configure Mullvad VPN client:
   - Download from [Mullvad's official website](https://mullvad.net/download)
   - Ensure the CLI tool is accessible in your system PATH

#### Usage

Run the Mullvad speed test with:
```bash
sudo python mullvad_speed_test.py
```

Optional arguments:
```bash
--location "City, Country"  # Reference location for distance calculation
--protocol [WireGuard|OpenVPN]  # VPN protocol to test, default WireGuard
--max-servers N  # Maximum number of servers to test. default 50
```

### Supporting Modules

#### Mullvad Coordinates (`mullvad_coordinates.py`)
A database module containing accurate geographical coordinates for Mullvad server locations worldwide. Used by the speed test tool for precise distance calculations.

## Contributing

Contributions are welcome! If you have ideas for new VPN tools or improvements to existing ones, please feel free to:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## Future Tools (Planned)
- VPN connection monitor and auto-reconnect utility
- Multi-VPN provider speed comparison tool
- VPN traffic analysis tool
- Split tunneling configuration helper

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Troubleshooting

### Common Issues

1. **Permission Denied for MTR**
   - Solution: Run the script with sudo privileges

2. **Mullvad CLI Not Found**
   - Solution: Ensure Mullvad is installed and its CLI is in your system PATH

3. **Speed Test Failures**
   - Solution: Check your internet connection and ensure speedtest-cli is properly installed

## Logging

The tools generate detailed logs that can be found in:
- `mullvad_speed_test.log` - Detailed operation logs
- `mullvad_test_results_*.log` - Test results and summaries

## Security Notes

- The tools require sudo privileges for MTR tests
- No sensitive data (like API keys or credentials) is stored
- All logs are stored locally and can be safely deleted