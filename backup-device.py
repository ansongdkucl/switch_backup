
import threading
import getpass
from multiprocessing import Queue
import getpass
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

from netmiko.exceptions import NetMikoTimeoutException
from paramiko.ssh_exception import SSHException
import subprocess
import logging

logging.basicConfig(filename='{}'.format(log_file), level=logging.DEBUG)
logger = logging.getLogger("netmiko")


#global failed_sw
#global backed_up 


failed_sw = 0
backed_up = 0

#global hostname1
#global router


rou_list = []


def getCred(): 
    global UN
    global PW
    global EP
    UN = input("Username : ")
    PW = getpass.getpass("Password : ")
    EP = getpass.getpass("Enable Password :")



################################################################################

def get_addresses():
    global rou_list
    ap = argparse.ArgumentParser()
    ap.add_argument("router", help="add router name i.e  cisco-bw ")
    args = ap.parse_args()

    #Macthes pattern against a single ip address from command line argument
    pat = '(\d+.\d+.\d+.\d+)'
    hostData = re.search(pat,str(args.router))
    print(hostData)
    if hostData:
        rou_list.append(hostData.group(0))
        print('the following switch will be backed up',rou_list)


    else:
        router_pat = routers['{}'.format(args.router)]
        print(router_pat)

#Browse to hostfile on system
        try:
            #os.chdir('/mnt/hosts')
            os.chdir('/media/hosts')
            file_name = host_file
        except:
            file_name = host_file

        with open (file_name) as f:
            for line in f:
                pat = router_pat
                m = re.match(pat, str(line))
                if m:
                    rou_list.append(m.group(0))

            print(len(rou_list))
            print('The following switches will be backed up',rou_list)

################################################################################################

def ssh_session():
    global hostname1
    global connect

    for router in rou_list:
        
        cmd = ['file prompt quiet','ip tftp blocksize 512']

        
        # Place what you want each thread to do here, for example connect to SSH, run a command, get output
        output_dict = {}
        hostname = router

        try:
            #print(UN, PW, EP)
            connect = ConnectHandler(device_type='cisco_ios'
            ,ip = router ,username= UN ,password= PW ,secret= EP)
           
        except:
            print('could not ssh into {} trying telnet device'.format(router))
            try:

                connect = ConnectHandler(device_type='cisco_ios_telnet'
                ,ip = router,username= UN,password= PW,secret= EP,fast_cli=False)    
                #print(' connected to via telnet')
                #connect.disconnect()
            except Exception:
                #print('could not log onto ', router)
                failed_print(router)
 
                continue
                
        

        try:
           host = connect.find_prompt()
        except:
            print('could not get to prompt')
            continue
            
        #print(host)
        hostname = host.replace('>',"")
        hostname1 = hostname + '-confg'
        
        try:

            connect.enable()
        except:
            print('could not get to enable')
            continue

        
        shuffle()
        try:
            connect.send_command('wr mem',expect_string=r"#")
        except:
            failed_print(hostname1)
            continue
            
        time.sleep(1)
        connect.send_config_set(cmd)
        out = connect.send_command_timing('copy run tftp://{}/'.format(foghorn_ip),delay_factor=2)
        
        
        
        #out = connect.send_command_timing('copy run tftp://{}/'.format(foghorn_ip))
        #print('output below')
        #print(out)

        if 'bytes copied in' or '' in out:
            connect.disconnect()
            copied_print()
    
        else:
            print('output is',out)
            connect.disconnect()
            failed_print(hostname1)
        


####################################################################################################

def shuffle():
    #os.chdir('/data/tftpboot')
    os.chdir('/media/tftp')

    test = subprocess.getoutput('test -f {} && echo "$FILE exists"'.format(hostname1))
 
    #print(test)
    if 'exists' not in test:
        print('No backup files exists for ', hostname1)
        print('file will need to be created')
        print('creating new backup files {}'.format(hostname1))
        #subprocess.call(cwd='/tftpboot')
        subprocess.call('touch {}'.format(hostname1),shell=True)
        subprocess.call('chmod 777 {}'.format(hostname1),shell=True)

    p=subprocess.Popen(('./AccessLists'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout, stderr = p.communicate(hostname1.encode())
    subprocess.call('chmod 777 {}'.format(hostname1),shell=True)
    #print(stdout)
    #backup()


###################################################################################################

def failed_print(hostname1):
    global failed_sw
    
    with open('/media/tftp/failed.txt','a') as f1: # dev path
    #with open('/data/tftpboot/failed.txt','a') as f1:
        print('*************!!!!!!!!  could NOT back up !!!!!!!!!!! - ' + hostname1)
        f1.write('could not back up ' + hostname1 +  ' ' + ctime() + "\n")
        failed_sw += 1
        #connect.disconnect()

def copied_print():
    global backed_up
    #print('about to save '  + hostname1 + '  *****')
    print('************************  config saved for ' + hostname1 + '  ****************************')
    #with open('/tftpboot/completed-backups.txt','a') as f2:
    with open('/media/tftp/completed-backups.txt','a') as f2:

        f2.write('Backed up ' + hostname1  +  ' ' + ctime() + "\n")
        backed_up += 1
        #connect.disconnect()



def ping(router):
    proc = subprocess.Popen(['ping -c 1 {}'.format(router)], stdout=subprocess.PIPE, shell=True)
    pResult = proc.stdout.read()
    #print(pResult)
    if b'1 received, 0% packet loss' not in pResult:
        print('device offline')
        print('writing to failed print')
        hostname1 = router
        failed_print()
    else:
        pass


if __name__ == "__main__":
    getCred()
    get_addresses()
    
    my_thread = threading.Thread(target=ssh_session)
    my_thread.start()
    # Wait for all threads to complete
    main_thread = threading.currentThread()
    for some_thread in threading.enumerate():
        if some_thread != main_thread:
            some_thread.join()
    print('Total Successful Backups ',backed_up)
    print('Total Switches NOT backed up ',failed_sw)
    

