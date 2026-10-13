#!/usr/bin/env python3
"""
Gaiacode FDSN Web Pipeline: HTTP Download & SAC Conversion
"""

import os
import subprocess
from pathlib import Path
from obspy import read
from obspy.core import AttribDict

# ==========================================
# CONFIGURATION
# ==========================================
# Pointed directly to the root of your data index.
# SANITIZED EXAMPLE — replace with your unit's address.
OMEGABOX_WEB_URL = "http://<INTERNAL_IP>/data/" 

LOCAL_ARCHIVE = "./mseed_archive/" 
SAC_OUT_DIR = "./sac_out/"
# Example station metadata — replace with your own station coordinates.
STATIONS = {
    "ST01": {"stla": 12.3456, "stlo": 78.9012, "stel": 500.0}
}

def sync_omega_box_web():
    """Mirror the /data/ directory using wget."""
    print(f"[*] Starting web sync from OmegaBox ({OMEGABOX_WEB_URL})...")
    
    os.makedirs(LOCAL_ARCHIVE, exist_ok=True)
    
    # -nH prevents creating a folder named after the unit's IP
    # --cut-dirs=1 removes the "data" folder from the local path, 
    # dropping the "2026" year folders straight into LOCAL_ARCHIVE
    wget_cmd = [
        "wget", "-m", "-np", "-nH", "--cut-dirs=1", 
        "-R", "index.html*",
        "-P", LOCAL_ARCHIVE,
        OMEGABOX_WEB_URL
    ]
    
    try:
        subprocess.run(wget_cmd, check=True)
        print("[+] Web mirror complete.")
    except subprocess.CalledProcessError as e:
        print(f"[-] wget failed: {e}")
        exit(1)

def convert_to_sac():
    """Read the downloaded miniSEED files and convert to SAC."""
    print("[*] Starting FDSN to SAC conversion...")
    os.makedirs(SAC_OUT_DIR, exist_ok=True)
    
    archive_path = Path(LOCAL_ARCHIVE)
    mseed_files = list(archive_path.rglob("*.mseed"))
    
    if not mseed_files:
        print("[-] No miniSEED files found to convert.")
        return

    converted_count = 0
    for f in mseed_files:
        try:
            st = read(str(f))
            for tr in st:
                station = tr.stats.station
                meta = STATIONS.get(station, {})
                
                if not hasattr(tr.stats, "sac"):
                    tr.stats.sac = AttribDict()
                
                if meta:
                    tr.stats.sac.stla = meta["stla"]
                    tr.stats.sac.stlo = meta["stlo"]
                    tr.stats.sac.stel = meta["stel"]
                
                sac_filename = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}.{tr.stats.channel}.SAC"
                sac_path = os.path.join(SAC_OUT_DIR, sac_filename)
                
                tr.write(sac_path, format="SAC")
                converted_count += 1
                
        except Exception as e:
            print(f"[-] Error converting {f.name}: {e}")
            
    print(f"[+] Conversion complete! Generated {converted_count} SAC files.")

if __name__ == "__main__":
    sync_omega_box_web()
    convert_to_sac()
