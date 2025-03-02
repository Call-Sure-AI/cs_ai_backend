from qdrant_client import QdrantClient
import socket
import concurrent.futures
import urllib.parse

# URL and API key
base_url = "https://qdrant.callsure.ai"
api_key = "68cd8841-53bd-439a-aafe-be4b32812943"

# Parse the URL to get the hostname
parsed_url = urllib.parse.urlparse(base_url)
hostname = parsed_url.netloc
if ':' in hostname:
    hostname = hostname.split(':')[0]

print(f"Testing connectivity to {hostname} on various ports...")

# Define common ports to check
common_ports = [80, 443, 6333, 6334, 8000, 8080]

# Function to check if a port is open
def check_port(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((hostname, port))
    sock.close()
    return port, result == 0

# Check multiple ports concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    port_results = list(executor.map(check_port, common_ports))

open_ports = [port for port, is_open in port_results if is_open]

if open_ports:
    print(f"Open ports found: {open_ports}")
    
    # Try connecting to Qdrant using each open port
    for port in open_ports:
        custom_url = f"{parsed_url.scheme}://{hostname}:{port}"
        print(f"\nAttempting connection to {custom_url}")
        try:
            client = QdrantClient(
                url=custom_url,
                api_key=api_key,
                timeout=10
            )
            collections = client.get_collections()
            print(f"✓ Success on port {port}!")
            print(f"Collections: {[c.name for c in collections.collections]}")
            print(f"\nWorking configuration: url={custom_url}, api_key={api_key}")
            break
        except Exception as e:
            print(f"✗ Failed on port {port}: {e}")
else:
    print("No open ports found. This suggests a network connectivity issue.")
    
    # Try the alternate protocol
    alt_scheme = "http" if parsed_url.scheme == "https" else "https"
    print(f"\nTrying alternate protocol: {alt_scheme}")
    
    alt_url = f"{alt_scheme}://{hostname}"
    try:
        client = QdrantClient(
            url=alt_url, 
            api_key=api_key,
            timeout=10
        )
        collections = client.get_collections()
        print(f"✓ Success with {alt_url}!")
        print(f"Collections: {[c.name for c in collections.collections]}")
    except Exception as e:
        print(f"✗ Failed with {alt_url}: {e}")
        
        print("\nAdditional troubleshooting suggestions:")
        print("1. Check VPN requirements - you might need to be on a specific network")
        print("2. Verify the exact host and port with your system administrator")
        print("3. Check for any required proxy settings")
        print("4. Try curl commands to test basic connectivity")
        print("5. The server might have IP-based access control that's blocking your requests")