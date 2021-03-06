#!/usr/bin/env python3
import subprocess
import sys
import binascii
import io
import os
from threading import Thread
import pprint
import time

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),'..', 'implementations', 'python3')))

import pysatl



import socket

#parameters that must be shared between master and slave
port = 5000
link_granularity = 1
ack = True
skip_init=False
#side specific parameters
buffer_length = 4
sfr_granularity = 1
long_test=False

if (len(sys.argv) > 8) | (len(sys.argv) < 2) | (sys.argv[1] not in ['slave', 'master']):
    print("ERROR: needs at least 1 arguement, accept at most 7 arguments")
    print("[slave | master] buffer_length granularity sfr_granularity skip_init port long_test")
    print("set buffer_length=0 when the link has built-in flow control")
    exit()

if len(sys.argv)>2:
    buffer_length = int(sys.argv[2])

if len(sys.argv)>3:
    link_granularity = int(sys.argv[3])

if len(sys.argv)>4:
    sfr_granularity = int(sys.argv[4])

if 0==buffer_length:
    ack=False

if len(sys.argv)>5:
    skip_init = bool(sys.argv[5])

if len(sys.argv)>6:
    port = int(sys.argv[6])

if len(sys.argv)>7:
    long_test = sys.argv[7]=='1'

#if ack:
#    assert(buffer_length>=4)

print("%s buffer_length="%sys.argv[1],buffer_length)

print("%s link_granularity="%sys.argv[1],link_granularity)

print("%s sfr_granularity="%sys.argv[1],sfr_granularity)

print("%s ack="%sys.argv[1],ack)


refdat = bytearray()
for i in range(0,(1<<16)+1):
    refdat.append(i & 0xFF)

refdatle = bytearray()
for i in range(0,(1<<16)+1):
    refdatle.append((i & 0xFF) ^ 0xFF)

if sys.argv[1]=='slave':
    serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serversocket.settimeout(None)
    serversocket.bind(('localhost', port))
    serversocket.listen(1) # become a server socket, maximum 1 connections

    connection, address = serversocket.accept()
    assert(serversocket.gettimeout() == None)

    link = connection
    slave_com = pysatl.SocketComDriver(link,buffer_length,link_granularity,sfr_granularity,ack)

    print("Slave connected")
    slave  = pysatl.PySatl(is_master=False,com_driver=slave_com,skip_init=skip_init)
    print("Slave init done")

    def slave_spy_frame_tx(data):
        print("SLAVE FRAME TX:",pysatl.Utils.hexstr(data))

    def slave_spy_frame_rx(data):
        print("SLAVE FRAME RX:",pysatl.Utils.hexstr(data))

    #slave simply replying the incoming data, length of reply indicated by P1 P2
    while True:
        cmd = slave.rx()
        #print(cmd)
        if cmd.CLA == 0xFE:
            if cmd == pysatl.CAPDU.from_hexstr("FE 00 00 01"):
                slave.spy_frame_tx = slave_spy_frame_tx
                slave.spy_frame_rx = slave_spy_frame_rx
            elif cmd == pysatl.CAPDU.from_hexstr("FE 00 00 00"):
                slave.spy_frame_tx = None
                slave.spy_frame_rx = None
            #in this case we just answer status word
            response = pysatl.RAPDU(0x69,0x00)
        else:
            ledat=None
            if cmd.LE>0:
                rle = cmd.INS<<16
                rle += cmd.P1<<8
                rle += cmd.P2
                #print(rle)
                assert(cmd.LE>=rle)
                ledat = cmd.DATA[0:rle]
                remaining = rle-len(cmd.DATA)
                if remaining>0:
                    ledat += refdatle[0:remaining]
            response = pysatl.RAPDU(0x90,0x00,ledat)
        #print(response)
        slave.tx(response)
        if cmd.CLA == 0xFF:
            time.sleep(1)
            print("slave done")
            exit()

else:
    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    clientsocket.settimeout(None)
    clientsocket.connect(('localhost', port))
    assert(clientsocket.gettimeout() == None)

    link = clientsocket
    master_com = pysatl.SocketComDriver(link,buffer_length,link_granularity,sfr_granularity,ack)
    master = pysatl.PySatl(is_master=True,com_driver=master_com,skip_init=skip_init)
    apdu = pysatl.CAPDU(CLA=1,INS=2,P1=3,P2=4)
    print(apdu, flush=True)
    master.tx(apdu)
    response = master.rx()
    print(response, flush=True)

    #test error case with LC data
    #apdu = pysatl.CAPDU(CLA=0xFE,INS=2,P1=3,P2=4,DATA=bytearray([1,2,3,4,5,6]))
    #print(apdu)
    #master.tx(apdu)
    #response = master.rx()
    #print(response)

    def test_lengths(lc,le,rle,*,print_apdu=False):
        assert(lc<=1<<16)
        assert(le<=1<<16)
        assert(rle<=le)
        lcdat=refdat[0:lc]
        capdu = pysatl.CAPDU(CLA=1,INS=rle>>16,P1=(rle>>8) & 0xFF,P2=rle & 0xFF,DATA=lcdat,LE=le)
        if print_apdu:
            print("CAPDU hexstr:",capdu.to_hexstr(skip_long_data=True))
            print(capdu.to_str(skip_long_data=True))
        master.tx(capdu)
        response = master.rx()
        if print_apdu:
            print(response.to_str(skip_long_data=True))
            print("RAPDU hexstr:",response.to_hexstr(skip_long_data=True))
        assert(len(response.DATA) == rle)
        assert(response.SW1 == 0x90)
        assert(response.SW2 == 0x00)
        l = min(lc,rle)
        assert(lcdat[0:l]==response.DATA[0:l])
        assert(refdatle[0:rle-l]==response.DATA[l:rle])

    def master_spy_frame_tx(data):
        dat = pysatl.Utils.hexstr(data[:12])
        if len(data)>12:
            dat += " "+pysatl.Utils.hexstr(data[12:],skip_long_data=True)
        print("MASTER FRAME TX:",dat)

    def master_spy_frame_rx(data):
        if len(data)>16:
            dat = pysatl.Utils.hexstr(data[:4]) + " " + pysatl.Utils.hexstr(data[4:-2],skip_long_data=True) + " " + pysatl.Utils.hexstr(data[-2:])
        else:
            dat = pysatl.Utils.hexstr(data)
        print("MASTER FRAME RX:",dat)

    def spy_apdu_case(msg,lc,le,rle=None):
        if rle is None:
            rle=le
        master.spy_frame_tx = master_spy_frame_tx
        master.spy_frame_rx = master_spy_frame_rx

        print(msg)
        test_lengths(lc,le,rle,print_apdu=True)

        master.spy_frame_tx = None
        master.spy_frame_rx = None

    spy_apdu_case("CASE 1:",            0,     0)
    spy_apdu_case("CASE 2S min:",       0,     1)
    spy_apdu_case("CASE 2S max:",       0,   256)
    spy_apdu_case("CASE 3S min:",       1,     0)
    spy_apdu_case("CASE 3S max:",     255,     0)
    spy_apdu_case("CASE 4S min:",       1,     1)
    spy_apdu_case("CASE 4S max:",     255,   256)
    spy_apdu_case("CASE 2E min:",       0,   257)
    spy_apdu_case("CASE 2E max:",       0, 65536)
    spy_apdu_case("CASE 3E min:",     256,     0)
    spy_apdu_case("CASE 3E max:",   65535,     0)
    spy_apdu_case("CASE 4E min 1:",   256,     1)
    spy_apdu_case("CASE 4E min 2:",     1,   257)
    spy_apdu_case("CASE 4E min 3:",   256,   257)
    spy_apdu_case("CASE 4E max 1:", 65535,     1)
    spy_apdu_case("CASE 4E max 2:",     2, 65536)
    spy_apdu_case("CASE 4E max 3:", 65535, 65536)

    #for i in range(0,2):
    #    test_lengths(269,269,268)
    #print(apdu, flush=True)
    #master.tx(apdu)
    #response = master.rx()
    #print(response, flush=True)

    basic_test_lengths = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,65533,65534,65535,65536]
    #basic_test_lengths = [269]
    for lc in basic_test_lengths:
        print(lc, flush=True)
        for le in basic_test_lengths:
            for rle in [0,1,2,3,le-3,le-2,le-1,le]:
                if (rle<le) & (rle>=0):
                    test_lengths(lc,le,rle)

    if long_test:
        for lc in range(0,(1<<16)+1):
            print(lc, flush=True)
            test_lengths(lc,lc,lc)

        for lc in range(0,1000):
            print(lc, flush=True)
            for le in range(0,1000):
                #for rle in range(0,le+1):
                test_lengths(lc,le,le)


    #tell the slave to quit
    master.tx(pysatl.CAPDU(CLA=0xFF,INS=2,P1=3,P2=4))
    response = master.rx()
    print(response, flush=True)
    time.sleep(1)
    print("done", flush=True)
    #input("Press enter to quit ")
