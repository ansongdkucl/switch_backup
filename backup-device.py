
import threading
import getpass
from multiprocessing import Queue
from netmiko import ConnectHandler
import re
import argparse
from config_backup import *
from routers import *
from time import ctime
import time
import sys
import os
import paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed

from netmiko.exceptions import NetMikoTimeoutException
from paramiko.ssh_exception import SSHException
import subprocess
import logging

# Configure logging
logging.basicConfig(
    filename='{}'.format(log_file), 
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("netmiko")

# Global counters
failed_sw = 0
backed_up = 0
rou_list = []

# Global credentials
UN = ""
PW = ""
EP = ""

def getCred(): 
    global UN, PW, EP
    UN = input("Username : ")
    PW = getpass.getpass("Password : ")
    EP = getpass.getpass("Enable Password : ")

def get_addresses():
    global rou_list
    ap = argparse.ArgumentParser()
    ap.add_argument("router", help="add router name i.e cisco-bw ")
    args = ap.parse_args()

    # Matches pattern against a single ip address from command line argument
    pat = r'(\d+\.\d+\.\d+\.\d+)'
    hostData = re.search(pat, str(args.router))
    
    if hostData:
        rou_list.append(hostData.group(0))
        print('The following switch will be backed up:', rou_list)
    else:
        try:
            router_pat = routers['{}'.format(args.router)]
            print(f"Router pattern: {router_pat}")
        except KeyError:
            print(f"Router pattern '{args.router}' not found in routers dictionary")
            sys.exit(1)

        # Browse to hostfile on system
        try:
            os.chdir('/media/hosts')
            file_name = host_file
        except:
            file_name = host_file

        try:
            with open(file_name) as f:
                for line in f:
                    pat = router_pat
                    m = re.match(pat, str(line.strip()))
                    if m:
                        rou_list.append(m.group(0))
        except FileNotFoundError:
            print(f"Host file '{file_name}' not found")
            sys.exit(1)

        print(f"Found {len(rou_list)} switches")
        print('The following switches will be backed up:', rou_list)

def ping_device(router):
    """Check if device is reachable"""
    try:
        proc = subprocess.Popen(['ping', '-c', '1', router], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        return b'1 received, 0% packet loss' in stdout
    except Exception as e:
        logger.error(f"Error pinging {router}: {e}")
        return False

def backup_device(router):
    """Backup a single device"""
    global failed_sw, backed_up
    
    # First ping the device
    if not ping_device(router):
        print(f"Device {router} is not reachable")
        failed_print(router)
        return
    
    connect = None
    hostname1 = ""
    
    try:
        # Try SSH first
        try:
            connect = ConnectHandler(
                device_type='cisco_ios',
                ip=router,
                username=UN,
                password=PW,
                secret=EP,
                timeout=30
            )
            print(f"Connected to {router} via SSH")
        except Exception as ssh_error:
            print(f'Could not SSH into {router}, trying telnet: {ssh_error}')
            try:
                connect = ConnectHandler(
                    device_type='cisco_ios_telnet',
                    ip=router,
                    username=UN,
                    password=PW,
                    secret=EP,
                    fast_cli=False,
                    timeout=30
                )
                print(f"Connected to {router} via Telnet")
            except Exception as telnet_error:
                print(f'Could not connect to {router}: {telnet_error}')
                failed_print(router)
                return

        # Get hostname
        try:
            host = connect.find_prompt()
            hostname = host.replace('>', "").replace('#', "")
            hostname1 = hostname + '-confg'
        except Exception as e:
            print(f'Could not get prompt from {router}: {e}')
            failed_print(router)
            return
        
        # Enable mode
        try:
            connect.enable()
        except Exception as e:
            print(f'Could not enter enable mode on {router}: {e}')
            failed_print(hostname1)
            return

        # Prepare backup file
        if not shuffle(hostname1):
            failed_print(hostname1)
            return
        
        # Save config to memory
        try:
            connect.send_command('write memory', expect_string=r"#")
        except Exception as e:
            print(f'Could not save config to memory on {router}: {e}')
            failed_print(hostname1)
            return
            
        time.sleep(1)
        
        # Configure TFTP settings
        cmd = ['file prompt quiet', 'ip tftp blocksize 512']
        connect.send_config_set(cmd)
        
        # Copy running config to TFTP
        out = connect.send_command_timing(
            f'copy run tftp://{foghorn_ip}/',
            delay_factor=2
        )
        
        if 'bytes copied in' in out:
            copied_print(hostname1)
        else:
            print(f'Copy failed for {router}. Output: {out}')
            failed_print(hostname1)
            
    except Exception as e:
        print(f'Unexpected error with {router}: {e}')
        logger.error(f'Unexpected error with {router}: {e}')
        failed_print(hostname1 if hostname1 else router)
    finally:
        if connect:
            try:
                connect.disconnect()
            except:
                pass

def shuffle(hostname1):
    """Prepare backup file"""
    try:
        os.chdir('/media/tftp')
        
        # Check if file exists
        if not os.path.exists(hostname1):
            print(f'Creating new backup file: {hostname1}')
            with open(hostname1, 'w') as f:
                pass  # Create empty file
            os.chmod(hostname1, 0o777)
        
        # Run AccessLists script
        try:
            p = subprocess.Popen('./AccessLists', 
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
            stdout, stderr = p.communicate(hostname1.encode())
            os.chmod(hostname1, 0o777)
            
            if stderr:
                print(f'AccessLists script error: {stderr.decode()}')
                
        except Exception as e:
            print(f'Error running AccessLists script: {e}')
            
        return True
        
    except Exception as e:
        print(f'Error in shuffle function: {e}')
        return False

def failed_print(hostname1):
    global failed_sw
    
    try:
        with open('/media/tftp/failed.txt', 'a') as f1:
            error_msg = f'Could not back up {hostname1} - {ctime()}\n'
            print(f'*************!!!!!!!!  could NOT back up !!!!!!!!!!! - {hostname1}')
            f1.write(error_msg)
            failed_sw += 1
    except Exception as e:
        print(f'Error writing to failed.txt: {e}')

def copied_print(hostname1):
    global backed_up
    
    try:
        print(f'************************  config saved for {hostname1}  ****************************')
        with open('/media/tftp/completed-backups.txt', 'a') as f2:
            success_msg = f'Backed up {hostname1} - {ctime()}\n'
            f2.write(success_msg)
            backed_up += 1
    except Exception as e:
        print(f'Error writing to completed-backups.txt: {e}')

def main():
    getCred()
    get_addresses()
    
    if not rou_list:
        print("No routers to backup!")
        return
    
    # Use ThreadPoolExecutor for better thread management
    max_workers = min(10, len(rou_list))  # Limit concurrent connections
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all backup tasks
        future_to_router = {executor.submit(backup_device, router): router 
                           for router in rou_list}
        
        # Wait for all tasks to complete
        for future in as_completed(future_to_router):
            router = future_to_router[future]
            try:
                future.result()
            except Exception as e:
                print(f'Error backing up {router}: {e}')
                logger.error(f'Error backing up {router}: {e}')
    
    print(f'Total Successful Backups: {backed_up}')
    print(f'Total Switches NOT backed up: {failed_sw}')

if __name__ == "__main__":
    main()