from obspy.clients.fdsn import Client
from obspy import UTCDateTime

# Connect directly to the OmegaBox unit's FDSNWS endpoint.
# SANITIZED EXAMPLE — replace with your unit's address.
client = Client("http://<INTERNAL_IP>")

# Define the time window for your event
t1 = UTCDateTime("2024-03-15T01:00:00")
t2 = UTCDateTime("2024-03-15T01:30:00")

# Download the data (example: network XX, station ST01)
print("Downloading waveform data...")
st = client.get_waveforms(network="XX", station="ST01", location="*", channel="BH*", starttime=t1, endtime=t2)

# Save directly to SAC
for tr in st:
    sac_filename = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}.{tr.stats.channel}.SAC"
    tr.write(sac_filename, format="SAC")
    print(f"Saved: {sac_filename}")
